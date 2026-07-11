"""Internal event contracts between product modules."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol


WAREHOUSE_EVENT_TYPES = {
    "RECEIPT_CREATED",
    "ISSUE_CREATED",
    "DELIVERY_IMPORTED",
    "DELIVERY_ACCEPTED",
    "CABLE_RECEIVED",
    "CABLE_ISSUED",
    "INVENTORY_CHECKED",
}


@dataclass(frozen=True)
class WarehouseEvent:
    event_type: str
    occurred_at: str
    actor: str
    entity_id: str = ""
    payload: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_audit_row(cls, row: dict[str, Any]) -> "WarehouseEvent":
        return cls(
            event_type=str(row.get("action") or ""),
            occurred_at=str(row.get("event_date") or datetime.utcnow().isoformat()),
            actor=str(row.get("author") or row.get("engineer") or ""),
            entity_id=str(row.get("entity_id") or ""),
            payload={"details": row.get("details", "")},
        )


class EventReader(Protocol):
    def warehouse_events(self, limit: int = 300) -> list[WarehouseEvent]:
        """Return read-only warehouse events for reporting."""


class EventPublisher(Protocol):
    def publish(self, event: WarehouseEvent) -> None:
        """Publish an internal event without coupling modules."""


class AuditLogEventReader:
    """Temporary event reader backed by the existing audit/history data."""

    def __init__(self, service: Any):
        self.service = service

    def warehouse_events(self, limit: int = 300) -> list[WarehouseEvent]:
        rows = self.service.warehouse_history(limit=limit)
        return [
            WarehouseEvent(
                event_type=str(row.get("action") or ""),
                occurred_at=str(row.get("event_date") or ""),
                actor=str(row.get("engineer") or ""),
                entity_id=str(row.get("serial_number") or row.get("entity_id") or ""),
                payload=dict(row),
            )
            for row in rows
        ]


class NoopEventPublisher:
    """Publisher placeholder; warehouse writes must not depend on subscribers."""

    def publish(self, event: WarehouseEvent) -> None:
        return None
