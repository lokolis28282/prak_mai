#!/usr/bin/env python3
"""Safely install additive Reports and Knowledge schemas into an existing DB."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from inventory.db import (
    DEFAULT_DB_PATH,
    install_knowledge_schema,
    install_reports_uvr_schema,
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def database_health(path: Path) -> dict[str, object]:
    uri = f"file:{path.as_posix()}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as connection:
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        work_log_columns = {
            str(row[1]) for row in connection.execute("PRAGMA table_info(work_logs)")
        }
    return {
        "sha256": sha256(path),
        "size_bytes": path.stat().st_size,
        "integrity_check": integrity,
        "foreign_key_violations": len(foreign_keys),
        "reports_ready": {"section", "needs_review"} <= work_log_columns,
        "knowledge_ready": {
            "knowledge_articles", "knowledge_attachments", "knowledge_article_tags",
        } <= tables,
    }


def sidecars(path: Path) -> list[str]:
    return [
        candidate.name
        for suffix in ("-wal", "-shm", "-journal")
        if (candidate := Path(str(path) + suffix)).exists()
    ]


def fsync_path(path: Path) -> None:
    with path.open("r+b") as stream:
        os.fsync(stream.fileno())


def create_backups(source: Path, directory: Path) -> dict[str, object]:
    directory.mkdir(parents=True, mode=0o700, exist_ok=False)
    byte_copy = directory / "warehouse.before-runtime-modules.db"
    sqlite_backup = directory / "warehouse.before-runtime-modules.sqlite-backup.db"
    shutil.copy2(source, byte_copy)
    fsync_path(byte_copy)
    with closing(sqlite3.connect(source)) as source_db:
        with closing(sqlite3.connect(sqlite_backup)) as target_db:
            source_db.backup(target_db)
    fsync_path(sqlite_backup)
    if sha256(byte_copy) != sha256(source):
        raise RuntimeError("Byte-copy backup SHA-256 mismatch")
    sqlite_health = database_health(sqlite_backup)
    if sqlite_health["integrity_check"] != "ok" or sqlite_health["foreign_key_violations"]:
        raise RuntimeError("SQLite backup validation failed")
    return {
        "byte_copy": str(byte_copy),
        "byte_copy_sha256": sha256(byte_copy),
        "sqlite_backup": str(sqlite_backup),
        "sqlite_backup_sha256": sha256(sqlite_backup),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Проверяемая миграция Reports/Knowledge с внешним backup"
    )
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="существующая SQLite-база")
    parser.add_argument("--backup-dir", help="новый каталог backup вне репозитория")
    parser.add_argument("--apply", action="store_true", help="применить миграцию")
    args = parser.parse_args()

    database = Path(args.db).expanduser().resolve()
    if not database.is_file() or database.is_symlink():
        raise SystemExit(f"Некорректный путь к существующей БД: {database}")
    before_sidecars = sidecars(database)
    before = database_health(database)
    if before["integrity_check"] != "ok" or before["foreign_key_violations"]:
        raise SystemExit("Preflight DB health check failed")
    if before_sidecars:
        raise SystemExit("Остановите writers и удалите SQLite sidecars штатным закрытием: " + ", ".join(before_sidecars))

    if not args.apply:
        print(json.dumps({"database": str(database), "status": before}, ensure_ascii=False, indent=2))
        return 0
    if not args.backup_dir:
        raise SystemExit("Для --apply обязателен новый --backup-dir вне репозитория")
    backup_dir = Path(args.backup_dir).expanduser().resolve()
    try:
        backup_dir.relative_to(ROOT)
    except ValueError:
        pass
    else:
        raise SystemExit("Backup-каталог должен находиться вне репозитория")
    if backup_dir.exists() or backup_dir.is_symlink():
        raise SystemExit("Backup-каталог уже существует или является symlink")

    backups = create_backups(database, backup_dir)
    install_reports_uvr_schema(database)
    install_knowledge_schema(database)
    after = database_health(database)
    after_sidecars = sidecars(database)
    if after["integrity_check"] != "ok" or after["foreign_key_violations"]:
        raise SystemExit("Post-migration DB health check failed; restore external backup")
    if not after["reports_ready"] or not after["knowledge_ready"]:
        raise SystemExit("Runtime module schema is incomplete; restore external backup")
    if after_sidecars:
        raise SystemExit("Unexpected SQLite sidecars after migration")

    manifest = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "database": str(database),
        "before": before,
        "after": after,
        "backups": backups,
        "sidecars_before": before_sidecars,
        "sidecars_after": after_sidecars,
    }
    manifest_path = backup_dir / "runtime-modules-migration-manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if os.name == "posix":
        manifest_path.chmod(0o600)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
