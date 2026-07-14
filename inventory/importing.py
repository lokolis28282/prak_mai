"""Tolerant CSV decoding and header normalization for bulk imports."""

from __future__ import annotations

import csv
import io
from typing import Any


PREVIEW_ROW_LIMIT = 100
PREVIEW_ERROR_LIMIT = 200
MAX_IMPORT_ROWS = 40_000


FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "work_date": ("Дата", "work_date", "date"),
    "receipt_date": ("Дата прихода", "receipt_date"),
    "issue_date": ("Дата расхода", "issue_date"),
    "serial_number": ("SN", "S/N", "Серийный номер", "Серийные номера", "Серийник", "Serial", "Serial Number", "serial_number"),
    "inventory_number": ("Инв.№", "Инв. №", "Инвентарный номер", "Inventory", "Inventory Number", "Asset Number", "inventory_number"),
    "item_name": ("Наименование", "Название", "Item", "Позиция", "item_name"),
    "quantity": ("Кол-во", "Количество", "Qty", "шт", "Кол-во / метраж", "Количество / метраж", "quantity"),
    "vendor": ("Вендор", "Производитель", "Vendor", "Manufacturer", "vendor"),
    "model": ("Модель", "Model", "model"),
    "shelf": ("Полка", "Стеллаж", "Стеллаж/Полка", "shelf"),
    "project": ("Проект", "Project", "project"),
    "responsible": ("ФИО", "Ответственный", "responsible"),
    "task_number": ("Номер задачи", "Задача", "Task", "task_number"),
    "category": ("Категория", "Category", "category"),
    "location": ("Место", "Location", "location"),
    "notes": ("Примечание", "Notes", "notes"),
    "datacenter": ("ЦОД", "Datacenter", "datacenter"),
    "basis": ("Основание", "Basis", "basis"),
    "task_source": ("Источник задачи", "Источник", "task_source"),
    "task_type": ("Тип задачи", "task_type"),
    "description": ("Описание работы", "Описание", "Описание / наименование", "description"),
    "status": ("Статус", "status"),
    "section": ("Раздел", "section"),
    "comment": ("Комментарий", "Комментарий / основание", "comment"),
    "report_block": ("Блок отчета", "report_block"),
    "order_date": ("Дата заказа", "order_date"),
    "request_number": ("Заявка", "Заявка№", "Заявка №", "Request", "request_number"),
    "order_number": ("Заказ", "Заказ№", "Заказ №", "Номер заказа", "Order", "order_number"),
    "plu": ("PLU", "plu"),
    "supplier": ("Поставщик", "Supplier", "supplier"),
    "object_name": ("Объект", "Object", "object_name"),
    "equipment_type": ("Тип оборудования", "equipment_type"),
    "component_type": ("Тип компонента", "component_type"),
    "cable_type": ("Тип кабеля", "cable_type"),
    "unit": ("Единица учета", "Ед.", "Unit", "unit"),
    "receipt_statement": ("Приходная ведомость",),
    "delivery_number": ("Поставка", "Номер поставки", "Delivery", "Delivery Number"),
    "planned_date": ("Плановая дата поставки",),
    "request_position": ("Поз.Заявки", "Поз. Заявки"),
    "order_position": ("Поз.Заказа", "Поз. Заказа"),
    "contract_number": ("Договор",),
    "accounting_object": ("Объект учета",),
    "asset_number": ("номер ОС", "Номер ОС"),
    "equipment_unit": ("единица оборудования", "Единица оборудования"),
    "target_serial_number": ("SN целевого объекта", "SN целевого Об-я", "target_serial_number"),
    "target_hostname": ("Hostname", "Hostname оборудования", "Hostname целевого оборудования", "target_hostname"),
    "source_serial_number": ("S/N списываемого", "SN списываемого", "source_serial_number"),
    "source_item_name": ("Наименование списываемого", "source_item_name"),
    "source_cable_type": ("Тип списываемого кабеля", "source_cable_type"),
}


REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "receipt": ("item_name", "quantity"),
    "issue": ("quantity",),
    "work_logs": ("description",),
    "inventory": ("serial_number",),
    "inventory_numbers": ("serial_number", "inventory_number"),
    "bulk_issue": ("serial_number",),
    "equipment": ("category", "model", "serial_number", "inventory_number", "location", "quantity"),
    "daily_report": ("description",),
    "delivery": ("serial_number",),
}


DISPLAY_NAMES = {
    "serial_number": "S/N", "item_name": "Наименование", "quantity": "Количество",
    "description": "Описание работы", "category": "Категория", "model": "Модель",
    "inventory_number": "Инвентарный номер", "location": "Место",
}


def _key(value: Any) -> str:
    return " ".join(str(value or "").replace("ё", "е").strip().casefold().split())


ALIAS_TO_FIELD = {
    _key(alias): field for field, aliases in FIELD_ALIASES.items() for alias in aliases
}


def supported_names(field: str) -> str:
    return ", ".join(FIELD_ALIASES.get(field, (field,)))


def parse_csv_bytes(body: bytes, kind: str) -> list[dict[str, str]]:
    """Decode a CSV, normalize known headers and enforce only essential columns."""
    try:
        text = body.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = body.decode("cp1251")
    try:
        delimiter = csv.Sniffer().sniff(text[:8192], delimiters=";,\t").delimiter
    except csv.Error:
        delimiter = ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    if not reader.fieldnames:
        raise ValueError("В CSV-файле отсутствует строка заголовков")
    header_map = {
        original: ALIAS_TO_FIELD.get(_key(original), "") for original in reader.fieldnames
    }
    available = set(header_map.values())
    for field in REQUIRED_FIELDS.get(kind, ()):
        if field not in available:
            label = DISPLAY_NAMES.get(field, field)
            raise ValueError(
                f"Не найден обязательный столбец: {label}. "
                f"Поддерживаемые названия: {supported_names(field)}"
            )
    rows: list[dict[str, str]] = []
    for source in reader:
        row = {
            canonical: str(source.get(original, "") or "").strip()
            for original, canonical in header_map.items() if canonical
        }
        if any(row.values()):
            rows.append(row)
            if len(rows) > MAX_IMPORT_ROWS:
                raise ValueError(f"CSV содержит больше {MAX_IMPORT_ROWS:,} строк")
    return rows


def _header_row_index(rows: list[list[str]]) -> int:
    """Find the row that best matches known column aliases (0 if none stand out)."""
    best_index, best_score = 0, 0
    for index, row in enumerate(rows[:20]):
        score = sum(1 for cell in row if _key(cell) in ALIAS_TO_FIELD)
        if score > best_score:
            best_index, best_score = index, score
    return best_index


def xlsx_rows_to_records(rows: list[list[str]]) -> list[dict[str, str]]:
    """Map a raw XLSX sheet (list of string rows) to canonical work-log records.

    Only the first contiguous block of recognised columns is read; a blank
    header cell marks the end of the block, so trailing warehouse blocks in the
    source workbook are ignored. Excel serial dates are normalised to ISO.
    """
    from inventory.shared.xlsx import excel_serial_to_iso

    if not rows:
        return []
    header_index = _header_row_index(rows)
    header = rows[header_index]
    column_field: dict[int, str] = {}
    for position, title in enumerate(header):
        if not str(title).strip():
            if column_field:
                break  # end of the first table block
            continue
        field = ALIAS_TO_FIELD.get(_key(title), "")
        if field:
            column_field[position] = field
    records: list[dict[str, str]] = []
    for row in rows[header_index + 1:]:
        record: dict[str, str] = {}
        for position, field in column_field.items():
            value = str(row[position]).strip() if position < len(row) else ""
            if field in ("work_date", "receipt_date", "issue_date"):
                value = excel_serial_to_iso(value)
            record[field] = value
        # A log entry is only meaningful when it carries work content; date-only
        # spacer rows from the source spreadsheet are skipped, not imported.
        if record.get("description") or record.get("task_number"):
            records.append(record)
            if len(records) > MAX_IMPORT_ROWS:
                raise ValueError(f"Файл содержит больше {MAX_IMPORT_ROWS:,} строк")
    return records


def unknown_csv_headers(body: bytes) -> list[str]:
    """Вернуть исходные заголовки, которые не удалось сопоставить со схемой ODE."""
    try:
        text = body.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = body.decode("cp1251")
    try:
        delimiter = csv.Sniffer().sniff(text[:8192], delimiters=";,\t").delimiter
    except csv.Error:
        delimiter = ","
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    headers = next(reader, [])
    return [str(name).strip() for name in headers if str(name).strip() and _key(name) not in ALIAS_TO_FIELD]
