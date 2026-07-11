"""Explicit delivery CSV column mapping."""

from __future__ import annotations

import re
from typing import Any


def _header_key(value: Any) -> str:
    text = str(value or "").replace("\ufeff", "").replace("ё", "е").casefold()
    text = re.sub(r"[\s.\u00a0]+", "", text)
    return text


FIELD_SYNONYMS: dict[str, tuple[str, ...]] = {
    "serial_number": (
        "S/N", "SN", "Серийный номер", "Серийник", "Серийные номера",
        "Serial", "Serial Number", "serial_number",
    ),
    "inventory_number": (
        "Инв.№", "Инв. №", "Инвентарный номер", "Inventory",
        "Asset Number", "Номер ОС", "inventory_number", "asset_number",
    ),
    "order_number": ("Заказ", "Заказ №", "Заказ№", "Номер заказа", "Order", "order_number"),
    "request_number": ("Заявка", "Заявка №", "Заявка№", "Request", "request_number"),
    "delivery_number": (
        "Поставка", "Номер поставки", "Delivery", "Delivery Number", "delivery_number",
    ),
    "supplier": ("Поставщик", "Supplier", "Vendor Supplier", "supplier"),
    "vendor": ("Вендор", "Производитель", "Vendor", "Manufacturer", "vendor"),
    "model": ("Модель", "Model", "model"),
    "item_type": (
        "Тип", "Тип оборудования", "Тип компонента", "Категория", "Item Type",
        "equipment_type", "component_type", "equipment_unit",
    ),
    "quantity": ("Количество", "Кол-во", "шт", "Qty", "Quantity", "quantity"),
    "delivery_date": ("Дата", "Дата документа", "Дата поставки", "delivery_date", "order_date"),
    "plu": ("PLU", "plu"),
    "project": ("Проект", "Project", "project"),
    "datacenter": ("ЦОД", "Datacenter", "datacenter"),
    "shelf": ("Полка", "Стеллаж", "Стеллаж/Полка", "shelf"),
    "comment": ("Комментарий", "Comment", "comment"),
    "receipt_statement": ("Приходная ведомость", "receipt_statement"),
    "planned_date": ("Плановая дата поставки", "planned_date"),
    "request_position": ("Поз.Заявки", "Поз. Заявки", "request_position"),
    "order_position": ("Поз.Заказа", "Поз. Заказа", "order_position"),
    "contract_number": ("Договор", "contract_number"),
    "accounting_object": ("Объект учета", "Объект учёта", "accounting_object"),
    "asset_number": ("номер ОС", "Номер ОС", "asset_number"),
    "equipment_unit": ("единица оборудования", "Единица оборудования", "equipment_unit"),
}

ALIAS_TO_FIELDS: dict[str, set[str]] = {}
for field, aliases in FIELD_SYNONYMS.items():
    for alias in aliases:
        ALIAS_TO_FIELDS.setdefault(_header_key(alias), set()).add(field)


def map_headers(headers: list[str]) -> dict[str, Any]:
    mapping: dict[str, str] = {}
    unknown: list[str] = []
    ambiguous: list[dict[str, Any]] = []
    used_targets: dict[str, str] = {}
    for header in headers:
        key = _header_key(header)
        fields = sorted(ALIAS_TO_FIELDS.get(key, set()))
        if not fields:
            if str(header or "").strip():
                unknown.append(str(header).strip())
            continue
        if len(fields) > 1:
            ambiguous.append({"header": header, "candidates": fields})
            continue
        target = fields[0]
        if target in used_targets and used_targets[target] != header:
            ambiguous.append({"header": header, "candidates": [target], "conflicts_with": used_targets[target]})
            continue
        mapping[header] = target
        used_targets[target] = header
    return {"mapping": mapping, "unknown_columns": unknown, "ambiguous_columns": ambiguous}


def normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    """Map either source headers or already-normalized keys to canonical fields."""
    result: dict[str, Any] = {}
    header_info = map_headers([str(key) for key in row.keys()])
    for key, value in row.items():
        target = header_info["mapping"].get(str(key))
        if target:
            result[target] = value
        else:
            normalized = _header_key(key)
            if normalized in ALIAS_TO_FIELDS and len(ALIAS_TO_FIELDS[normalized]) == 1:
                result[next(iter(ALIAS_TO_FIELDS[normalized]))] = value
            elif str(key) in FIELD_SYNONYMS or str(key) in {
                "serial_number", "inventory_number", "delivery_number", "supplier",
                "vendor", "model", "quantity", "request_number", "order_number",
                "plu", "project", "datacenter", "shelf", "comment", "item_type",
                "delivery_date", "equipment_type", "component_type",
            }:
                result[str(key)] = value
    if "item_type" not in result:
        result["item_type"] = row.get("equipment_type") or row.get("component_type") or row.get("equipment_unit") or ""
    if "inventory_number" not in result and row.get("asset_number"):
        result["inventory_number"] = row.get("asset_number")
    return result
