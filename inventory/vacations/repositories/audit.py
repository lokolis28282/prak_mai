"""History and audit persistence owned by Vacations."""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Iterable

from inventory.shared.db import connect


class VacationAuditRepository:
    """Shared persistence primitives used inside vacation transactions."""

    def history(self, limit: int = 200) -> list[dict[str, Any]]:
        with connect(self.db_path) as db:
            return [
                dict(row)
                for row in db.execute(
                    """SELECT * FROM vacation_history
                       ORDER BY id DESC LIMIT ?""",
                    (limit,),
                ).fetchall()
            ]

    @staticmethod
    def _replace_conflicts(
        db: sqlite3.Connection,
        request_id: int,
        conflicts: Iterable[dict[str, Any]],
    ) -> None:
        db.executemany(
            """INSERT INTO vacation_conflicts(
                   request_id, code, conflict_date, related_employee_id, details
               ) VALUES (?, ?, ?, ?, ?)""",
            [
                (
                    request_id,
                    conflict["code"],
                    conflict.get("conflict_date"),
                    conflict.get("related_employee_id"),
                    conflict["details"],
                )
                for conflict in conflicts
            ],
        )

    @staticmethod
    def _history(
        db: sqlite3.Connection,
        entity_type: str,
        entity_id: int,
        action: str,
        actor: str,
        details: dict[str, Any],
    ) -> None:
        db.execute(
            """INSERT INTO vacation_history(
                   entity_type, entity_id, action, actor, details
               ) VALUES (?, ?, ?, ?, ?)""",
            (
                entity_type,
                entity_id,
                action,
                actor,
                json.dumps(details, ensure_ascii=False, sort_keys=True),
            ),
        )

    @staticmethod
    def _audit(
        db: sqlite3.Connection,
        *,
        action: str,
        entity_type: str,
        actor: str,
        entity_id: int | str | None = None,
        details: dict[str, Any] | str | None = None,
    ) -> None:
        serialized = (
            json.dumps(details, ensure_ascii=False, sort_keys=True)
            if isinstance(details, dict)
            else str(details or "")
        )
        db.execute(
            """INSERT INTO vacation_audit_log(
                   action, entity_type, entity_id, actor, details
               ) VALUES (?, ?, ?, ?, ?)""",
            (
                action,
                entity_type,
                "" if entity_id is None else str(entity_id),
                actor,
                serialized,
            ),
        )
