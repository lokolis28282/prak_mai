"""Reports-owned validation rules."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from inventory.shared.validators import WarehouseError


TASK_SOURCES = ("Rooms", "Outlook", "ITSM", "Zabbix", "DCIM", "Склад", "Другое")
TASK_TYPES = ("ЗНР", "ПНР", "ИЗМ", "ЗНО", "ИНЦ", "Другое")
WORK_LOG_STATUSES = ("Выполнено", "В работе", "Ожидание", "Отложено")


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


def soft_work_log_source(source: dict[str, Any]) -> dict[str, Any]:
    row = dict(source)
    row["work_date"] = str(row.get("work_date") or date.today().isoformat())
    row["task_source"] = str(row.get("task_source") or "Не указан")
    row["task_type"] = str(row.get("task_type") or "")
    row["task_number"] = str(row.get("task_number") or "")
    row["status"] = str(row.get("status") or "Выполнено")
    return row


def prepare_work_log(
    source: dict[str, Any],
    *,
    references: dict[str, set[str]],
    line_number: int | None = None,
    strict_references: bool = True,
) -> dict[str, str]:
    prefix = f"Строка {line_number}: " if line_number is not None else ""
    try:
        return {
            "work_date": parse_date(str(source.get("work_date", "")), "дата"),
            "task_source": reference(
                str(source.get("task_source", "")), "источник задачи", "task_source",
                references or {"task_source": {x.casefold() for x in TASK_SOURCES}},
                strict=strict_references,
            ),
            "task_type": reference(
                str(source.get("task_type", "")), "тип задачи", "task_type",
                references or {"task_type": {x.casefold() for x in TASK_TYPES}},
                optional=True, strict=strict_references,
            ),
            "task_number": required(str(source.get("task_number", "")), "номер задачи"),
            "description": required(str(source.get("description", "")), "описание работы"),
            "status": reference(
                str(source.get("status", "")), "статус", "work_log_status",
                references or {"work_log_status": {x.casefold() for x in WORK_LOG_STATUSES}},
            ),
            "comment": str(source.get("comment", "")).strip(),
        }
    except WarehouseError as error:
        raise WarehouseError(prefix + str(error)) from error


def prepare_daily_report_row(
    source: dict[str, Any],
    *,
    line_number: int | None = None,
) -> dict[str, str]:
    prefix = f"Строка {line_number}: " if line_number is not None else ""
    try:
        return {
            "date": parse_date(str(source.get("date", "")), "дата"),
            "report_block": str(source.get("report_block", "")).strip(),
            "task_number": str(source.get("task_number", "")).strip(),
            "description": required(
                str(source.get("description", "")), "описание / наименование"
            ),
            "quantity": str(source.get("quantity", "")).strip(),
            "serial_number": str(source.get("serial_number", "")).strip(),
            "responsible": str(source.get("responsible", "")).strip(),
            "comment": str(source.get("comment", "")).strip(),
        }
    except WarehouseError as error:
        raise WarehouseError(prefix + str(error)) from error
