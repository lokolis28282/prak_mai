"""Read-only projection of components issued to serialized equipment."""

from __future__ import annotations

from collections import OrderedDict
import re
from typing import Any

from inventory.db import connect

from .component import WarehouseComponent


_GROUPS = (
    ("transceivers", "Трансиверы", ("трансив", "qsfp", "sfp", "оптическ модул")),
    ("drives", "Диски", ("ssd", "hdd", "диск", "накопител", "nvme")),
    ("memory", "Память", ("ram", "памят", "dimm")),
    (
        "adapters",
        "Адаптеры и контроллеры",
        ("nic", "hba", "raid", "сетев", "адаптер", "контроллер", "карта"),
    ),
    ("compute", "Вычислительные модули", ("cpu", "gpu", "процессор")),
    ("power", "Питание и охлаждение", ("блок питания", "вентилятор", "fan", "psu")),
)


def composition_group(*values: Any) -> tuple[str, str]:
    """Classify a historical issue for compact operator-facing grouping."""
    haystack = " ".join(str(value or "") for value in values).casefold()
    for key, label, needles in _GROUPS:
        if any(needle in haystack for needle in needles):
            return key, label
    return "other", "Другое"


_TASK_IN_COMMENT = re.compile(
    r"\b(?:ИЗМ|ЗНР|ПНР|ЗНО|ИНЦ)\s*(?:[-№:#]\s*)?[A-ZА-ЯЁ0-9][A-ZА-ЯЁ0-9._/-]*",
    re.IGNORECASE,
)


def _task_reference(
    task_type: Any, task_number: Any, comment: Any
) -> tuple[str, str]:
    task_type = str(task_type or "").strip()
    task_number = str(task_number or "").strip()
    if task_type and task_number:
        return f"{task_type}-{task_number}", "fields"
    if task_type or task_number:
        return task_type or task_number, "fields"
    match = _TASK_IN_COMMENT.search(str(comment or ""))
    return (match.group(0).strip(), "comment") if match else ("", "")


class EquipmentCompositionService(WarehouseComponent):
    """Build an evidence-only view; it never claims verified physical state."""

    def for_target(self, serial_number: str) -> dict[str, Any]:
        target_serial = str(serial_number or "").strip()
        operations: list[dict[str, Any]] = []
        if target_serial:
            with connect(self.db_path) as db:
                rows = db.execute(
                    """WITH allocation_summary AS (
                           SELECT a.issue_id,
                                  SUM(a.quantity) AS allocated_quantity,
                                  MIN(r.item_name) AS item_name,
                                  MIN(r.vendor) AS vendor,
                                  MIN(r.model) AS model,
                                  MIN(r.inventory_number) AS inventory_number,
                                  MIN(r.serial_number) AS serial_number,
                                  MIN(r.equipment_type) AS equipment_type,
                                  MIN(r.component_type) AS component_type,
                                  MIN(r.cable_type) AS cable_type,
                                  MIN(r.unit) AS unit
                             FROM stock_issue_allocations a
                             JOIN stock_receipts r ON r.id = a.receipt_id
                            GROUP BY a.issue_id
                       )
                       SELECT i.id AS issue_id, i.issue_date, i.responsible,
                              i.task_type, i.task_number, i.target_serial_number,
                              i.target_hostname, i.source_serial_number,
                              i.source_item_name, i.source_cable_type,
                              i.quantity, i.comment,
                              COALESCE(a.allocated_quantity, i.quantity) AS linked_quantity,
                              COALESCE(NULLIF(i.source_item_name, ''), a.item_name, '') AS item_name,
                              COALESCE(a.vendor, '') AS vendor,
                              COALESCE(a.model, '') AS model,
                              COALESCE(a.inventory_number, '') AS inventory_number,
                              COALESCE(NULLIF(i.source_serial_number, ''), a.serial_number, '') AS serial_number,
                              COALESCE(a.equipment_type, '') AS equipment_type,
                              COALESCE(a.component_type, '') AS component_type,
                              COALESCE(NULLIF(i.source_cable_type, ''), a.cable_type, '') AS cable_type,
                              COALESCE(a.unit, '') AS unit
                         FROM stock_issues i
                         LEFT JOIN allocation_summary a ON a.issue_id = i.id
                        WHERE trim(i.target_serial_number) <> ''
                          AND trim(i.target_serial_number) = trim(?) COLLATE NOCASE
                        ORDER BY NULLIF(trim(i.issue_date), '') DESC, i.id DESC""",
                    (target_serial,),
                ).fetchall()
            for row in rows:
                item_type = (
                    row["component_type"] or row["equipment_type"] or row["cable_type"]
                )
                group_key, group_label = composition_group(
                    item_type, row["item_name"], row["model"]
                )
                task_reference, task_reference_source = _task_reference(
                    row["task_type"], row["task_number"], row["comment"]
                )
                operations.append({
                    "issue_id": int(row["issue_id"]),
                    "issue_date": str(row["issue_date"] or ""),
                    "source_serial_number": str(row["serial_number"] or ""),
                    "item_name": str(row["item_name"] or ""),
                    "vendor": str(row["vendor"] or ""),
                    "model": str(row["model"] or ""),
                    "inventory_number": str(row["inventory_number"] or ""),
                    "item_type": str(item_type or ""),
                    "group_key": group_key,
                    "group_label": group_label,
                    "quantity": float(row["linked_quantity"] or 0),
                    "unit": str(row["unit"] or "шт"),
                    "target_hostname": str(row["target_hostname"] or ""),
                    "task_type": str(row["task_type"] or ""),
                    "task_number": str(row["task_number"] or ""),
                    "task_reference": task_reference,
                    "task_reference_source": task_reference_source,
                    "responsible": str(row["responsible"] or ""),
                    "comment": str(row["comment"] or ""),
                    "current_state": "unconfirmed",
                    "placement_known": False,
                })

        grouped: OrderedDict[str, dict[str, Any]] = OrderedDict()
        for operation in operations:
            key = operation["group_key"]
            group = grouped.setdefault(key, {
                "key": key,
                "label": operation["group_label"],
                "operations_count": 0,
                "quantity": 0.0,
                "latest_date": operation["issue_date"],
            })
            group["operations_count"] += 1
            group["quantity"] += float(operation["quantity"])

        return {
            "basis": "ISSUE_HISTORY",
            "title": "Связанные компоненты по данным списаний",
            "current_state_confirmed": False,
            "placement_known": False,
            "total_operations": len(operations),
            "total_quantity": sum(float(row["quantity"]) for row in operations),
            "groups": list(grouped.values()),
            "operations": operations,
        }
