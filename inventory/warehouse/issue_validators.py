"""Serialized equipment/component issue validation."""

from __future__ import annotations

from datetime import date
from typing import Any

from inventory.shared.validators import WarehouseError

from .validators import parse_date, positive_number, reference, required


ISSUE_REFERENCE_FIELDS = {
    "source_item_name": "item_name",
    "source_cable_type": "cable_type",
}

TASK_TYPES = ("ЗНР", "ПНР", "ИЗМ", "ЗНО", "ИНЦ", "Другое")


def soft_issue_source(source: dict[str, Any]) -> dict[str, Any]:
    row = dict(source)
    row["issue_date"] = str(row.get("issue_date") or date.today().isoformat())
    row["responsible"] = str(row.get("responsible") or "Не указан")
    row["quantity"] = str(row.get("quantity") or "1")
    return row


def is_serialized_issue(source: dict[str, Any]) -> bool:
    return bool(str(source.get("source_serial_number", "")).strip())


def prepare_issue(
    source: dict[str, Any],
    references: dict[str, set[str]],
    *,
    line_number: int | None = None,
    strict_references: bool = True,
) -> dict[str, Any]:
    prefix = f"Строка {line_number}: " if line_number is not None else ""
    try:
        task_type = str(source.get("task_type", "")).strip()
        if task_type and strict_references:
            allowed = {item.casefold() for item in TASK_TYPES} | references.get("task_type", set())
            if task_type.casefold() not in allowed:
                raise WarehouseError(f"тип задачи «{task_type}» отсутствует в справочнике")
        row = {
            "issue_date": parse_date(str(source.get("issue_date", "")), "дата"),
            "responsible": required(str(source.get("responsible", "")), "ФИО"),
            "task_type": task_type,
            "task_number": str(source.get("task_number", "")).strip(),
            "target_serial_number": str(source.get("target_serial_number", "")).strip().upper(),
            "target_hostname": str(source.get("target_hostname", "")).strip(),
            "source_serial_number": str(source.get("source_serial_number", "")).strip().upper(),
            "source_item_name": reference(
                str(source.get("source_item_name", "")), "наименование", "item_name",
                references, optional=True, strict=strict_references,
            ),
            "source_cable_type": reference(
                str(source.get("source_cable_type", "")), "тип кабеля", "cable_type",
                references, optional=True, strict=strict_references,
            ),
            "quantity": positive_number(source.get("quantity", ""), "количество"),
            "comment": str(source.get("comment", "")).strip(),
        }
        return row
    except WarehouseError as error:
        raise WarehouseError(prefix + str(error)) from error
