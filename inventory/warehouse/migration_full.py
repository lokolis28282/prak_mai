"""Warehouse-owned writes for the disposable full migration candidate.

The offline builder owns classification and the transaction.  This adapter
only writes current ODE operational tables and the existing ``audit_log``
event stream; it never opens or commits a database by itself.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from inventory.shared.audit import write_audit_entry
from inventory.shared.validators import WarehouseError


MIGRATION_RECEIPT_IMPORTED = "MIGRATION_RECEIPT_IMPORTED"
MIGRATION_SOURCE_ROW_LINKED = "MIGRATION_SOURCE_ROW_LINKED"
MIGRATION_EXACT_DUPLICATE_SKIPPED = "MIGRATION_EXACT_DUPLICATE_SKIPPED"
MIGRATION_CONFLICT_RECORDED = "MIGRATION_CONFLICT_RECORDED"
MIGRATION_NUMERIC_IDENTITY_PROVISIONAL = "MIGRATION_NUMERIC_IDENTITY_PROVISIONAL"
MIGRATION_OPENING_STATE_CREATED = "MIGRATION_OPENING_STATE_CREATED"
MIGRATION_ISSUE_IMPORTED = "MIGRATION_ISSUE_IMPORTED"
MIGRATION_SERIAL_QUARANTINED = "MIGRATION_SERIAL_QUARANTINED"

MIGRATION_EVENTS = frozenset({
    MIGRATION_RECEIPT_IMPORTED,
    MIGRATION_SOURCE_ROW_LINKED,
    MIGRATION_EXACT_DUPLICATE_SKIPPED,
    MIGRATION_CONFLICT_RECORDED,
    MIGRATION_NUMERIC_IDENTITY_PROVISIONAL,
    MIGRATION_OPENING_STATE_CREATED,
    MIGRATION_ISSUE_IMPORTED,
    MIGRATION_SERIAL_QUARANTINED,
})

_LOCAL_PATH = re.compile(
    r"(?<![\w:])(?:[A-Za-z]:[\\/][^\s;,]+|"
    r"/(?:Users|home|private|tmp|var|opt|etc)/[^\s;,]+)"
)


def _text(source: Mapping[str, Any], field: str, default: str = "") -> str:
    value = source.get(field, default)
    if value is None:
        value = default
    if not isinstance(value, str):
        raise WarehouseError(f"Поле «{field}» должно быть строкой")
    return value


def _serialized_quantity(value: Any) -> int:
    if isinstance(value, bool):
        raise WarehouseError("Serialized migration quantity должна быть равна 1")
    try:
        quantity = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise WarehouseError("Serialized migration quantity должна быть равна 1") from error
    if not quantity.is_finite() or quantity != Decimal("1"):
        raise WarehouseError("Serialized migration quantity должна быть равна 1")
    return 1


def _portable_source(value: Any) -> str:
    return Path(str(value or "").replace("\\", "/")).name


def _safe(value: Any) -> str:
    return _LOCAL_PATH.sub("[local-path-redacted]", str(value or ""))


def _list(value: Any) -> list[str]:
    candidate = value
    if isinstance(candidate, str):
        try:
            candidate = json.loads(candidate)
        except json.JSONDecodeError:
            candidate = [candidate]
    if candidate in (None, ""):
        return []
    if not isinstance(candidate, (list, tuple, set)):
        candidate = [candidate]
    return [_safe(item) for item in candidate if str(item or "").strip()]


def _details(source: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "source_file": _portable_source(source.get("source_file")),
        "source_sheet": _safe(source.get("source_sheet")),
        "source_row": int(source.get("source_row") or 0),
        "source_row_hash": _safe(source.get("source_row_hash")),
        "source_item_name": _safe(source.get("source_item_name")),
        "canonical_item_name": _safe(source.get("canonical_item_name")),
        "source_serial_value": _safe(source.get("source_serial_value")),
        "display_serial_value": _safe(source.get("display_serial_value")),
        "preservation_status": _safe(source.get("preservation_status")),
        "final_status": _safe(source.get("final_status")),
        "warnings": _list(source.get("warnings")),
        "conflicts": _list(source.get("conflicts")),
    }


class MigrationFullWarehouseWriter:
    """Write deterministic full-candidate receipts, issues and audit events."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)

    def write_receipt(
        self,
        connection: sqlite3.Connection,
        source: Mapping[str, Any],
        *,
        receipt_id: int,
        opening_state: bool,
        author: str,
    ) -> int:
        serial = _text(source, "display_serial_value")
        if not serial:
            raise WarehouseError("Full candidate identity не может иметь пустой S/N")
        quantity = _serialized_quantity(source.get("quantity", "1"))
        if source.get("preservation_status") == "NUMERIC_FORMAT_UNPROVEN":
            if _text(source, "inventory_number"):
                raise WarehouseError(
                    "Provisional numeric identity не может получить Inventory Number"
                )
        if receipt_id < 1_000_001:
            raise WarehouseError("Full candidate receipt ID вне выделенного диапазона")
        if connection.execute(
            "SELECT 1 FROM stock_receipts WHERE id=?", (receipt_id,)
        ).fetchone():
            raise WarehouseError("Повторный full candidate receipt ID")

        values = (
            receipt_id,
            _text(source, "operation_date"),
            _text(source, "responsible", "Историческая миграция")
            or "Историческая миграция",
            "" if opening_state else _text(source, "order_date"),
            "" if opening_state else _text(source, "request_number"),
            "" if opening_state else _text(source, "order_number"),
            "" if opening_state else _text(source, "plu"),
            _text(source, "canonical_item_name") or "Историческая позиция без прихода",
            "" if opening_state else _text(source, "project"),
            serial,
            "" if opening_state else _text(source, "inventory_number"),
            "" if opening_state else _text(source, "supplier"),
            _text(source, "vendor"),
            _text(source, "model"),
            _text(source, "shelf"),
            "" if opening_state else _text(source, "object_name"),
            "" if opening_state else _text(source, "datacenter"),
            _text(source, "equipment_type"),
            _text(source, "component_type"),
            "",
            "шт",
            quantity,
            int(opening_state),
            _text(source, "created_at"),
        )
        connection.execute(
            """INSERT INTO stock_receipts(
                   id, receipt_date, responsible, order_date, request_number,
                   order_number, plu, item_name, project, serial_number,
                   inventory_number, supplier, vendor, model, shelf, object_name,
                   datacenter, equipment_type, component_type, cable_type, unit,
                   quantity, is_opening_balance, created_at
               ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            values,
        )
        action = (
            MIGRATION_OPENING_STATE_CREATED
            if opening_state else MIGRATION_RECEIPT_IMPORTED
        )
        self.write_event(
            connection,
            action=action,
            entity_type="stock_receipt",
            entity_id=receipt_id,
            source=source,
            author=author,
        )
        return receipt_id

    def write_issue(
        self,
        connection: sqlite3.Connection,
        source: Mapping[str, Any],
        *,
        issue_id: int,
        allocation_id: int,
        receipt_id: int,
        author: str,
    ) -> int:
        if issue_id < 2_000_001 or allocation_id < 3_000_001:
            raise WarehouseError("Full candidate issue/allocation ID вне диапазона")
        quantity = _serialized_quantity(source.get("quantity", "1"))
        connection.execute(
            """INSERT INTO stock_issues(
                   id, issue_date, responsible, task_type, task_number,
                   target_serial_number, target_hostname, source_serial_number,
                   source_item_name, source_cable_type, quantity, comment, created_at
               ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                issue_id,
                _text(source, "operation_date"),
                _text(source, "responsible") or "Историческая миграция",
                _text(source, "task_type"),
                _text(source, "task_number"),
                _text(source, "target_serial_number"),
                _text(source, "target_hostname"),
                _text(source, "display_serial_value"),
                "",
                "",
                quantity,
                _text(source, "comment"),
                _text(source, "created_at"),
            ),
        )
        connection.execute(
            """INSERT INTO stock_issue_allocations(
                   id, issue_id, receipt_id, quantity
               ) VALUES (?, ?, ?, ?)""",
            (allocation_id, issue_id, receipt_id, quantity),
        )
        self.write_event(
            connection,
            action=MIGRATION_ISSUE_IMPORTED,
            entity_type="stock_issue",
            entity_id=issue_id,
            source=source,
            author=author,
        )
        return issue_id

    @staticmethod
    def write_event(
        connection: sqlite3.Connection,
        *,
        action: str,
        entity_type: str,
        entity_id: int | str,
        source: Mapping[str, Any],
        author: str,
    ) -> None:
        if action not in MIGRATION_EVENTS:
            raise WarehouseError(f"Недопустимое migration event: {action}")
        write_audit_entry(
            connection,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            author=author,
            details=_details(source),
            event_date=_text(source, "audit_event_date")
            or _text(source, "created_at"),
        )


__all__ = [
    "MIGRATION_CONFLICT_RECORDED",
    "MIGRATION_EVENTS",
    "MIGRATION_EXACT_DUPLICATE_SKIPPED",
    "MIGRATION_ISSUE_IMPORTED",
    "MIGRATION_NUMERIC_IDENTITY_PROVISIONAL",
    "MIGRATION_OPENING_STATE_CREATED",
    "MIGRATION_RECEIPT_IMPORTED",
    "MIGRATION_SERIAL_QUARANTINED",
    "MIGRATION_SOURCE_ROW_LINKED",
    "MigrationFullWarehouseWriter",
]
