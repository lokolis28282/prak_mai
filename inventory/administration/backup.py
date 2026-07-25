"""Safe database backup, restore, and production replacement workflows."""

from __future__ import annotations

import os
import shutil
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from ..db import connect, initialize
from ..shared.helpers import WarehouseError


class AdministrationContext(Protocol):
    db_path: Path
    lock: Any
    key_tables: set[str]
    restore_base_tables: set[str]

    def _require_role(self, *roles: str) -> dict[str, Any]: ...

    def _audit(
        self,
        db: sqlite3.Connection,
        action: str,
        entity_type: str,
        entity_id: int | str | None = None,
        details: dict[str, Any] | str | None = None,
    ) -> None: ...

    def database_check(
        self,
        path: str | Path | None = None,
        required_tables: set[str] | None = None,
    ) -> dict[str, Any]: ...


class AdministrationBackupService:
    def __init__(self, context: AdministrationContext):
        self.context = context

    @property
    def backup_dir(self) -> Path:
        return self.context.db_path.parent / "backups"

    def list_backups(self) -> list[dict[str, Any]]:
        self.context._require_role("admin")
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        result = []
        for path in sorted(
            self.backup_dir.glob("*.db"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        ):
            stat = path.stat()
            result.append(
                {
                    "name": path.name,
                    "size": stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(
                        timespec="seconds"
                    ),
                }
            )
        return result

    def next_backup_path(self, prefix: str) -> Path:
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        candidate = self.backup_dir / f"{prefix}_{timestamp}.db"
        counter = 2
        while candidate.exists():
            candidate = self.backup_dir / f"{prefix}_{timestamp}_{counter}.db"
            counter += 1
        return candidate

    def create_backup(self, prefix: str = "warehouse") -> dict[str, Any]:
        self.context._require_role("admin")
        with self.context.lock:
            destination = self.next_backup_path(prefix)
            try:
                with (
                    closing(sqlite3.connect(self.context.db_path)) as source_db,
                    closing(sqlite3.connect(destination)) as backup_db,
                ):
                    source_db.backup(backup_db)
                check = self.context.database_check(
                    destination, self.context.key_tables
                )
                if not check["ok"]:
                    destination.unlink(missing_ok=True)
                    raise WarehouseError(
                        "Созданный backup не прошёл проверку целостности"
                    )
                with connect(self.context.db_path) as db:
                    self.context._audit(
                        db,
                        "BACKUP_CREATE",
                        "database_backup",
                        destination.name,
                        {
                            "path": str(destination),
                            "size": destination.stat().st_size,
                        },
                    )
                return next(
                    item
                    for item in self.list_backups()
                    if item["name"] == destination.name
                )
            except (OSError, sqlite3.Error) as error:
                destination.unlink(missing_ok=True)
                raise WarehouseError(
                    f"Не удалось создать backup: {error}"
                ) from error

    def backup_by_name(self, filename: str) -> Path:
        if not filename or Path(filename).name != filename:
            raise WarehouseError("Некорректное имя backup-файла")
        path = self.backup_dir / filename
        if not path.is_file() or path.suffix.lower() != ".db":
            raise WarehouseError("Backup-файл не найден")
        return path

    def restore_backup(
        self, filename: str, confirmed: bool = False
    ) -> dict[str, Any]:
        self.context._require_role("admin")
        if not confirmed:
            raise WarehouseError(
                "Восстановление требует явного подтверждения"
            )
        with self.context.lock:
            selected = self.backup_by_name(filename)
            check = self.context.database_check(
                selected, self.context.restore_base_tables
            )
            if not check["ok"]:
                raise WarehouseError(
                    "Выбранный backup повреждён или не содержит ключевые таблицы"
                )
            with connect(self.context.db_path) as db:
                self.context._audit(
                    db, "RESTORE_START", "database_backup", selected.name
                )
            safety = self.create_backup(prefix="warehouse_before_restore")
            temporary = self.context.db_path.with_name(
                f".{self.context.db_path.name}.restore_tmp"
            )
            try:
                shutil.copy2(selected, temporary)
                os.replace(temporary, self.context.db_path)
                for suffix in ("-wal", "-shm"):
                    Path(str(self.context.db_path) + suffix).unlink(
                        missing_ok=True
                    )
                initialize(self.context.db_path)
                final_check = self.context.database_check(
                    self.context.db_path, self.context.key_tables
                )
                if not final_check["ok"]:
                    raise WarehouseError(
                        "Восстановленная база не прошла проверку целостности"
                    )
                with connect(self.context.db_path) as db:
                    self.context._audit(
                        db,
                        "RESTORE_SUCCESS",
                        "database_backup",
                        selected.name,
                        {"safety_backup": safety["name"]},
                    )
                return {
                    "ok": True,
                    "restored_from": selected.name,
                    "safety_backup": safety["name"],
                    "integrity": final_check,
                }
            except Exception as error:
                temporary.unlink(missing_ok=True)
                safety_path = self.backup_by_name(safety["name"])
                shutil.copy2(safety_path, temporary)
                os.replace(temporary, self.context.db_path)
                initialize(self.context.db_path)
                with connect(self.context.db_path) as db:
                    self.context._audit(
                        db,
                        "RESTORE_ROLLBACK",
                        "database_backup",
                        selected.name,
                        {
                            "error": str(error),
                            "safety_backup": safety["name"],
                        },
                    )
                if isinstance(error, WarehouseError):
                    raise
                raise WarehouseError(
                    f"Не удалось восстановить backup: {error}"
                ) from error

    def replace_production_database(
        self, uploaded_path: str | Path, confirmed: bool = False
    ) -> dict[str, Any]:
        """Safely replace the working database with an uploaded SQLite file."""
        actor = self.context._require_role("admin")
        if not confirmed:
            raise WarehouseError(
                "Загрузка базы в прод требует явного подтверждения"
            )
        source = Path(uploaded_path)
        if not source.is_file() or source.suffix.lower() != ".db":
            raise WarehouseError("Выберите SQLite-файл с расширением .db")
        source_check = self.context.database_check(
            source, self.context.restore_base_tables
        )
        if not source_check["ok"]:
            raise WarehouseError(
                "Загруженная база повреждена или не содержит ключевые таблицы"
            )
        with self.context.lock:
            safety = self.create_backup(prefix="warehouse_before_prod_upload")
            temporary = self.context.db_path.with_name(
                f".{self.context.db_path.name}.prod_upload_tmp"
            )
            try:
                shutil.copy2(source, temporary)
                os.replace(temporary, self.context.db_path)
                for suffix in ("-wal", "-shm"):
                    Path(str(self.context.db_path) + suffix).unlink(
                        missing_ok=True
                    )
                initialize(self.context.db_path)
                final_check = self.context.database_check(
                    self.context.db_path, self.context.key_tables
                )
                if not final_check["ok"]:
                    raise WarehouseError(
                        "Загруженная база не прошла итоговую проверку"
                    )
                with connect(self.context.db_path) as db:
                    active_admins = int(
                        db.execute(
                            """SELECT count(*) FROM users
                               WHERE role = 'admin' AND is_active = 1"""
                        ).fetchone()[0]
                    )
                    if active_admins == 0:
                        raise WarehouseError(
                            "В загруженной базе нет активного администратора"
                        )
                    self.context._audit(
                        db,
                        "PRODUCTION_DATABASE_UPLOAD",
                        "database",
                        source.name,
                        {
                            "safety_backup": safety["name"],
                            "uploaded_by": actor["email"],
                        },
                    )
                return {
                    "ok": True,
                    "uploaded": source.name,
                    "safety_backup": safety["name"],
                    "integrity": final_check,
                }
            except Exception as error:
                temporary.unlink(missing_ok=True)
                safety_path = self.backup_by_name(safety["name"])
                shutil.copy2(safety_path, temporary)
                os.replace(temporary, self.context.db_path)
                initialize(self.context.db_path)
                with connect(self.context.db_path) as db:
                    self.context._audit(
                        db,
                        "PRODUCTION_DATABASE_ROLLBACK",
                        "database",
                        source.name,
                        {
                            "error": str(error),
                            "safety_backup": safety["name"],
                        },
                    )
                if isinstance(error, WarehouseError):
                    raise
                raise WarehouseError(
                    f"Не удалось загрузить базу в прод: {error}"
                ) from error
