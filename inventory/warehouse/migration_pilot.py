"""Preservation-aware receipt writes for the disposable migration pilot.

This module deliberately bypasses the ordinary receipt validators: those
validators normalize Serial Number values with ``strip().upper()``.  The
caller owns both the SQLite connection and its transaction and is responsible
for enforcing the pilot-database marker/path boundary before invoking this
contract.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

from inventory.shared.audit import write_audit_entry
from inventory.shared.validators import WarehouseError

from .receipt_repository import ReceiptRepository


MIGRATION_RECEIPT_IMPORTED = "MIGRATION_RECEIPT_IMPORTED"
MIGRATION_SOURCE_ROW_LINKED = "MIGRATION_SOURCE_ROW_LINKED"
MIGRATION_CONFLICT_RECORDED = "MIGRATION_CONFLICT_RECORDED"
MIGRATION_EXACT_DUPLICATE_SKIPPED = "MIGRATION_EXACT_DUPLICATE_SKIPPED"
MIGRATION_SERIAL_QUARANTINED = "MIGRATION_SERIAL_QUARANTINED"

_LOCAL_PATH = re.compile(
    r"(?<![\w:])(?:[A-Za-z]:[\\/][^\s;,]+|"
    r"/(?:Users|home|private|tmp|var|opt|etc)/[^\s;,]+)"
)


def _required_text(source: Mapping[str, Any], field: str, label: str) -> str:
    value = source.get(field, "")
    if not isinstance(value, str):
        raise WarehouseError(f"Поле «{label}» должно быть строкой")
    cleaned = value.strip()
    if not cleaned:
        raise WarehouseError(f"Поле «{label}» не может быть пустым")
    return cleaned


def _optional_text(
    source: Mapping[str, Any], field: str, *, default: str = ""
) -> str:
    value = source.get(field, default)
    if value is None:
        value = default
    if not isinstance(value, str):
        raise WarehouseError(f"Поле «{field}» должно быть строкой")
    return value.strip()


def _optional_identifier(source: Mapping[str, Any], field: str) -> str:
    """Return an optional identifier without numeric conversion or cleanup."""

    value = source.get(field, "")
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise WarehouseError(f"Поле «{field}» должно быть текстом")
    return value


def _serialized_quantity(value: Any) -> int:
    if isinstance(value, bool):
        raise WarehouseError("Пилотный serialized-приход должен иметь quantity=1")
    try:
        quantity = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise WarehouseError(
            "Пилотный serialized-приход должен иметь quantity=1"
        ) from error
    if not quantity.is_finite() or quantity != Decimal("1"):
        raise WarehouseError("Пилотный serialized-приход должен иметь quantity=1")
    return 1


def _basename(value: Any) -> str:
    text = str(value or "").replace("\\", "/")
    return text.rsplit("/", 1)[-1]


def _redact_local_paths(value: Any) -> str:
    return _LOCAL_PATH.sub("[local-path-redacted]", str(value or ""))


def _warning_list(value: Any) -> list[str]:
    candidate = value
    if isinstance(candidate, str):
        try:
            decoded = json.loads(candidate)
        except json.JSONDecodeError:
            decoded = candidate
        candidate = decoded
    if candidate in (None, ""):
        return []
    if isinstance(candidate, (list, tuple, set)):
        values = candidate
    else:
        values = [candidate]
    return [
        _redact_local_paths(item)
        for item in values
        if str(item or "").strip()
    ]


def _audit_details(source: Mapping[str, Any]) -> dict[str, Any]:
    try:
        source_row = int(source.get("source_row", 0))
    except (TypeError, ValueError) as error:
        raise WarehouseError("Поле «source_row» должно быть номером строки") from error
    if isinstance(source.get("source_row"), bool) or source_row <= 0:
        raise WarehouseError("Поле «source_row» должно быть положительным номером строки")
    source_file = _basename(source.get("source_file", ""))
    source_sheet = _redact_local_paths(source.get("source_sheet", "")).strip()
    if not source_file:
        raise WarehouseError("Поле «source_file» не может быть пустым")
    if not source_sheet:
        raise WarehouseError("Поле «source_sheet» не может быть пустым")
    return {
        "source_file": source_file,
        "source_sheet": source_sheet,
        "source_row": source_row,
        "source_item_name": _redact_local_paths(source.get("source_item_name", "")),
        "canonical_item_name": _redact_local_paths(
            source.get("canonical_item_name", "")
        ),
        "warnings": _warning_list(source.get("migration_warnings", [])),
    }


def _write_receipt_audit(
    connection: sqlite3.Connection,
    *,
    action: str,
    receipt_id: int,
    source: Mapping[str, Any],
    author: str,
) -> None:
    write_audit_entry(
        connection,
        action=action,
        entity_type="stock_receipt",
        entity_id=receipt_id,
        author=author,
        details=_audit_details(source),
    )


def write_migration_source_row_linked(
    connection: sqlite3.Connection,
    *,
    receipt_id: int,
    source: Mapping[str, Any],
    author: str,
) -> None:
    _write_receipt_audit(
        connection,
        action=MIGRATION_SOURCE_ROW_LINKED,
        receipt_id=receipt_id,
        source=source,
        author=author,
    )


def write_migration_conflict_recorded(
    connection: sqlite3.Connection,
    *,
    receipt_id: int,
    source: Mapping[str, Any],
    author: str,
) -> None:
    _write_receipt_audit(
        connection,
        action=MIGRATION_CONFLICT_RECORDED,
        receipt_id=receipt_id,
        source=source,
        author=author,
    )


def write_migration_exact_duplicate_skipped(
    connection: sqlite3.Connection,
    *,
    receipt_id: int,
    source: Mapping[str, Any],
    author: str,
) -> None:
    _write_receipt_audit(
        connection,
        action=MIGRATION_EXACT_DUPLICATE_SKIPPED,
        receipt_id=receipt_id,
        source=source,
        author=author,
    )


def write_migration_serial_quarantined(
    connection: sqlite3.Connection,
    *,
    source: Mapping[str, Any],
    author: str,
    staging_row_id: int | str | None = None,
) -> None:
    entity_id = staging_row_id
    if entity_id is None:
        entity_id = source.get("staging_row_id") or source.get("source_row", "")
    write_audit_entry(
        connection,
        action=MIGRATION_SERIAL_QUARANTINED,
        entity_type="migration_staging_row",
        entity_id=entity_id,
        author=author,
        details=_audit_details(source),
    )


class MigrationPilotReceiptWriter:
    """Write one approved pilot receipt without changing its source S/N."""

    def __init__(self, repository: ReceiptRepository):
        self.repository = repository

    def write_receipt(
        self,
        connection: sqlite3.Connection,
        source: Mapping[str, Any],
        *,
        author: str,
    ) -> int:
        """Insert one pilot card in the caller-owned SQLite transaction.

        The caller must have classified the row as ``IMPORT``.  Numeric,
        reconstructed and corrupted serials are rejected by requiring an exact
        text preservation status and a non-empty, independently stored match
        key.  This method never commits or rolls back the connection.
        """

        if not isinstance(source, Mapping):
            raise WarehouseError("Пилотная строка должна быть объектом")
        if source.get("decision") != "IMPORT":
            raise WarehouseError("Карточка создаётся только для решения IMPORT")

        source_serial_value = source.get("source_serial_value")
        if not isinstance(source_serial_value, str):
            raise WarehouseError("source_serial_value должен быть текстом")
        if source_serial_value == "":
            raise WarehouseError("source_serial_value не может быть пустым")
        if source.get("serial_preservation_status") != "TEXT_EXACT":
            raise WarehouseError(
                "Для создания карточки требуется serial_preservation_status=TEXT_EXACT"
            )
        normalized_match_value = source.get("normalized_match_value")
        if (
            not isinstance(normalized_match_value, str)
            or not normalized_match_value.strip()
        ):
            raise WarehouseError("normalized_match_value не может быть пустым")

        quantity = _serialized_quantity(source.get("quantity"))
        canonical_item_name = _required_text(
            source, "canonical_item_name", "canonical_item_name"
        )
        row = {
            "receipt_date": _required_text(source, "receipt_date", "receipt_date"),
            "responsible": _optional_text(
                source, "responsible", default="Миграционный пилот"
            )
            or "Миграционный пилот",
            "order_date": _optional_identifier(source, "order_date"),
            "request_number": _optional_identifier(source, "request_number"),
            "order_number": _optional_identifier(source, "order_number"),
            "plu": _optional_identifier(source, "plu"),
            "item_name": canonical_item_name,
            "project": _optional_text(source, "project"),
            # Critical invariant: write the exact string, with no strip/upper.
            "serial_number": source_serial_value,
            "inventory_number": _optional_identifier(source, "inventory_number"),
            "supplier": _optional_text(
                source, "supplier", default="Не указан"
            )
            or "Не указан",
            "vendor": _optional_text(source, "vendor", default="Не указан")
            or "Не указан",
            "model": _optional_text(source, "model"),
            "shelf": _optional_text(source, "shelf"),
            "object_name": _optional_text(
                source, "object_name", default="Не указано"
            )
            or "Не указано",
            "datacenter": _optional_text(
                source, "datacenter", default="Не указано"
            )
            or "Не указано",
            "equipment_type": _optional_text(source, "equipment_type"),
            "component_type": _optional_text(source, "component_type"),
            "cable_type": "",
            "unit": "шт",
            "quantity": quantity,
        }

        receipt_id = self.repository.insert_one_in_transaction(
            connection,
            row,
            author=author,
            collect_refs=False,
            audit_action=MIGRATION_RECEIPT_IMPORTED,
        )
        updated = connection.execute(
            "UPDATE stock_receipts SET is_opening_balance=1 WHERE id=?",
            (receipt_id,),
        )
        if updated.rowcount != 1:
            raise WarehouseError("Не удалось пометить пилотную карточку")

        stored = connection.execute(
            """SELECT serial_number, typeof(serial_number) AS serial_type,
                      legacy_equipment_id, quantity, is_opening_balance
                 FROM stock_receipts WHERE id=?""",
            (receipt_id,),
        ).fetchone()
        if (
            stored is None
            or stored[1] != "text"
            or stored[0] != source_serial_value
            or stored[2] is not None
            or Decimal(str(stored[3])) != Decimal("1")
            or int(stored[4]) != 1
        ):
            raise WarehouseError("Проверка сохранности пилотной карточки не пройдена")

        write_migration_source_row_linked(
            connection,
            receipt_id=receipt_id,
            source=source,
            author=author,
        )
        return receipt_id


__all__ = [
    "MIGRATION_CONFLICT_RECORDED",
    "MIGRATION_EXACT_DUPLICATE_SKIPPED",
    "MIGRATION_RECEIPT_IMPORTED",
    "MIGRATION_SERIAL_QUARANTINED",
    "MIGRATION_SOURCE_ROW_LINKED",
    "MigrationPilotReceiptWriter",
    "write_migration_conflict_recorded",
    "write_migration_exact_duplicate_skipped",
    "write_migration_serial_quarantined",
    "write_migration_source_row_linked",
]
