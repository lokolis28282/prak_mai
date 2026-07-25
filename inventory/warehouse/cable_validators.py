"""Cable receipt and issue validation."""

from __future__ import annotations

from datetime import date
from typing import Any

from inventory.shared.validators import WarehouseError

from .validators import parse_date, positive_number, reference, required


CABLE_REFERENCE_FIELDS = {
    "item_name": "item_name",
    "supplier": "supplier",
    "vendor": "vendor",
    "shelf": "shelf",
    "project": "project",
    "object_name": "object",
    "datacenter": "datacenter",
    "cable_type": "cable_type",
    "unit": "unit",
}

CABLE_ISSUE_REFERENCE_FIELDS = {
    "source_item_name": "item_name",
    "source_cable_type": "cable_type",
}


def is_cable_receipt(source: dict[str, Any]) -> bool:
    category = str(source.get("category", "")).strip().casefold()
    return category == "кабели" or bool(str(source.get("cable_type", "")).strip())


def is_cable_issue(source: dict[str, Any]) -> bool:
    return (
        not str(source.get("source_serial_number", "")).strip()
        and bool(str(source.get("source_item_name", "")).strip())
        and bool(str(source.get("source_cable_type", "")).strip())
    )


def soft_cable_receipt_source(source: dict[str, Any]) -> dict[str, Any]:
    row = dict(source)
    row["receipt_date"] = str(row.get("receipt_date") or date.today().isoformat())
    row["responsible"] = str(row.get("responsible") or "Не указан")
    row["supplier"] = str(row.get("supplier") or "Не указан")
    row["vendor"] = str(row.get("vendor") or "Не указан")
    row["object_name"] = str(row.get("object_name") or "Не указано")
    row["datacenter"] = str(row.get("datacenter") or "Ixcellerate")
    row["unit"] = str(row.get("unit") or "шт")
    row["cable_type"] = str(row.get("cable_type") or row.get("item_type") or "Не указан")
    return row


def prepare_cable_receipt(
    source: dict[str, Any],
    references: dict[str, set[str]],
    *,
    line_number: int | None = None,
    strict_references: bool = True,
) -> dict[str, Any]:
    prefix = f"Строка {line_number}: " if line_number is not None else ""
    try:
        source = dict(source)
        category = str(source.get("category", "")).strip()
        item_type = str(source.get("item_type", "")).strip()
        if category.casefold() == "кабели" and item_type:
            source["cable_type"] = item_type
        source["supplier"] = str(source.get("supplier") or "Не указан")
        source["vendor"] = str(source.get("vendor") or "Не указан")
        source["object_name"] = str(source.get("object_name") or "Не указано")
        source["datacenter"] = str(source.get("datacenter") or "Ixcellerate")
        source["unit"] = str(source.get("unit") or "шт")
        quantity = positive_number(source.get("quantity", ""), "количество")
        if not float(quantity).is_integer():
            raise WarehouseError("кабели учитываются целыми штуками")
        return {
            "receipt_date": parse_date(str(source.get("receipt_date", "")), "дата"),
            "responsible": required(str(source.get("responsible", "")), "ФИО"),
            "order_date": str(source.get("order_date", "")).strip(),
            "request_number": str(source.get("request_number", "")).strip(),
            "order_number": str(source.get("order_number", "")).strip(),
            "plu": str(source.get("plu", "")).strip(),
            "item_name": reference(str(source.get("item_name", "")), "наименование", "item_name", references, strict=strict_references),
            "project": reference(str(source.get("project", "")), "проект", "project", references, optional=True, strict=strict_references),
            "serial_number": "",
            "inventory_number": "",
            "supplier": reference(str(source.get("supplier", "")), "поставщик", "supplier", references, strict=strict_references),
            "vendor": reference(str(source.get("vendor", "")), "вендор", "vendor", references, strict=strict_references),
            "model": "",
            "shelf": reference(str(source.get("shelf", "")), "стеллаж/полка", "shelf", references, optional=True, strict=strict_references),
            "object_name": reference(str(source.get("object_name", "")), "объект", "object", references, strict=strict_references),
            "datacenter": reference(str(source.get("datacenter", "")), "ЦОД", "datacenter", references, strict=strict_references),
            "equipment_type": "",
            "component_type": "",
            "cable_type": reference(str(source.get("cable_type", "")), "тип кабеля", "cable_type", references, strict=strict_references),
            "unit": reference(str(source.get("unit", "")), "единица учета", "unit", references, strict=strict_references),
            "quantity": quantity,
            "comment": str(source.get("comment", "")).strip(),
        }
    except WarehouseError as error:
        raise WarehouseError(prefix + str(error)) from error


def prepare_cable_issue(
    source: dict[str, Any],
    references: dict[str, set[str]],
    *,
    line_number: int | None = None,
    strict_references: bool = True,
) -> dict[str, Any]:
    prefix = f"Строка {line_number}: " if line_number is not None else ""
    try:
        task_type = str(source.get("task_type", "")).strip()
        task_number = str(source.get("task_number", "")).strip()
        if (task_type and not task_number) or (task_number and not task_type):
            raise WarehouseError("тип и номер задачи заполняются вместе")
        if task_type and strict_references and task_type.casefold() not in references.get("task_type", set()):
            raise WarehouseError(f"тип задачи «{task_type}» отсутствует в справочнике")
        quantity = positive_number(source.get("quantity", ""), "количество")
        if not float(quantity).is_integer():
            raise WarehouseError("кабели учитываются целыми штуками")
        return {
            "issue_date": parse_date(str(source.get("issue_date", "")), "дата"),
            "responsible": required(str(source.get("responsible", "")), "ФИО"),
            "task_type": task_type,
            "task_number": task_number,
            "target_serial_number": "",
            "target_hostname": str(source.get("target_hostname", "")).strip(),
            "source_serial_number": "",
            "source_item_name": reference(str(source.get("source_item_name", source.get("item_name", ""))), "наименование", "item_name", references, strict=strict_references),
            "source_cable_type": reference(str(source.get("source_cable_type", source.get("cable_type", ""))), "тип кабеля", "cable_type", references, strict=strict_references),
            "project": str(source.get("project", "")).strip(),
            "datacenter": str(source.get("datacenter", "")).strip(),
            "shelf": str(source.get("shelf", "")).strip(),
            "quantity": quantity,
            "comment": str(source.get("comment", "")).strip(),
        }
    except WarehouseError as error:
        raise WarehouseError(prefix + str(error)) from error
