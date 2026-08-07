"""Reports-owned validation rules."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from inventory.shared.validators import WarehouseError


TASK_SOURCES = (
    "PNR", "ИЗМ", "ЗНР", "ЗНО", "ИНЦ", "Сопровождение", "ROOMS", "Time", "Zabbix",
    "Заказ", "Волна", "DCIM", "ITSM", "Outlook", "Rooms", "Склад", "Другое",
)
TASK_TYPES = ("ЗНО", "ЗНР", "ИЗМ", "ИНЦ", "Ночные работы", "ПНР", "Работа", "Другое")
WORK_LOG_STATUSES = ("Выполнено", "В работе", "В ожидании", "Ожидание", "Отложено")

PNR_SOURCE = "PNR"
STATUS_DONE = "Выполнено"
STATUS_PARTIAL = "В работе"

# PNR checklist steps and the completed-form phrasing used in the auto-generated
# description. Keys are the canonical step identifiers; the tuple is
# (label shown in the UI, phrasing for the "выполнено" sentence, prerequisite key
# or None). A step with a prerequisite can only be checked once the prerequisite
# is checked, so the checklist enforces a real work order.
PNR_CHECKLIST = (
    ("servers", "Установка оборудования в стойки", "установлено оборудование в стойки", None, "установить оборудование в стойки"),
    ("power", "Подключение питания", "подключено питание", None, "подключить питание"),
    ("transceivers", "Установка трансиверов", "установлены трансиверы", None, "установить трансиверы"),
    ("marking", "Маркировка кабеля", "промаркирован кабель", None, "промаркировать кабель"),
    ("laying", "Прокладка кабеля", "проложен кабель", "marking", "проложить кабель"),
    ("switching", "Коммутация кабельных систем", "выполнена коммутация кабельных систем", "laying", "выполнить коммутацию кабельных систем"),
)
PNR_CHECKLIST_KEYS = tuple(step[0] for step in PNR_CHECKLIST)
PNR_PREREQUISITES = {step[0]: step[3] for step in PNR_CHECKLIST}


def is_pnr_source(source: str) -> bool:
    return str(source or "").strip().casefold() == PNR_SOURCE.casefold()


def normalize_pnr_checklist(raw: Any) -> list[str]:
    """Return the checked PNR step keys, order-preserving and de-duplicated.

    The work order is enforced here so the stored data stays consistent: a step
    is dropped if its prerequisite is not also checked (e.g. «Коммутация» without
    «Прокладка кабеля»). This mirrors the UI blocking and cannot be bypassed by a
    crafted request.
    """
    if isinstance(raw, str):
        raw = [part.strip() for part in raw.replace(";", ",").split(",")]
    if not isinstance(raw, (list, tuple, set)):
        return []
    requested = {str(item).strip() for item in raw if str(item).strip()}
    result: list[str] = []
    for key in PNR_CHECKLIST_KEYS:
        if key not in requested:
            continue
        prerequisite = PNR_PREREQUISITES.get(key)
        if prerequisite and prerequisite not in result:
            continue  # prerequisite not satisfied → step is not accepted
        result.append(key)
    return result


def pnr_description(checked: list[str]) -> str:
    """Build the auto-description from the checked PNR steps."""
    done = [phrase for key, _label, phrase, _prereq, _todo in PNR_CHECKLIST if key in checked]
    if not done:
        return "PNR: работы не отмечены"
    return "PNR выполнены работы:\n" + "\n".join(f"- {phrase};" for phrase in done)


def pnr_remaining_steps(checked: list[str]) -> list[str]:
    """Imperative phrases for the PNR steps that are not yet completed, in
    work order. Used by the shift-handover text so the next shift sees exactly
    what is left to do."""
    return [
        todo for key, _label, _phrase, _prereq, todo in PNR_CHECKLIST
        if key not in checked
    ]


def pnr_handover_text(checked: list[str]) -> str:
    """Human-readable «what is left to do» for an unfinished PNR task.

    One remaining step → «Необходимо выполнить: <шаг>.». Several remaining →
    a bullet list. Nothing remaining is not expected here (finished PNR does
    not reach handover), but is handled defensively."""
    remaining = pnr_remaining_steps(checked)
    if not remaining:
        return ""
    if len(remaining) == 1:
        return f"Необходимо выполнить: {remaining[0]}."
    lines = "\n".join(f"- {step};" for step in remaining)
    return "Необходимо выполнить:\n" + lines


def pnr_progress_percent(checked: list[str]) -> int:
    """Percent of completed PNR steps, rounded to the nearest integer."""
    total = len(PNR_CHECKLIST_KEYS)
    if not total:
        return 0
    return round(len(checked) * 100 / total)


def pnr_status(checked: list[str]) -> str:
    """All steps checked → done; at least one but not all → partial."""
    if len(checked) == len(PNR_CHECKLIST_KEYS):
        return STATUS_DONE
    return STATUS_PARTIAL


def _normalize(value: str) -> str:
    return " ".join(str(value or "").replace("ё", "е").strip().casefold().split())


def match_section(value: str, known: dict[str, str]) -> tuple[str, bool]:
    """Map a raw section value onto a known canonical section.

    `known` maps normalized section names to their canonical display form.
    Returns the resolved value and a flag that is True when the value could not
    be matched and must be reviewed manually. Nothing is ever dropped: an
    unmatched value is kept verbatim so migrated data is not lost.
    """
    text = str(value or "").strip()
    if not text:
        return "", False
    normalized = _normalize(text)
    if normalized in known:
        return known[normalized], False
    for canonical_norm, canonical in known.items():
        if normalized in canonical_norm or canonical_norm in normalized:
            return canonical, False
    return text, True


def _task_number(number: str, source: str) -> str:
    """Task number is optional for standalone task templates (ROOMS, Time, …).

    It is only mandatory when the task source carries no identity of its own, so
    a fully anonymous entry (no source and no number) is still rejected.
    """
    number = number.strip()
    if number:
        return number
    if source.strip() and source.strip().casefold() not in ("не указан", ""):
        return ""
    raise WarehouseError("Укажите имя задачи (шаблон или номер)")


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
    row["section"] = str(row.get("section") or "")
    return row


def migration_placeholders(source: dict[str, Any]) -> dict[str, Any]:
    """Fill placeholders for empty required fields during file migration only.

    Unlike the general soft import path, a spreadsheet migration must never drop
    a content-bearing row: an empty task number or description is replaced with a
    placeholder and the row is flagged for manual review.
    """
    row = dict(source)
    if not str(row.get("task_number") or "").strip():
        row["task_number"] = "—"
        row["needs_review"] = 1
    if not str(row.get("description") or "").strip():
        row["description"] = "(без описания)"
        row["needs_review"] = 1
    return row


def prepare_work_log(
    source: dict[str, Any],
    *,
    references: dict[str, set[str]],
    line_number: int | None = None,
    strict_references: bool = True,
    require_due_date: bool = False,
) -> dict[str, str]:
    prefix = f"Строка {line_number}: " if line_number is not None else ""
    try:
        task_source = reference(
            str(source.get("task_source", "")), "источник задачи", "task_source",
            references or {"task_source": {x.casefold() for x in TASK_SOURCES}},
            strict=strict_references,
        )
        due_date = str(source.get("due_date", "")).strip()
        if due_date:
            due_date = parse_date(due_date, "срок выполнения")
        elif require_due_date:
            # Only interactive UI entry opts in; legacy helpers and bulk imports
            # may omit the deadline.
            raise WarehouseError("Поле «срок выполнения» не может быть пустым")
        prepared = {
            "work_date": parse_date(str(source.get("work_date", "")), "дата"),
            "task_source": task_source,
            "task_type": reference(
                str(source.get("task_type", "")), "тип задачи", "task_type",
                references or {"task_type": {x.casefold() for x in TASK_TYPES}},
                optional=True, strict=strict_references,
            ),
            "task_number": _task_number(
                str(source.get("task_number", "")), str(source.get("task_source", ""))
            ),
            "section": reference(
                str(source.get("section", "")), "раздел", "work_log_section",
                references or {"work_log_section": set()},
                optional=True, strict=strict_references,
            ),
            "needs_review": int(bool(source.get("needs_review", 0))),
            "due_date": due_date,
            "pnr_checklist": "",
            "comment": str(source.get("comment", "")).strip(),
        }
        if is_pnr_source(task_source):
            # PNR: description and status are derived from the checklist, not
            # entered by hand. Comment stays separate.
            checked = normalize_pnr_checklist(source.get("pnr_checklist"))
            prepared["pnr_checklist"] = ",".join(checked)
            prepared["description"] = pnr_description(checked)
            prepared["status"] = pnr_status(checked)
        else:
            prepared["description"] = required(
                str(source.get("description", "")), "описание работы"
            )
            prepared["status"] = reference(
                str(source.get("status", "")), "статус", "work_log_status",
                references or {"work_log_status": {x.casefold() for x in WORK_LOG_STATUSES}},
            )
        return prepared
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
