"""Administration-owned access to the shared audit log."""

from __future__ import annotations

import sqlite3
from typing import Any, Protocol

from ..db import connect
from ..shared.audit import write_audit
from ..shared.helpers import WarehouseError


class AdministrationContext(Protocol):
    db_path: Any
    _actor_email: Any
    _actor_name: Any

    def _require_role(self, *roles: str) -> dict[str, Any]: ...


class AdministrationAuditService:
    def __init__(self, context: AdministrationContext):
        self.context = context

    def write(
        self,
        db: sqlite3.Connection,
        action: str,
        entity_type: str,
        entity_id: int | str | None = None,
        details: dict[str, Any] | str | None = None,
    ) -> None:
        write_audit(
            self.context,
            db,
            action,
            entity_type,
            entity_id,
            details,
        )

    def entries(self, limit: int = 200) -> list[dict[str, Any]]:
        self.context._require_role("admin")
        if limit <= 0 or limit > 5000:
            raise WarehouseError("Лимит аудита должен быть от 1 до 5000")
        with connect(self.context.db_path) as db:
            return [
                dict(row)
                for row in db.execute(
                    """SELECT id, event_date, action, entity_type, entity_id, details, author
                       FROM audit_log ORDER BY event_date DESC, id DESC LIMIT ?""",
                    (limit,),
                )
            ]
