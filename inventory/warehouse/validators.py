"""Warehouse receipt validation rules."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from inventory.shared.validators import WarehouseError
from inventory.warehouse.classification import (
    canonical_vendor,
    classify_card,
    infer_vendor,
)


RECEIPT_REFERENCE_FIELDS = {
    "item_name": "item_name", "model": "model", "shelf": "shelf",
    "project": "project", "supplier": "supplier", "vendor": "vendor",
    "object_name": "object", "datacenter": "datacenter",
    "equipment_type": "equipment_type", "component_type": "component_type",
    "cable_type": "cable_type", "unit": "unit",
}


def required(value: str, field: str) -> str:
    value = value.strip()
    if not value:
        raise WarehouseError(f"Поле «{field}» не может быть пустым")
    return value


def parse_date(value: str, field: str = "дата") -> str:
    value = value.strip()
    for date_format in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, date_format).date().isoformat()
        except ValueError:
            pass
    raise WarehouseError(
        f"Поле «{field}» должно содержать дату в формате "
        "ГГГГ-ММ-ДД, ДД.ММ.ГГГГ или ДД/ММ/ГГГГ"
    )


def positive_number(value: Any, field: str = "количество / метраж") -> float:
    try:
        number = float(str(value).replace(",", "."))
    except ValueError as error:
        raise WarehouseError(f"Поле «{field}» должно быть числом") from error
    if number <= 0:
        raise WarehouseError(f"Поле «{field}» должно быть больше нуля")
    return number


def reference(
    value: str,
    field: str,
    kind: str,
    references: dict[str, set[str]],
    *,
    optional: bool = False,
    strict: bool = True,
) -> str:
    value = value.strip()
    if optional and not value:
        return ""
    if not value:
        raise WarehouseError(f"Поле «{field}» не может быть пустым")
    if strict and value.casefold() not in references.get(kind, set()):
        raise WarehouseError(
            f"Поле «{field}»: значение «{value}» отсутствует в активном справочнике"
        )
    return value


def soft_receipt_source(source: dict[str, Any]) -> dict[str, Any]:
    row = dict(source)
    row["receipt_date"] = str(row.get("receipt_date") or date.today().isoformat())
    row["responsible"] = str(row.get("responsible") or "Не указан")
    row["supplier"] = str(row.get("supplier") or "Не указан")
    supplied_vendor = canonical_vendor(row.get("vendor"))
    inferred_vendor = infer_vendor(
        row.get("item_name"), row.get("model"), row.get("part_number") or row.get("pn")
    )
    row["vendor"] = supplied_vendor or inferred_vendor or "Не указан"
    row["object_name"] = str(row.get("object_name") or "Не указано")
    row["datacenter"] = str(row.get("datacenter") or "Ixcellerate")
    row["unit"] = str(row.get("unit") or "шт")
    if not any(str(row.get(key) or "").strip() for key in (
        "equipment_type", "component_type", "cable_type"
    )):
        classification = classify_card(
            item_name=row.get("item_name"), vendor=row.get("vendor"),
            model=row.get("model"),
            part_number=row.get("part_number") or row.get("pn"),
        )
        if classification.confidence != "LOW":
            row[classification.field] = classification.value
        elif str(row.get("serial_number") or "").strip():
            row["equipment_type"] = "Не указан"
        else:
            row["cable_type"] = "Не указан"
    return row


def is_cable_receipt(source: dict[str, Any]) -> bool:
    category = str(source.get("category", "")).strip().casefold()
    return category == "кабели" or bool(str(source.get("cable_type", "")).strip())


def prepare_receipt(
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
        category_fields = {
            "оборудование": "equipment_type",
            "компоненты": "component_type",
            "кабели": "cable_type",
        }
        if category or item_type:
            target = category_fields.get(category.casefold())
            if not target or not item_type:
                raise WarehouseError("выберите «Что приехало?» и тип")
            for field in category_fields.values():
                source[field] = item_type if field == target else ""
        if str(source.get("cable_type", "")).strip():
            raise WarehouseError("приход кабелей переносится отдельным этапом")
        source["supplier"] = str(source.get("supplier") or "Не указан")
        source["vendor"] = str(source.get("vendor") or "Не указан")
        source["object_name"] = str(source.get("object_name") or "Не указано")
        source["datacenter"] = str(source.get("datacenter") or "Ixcellerate")
        source["unit"] = str(source.get("unit") or "шт")
        if category:
            source["quantity"] = 1
        row: dict[str, Any] = {
            "receipt_date": parse_date(str(source.get("receipt_date", "")), "дата"),
            "responsible": required(str(source.get("responsible", "")), "ФИО"),
            "order_date": str(source.get("order_date", "")).strip(),
            "request_number": str(source.get("request_number", "")).strip(),
            "order_number": str(source.get("order_number", "")).strip(),
            "plu": str(source.get("plu", "")).strip(),
            "item_name": reference(str(source.get("item_name", "")), "наименование", "item_name", references, strict=strict_references),
            "project": reference(str(source.get("project", "")), "проект", "project", references, optional=True, strict=strict_references),
            "serial_number": str(source.get("serial_number", "")).strip().upper(),
            "inventory_number": str(source.get("inventory_number", "")).strip().upper(),
            "supplier": reference(str(source.get("supplier", "")), "поставщик", "supplier", references, strict=strict_references),
            "vendor": reference(str(source.get("vendor", "")), "вендор", "vendor", references, strict=strict_references),
            "model": reference(str(source.get("model", "")), "модель", "model", references, optional=True, strict=strict_references),
            "shelf": reference(str(source.get("shelf", "")), "стеллаж/полка", "shelf", references, optional=True, strict=strict_references),
            "object_name": reference(str(source.get("object_name", "")), "объект", "object", references, strict=strict_references),
            "datacenter": reference(str(source.get("datacenter", "Ixcellerate")), "ЦОД", "datacenter", references, strict=strict_references),
            "equipment_type": reference(str(source.get("equipment_type", "")), "тип оборудования", "equipment_type", references, optional=True, strict=strict_references),
            "component_type": reference(str(source.get("component_type", "")), "тип компонента", "component_type", references, optional=True, strict=strict_references),
            "cable_type": "",
            "unit": reference(str(source.get("unit", "")), "единица учета", "unit", references, strict=strict_references),
            "quantity": positive_number(source.get("quantity", "")),
        }
        if row["order_date"]:
            row["order_date"] = parse_date(row["order_date"], "дата заказа")
        classifications = sum(bool(row[key]) for key in ("equipment_type", "component_type"))
        if classifications != 1:
            raise WarehouseError("укажите ровно один классификатор: тип оборудования или компонента")
        if not row["serial_number"]:
            raise WarehouseError("S/N обязателен для оборудования и компонентов")
        if not float(row["quantity"]).is_integer():
            raise WarehouseError("оборудование и компоненты учитываются целыми штуками")
        return row
    except WarehouseError as error:
        raise WarehouseError(prefix + str(error)) from error
