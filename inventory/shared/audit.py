"""Audit helpers for service modules."""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Protocol


class AuditContext(Protocol):
    _actor_email: Any
    _actor_name: Any


def write_audit(
    service: AuditContext,
    db: sqlite3.Connection,
    action: str,
    entity_type: str,
    entity_id: int | str | None = None,
    details: dict[str, Any] | str | None = None,
) -> None:
    serialized = (
        json.dumps(details, ensure_ascii=False, sort_keys=True)
        if isinstance(details, dict)
        else str(details or "")
    )
    db.execute(
        """INSERT INTO audit_log(action, entity_type, entity_id, details, author)
           VALUES (?, ?, ?, ?, ?)""",
        (
            action,
            entity_type,
            "" if entity_id is None else str(entity_id),
            serialized,
            service._actor_name.get() or service._actor_email.get() or "lokolis",
        ),
    )


def write_audit_entry(
    db: sqlite3.Connection,
    *,
    action: str,
    entity_type: str,
    author: str,
    entity_id: int | str | None = None,
    details: dict[str, Any] | str | None = None,
) -> None:
    serialized = (
        json.dumps(details, ensure_ascii=False, sort_keys=True)
        if isinstance(details, dict)
        else str(details or "")
    )
    db.execute(
        """INSERT INTO audit_log(action, entity_type, entity_id, details, author)
           VALUES (?, ?, ?, ?, ?)""",
        (
            action,
            entity_type,
            "" if entity_id is None else str(entity_id),
            serialized,
            author or "lokolis",
        ),
    )
