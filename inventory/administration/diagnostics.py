"""Database integrity diagnostics owned by Administration."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Protocol

from ..db import connect


class AdministrationContext(Protocol):
    db_path: Path
    lock: Any
    key_tables: set[str]

    def _require_role(self, *roles: str) -> dict[str, Any]: ...

    def _audit(
        self,
        db: sqlite3.Connection,
        action: str,
        entity_type: str,
        entity_id: int | str | None = None,
        details: dict[str, Any] | str | None = None,
    ) -> None: ...


class AdministrationDiagnosticsService:
    def __init__(self, context: AdministrationContext):
        self.context = context

    @staticmethod
    def database_check(path: Path, required_tables: set[str]) -> dict[str, Any]:
        try:
            with closing(sqlite3.connect(path)) as db:
                db.execute("PRAGMA foreign_keys = ON")
                messages = [str(row[0]) for row in db.execute("PRAGMA integrity_check")]
                foreign_key_errors = [
                    tuple(row) for row in db.execute("PRAGMA foreign_key_check")
                ]
                tables = {
                    str(row[0])
                    for row in db.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
        except sqlite3.Error as error:
            return {
                "ok": False,
                "messages": [str(error)],
                "missing_tables": sorted(required_tables),
                "foreign_key_errors": [],
            }
        missing = sorted(required_tables - tables)
        return {
            "ok": messages == ["ok"] and not missing and not foreign_key_errors,
            "messages": messages,
            "missing_tables": missing,
            "foreign_key_errors": foreign_key_errors,
        }

    def check_integrity(self) -> dict[str, Any]:
        self.context._require_role("admin")
        with self.context.lock:
            result = self.database_check(
                self.context.db_path, self.context.key_tables
            )
            try:
                with connect(self.context.db_path) as db:
                    self.context._audit(
                        db, "INTEGRITY_CHECK", "database", details=result
                    )
            except sqlite3.Error:
                # Integrity results must remain visible even if audit_log is damaged.
                pass
            return result
