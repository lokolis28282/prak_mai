"""Verified SQLite snapshots for all independent ODE runtime databases."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from ..db import connect
from ..shared.helpers import WarehouseError
from .runtime_databases import RuntimeDatabase, RuntimeDatabaseRegistry


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SIDECAR_SUFFIXES = ("-wal", "-shm", "-journal")


class MultiDatabaseBackupContext(Protocol):
    db_path: Path
    lock: Any

    def _require_role(self, *roles: str) -> dict[str, Any]: ...

    def _audit(
        self,
        db: sqlite3.Connection,
        action: str,
        entity_type: str,
        entity_id: int | str | None = None,
        details: dict[str, Any] | str | None = None,
    ) -> None: ...


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _default_backup_root(primary_database: Path) -> Path:
    configured = os.environ.get("ODE_BACKUP_DIR", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    primary = primary_database.expanduser().resolve()
    if not _is_within(primary, REPOSITORY_ROOT):
        return primary.parent / "ode-runtime-backups"
    if os.name == "nt":
        base = Path(
            os.environ.get("LOCALAPPDATA")
            or os.environ.get("APPDATA")
            or primary.parent.parent
        )
        return (base / "ODE" / "backups").resolve()
    data_home = os.environ.get("XDG_DATA_HOME", "").strip()
    base = Path(data_home).expanduser() if data_home else Path.home() / ".local" / "share"
    return (base / "ode" / "backups").resolve()


class MultiDatabaseBackupService:
    """Read database health and create verified external SQLite backups."""

    def __init__(
        self,
        context: MultiDatabaseBackupContext,
        registry: RuntimeDatabaseRegistry,
        *,
        backup_root: str | Path | None = None,
    ):
        self.context = context
        self.registry = registry
        self.backup_root = (
            Path(os.path.abspath(Path(backup_root).expanduser()))
            if backup_root is not None
            else _default_backup_root(context.db_path)
        )

    def configure(
        self,
        registry: RuntimeDatabaseRegistry,
        *,
        backup_root: str | Path | None = None,
    ) -> None:
        self.registry = registry
        if backup_root is not None:
            self.backup_root = Path(
                os.path.abspath(Path(backup_root).expanduser())
            )

    @staticmethod
    def _source_guard(database: RuntimeDatabase) -> None:
        candidate = database.path
        if candidate.is_symlink():
            raise WarehouseError(
                f"{database.label}: symbolic link нельзя использовать как runtime-базу"
            )
        if not candidate.is_file():
            raise WarehouseError(f"{database.label}: файл базы не найден")
        try:
            if candidate.stat().st_nlink > 1:
                raise WarehouseError(
                    f"{database.label}: hardlink нельзя использовать как runtime-базу"
                )
        except OSError as error:
            raise WarehouseError(
                f"{database.label}: не удалось проверить файл базы"
            ) from error

    def _storage_root(self, *, create: bool) -> Path:
        root = self.backup_root
        if root.exists() and root.is_symlink():
            raise WarehouseError(
                "Каталог резервных копий не может быть symbolic link"
            )
        resolved_root = root.resolve()
        if _is_within(resolved_root, REPOSITORY_ROOT):
            raise WarehouseError(
                "Каталог резервных копий должен находиться вне Git-репозитория"
            )
        if create:
            root.mkdir(parents=True, exist_ok=True)
        return root

    def _database_directory(
        self, database: RuntimeDatabase, *, create: bool
    ) -> Path:
        directory = self._storage_root(create=create) / database.database_id
        if directory.exists() and directory.is_symlink():
            raise WarehouseError(
                "Каталог конкретной runtime-базы не может быть symbolic link"
            )
        if create:
            directory.mkdir(parents=True, exist_ok=True)
        return directory

    @staticmethod
    def _health(
        path: Path,
        required_tables: frozenset[str],
        *,
        guard_alias: bool = False,
    ) -> dict[str, Any]:
        if not path.is_file():
            return {
                "ok": False,
                "integrity": ["Файл базы не найден"],
                "foreign_key_errors": 0,
                "missing_tables": sorted(required_tables),
                "sidecars": [],
            }
        if path.is_symlink():
            return {
                "ok": False,
                "integrity": ["Symbolic link запрещён"],
                "foreign_key_errors": 0,
                "missing_tables": sorted(required_tables),
                "sidecars": [],
            }
        if guard_alias and path.stat().st_nlink > 1:
            return {
                "ok": False,
                "integrity": ["Hardlink запрещён"],
                "foreign_key_errors": 0,
                "missing_tables": sorted(required_tables),
                "sidecars": [],
            }
        sidecars = [
            Path(str(path) + suffix).name
            for suffix in SIDECAR_SUFFIXES
            if Path(str(path) + suffix).exists()
        ]
        try:
            uri = f"file:{path.resolve().as_posix()}?mode=ro"
            with closing(sqlite3.connect(uri, uri=True)) as database:
                database.execute("PRAGMA query_only=ON")
                integrity = [
                    str(row[0])
                    for row in database.execute("PRAGMA integrity_check")
                ]
                foreign_key_errors = len(
                    database.execute("PRAGMA foreign_key_check").fetchall()
                )
                tables = {
                    str(row[0])
                    for row in database.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
        except (OSError, sqlite3.Error) as error:
            return {
                "ok": False,
                "integrity": [str(error)],
                "foreign_key_errors": 0,
                "missing_tables": sorted(required_tables),
                "sidecars": sidecars,
            }
        missing = sorted(required_tables - tables)
        return {
            "ok": integrity == ["ok"] and not foreign_key_errors and not missing,
            "integrity": integrity,
            "foreign_key_errors": foreign_key_errors,
            "missing_tables": missing,
            "sidecars": sidecars,
        }

    def list_backups(
        self, database_id: str | None = None
    ) -> list[dict[str, Any]]:
        self.context._require_role("admin")
        databases = (
            (self.registry.get(database_id),)
            if database_id
            else self.registry.all()
        )
        result: list[dict[str, Any]] = []
        for database in databases:
            directory = self._database_directory(database, create=False)
            if not directory.is_dir():
                continue
            for path in directory.glob(f"{database.database_id}_*.db"):
                if not path.is_file() or path.is_symlink():
                    continue
                stat = path.stat()
                manifest_path = path.with_suffix(".manifest.json")
                manifest: dict[str, Any] = {}
                if manifest_path.is_file() and not manifest_path.is_symlink():
                    try:
                        loaded = json.loads(
                            manifest_path.read_text(encoding="utf-8")
                        )
                        if isinstance(loaded, dict):
                            manifest = loaded
                    except (OSError, ValueError):
                        manifest = {}
                result.append(
                    {
                        "database_id": database.database_id,
                        "database_label": database.label,
                        "name": path.name,
                        "size": stat.st_size,
                        "modified": datetime.fromtimestamp(
                            stat.st_mtime, timezone.utc
                        ).isoformat(timespec="seconds"),
                        "sha256": str(manifest.get("sha256") or ""),
                        "verified": bool(
                            isinstance(manifest.get("verification"), dict)
                            and manifest["verification"].get("ok")
                        ),
                    }
                )
        return sorted(
            result,
            key=lambda item: (str(item["modified"]), str(item["name"])),
            reverse=True,
        )

    def database_statuses(self) -> list[dict[str, Any]]:
        self.context._require_role("admin")
        backups = self.list_backups()
        last_by_database: dict[str, dict[str, Any]] = {}
        for backup in backups:
            last_by_database.setdefault(str(backup["database_id"]), backup)
        result = []
        for database in self.registry.all():
            path = database.path
            health = self._health(
                path, database.required_tables, guard_alias=True
            )
            stat = path.stat() if path.is_file() else None
            result.append(
                {
                    "database_id": database.database_id,
                    "label": database.label,
                    "profile": database.profile,
                    "path": str(path),
                    "exists": stat is not None,
                    "size": stat.st_size if stat is not None else 0,
                    "modified": (
                        datetime.fromtimestamp(
                            stat.st_mtime, timezone.utc
                        ).isoformat(timespec="seconds")
                        if stat is not None
                        else ""
                    ),
                    "health": health,
                    "last_backup": last_by_database.get(database.database_id),
                }
            )
        return result

    def capabilities(self) -> dict[str, Any]:
        self.context._require_role("admin")
        return {
            "backup_root": str(self.backup_root),
            "create_backup": True,
            "restore": {
                "available": False,
                "reason": (
                    "Восстановление отключено до реализации проверяемого "
                    "токена предварительной проверки и атомарной публикации."
                ),
            },
        }

    @staticmethod
    def _fsync(path: Path) -> None:
        # Windows rejects FlushFileBuffers for a read-only descriptor.
        with path.open("r+b") as stream:
            os.fsync(stream.fileno())

    def create_backup(self, database_id: str) -> dict[str, Any]:
        self.context._require_role("admin")
        try:
            database = self.registry.get(database_id)
        except ValueError as error:
            raise WarehouseError(str(error)) from error
        with self.context.lock:
            self._source_guard(database)
            directory = self._database_directory(database, create=True)
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            nonce = secrets.token_hex(4)
            final_path = directory / (
                f"{database.database_id}_{timestamp}_{nonce}.db"
            )
            next_path = final_path.with_suffix(".db.next")
            manifest_path = final_path.with_suffix(".manifest.json")
            manifest_next = manifest_path.with_suffix(".json.next")
            if any(
                path.exists() or path.is_symlink()
                for path in (final_path, next_path, manifest_path, manifest_next)
            ):
                raise WarehouseError(
                    "Не удалось выбрать уникальное имя резервной копии"
                )
            try:
                source_uri = f"file:{database.path.as_posix()}?mode=ro"
                with (
                    closing(sqlite3.connect(source_uri, uri=True)) as source,
                    closing(sqlite3.connect(next_path)) as target,
                ):
                    source.execute("PRAGMA query_only=ON")
                    source.backup(target)
                os.chmod(next_path, 0o600)
                self._fsync(next_path)
                verification = self._health(
                    next_path, database.required_tables, guard_alias=True
                )
                if not verification["ok"]:
                    raise WarehouseError(
                        "Резервная копия не прошла integrity/FK/schema-проверку"
                    )
                digest = _sha256(next_path)
                manifest = {
                    "format": 1,
                    "database_id": database.database_id,
                    "database_label": database.label,
                    "profile": database.profile,
                    "source_path": str(database.path),
                    "created_at": datetime.now(timezone.utc).isoformat(
                        timespec="seconds"
                    ),
                    "filename": final_path.name,
                    "size": next_path.stat().st_size,
                    "sha256": digest,
                    "verification": verification,
                    "method": "sqlite_backup_api",
                }
                manifest_next.write_text(
                    json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                os.chmod(manifest_next, 0o600)
                self._fsync(manifest_next)
                os.replace(next_path, final_path)
                os.replace(manifest_next, manifest_path)
                with connect(self.context.db_path) as audit_db:
                    self.context._audit(
                        audit_db,
                        "RUNTIME_DATABASE_BACKUP_CREATE",
                        "runtime_database_backup",
                        database.database_id,
                        {
                            "database_id": database.database_id,
                            "filename": final_path.name,
                            "size": final_path.stat().st_size,
                            "sha256": digest,
                            "integrity": "ok",
                            "foreign_key_errors": 0,
                            "schema_compatible": True,
                        },
                    )
                return {
                    "database_id": database.database_id,
                    "database_label": database.label,
                    "name": final_path.name,
                    "size": final_path.stat().st_size,
                    "modified": datetime.fromtimestamp(
                        final_path.stat().st_mtime, timezone.utc
                    ).isoformat(timespec="seconds"),
                    "sha256": digest,
                    "verified": True,
                }
            except WarehouseError:
                final_path.unlink(missing_ok=True)
                manifest_path.unlink(missing_ok=True)
                raise
            except (OSError, sqlite3.Error) as error:
                final_path.unlink(missing_ok=True)
                manifest_path.unlink(missing_ok=True)
                raise WarehouseError(
                    f"Не удалось создать резервную копию {database.label}"
                ) from error
            finally:
                next_path.unlink(missing_ok=True)
                manifest_next.unlink(missing_ok=True)


__all__ = ["MultiDatabaseBackupService"]
