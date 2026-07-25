"""Versioned, external SQLite workspace for FULL inventory Preview evidence."""

from __future__ import annotations

from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
from typing import Any, Iterator


APPLICATION_ID = 0x4F445057
SCHEMA_VERSION = 2
_HERE = Path(__file__).resolve().parent
_SCHEMA = _HERE / "workspace_schema.sql"
_MIGRATION_V1_V2 = _HERE / "workspace_v1_to_v2.sql"
_REQUIRED_TABLES = {
    "preview_sessions",
    "preview_runs",
    "preview_rows",
    "preview_cells",
    "preview_findings",
    "preview_matches",
    "preview_resolutions",
    "preview_statistics",
    "preview_activity_events",
}
_REQUIRED_TRIGGERS = {
    "tr_preview_runs_session_insert",
    "tr_preview_runs_session_update",
    "tr_preview_activity_no_update",
    "tr_preview_activity_no_delete",
    "tr_preview_resolutions_no_update",
    "tr_preview_resolutions_no_delete",
    "tr_preview_session_active_run_insert",
    "tr_preview_session_active_run_update",
}


class WorkspaceError(RuntimeError):
    code = "FULL_INVENTORY_WORKSPACE_INVALID"


def _connect(path: Path, *, read_only: bool = False) -> sqlite3.Connection:
    if read_only:
        connection = sqlite3.connect(
            f"file:{path.as_posix()}?mode=ro", uri=True, timeout=10
        )
    else:
        connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 10000")
    connection.execute("PRAGMA trusted_schema = OFF")
    if read_only:
        connection.execute("PRAGMA query_only = ON")
    return connection


def secure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink() or not path.is_dir():
        raise WorkspaceError("Runtime state directory must be a real directory")
    try:
        path.chmod(0o700)
    except OSError as error:
        raise WorkspaceError("Cannot secure runtime state directory") from error


def secure_file(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise WorkspaceError("Workspace must be a regular file")
    try:
        path.chmod(0o600)
    except OSError as error:
        raise WorkspaceError("Cannot secure workspace file") from error


def _normalized_sql(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).replace(" IF NOT EXISTS ", " ")


def schema_manifest(connection: sqlite3.Connection) -> dict[str, Any]:
    objects = []
    for row in connection.execute(
        """SELECT type,name,tbl_name,sql FROM sqlite_master
           WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"""
    ):
        objects.append(
            {
                "type": str(row["type"]),
                "name": str(row["name"]),
                "table": str(row["tbl_name"]),
            }
        )
    tables: dict[str, list[dict[str, Any]]] = {}
    indexes: dict[str, list[dict[str, Any]]] = {}
    for table in sorted(_REQUIRED_TABLES):
        tables[table] = [
            {
                "name": str(row["name"]),
                "type": str(row["type"]),
                "notnull": int(row["notnull"]),
                "default": row["dflt_value"],
                "pk": int(row["pk"]),
            }
            for row in connection.execute(f'PRAGMA table_info("{table}")')
        ]
        indexes[table] = []
        for index in connection.execute(f'PRAGMA index_list("{table}")'):
            index_name = str(index["name"])
            indexes[table].append({
                "name": index_name,
                "unique": int(index["unique"]),
                "partial": int(index["partial"]),
                "columns": [
                    str(column["name"] or "")
                    for column in connection.execute(
                        f'PRAGMA index_info("{index_name}")'
                    )
                ],
            })
    return {
        "version": SCHEMA_VERSION,
        "objects": objects,
        "tables": tables,
        "indexes": indexes,
    }


def schema_fingerprint(connection: sqlite3.Connection) -> str:
    payload = json.dumps(
        schema_manifest(connection), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def verify_workspace(path: str | Path, *, verify_sources: bool = False) -> dict[str, Any]:
    target = Path(path)
    if target.is_symlink() or not target.is_file():
        raise WorkspaceError("Workspace file is missing or is not regular")
    sidecars = [
        Path(str(target) + suffix)
        for suffix in ("-wal", "-shm", "-journal")
        if Path(str(target) + suffix).exists()
    ]
    if sidecars:
        raise WorkspaceError("Workspace has unexpected SQLite sidecars")
    with closing(_connect(target, read_only=True)) as db:
        application_id = int(db.execute("PRAGMA application_id").fetchone()[0])
        version = int(db.execute("PRAGMA user_version").fetchone()[0])
        if application_id != APPLICATION_ID:
            raise WorkspaceError("Workspace application_id mismatch")
        if version != SCHEMA_VERSION:
            raise WorkspaceError("Unsupported workspace schema version")
        rows = db.execute(
            "SELECT type,name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
        ).fetchall()
        tables = {str(row["name"]) for row in rows if row["type"] == "table"}
        triggers = {str(row["name"]) for row in rows if row["type"] == "trigger"}
        if not _REQUIRED_TABLES.issubset(tables):
            raise WorkspaceError("Workspace schema is incomplete")
        if not _REQUIRED_TRIGGERS.issubset(triggers):
            raise WorkspaceError("Workspace append-only/FK guards are incomplete")
        integrity = str(db.execute("PRAGMA integrity_check").fetchone()[0])
        foreign_keys = [tuple(row) for row in db.execute("PRAGMA foreign_key_check")]
        if integrity != "ok" or foreign_keys:
            raise WorkspaceError("Workspace integrity or foreign keys failed")
        sessions = [dict(row) for row in db.execute("SELECT * FROM preview_sessions")]
        if verify_sources:
            for session in sessions:
                if session["source_opaque_key"] and session["source_sha256"] is None:
                    raise WorkspaceError("Workspace source provenance is incomplete")
        return {
            "path": target,
            "application_id": application_id,
            "user_version": version,
            "integrity_check": integrity,
            "foreign_key_check": len(foreign_keys),
            "schema_fingerprint": schema_fingerprint(db),
            "sessions": sessions,
        }


def create_workspace(path: str | Path) -> dict[str, Any]:
    target = Path(path)
    secure_directory(target.parent)
    if target.exists() or target.is_symlink():
        raise WorkspaceError("Workspace already exists")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        temporary.chmod(0o600)
        with closing(_connect(temporary)) as db:
            db.executescript(_SCHEMA.read_text(encoding="utf-8"))
        secure_file(temporary)
        os.replace(temporary, target)
        secure_file(target)
        return verify_workspace(target)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def migrate_workspace(path: str | Path) -> dict[str, Any]:
    target = Path(path)
    secure_file(target)
    with closing(_connect(target)) as db:
        application_id = int(db.execute("PRAGMA application_id").fetchone()[0])
        version = int(db.execute("PRAGMA user_version").fetchone()[0])
        if application_id != APPLICATION_ID:
            raise WorkspaceError("Workspace application_id mismatch")
        if version == SCHEMA_VERSION:
            pass
        elif version == 1:
            tables = {
                str(row[0])
                for row in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            if "preview_runs" not in tables or "preview_sessions" in tables:
                raise WorkspaceError("Workspace v1 schema is not recognized")
            db.executescript(_MIGRATION_V1_V2.read_text(encoding="utf-8"))
        else:
            raise WorkspaceError("Unsupported workspace schema version")
    secure_file(target)
    return verify_workspace(target)


def iter_workspace_files(previews_root: str | Path) -> Iterator[Path]:
    root = Path(previews_root)
    if not root.exists():
        return
    if root.is_symlink() or not root.is_dir():
        raise WorkspaceError("Preview root is not a trusted directory")
    for path in sorted(root.glob("*.db")):
        if path.is_file() and not path.is_symlink():
            yield path


class WorkspaceStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def connect(self, *, read_only: bool = False) -> sqlite3.Connection:
        return _connect(self.path, read_only=read_only)

    def verify(self) -> dict[str, Any]:
        return verify_workspace(self.path)

    def append_activity(
        self,
        *,
        session_id: str,
        event_type: str,
        actor_id: str,
        actor_display: str,
        actor_role: str,
        occurred_at: int,
        correlation_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        safe = metadata or {}
        forbidden = {"password", "password_hash", "token", "session_token", "path", "payload"}
        if forbidden.intersection(key.casefold() for key in safe):
            raise WorkspaceError("Sensitive activity metadata is forbidden")
        encoded = json.dumps(safe, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        with closing(self.connect()) as db:
            db.execute(
                """INSERT INTO preview_activity_events(
                       session_id,event_type,actor_id,actor_display_snapshot,
                       actor_role_snapshot,occurred_at,correlation_id,safe_metadata_json
                   ) VALUES (?,?,?,?,?,?,?,?)""",
                (
                    session_id,
                    event_type,
                    actor_id,
                    actor_display,
                    actor_role,
                    occurred_at,
                    correlation_id,
                    encoded,
                ),
            )
            db.commit()
