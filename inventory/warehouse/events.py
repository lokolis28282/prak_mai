"""Warehouse event reader contract for read-only reporting."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

from inventory.db import connect


WAREHOUSE_EVENT_TYPES = {
    "RECEIPT_CREATED",
    "RECEIPT_IMPORTED",
    "ISSUE_CREATED",
    "ISSUE_IMPORTED",
    "DELIVERY_IMPORTED",
    "DELIVERY_ACCEPTED",
    "DELIVERY_UPDATED",
    "DELIVERY_CLOSED",
    "CABLE_RECEIVED",
    "CABLE_ISSUED",
    "INVENTORY_CHECKED",
    "DATA_PROBLEM_FOUND",
}

SECRET_KEYS = {"password", "password_hash", "token", "session", "session_token"}


@dataclass(frozen=True)
class WarehouseEvent:
    event_id: str
    event_type: str
    event_date: str
    event_time: str = ""
    actor: str = ""
    entity_type: str = ""
    entity_id: str = ""
    serial_number: str = ""
    item_name: str = ""
    quantity: float = 0.0
    unit: str = ""
    project: str = ""
    supplier: str = ""
    task_number: str = ""
    comment: str = ""
    source: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _plain(asdict(self))


def _plain(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _plain(item)
            for key, item in value.items()
            if str(key) not in SECRET_KEYS
        }
    if isinstance(value, list):
        return [_plain(item) for item in value]
    if hasattr(value, "keys"):
        return _plain(dict(value))
    return value


def _event_time(value: str) -> str:
    text = str(value or "")
    return text[11:19] if len(text) >= 19 and text[10] in {" ", "T"} else ""


def _date_part(value: str) -> str:
    return str(value or "")[:10]


class WarehouseEventReader:
    """Compatibility-backed public reader for warehouse facts.

    SQL over warehouse-owned tables is intentionally contained in this module.
    Reports receives only WarehouseEvent objects.
    """

    def __init__(self, service: Any):
        self.service = service

    def list_events(
        self,
        date_from: str,
        date_to: str,
        event_types: Iterable[str] | None = None,
        limit: int | None = None,
    ) -> list[WarehouseEvent]:
        start, end = self.service._validated_period(date_from, date_to)
        wanted = set(event_types or [])
        events = [
            *self._receipt_events(start, end),
            *self._issue_events(start, end),
            *self._delivery_events(start, end),
            *self.list_problem_events(start, end),
        ]
        if wanted:
            events = [event for event in events if event.event_type in wanted]
        events = self._dedupe(events)
        events.sort(key=lambda event: (event.event_date, event.event_time, event.source, event.event_id))
        return events[:limit] if limit is not None else events

    def list_report_events(self, date_from: str, date_to: str) -> list[WarehouseEvent]:
        return self.list_events(date_from, date_to)

    def list_problem_events(self, date_from: str, date_to: str) -> list[WarehouseEvent]:
        start, end = self.service._validated_period(date_from, date_to)
        problems = self.service.data_quality_problems(start, end)
        events: list[WarehouseEvent] = []
        for kind, rows in problems.items():
            for index, row in enumerate(rows):
                event_date = _date_part(row.get("date") or row.get("issue_date") or start)
                events.append(WarehouseEvent(
                    event_id=f"problem:{kind}:{row.get('id', index)}:{event_date}",
                    event_type="DATA_PROBLEM_FOUND",
                    event_date=event_date,
                    actor=str(row.get("responsible") or ""),
                    entity_type=kind,
                    entity_id=str(row.get("id") or row.get("serial_number") or index),
                    serial_number=str(row.get("serial_number") or ""),
                    item_name=str(row.get("item_name") or ""),
                    quantity=float(row.get("unmatched_quantity") or row.get("count") or row.get("balance") or 0),
                    unit=str(row.get("unit") or ""),
                    project=str(row.get("project") or ""),
                    comment=str(row.get("comment") or ""),
                    source="warehouse:problems",
                    metadata={"kind": kind, "row": _plain(row)},
                ))
        return events

    def get_event(self, event_id: str) -> WarehouseEvent | None:
        # Bounded broad lookup for diagnostics; reports use range reads.
        events = self.list_events("1900-01-01", "2999-12-31")
        return next((event for event in events if event.event_id == event_id), None)

    @staticmethod
    def _dedupe(events: list[WarehouseEvent]) -> list[WarehouseEvent]:
        result: list[WarehouseEvent] = []
        seen: set[str] = set()
        for event in events:
            if event.event_id in seen:
                continue
            seen.add(event.event_id)
            result.append(event)
        return result

    def _receipt_events(self, start: str, end: str) -> list[WarehouseEvent]:
        with connect(self.service.db_path) as db:
            rows = db.execute(
                """SELECT id, receipt_date, created_at, responsible, item_name, model,
                          inventory_number, serial_number, quantity, unit, project,
                          supplier, order_number, request_number, equipment_type,
                          component_type, cable_type, is_opening_balance
                   FROM stock_receipts
                   WHERE is_opening_balance = 0 AND receipt_date BETWEEN ? AND ?
                   ORDER BY receipt_date, id""",
                (start, end),
            ).fetchall()
        events: list[WarehouseEvent] = []
        for row in rows:
            event_type = "CABLE_RECEIVED" if row["cable_type"] else "RECEIPT_CREATED"
            events.append(WarehouseEvent(
                event_id=f"receipt:{row['id']}",
                event_type=event_type,
                event_date=str(row["receipt_date"]),
                event_time=_event_time(str(row["created_at"] or "")),
                actor=str(row["responsible"] or ""),
                entity_type="stock_receipt",
                entity_id=str(row["id"]),
                serial_number=str(row["serial_number"] or ""),
                item_name=str(row["item_name"] or ""),
                quantity=float(row["quantity"] or 0),
                unit=str(row["unit"] or ""),
                project=str(row["project"] or ""),
                supplier=str(row["supplier"] or ""),
                comment=str(row["order_number"] or row["request_number"] or ""),
                source="warehouse:stock_receipts",
                metadata=_plain(dict(row)),
            ))
        return events

    def _issue_events(self, start: str, end: str) -> list[WarehouseEvent]:
        with connect(self.service.db_path) as db:
            issue_rows = db.execute(
                """SELECT i.id, i.issue_date, i.created_at, i.responsible,
                          i.task_type, i.task_number,
                          COALESCE(NULLIF(i.source_item_name, ''), MIN(r.item_name)) AS item_name,
                          COALESCE(NULLIF(i.source_serial_number, ''), MIN(r.serial_number)) AS serial_number,
                          i.quantity, MIN(r.unit) AS unit, i.comment,
                          MIN(r.project) AS project, MIN(r.supplier) AS supplier,
                          MIN(r.cable_type) AS cable_type,
                          COALESCE(SUM(a.quantity), 0) AS matched_quantity
                   FROM stock_issues i
                   LEFT JOIN stock_issue_allocations a ON a.issue_id = i.id
                   LEFT JOIN stock_receipts r ON r.id = a.receipt_id
                   WHERE i.issue_date BETWEEN ? AND ?
                   GROUP BY i.id ORDER BY i.issue_date, i.id""",
                (start, end),
            ).fetchall()
            allocation_rows = db.execute(
                """SELECT i.id AS issue_id, r.project, r.equipment_type, r.component_type,
                          r.cable_type, SUM(a.quantity) AS quantity
                   FROM stock_issues i
                   JOIN stock_issue_allocations a ON a.issue_id = i.id
                   JOIN stock_receipts r ON r.id = a.receipt_id
                   WHERE i.issue_date BETWEEN ? AND ?
                   GROUP BY i.id, r.project, r.equipment_type, r.component_type, r.cable_type
                   ORDER BY i.id""",
                (start, end),
            ).fetchall()
        allocations: dict[int, list[dict[str, Any]]] = {}
        for row in allocation_rows:
            allocations.setdefault(int(row["issue_id"]), []).append(_plain(dict(row)))
        events: list[WarehouseEvent] = []
        for row in issue_rows:
            issue_id = int(row["id"])
            event_type = "CABLE_ISSUED" if row["cable_type"] else "ISSUE_CREATED"
            task = f"{row['task_type']}-{row['task_number']}" if row["task_type"] else ""
            events.append(WarehouseEvent(
                event_id=f"issue:{issue_id}",
                event_type=event_type,
                event_date=str(row["issue_date"]),
                event_time=_event_time(str(row["created_at"] or "")),
                actor=str(row["responsible"] or ""),
                entity_type="stock_issue",
                entity_id=str(issue_id),
                serial_number=str(row["serial_number"] or ""),
                item_name=str(row["item_name"] or ""),
                quantity=float(row["quantity"] or 0),
                unit=str(row["unit"] or ""),
                project=str(row["project"] or ""),
                supplier=str(row["supplier"] or ""),
                task_number=task,
                comment=str(row["comment"] or ""),
                source="warehouse:stock_issues",
                metadata={**_plain(dict(row)), "allocations": allocations.get(issue_id, [])},
            ))
        return events

    def _delivery_events(self, start: str, end: str) -> list[WarehouseEvent]:
        start_dt, end_dt = f"{start} 00:00:00", f"{end} 23:59:59"
        events: list[WarehouseEvent] = []
        with connect(self.service.db_path) as db:
            uploads = db.execute(
                """SELECT id, uploaded_at, uploaded_by, delivery_number, supplier,
                          source_filename
                   FROM deliveries
                   WHERE datetime(uploaded_at) BETWEEN ? AND ?
                   ORDER BY uploaded_at, id""",
                (start_dt, end_dt),
            ).fetchall()
            accepted = db.execute(
                """SELECT l.id, l.serial_number, l.item_name, l.quantity, l.unit,
                          d.delivery_number, d.supplier, r.receipt_date, r.responsible,
                          r.id AS receipt_id
                   FROM delivery_lines l
                   JOIN deliveries d ON d.id = l.delivery_id
                   JOIN stock_receipts r ON r.id = l.receipt_id
                   WHERE r.receipt_date BETWEEN ? AND ?
                   ORDER BY r.receipt_date, l.id""",
                (start, end),
            ).fetchall()
            problems = db.execute(
                """SELECT l.id, substr(l.updated_at,1,10) AS event_date,
                          substr(l.updated_at,12,8) AS event_time, l.updated_by,
                          l.serial_number, l.error_text, d.delivery_number, d.supplier
                   FROM delivery_lines l
                   JOIN deliveries d ON d.id = l.delivery_id
                   WHERE l.state IN ('Ошибка','Дубль в файле','Уже на складе')
                     AND datetime(l.updated_at) BETWEEN ? AND ?
                   ORDER BY l.updated_at, l.id""",
                (start_dt, end_dt),
            ).fetchall()
        for row in uploads:
            events.append(WarehouseEvent(
                event_id=f"delivery:{row['id']}",
                event_type="DELIVERY_IMPORTED",
                event_date=_date_part(row["uploaded_at"]),
                event_time=_event_time(str(row["uploaded_at"] or "")),
                actor=str(row["uploaded_by"] or ""),
                entity_type="delivery",
                entity_id=str(row["id"]),
                supplier=str(row["supplier"] or ""),
                task_number=str(row["delivery_number"] or ""),
                comment=str(row["source_filename"] or ""),
                source="warehouse:deliveries",
                metadata=_plain(dict(row)),
            ))
        for row in accepted:
            events.append(WarehouseEvent(
                event_id=f"delivery-line-accepted:{row['id']}",
                event_type="DELIVERY_ACCEPTED",
                event_date=str(row["receipt_date"]),
                actor=str(row["responsible"] or ""),
                entity_type="delivery_line",
                entity_id=str(row["id"]),
                serial_number=str(row["serial_number"] or ""),
                item_name=str(row["item_name"] or ""),
                quantity=float(row["quantity"] or 0),
                unit=str(row["unit"] or ""),
                supplier=str(row["supplier"] or ""),
                task_number=str(row["delivery_number"] or ""),
                source="warehouse:delivery_lines",
                metadata=_plain(dict(row)),
            ))
        for row in problems:
            events.append(WarehouseEvent(
                event_id=f"delivery-line-problem:{row['id']}",
                event_type="DATA_PROBLEM_FOUND",
                event_date=str(row["event_date"] or ""),
                event_time=str(row["event_time"] or ""),
                actor=str(row["updated_by"] or ""),
                entity_type="delivery_line",
                entity_id=str(row["id"]),
                serial_number=str(row["serial_number"] or ""),
                supplier=str(row["supplier"] or ""),
                task_number=str(row["delivery_number"] or ""),
                comment=str(row["error_text"] or ""),
                source="warehouse:delivery_lines",
                metadata={**_plain(dict(row)), "kind": "delivery_problem_rows"},
            ))
        return events
