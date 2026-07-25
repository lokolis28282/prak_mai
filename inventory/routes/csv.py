"""CSV presentation contracts shared by HTTP route modules."""

from __future__ import annotations

import csv
import io
from typing import Any


WORK_LOG_HEADERS = {
    "work_date": "Дата", "full_task_name": "Имя задачи",
    "description": "Описание работ", "status": "Статус",
    "section": "Раздел", "task_type": "Тип", "comment": "Комментарий",
}
REPORT_HEADERS = {
    "date": "Дата", "report_block": "Блок отчета", "task_number": "Номер задачи",
    "description": "Описание / наименование", "quantity": "Количество / метраж",
    "serial_number": "S/N", "responsible": "ФИО",
    "comment": "Комментарий / основание",
}
RECEIPT_HEADERS = {
    "receipt_date": "Дата", "responsible": "ФИО", "order_date": "Дата заказа",
    "request_number": "Заявка№", "order_number": "Заказ№", "plu": "PLU",
    "item_name": "Наименование", "project": "Проект", "serial_number": "SN",
    "inventory_number": "Инв.№", "supplier": "Поставщик", "vendor": "Вендор",
    "model": "Модель", "shelf": "Стеллаж/Полка", "object_name": "Объект",
    "datacenter": "ЦОД",
    "equipment_type": "Тип оборудования", "component_type": "Тип компонента",
    "cable_type": "Тип кабеля", "unit": "Единица учета",
    "quantity": "Кол-во",
}
RECEIPT_EXPORT_HEADERS = {
    **RECEIPT_HEADERS,
    "is_opening_balance": "Начальный исторический остаток",
}
BALANCE_HEADERS = {
    "project": "Проект", "item_name": "Наименование", "vendor": "Вендор", "model": "Модель",
    "serial_number": "SN", "inventory_number": "Инв.№", "balance": "Остаток",
    "unit": "Единица учета", "shelf": "Стеллаж/Полка", "object_name": "Объект",
    "equipment_type": "Тип оборудования", "component_type": "Тип компонента",
    "cable_type": "Тип кабеля", "datacenter": "ЦОД",
}
ISSUE_HEADERS = {
    "issue_date": "Дата", "responsible": "ФИО", "task_number": "Номер задачи",
    "target_serial_number": "SN целевого Об-я", "target_hostname": "Hostname оборудования",
    "target_item_name": "Целевое оборудование",
    "target_model": "Модель целевого оборудования",
    "target_inventory_number": "Инв.№ целевого оборудования",
    "item_name": "Наименование списываемого",
    "component_model": "Модель компонента", "quantity": "Кол-во / метраж",
    "serial_number": "S/N списываемого", "inventory_number": "Инв.№",
    "shelf": "Стеллаж/Полка", "object_name": "Объект",
    "equipment_type": "Тип оборудования", "component_type": "Тип компонента",
    "cable_type": "Тип кабеля", "project": "Проект", "unit": "Единица учета",
    "matched_quantity": "Сопоставлено", "unmatched_quantity": "Не сопоставлено",
    "status": "Статус", "comment": "Комментарий",
}
ISSUE_IMPORT_HEADERS = {
    "issue_date": "Дата", "responsible": "ФИО", "task_type": "Тип задачи",
    "task_number": "Номер задачи", "target_serial_number": "SN целевого объекта",
    "target_hostname": "Hostname целевого оборудования", "quantity": "Кол-во",
    "source_serial_number": "S/N списываемого",
    "source_item_name": "Наименование", "source_cable_type": "Тип кабеля",
    "comment": "Комментарий",
}
USER_CSV_TEMPLATES = {
    "equipment": "Категория;Модель;Серийный номер;Инвентарный номер;ЦОД;Место;Количество;Примечание\r\n",
    "receipt": ";".join(RECEIPT_HEADERS.values()) + "\r\n",
    "issue": (
        "Дата;ФИО;Тип задачи;Номер задачи;SN целевого объекта;"
        "Hostname целевого оборудования;Кол-во;S/N списываемого;"
        "Наименование;Тип кабеля;Комментарий\r\n"
    ),
    "bulk_issue": "S/N;Комментарий\r\n",
    "inventory": "S/N\r\n",
    "inventory_numbers": "Serial Number;Inventory Number\r\n",
    "work_logs": "Дата;Источник задачи;Тип задачи;Номер задачи;Описание работы;Статус;Раздел;Комментарий\r\n",
    "daily_report": ";".join(REPORT_HEADERS.values()) + "\r\n",
    "delivery": "Дата;Поставщик;Номер поставки;Заявка;Заказ;PLU;Серийный номер;Инвентарный номер;Вендор;Модель;Тип оборудования;Проект;ЦОД;Полка;Количество;Комментарий\r\n",
}


def localized(
    rows: list[dict[str, Any]], headers: dict[str, str]
) -> list[dict[str, Any]]:
    """Map internal field names to presentation headers."""
    return [{headers[key]: row.get(key, "") for key in headers} for row in rows]


def csv_download_bytes(
    rows: list[dict[str, Any]],
    delimiter: str = ";",
    *,
    fieldnames: list[str] | None = None,
) -> bytes:
    """Build Excel-friendly CSV with BOM and formula-injection protection."""

    def safe_cell(value: Any) -> Any:
        if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
            return "'" + value
        return value

    buffer = io.StringIO(newline="")
    columns = fieldnames or (list(rows[0]) if rows else [])
    if columns:
        writer = csv.DictWriter(buffer, fieldnames=columns, delimiter=delimiter)
        writer.writeheader()
        if rows:
            writer.writerows(
                {key: safe_cell(value) for key, value in row.items()} for row in rows
            )
    return ("\ufeff" + buffer.getvalue()).encode("utf-8")
