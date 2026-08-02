"""Extracted Warehouse domain service."""

from __future__ import annotations

import csv
import json
import re
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

from inventory.db import connect
from inventory.shared.validators import WarehouseError

from .classification import (
    canonical_vendor,
    classify_card,
    infer_vendor,
    operational_category,
)
from .component import WarehouseComponent
from .issue_repository import IssueRepository


class WarehouseBalanceService(WarehouseComponent):
    @staticmethod
    def _operational_category(
        equipment_type: Any, component_type: Any, cable_type: Any
    ) -> str:
        return operational_category(equipment_type, component_type, cable_type)

    def dashboard_stats(self) -> dict[str, int | float]:
        """Вернуть показатели, рассчитанные только по новой складской модели."""
        with connect(self.db_path) as db:
            row = db.execute(
                """WITH lots AS (
                       SELECT r.project, r.item_name, r.vendor, r.model,
                              r.serial_number, r.inventory_number, r.unit,
                              r.object_name, r.equipment_type, r.component_type,
                              r.cable_type, r.datacenter,
                              r.quantity - COALESCE(SUM(a.quantity), 0) AS balance
                       FROM stock_receipts r
                       LEFT JOIN stock_issue_allocations a ON a.receipt_id = r.id
                       GROUP BY r.id
                   ), positions AS (
                       SELECT cable_type, SUM(balance) AS balance
                       FROM lots
                       GROUP BY project, item_name, vendor, model, serial_number,
                                inventory_number, unit, object_name, equipment_type,
                                component_type, cable_type, datacenter
                   )
                   SELECT
                       COALESCE((SELECT SUM(quantity) FROM stock_receipts), 0) AS receipts,
                       COALESCE((SELECT SUM(quantity) FROM stock_issues), 0) AS issues,
                       (SELECT COUNT(*) FROM stock_receipts) AS cards,
                       (SELECT COUNT(DISTINCT trim(supplier)) FROM stock_receipts
                         WHERE trim(supplier) <> '') AS suppliers,
                       (SELECT COUNT(DISTINCT CASE
                            WHEN trim(equipment_type) <> '' THEN 'equipment:' || trim(equipment_type)
                            WHEN trim(component_type) <> '' THEN 'component:' || trim(component_type)
                            WHEN trim(cable_type) <> '' THEN 'cable:' || trim(cable_type)
                            ELSE 'other'
                        END) FROM stock_receipts) AS categories,
                       COALESCE((SELECT SUM(quantity) FROM stock_receipts), 0)
                         - COALESCE((SELECT SUM(quantity) FROM stock_issue_allocations), 0)
                         AS balance,
                       COALESCE((SELECT SUM(quantity) FROM stock_receipts
                                 WHERE receipt_date = date('now', 'localtime')), 0)
                         AS received_today,
                       COALESCE((SELECT SUM(a.quantity)
                                 FROM stock_issue_allocations a
                                 JOIN stock_issues i ON i.id = a.issue_id
                                 WHERE i.issue_date = date('now', 'localtime')), 0)
                         AS issued_today,
                       (SELECT COUNT(*) FROM deliveries) AS deliveries,
                       (SELECT COUNT(*) FROM positions WHERE balance > 0.0000001) AS positions,
                       COALESCE((SELECT SUM(balance) FROM positions
                                 WHERE balance > 0.0000001 AND cable_type = ''), 0)
                         AS equipment,
                       COALESCE((SELECT SUM(balance) FROM positions
                                 WHERE balance > 0.0000001 AND cable_type <> ''), 0)
                         AS cables
                """
            ).fetchone()
        return {
            "receipts": float(row["receipts"]),
            "issues": float(row["issues"]),
            "cards": int(row["cards"]),
            "suppliers": int(row["suppliers"]),
            "categories": int(row["categories"]),
            "balance": float(row["balance"]),
            "positions": int(row["positions"]),
            "equipment": float(row["equipment"]),
            "cables": float(row["cables"]),
            "received_today": float(row["received_today"]),
            "issued_today": float(row["issued_today"]),
            "deliveries": int(row["deliveries"]),
        }

    def balance_by_category(self) -> list[dict[str, Any]]:
        """Вернуть остатки, сгруппированные по категории и ЦОД."""
        with connect(self.db_path) as db:
            rows = db.execute(
                """SELECT c.name AS category, e.datacenter,
                          COUNT(*) AS positions, COALESCE(SUM(e.quantity), 0) AS quantity
                   FROM equipment e
                   JOIN categories c ON c.id = e.category_id
                   GROUP BY c.name, e.datacenter
                   ORDER BY c.name, e.datacenter"""
            ).fetchall()
            return [dict(row) for row in rows]

    def warehouse_categories(self) -> list[dict[str, Any]]:
        names = ("Серверы", "Диски", "Память", "Сетевое оборудование", "Кабели", "Прочее")
        totals = {name: 0.0 for name in names}

        def category_name(
            item_name: str, equipment_type: str, component_type: str, cable_type: str
        ) -> str:
            text = " ".join((
                str(item_name or ""), str(equipment_type or ""),
                str(component_type or ""), str(cable_type or ""),
            )).casefold()
            if cable_type:
                return "Кабели"
            if "сервер" in text:
                return "Серверы"
            if any(value in text for value in ("диск", "ssd", "hdd")):
                return "Диски"
            if any(value in text for value in ("памят", "ram", "dimm")):
                return "Память"
            if any(value in text for value in ("сет", "коммут", "switch", "маршрут")):
                return "Сетевое оборудование"
            return "Прочее"

        with connect(self.db_path) as db:
            db.create_function("ode_warehouse_category", 4, category_name, deterministic=True)
            rows = db.execute(
                """SELECT ode_warehouse_category(
                              r.item_name, r.equipment_type, r.component_type, r.cable_type
                          ) AS category,
                          SUM(r.quantity - COALESCE(a.issued, 0)) AS balance
                   FROM stock_receipts r
                   LEFT JOIN (
                       SELECT receipt_id, SUM(quantity) AS issued
                       FROM stock_issue_allocations GROUP BY receipt_id
                   ) a ON a.receipt_id = r.id
                   GROUP BY category"""
            ).fetchall()
        for row in rows:
            totals[str(row["category"])] = float(row["balance"])
        return [{"name": name, "quantity": totals[name]} for name in names]

    def warehouse_type_summary(self) -> list[dict[str, Any]]:
        """Вернуть точные остатки и число складских позиций по рабочим типам."""
        with connect(self.db_path) as db:
            rows = db.execute(
                """WITH allocations AS (
                       SELECT receipt_id, SUM(quantity) AS issued
                       FROM stock_issue_allocations GROUP BY receipt_id
                   ), lots AS (
                       SELECT r.project, r.item_name, r.supplier, r.vendor, r.model,
                              r.serial_number, r.inventory_number, r.unit, r.object_name,
                              r.equipment_type, r.component_type, r.cable_type, r.datacenter,
                              r.quantity - COALESCE(a.issued, 0) AS balance
                       FROM stock_receipts r
                       LEFT JOIN allocations a ON a.receipt_id = r.id
                   ), positions AS (
                       SELECT CASE
                                  WHEN lower(trim(cable_type)) IN ('aoc','dac') THEN 'Кабельные сборки'
                                  WHEN trim(cable_type) <> '' THEN 'Кабели'
                                  WHEN trim(COALESCE(NULLIF(trim(component_type),''),NULLIF(trim(equipment_type),''),'')) = 'Трансивер'
                                       OR lower(trim(COALESCE(NULLIF(trim(component_type),''),NULLIF(trim(equipment_type),''),''))) = 'transceiver'
                                      THEN 'Трансиверы'
                                  WHEN trim(COALESCE(NULLIF(trim(component_type),''),NULLIF(trim(equipment_type),''),'')) = 'Оперативная память'
                                       OR lower(trim(COALESCE(NULLIF(trim(component_type),''),NULLIF(trim(equipment_type),''),''))) IN ('memory','ram')
                                      THEN 'Память'
                                  WHEN lower(trim(COALESCE(NULLIF(component_type,''),NULLIF(equipment_type,''),'')))
                                       IN ('ssd','hdd') THEN 'Накопители'
                                  WHEN trim(COALESCE(NULLIF(trim(component_type),''),NULLIF(trim(equipment_type),''),''))
                                       IN ('Сетевой адаптер','HBA-адаптер','RAID-контроллер')
                                       OR lower(trim(COALESCE(NULLIF(trim(component_type),''),NULLIF(trim(equipment_type),''),'')))
                                       IN ('nic','hba','raid controller')
                                      THEN 'Адаптеры и контроллеры'
                                  WHEN trim(COALESCE(NULLIF(trim(component_type),''),NULLIF(trim(equipment_type),''),'')) = 'Аксессуар'
                                       OR lower(trim(COALESCE(NULLIF(trim(component_type),''),NULLIF(trim(equipment_type),''),''))) = 'accessory'
                                      THEN 'Другое оборудование'
                                  WHEN trim(component_type) = 'Прочий компонент'
                                       OR lower(trim(component_type)) = 'other'
                                      THEN 'Другое оборудование'
                                  WHEN trim(component_type) <> '' THEN 'Комплектующие'
                                  WHEN trim(equipment_type) = 'Прочее оборудование'
                                       OR lower(trim(equipment_type)) = 'other'
                                      THEN 'Другое оборудование'
                                  WHEN trim(equipment_type) <> '' THEN 'Оборудование'
                                  ELSE 'Другое оборудование'
                              END AS category,
                              COALESCE(
                                  NULLIF(trim(equipment_type), ''),
                                  NULLIF(trim(component_type), ''),
                                  NULLIF(trim(cable_type), ''),
                                  'Без типа'
                              ) AS item_type,
                              SUM(balance) AS balance
                       FROM lots
                       GROUP BY project, item_name, supplier, vendor, model,
                                serial_number, inventory_number, unit, object_name,
                                equipment_type, component_type, cable_type, datacenter
                   )
                   SELECT category, item_type, COUNT(*) AS positions,
                          SUM(balance) AS quantity
                   FROM positions
                   WHERE balance > 0.0000001
                   GROUP BY category, item_type
                   ORDER BY CASE category
                                WHEN 'Оборудование' THEN 1
                                WHEN 'Трансиверы' THEN 2
                                WHEN 'Память' THEN 3
                                WHEN 'Накопители' THEN 4
                                WHEN 'Адаптеры и контроллеры' THEN 5
                                WHEN 'Комплектующие' THEN 6
                                WHEN 'Кабели' THEN 7
                                WHEN 'Кабельные сборки' THEN 8
                                ELSE 9
                            END,
                            positions DESC, item_type COLLATE NOCASE"""
            ).fetchall()
        return [
            {
                "category": str(row["category"]),
                "item_type": str(row["item_type"]),
                "positions": int(row["positions"]),
                "quantity": float(row["quantity"]),
            }
            for row in rows
        ]

    def warehouse_model_options(self) -> list[dict[str, Any]]:
        """Return model choices scoped by the actually observed vendor and item type."""
        with connect(self.db_path) as db:
            rows = db.execute(
                """WITH allocations AS (
                       SELECT receipt_id, SUM(quantity) AS issued
                       FROM stock_issue_allocations GROUP BY receipt_id
                   ), lots AS (
                       SELECT trim(r.vendor) AS vendor, trim(r.model) AS model,
                              COALESCE(
                                  NULLIF(trim(r.equipment_type), ''),
                                  NULLIF(trim(r.component_type), ''),
                                  NULLIF(trim(r.cable_type), ''),
                                  'Без типа'
                              ) AS item_type,
                              r.quantity - COALESCE(a.issued, 0) AS balance
                       FROM stock_receipts r
                       LEFT JOIN allocations a ON a.receipt_id = r.id
                   )
                   SELECT vendor, model, item_type, COUNT(*) AS positions
                   FROM lots
                   WHERE balance > 0.0000001 AND vendor <> '' AND model <> ''
                   GROUP BY vendor, model, item_type
                   ORDER BY vendor COLLATE NOCASE, item_type COLLATE NOCASE,
                            positions DESC, model COLLATE NOCASE"""
            ).fetchall()
        return [dict(row) for row in rows]

    def stock_balance(
        self,
        query: str = "",
        project: str = "",
        object_name: str = "",
        equipment_type: str = "",
        component_type: str = "",
        cable_type: str = "",
        unit: str = "",
        datacenter: str = "",
        category: str = "",
        item_type: str = "",
        supplier: str = "",
        vendor: str = "",
        stock_state: str = "",
        sort_by: str = "item_name",
        sort_dir: str = "asc",
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Рассчитать баланс как приход минус распределенный расход, без учета полки."""
        filters = {
            "project": project, "object_name": object_name,
            "equipment_type": equipment_type, "component_type": component_type,
            "cable_type": cable_type, "unit": unit, "datacenter": datacenter,
            "supplier": supplier, "vendor": vendor,
        }
        where: list[str] = []
        params: list[Any] = []
        for field, value in filters.items():
            if value:
                where.append(f"{field} = ? COLLATE NOCASE")
                params.append(value)
        if query.strip():
            term = f"%{query.strip()}%"
            where.append(
                "(serial_number LIKE ? OR inventory_number LIKE ? OR item_name LIKE ? "
                "OR model LIKE ? OR vendor LIKE ? OR supplier LIKE ? OR project LIKE ? "
                "OR object_name LIKE ? OR shelf LIKE ?)"
            )
            params.extend([term] * 9)
        where_sql = "WHERE " + " AND ".join(where) if where else ""
        position_filters: list[str] = []
        if category:
            position_filters.append("category = ? COLLATE NOCASE")
            params.append(category)
        if item_type:
            position_filters.append("item_type = ? COLLATE NOCASE")
            params.append(item_type)
        if stock_state == "positive":
            position_filters.append("balance > 0.0000001")
        elif stock_state == "zero":
            position_filters.append("abs(balance) <= 0.0000001")
        position_where_sql = (
            "WHERE " + " AND ".join(position_filters) if position_filters else ""
        )
        sort_columns = {
            "item_name": "item_name COLLATE NOCASE",
            "item_type": "item_type COLLATE NOCASE",
            "category": "category COLLATE NOCASE",
            "balance": "balance",
            "serial_number": "serial_number COLLATE NOCASE",
            "shelf": "shelf COLLATE NOCASE",
            "vendor": "vendor COLLATE NOCASE",
            "model": "model COLLATE NOCASE",
            "supplier": "supplier COLLATE NOCASE",
            "project": "project COLLATE NOCASE",
        }
        order_column = sort_columns.get(sort_by, sort_columns["item_name"])
        order_direction = "DESC" if sort_dir.casefold() == "desc" else "ASC"
        with connect(self.db_path) as db:
            limit_sql = ""
            if limit is not None:
                limit = max(1, min(int(limit), 10_000))
                offset = max(0, int(offset))
                limit_sql = " LIMIT ? OFFSET ?"
                params.extend((limit, offset))
            rows = db.execute(
                f"""WITH allocations AS (
                       SELECT receipt_id, SUM(quantity) AS issued
                       FROM stock_issue_allocations GROUP BY receipt_id
                   ), lots AS (
                       SELECT r.id, r.project, r.item_name, r.supplier, r.vendor, r.model, r.serial_number,
                              r.inventory_number, r.shelf, r.object_name,
                              r.equipment_type, r.component_type, r.cable_type,
                              r.unit, r.datacenter,
                              r.quantity - COALESCE(a.issued, 0) AS balance
                       FROM stock_receipts r
                       LEFT JOIN allocations a ON a.receipt_id = r.id
                   ), positions AS (
                   SELECT GROUP_CONCAT(id) AS receipt_ids,
                          project, item_name, supplier, vendor, model, serial_number, inventory_number,
                          SUM(balance) AS balance, unit,
                          GROUP_CONCAT(DISTINCT NULLIF(shelf, '')) AS shelf,
                          object_name, equipment_type, component_type, cable_type,
                          datacenter,
                          CASE
                              WHEN lower(trim(cable_type)) IN ('aoc','dac') THEN 'Кабельные сборки'
                              WHEN trim(cable_type) <> '' THEN 'Кабели'
                              WHEN trim(COALESCE(NULLIF(trim(component_type),''),NULLIF(trim(equipment_type),''),'')) = 'Трансивер'
                                   OR lower(trim(COALESCE(NULLIF(trim(component_type),''),NULLIF(trim(equipment_type),''),''))) = 'transceiver'
                                  THEN 'Трансиверы'
                              WHEN trim(COALESCE(NULLIF(trim(component_type),''),NULLIF(trim(equipment_type),''),'')) = 'Оперативная память'
                                   OR lower(trim(COALESCE(NULLIF(trim(component_type),''),NULLIF(trim(equipment_type),''),''))) IN ('memory','ram')
                                  THEN 'Память'
                              WHEN lower(trim(COALESCE(NULLIF(component_type,''),NULLIF(equipment_type,''),'')))
                                   IN ('ssd','hdd') THEN 'Накопители'
                              WHEN trim(COALESCE(NULLIF(trim(component_type),''),NULLIF(trim(equipment_type),''),''))
                                   IN ('Сетевой адаптер','HBA-адаптер','RAID-контроллер')
                                   OR lower(trim(COALESCE(NULLIF(trim(component_type),''),NULLIF(trim(equipment_type),''),'')))
                                   IN ('nic','hba','raid controller')
                                  THEN 'Адаптеры и контроллеры'
                              WHEN trim(COALESCE(NULLIF(trim(component_type),''),NULLIF(trim(equipment_type),''),'')) = 'Аксессуар'
                                   OR lower(trim(COALESCE(NULLIF(trim(component_type),''),NULLIF(trim(equipment_type),''),''))) = 'accessory'
                                  THEN 'Другое оборудование'
                              WHEN trim(component_type) = 'Прочий компонент'
                                   OR lower(trim(component_type)) = 'other'
                                  THEN 'Другое оборудование'
                              WHEN trim(component_type) <> '' THEN 'Комплектующие'
                              WHEN trim(equipment_type) = 'Прочее оборудование'
                                   OR lower(trim(equipment_type)) = 'other'
                                  THEN 'Другое оборудование'
                              WHEN trim(equipment_type) <> '' THEN 'Оборудование'
                              ELSE 'Другое оборудование'
                          END AS category,
                          COALESCE(
                              NULLIF(trim(equipment_type), ''),
                              NULLIF(trim(component_type), ''),
                              NULLIF(trim(cable_type), ''),
                              'Без типа'
                          ) AS item_type
                   FROM lots {where_sql}
                   GROUP BY project, item_name, supplier, vendor, model, serial_number, inventory_number,
                            unit, object_name, equipment_type, component_type,
                            cable_type, datacenter
                   )
                   SELECT * FROM positions {position_where_sql}
                   ORDER BY {order_column} {order_direction},
                            item_name COLLATE NOCASE, model COLLATE NOCASE,
                            serial_number COLLATE NOCASE{limit_sql}""",
                params,
            ).fetchall()
            result = [dict(row) for row in rows]
            for row in result:
                row["position_key"] = (
                    f"sn:{row['serial_number']}" if row["serial_number"] else
                    "cable:" + "|".join(str(row.get(key) or "") for key in (
                        "item_name", "cable_type", "project", "datacenter"
                    ))
                )
            return result

    def search_stock_positions(self, query: str, limit: int = 100) -> list[dict[str, Any]]:
        query = self._required(query, "поисковый запрос")
        return self.stock_balance(query=query, limit=max(1, min(int(limit), 500)))

    def global_search(self, query: str, limit: int = 30) -> list[dict[str, Any]]:
        """Искать складские позиции, поставки и инженеров одной ограниченной выдачей."""
        query = self._required(query, "поисковый запрос")
        if len(query) < 2:
            raise WarehouseError("Введите не менее двух символов")
        if len(query) > 120:
            raise WarehouseError("Поисковый запрос слишком длинный")
        limit = max(1, min(int(limit), 50))
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        term = f"%{escaped}%"
        match = " LIKE ? ESCAPE '\\' COLLATE NOCASE"
        select_position = """SELECT r.id, r.serial_number, r.inventory_number, r.item_name,
                                    r.vendor, r.model, r.project, r.shelf, r.datacenter,
                                    r.equipment_type, r.component_type, r.cable_type,
                                    COALESCE((SELECT d.delivery_number
                                              FROM delivery_lines l
                                              JOIN deliveries d ON d.id = l.delivery_id
                                              WHERE l.receipt_id = r.id LIMIT 1), '') delivery_number
                             FROM stock_receipts r"""
        position_rows: list[sqlite3.Row] = []
        position_ids: set[int] = set()

        def add_positions(rows: Iterable[sqlite3.Row]) -> None:
            for row in rows:
                row_id = int(row["id"])
                if row_id not in position_ids and len(position_rows) < limit:
                    position_ids.add(row_id)
                    position_rows.append(row)

        with connect(self.db_path) as db:
            # Exact identifiers use the existing partial unique indexes. This is
            # the dominant scanner/search path and stays fast on large databases.
            add_positions(db.execute(
                select_position
                + " WHERE trim(r.serial_number) <> '' AND trim(r.serial_number) = trim(?) COLLATE NOCASE LIMIT ?",
                (query, limit),
            ))
            add_positions(db.execute(
                select_position
                + " WHERE trim(r.inventory_number) <> '' AND r.inventory_number = ? COLLATE NOCASE LIMIT ?",
                (query, limit),
            ))

            exact_position = bool(position_rows)
            remaining = 0 if exact_position else limit - len(position_rows)
            if remaining:
                base_fields = (
                    "r.serial_number", "r.inventory_number", "r.item_name", "r.equipment_type",
                    "r.component_type", "r.cable_type", "r.vendor", "r.model", "r.project",
                    "r.shelf", "r.object_name", "r.datacenter", "r.responsible",
                    "r.order_number", "r.request_number",
                )
                add_positions(db.execute(
                    select_position
                    + f" WHERE {' OR '.join(field + match for field in base_fields)} LIMIT ?",
                    [term] * len(base_fields) + [remaining],
                ))

            remaining = 0 if exact_position else limit - len(position_rows)
            if remaining:
                has_migration_identity = db.execute(
                    """SELECT 1 FROM sqlite_master
                       WHERE type='table' AND name='migration_full_identities'"""
                ).fetchone() is not None
                if has_migration_identity:
                    migration_ids = [int(row[0]) for row in db.execute(
                        f"""SELECT DISTINCT target_receipt_id
                             FROM migration_full_identities
                             WHERE target_receipt_id IS NOT NULL AND (
                               canonical_item_name{match} OR source_item_name{match} OR
                               part_number{match} OR vendor{match} OR model{match})
                             LIMIT ?""",
                        [term] * 5 + [remaining],
                    )]
                    if migration_ids:
                        placeholders = ",".join("?" for _ in migration_ids)
                        add_positions(db.execute(
                            select_position + f" WHERE r.id IN ({placeholders}) LIMIT ?",
                            [*migration_ids, remaining],
                        ))

            remaining = 0 if exact_position else limit - len(position_rows)
            if remaining:
                related_ids = [int(row[0]) for row in db.execute(
                    f"""SELECT DISTINCT l.receipt_id
                         FROM delivery_lines l JOIN deliveries d ON d.id = l.delivery_id
                         WHERE l.receipt_id IS NOT NULL AND (
                           d.delivery_number{match} OR d.supplier{match} OR
                           l.delivery_number{match} OR l.order_number{match} OR
                           l.request_number{match}) LIMIT ?""",
                    [term] * 5 + [remaining],
                )]
                related_ids.extend(int(row[0]) for row in db.execute(
                    f"""SELECT DISTINCT a.receipt_id
                         FROM stock_issues i
                         JOIN stock_issue_allocations a ON a.issue_id = i.id
                         WHERE i.responsible{match} LIMIT ?""",
                    (term, remaining),
                ))
                target_serials = [str(row[0]) for row in db.execute(
                    f"""SELECT DISTINCT target_serial_number FROM stock_issues
                         WHERE trim(target_serial_number) <> '' AND target_hostname{match} LIMIT ?""",
                    (term, remaining),
                )]
                if related_ids:
                    unique_ids = list(dict.fromkeys(related_ids))[:remaining]
                    placeholders = ",".join("?" for _ in unique_ids)
                    add_positions(db.execute(
                        select_position + f" WHERE r.id IN ({placeholders}) LIMIT ?",
                        [*unique_ids, remaining],
                    ))
                if target_serials and len(position_rows) < limit:
                    placeholders = ",".join("?" for _ in target_serials)
                    add_positions(db.execute(
                        select_position
                        + f" WHERE trim(r.serial_number) <> '' AND r.serial_number COLLATE NOCASE IN ({placeholders}) LIMIT ?",
                        [*target_serials, limit - len(position_rows)],
                    ))

            remaining = 0 if exact_position else max(0, limit - len(position_rows))
            delivery_fields = (
                "d.delivery_number", "d.supplier", "d.source_filename", "d.uploaded_by",
                "l.serial_number", "l.asset_number", "l.order_number", "l.request_number",
                "l.item_name", "l.vendor", "l.model", "l.project", "l.shelf", "l.datacenter",
            )
            delivery_rows = db.execute(
                f"""SELECT DISTINCT d.id, d.delivery_number, d.supplier, d.status,
                           d.source_filename
                    FROM deliveries d
                    LEFT JOIN delivery_lines l ON l.delivery_id = d.id
                    WHERE {" OR ".join(field + match for field in delivery_fields)}
                    ORDER BY d.uploaded_at DESC, d.id DESC LIMIT ?""",
                [term] * len(delivery_fields) + [remaining],
            ).fetchall() if remaining else []
            remaining = max(0, remaining - len(delivery_rows))
            engineer_rows: list[dict[str, Any]] = []
            seen_engineers: set[str] = set()
            for table, name_column, date_column in (
                ("stock_receipts", "responsible", "created_at"),
                ("stock_issues", "responsible", "created_at"),
                ("audit_log", "author", "event_date"),
            ):
                if len(engineer_rows) >= remaining:
                    break
                for row in db.execute(
                    f"""SELECT {name_column} engineer, {date_column} last_activity
                         FROM {table} WHERE trim({name_column}) <> ''
                           AND {name_column}{match} LIMIT ?""",
                    (term, remaining - len(engineer_rows)),
                ):
                    key = str(row["engineer"]).casefold()
                    if key not in seen_engineers:
                        seen_engineers.add(key)
                        engineer_rows.append(dict(row))
        results: list[dict[str, Any]] = []
        for row in position_rows:
            item = dict(row)
            item_type = item["equipment_type"] or item["component_type"] or item["cable_type"]
            item["category"] = self._operational_category(
                item["equipment_type"], item["component_type"], item["cable_type"]
            )
            item["item_type"] = item_type
            item["position_key"] = (
                f"sn:{item['serial_number']}" if item["serial_number"] else
                "cable:" + "|".join(str(item.get(key) or "") for key in (
                    "item_name", "cable_type", "project", "datacenter"
                ))
            )
            results.append({"kind": "position", "position": item})
        results.extend({"kind": "delivery", "delivery": dict(row)} for row in delivery_rows)
        results.extend({"kind": "engineer", "engineer": dict(row)} for row in engineer_rows)
        return results[:limit]

    def position_card(
        self,
        serial_number: str = "",
        item_name: str = "",
        cable_type: str = "",
        project: str = "",
        datacenter: str = "",
        receipt_id: int | None = None,
        include_migration_audit: bool = True,
    ) -> dict[str, Any]:
        """Вернуть карточку агрегированной позиции и связанную хронологию."""
        serial_number = serial_number.strip().upper()
        where: list[str] = []
        params: list[Any] = []
        if receipt_id is not None:
            if isinstance(receipt_id, bool) or not isinstance(receipt_id, int) or receipt_id <= 0:
                raise WarehouseError("Некорректный идентификатор складской позиции")
            where.append("r.id = ?")
            params.append(receipt_id)
        elif serial_number:
            where.extend(("trim(r.serial_number) <> ''", "trim(r.serial_number) = trim(?) COLLATE NOCASE"))
            params.append(serial_number)
        else:
            item_name = self._required(item_name, "наименование")
            cable_type = self._required(cable_type, "тип кабеля")
            where.extend((
                "r.serial_number = ''", "r.item_name = ? COLLATE NOCASE",
                "r.cable_type = ? COLLATE NOCASE",
            ))
            params.extend((item_name, cable_type))
            if project:
                where.append("r.project = ? COLLATE NOCASE")
                params.append(project)
            if datacenter:
                where.append("r.datacenter = ? COLLATE NOCASE")
                params.append(datacenter)
        where_sql = " AND ".join(where)
        with connect(self.db_path) as db:
            receipts = db.execute(
                f"""SELECT r.*,
                           r.quantity - COALESCE(SUM(a.quantity), 0) AS available
                    FROM stock_receipts r
                    LEFT JOIN stock_issue_allocations a ON a.receipt_id = r.id
                    WHERE {where_sql} GROUP BY r.id ORDER BY r.receipt_date, r.id""",
                params,
            ).fetchall()
            if not receipts:
                raise WarehouseError("Позиция не найдена")
            exact_serial_number = str(receipts[0]["serial_number"] or "")
            receipt_ids = [int(row["id"]) for row in receipts]
            placeholders = ",".join("?" for _ in receipt_ids)
            identity = None
            if db.execute(
                """SELECT 1 FROM sqlite_master
                   WHERE type='table' AND name='migration_full_identities'"""
            ).fetchone() is not None:
                identity = db.execute(
                    f"""SELECT source_item_name,canonical_item_name,part_number,
                               category,equipment_type,component_type,vendor,model
                        FROM migration_full_identities
                        WHERE target_receipt_id IN ({placeholders})
                        ORDER BY authoritative DESC,id LIMIT 1""",
                    receipt_ids,
                ).fetchone()
            issues = db.execute(
                f"""SELECT i.*, a.receipt_id, a.quantity AS allocated_quantity
                    FROM stock_issues i
                    JOIN stock_issue_allocations a ON a.issue_id = i.id
                    WHERE a.receipt_id IN ({placeholders})
                    ORDER BY i.issue_date, i.id, a.id""",
                receipt_ids,
            ).fetchall()
            delivery_rows = db.execute(
                f"""SELECT l.*, d.delivery_number AS parent_delivery_number,
                           d.source_filename, d.uploaded_by, d.uploaded_at
                    FROM delivery_lines l JOIN deliveries d ON d.id = l.delivery_id
                    WHERE l.receipt_id IN ({placeholders})
                    ORDER BY l.updated_at, l.id""",
                receipt_ids,
            ).fetchall()
            issue_ids = sorted({int(row["id"]) for row in issues})
            audit_terms = [
                "(entity_type = 'stock_receipt' AND entity_id IN ("
                + placeholders + "))"
            ]
            audit_params: list[Any] = [str(value) for value in receipt_ids]
            if issue_ids:
                issue_placeholders = ",".join("?" for _ in issue_ids)
                audit_terms.append(
                    "(entity_type = 'stock_issue' AND entity_id IN ("
                    + issue_placeholders + "))"
                )
                audit_params.extend(str(value) for value in issue_ids)
            delivery_line_ids = [int(row["id"]) for row in delivery_rows]
            if delivery_line_ids:
                line_placeholders = ",".join("?" for _ in delivery_line_ids)
                audit_terms.append(
                    "(entity_type = 'delivery_line' AND entity_id IN ("
                    + line_placeholders + "))"
                )
                audit_params.extend(str(value) for value in delivery_line_ids)
            migration_clause = (
                "" if include_migration_audit
                else " AND action NOT LIKE 'MIGRATION_%'"
            )
            audits = db.execute(
                "SELECT * FROM audit_log WHERE (" + " OR ".join(audit_terms)
                + ")" + migration_clause + " ORDER BY event_date, id",
                audit_params,
            ).fetchall()
        first = dict(receipts[0])
        card = {key: first.get(key, "") for key in (
            "serial_number", "inventory_number", "item_name", "vendor", "model",
            "project", "object_name", "datacenter", "equipment_type",
            "component_type", "cable_type", "unit", "supplier", "order_number",
            "request_number", "receipt_date", "responsible",
        )}
        card["category"] = self._operational_category(
            card["equipment_type"], card["component_type"], card["cable_type"]
        )
        card["item_type"] = (
            card["equipment_type"] or card["component_type"] or card["cable_type"]
        )
        card["shelf"] = ", ".join(sorted({str(row["shelf"]) for row in receipts if row["shelf"]}))
        card["current_balance"] = sum(float(row["available"]) for row in receipts)
        card["status"] = "В наличии" if card["current_balance"] > 1e-9 else "Списано"
        card["delivery_number"] = ""
        card["hostname"] = ""
        card["rack_row"] = ""
        card["rack_unit"] = ""
        card["comment"] = ""
        card["canonical_name"] = str(identity["canonical_item_name"] or "") if identity else card["item_name"]
        card["source_name"] = str(identity["source_item_name"] or "") if identity else card["item_name"]
        card["part_number"] = str(identity["part_number"] or "") if identity else ""
        if identity:
            card["vendor"] = card["vendor"] or str(identity["vendor"] or "")
            card["model"] = card["model"] or str(identity["model"] or "")
            card["category"] = card["category"] or str(identity["category"] or "")
        if delivery_rows:
            delivery = dict(delivery_rows[-1])
            card["delivery_number"] = (
                delivery.get("parent_delivery_number") or delivery.get("delivery_number") or ""
            )
            card["order_number"] = card["order_number"] or delivery.get("order_number", "")
            card["request_number"] = card["request_number"] or delivery.get("request_number", "")
            card["comment"] = delivery.get("error_text", "")
        composition = self.actor_provider.equipment_composition.for_target(
            exact_serial_number
        )
        if composition["operations"]:
            card["hostname"] = composition["operations"][0]["target_hostname"]
        history: list[dict[str, Any]] = []
        for row in receipts:
            opening_state = bool(int(row["is_opening_balance"] or 0))
            history.append({
                "date": row["receipt_date"],
                "event_type": "Начальный остаток" if opening_state else "Приход",
                "quantity": float(row["quantity"]), "task": "",
                "responsible": row["responsible"],
                "comment": (
                    "Восстановлено начальное состояние до доступной истории операций"
                    if opening_state
                    else row["order_number"] or row["request_number"] or ""
                ),
                "sort_id": int(row["id"]),
            })
        for row in issues:
            history.append({
                "date": row["issue_date"], "event_type": "Расход",
                "quantity": -float(row["allocated_quantity"]),
                "task": (
                    f"{row['task_type']}-{row['task_number']}" if row["task_type"] else ""
                ),
                "responsible": row["responsible"], "comment": row["comment"],
                "sort_id": 1_000_000 + int(row["id"]),
            })
        for row in reversed(composition["operations"]):
            history.append({
                "date": row["issue_date"], "event_type": "Компонент списан на оборудование",
                "quantity": float(row["quantity"]),
                "task": row["task_reference"],
                "responsible": row["responsible"],
                "comment": " ".join(filter(None, (
                    str(row["source_serial_number"] or row["item_name"]),
                    str(row["comment"] or ""),
                ))),
                "sort_id": 1_250_000 + int(row["issue_id"]),
            })
        for row in delivery_rows:
            history.append({
                "date": row["updated_at"] or row["uploaded_at"],
                "event_type": "Принято по поставке",
                "quantity": float(row["quantity"]),
                "task": row["parent_delivery_number"] or row["delivery_number"],
                "responsible": row["updated_by"] or row["uploaded_by"],
                "comment": row["source_filename"],
                "sort_id": 1_500_000 + int(row["id"]),
            })
        for row in audits:
            history.append({
                "date": row["event_date"], "event_type": f"Запись журнала: {row['action']}",
                "quantity": "", "task": "", "responsible": row["author"],
                "comment": row["details"], "sort_id": 2_000_000 + int(row["id"]),
            })
        history.sort(key=lambda row: (str(row["date"]), int(row["sort_id"])))
        for row in history:
            row.pop("sort_id", None)
        return {"position": card, "history": history, "composition": composition}

    def update_position_card(
        self, serial_number: str, fields: dict[str, Any]
    ) -> dict[str, Any]:
        """Update descriptive fields of one serialized card without changing identity/history."""

        actor = self._require_write()
        serial_number = self._required(str(serial_number or ""), "S/N")
        editable = (
            "item_name", "supplier", "vendor", "model", "project", "shelf",
            "object_name", "datacenter", "equipment_type", "component_type",
            "cable_type", "unit",
        )
        normalized: dict[str, str] = {}
        for field in editable:
            value = str(fields.get(field, "") or "").strip()
            if len(value) > (1000 if field == "item_name" else 255):
                raise WarehouseError(f"Поле «{field}» слишком длинное")
            normalized[field] = value
        # Обязательны только идентификационно значимые поля: наименование и
        # тип (проверяется ниже). Остальные — описательные (поставщик, объект,
        # ЦОД, единица, вендор, модель, проект, полка) — могут быть пустыми:
        # у 99% исторических карточек «Объект» и у части «Поставщик» изначально
        # пусты, и требование их заполнения блокировало бы любое редактирование.
        normalized["item_name"] = self._required(normalized["item_name"], "наименование")
        selected_types = [
            field for field in ("equipment_type", "component_type", "cable_type")
            if normalized[field]
        ]
        if len(selected_types) != 1:
            raise WarehouseError("Выберите ровно один тип карточки")

        with self.lock, connect(self.db_path) as db:
            rows = db.execute(
                "SELECT * FROM stock_receipts WHERE serial_number=? COLLATE NOCASE ORDER BY id",
                (serial_number,),
            ).fetchall()
            if len(rows) != 1:
                raise WarehouseError(
                    "Карточка не найдена" if not rows
                    else "Для S/N найдено несколько карточек; автоматическое редактирование заблокировано"
                )
            row = rows[0]
            type_field = selected_types[0]
            if normalized[type_field] != str(row[type_field] or ""):
                if self.reference_catalog.has_v2(db):
                    exists = db.execute(
                        """SELECT 1 FROM reference_values_v2 v
                           JOIN reference_domains_v2 d ON d.id=v.domain_id
                           WHERE d.domain_key=? AND v.display_name=? COLLATE NOCASE
                             AND v.active=1 AND v.approval_status='APPROVED'""",
                        (type_field, normalized[type_field]),
                    ).fetchone()
                else:
                    exists = db.execute(
                        """SELECT 1 FROM reference_values
                           WHERE kind=? AND name=? COLLATE NOCASE AND is_active=1""",
                        (type_field, normalized[type_field]),
                    ).fetchone()
                if exists is None:
                    raise WarehouseError("Выбранный тип отсутствует в активном справочнике")
            before = {field: str(row[field] or "") for field in editable}
            changed = {
                field: {"before": before[field], "after": normalized[field]}
                for field in editable if before[field] != normalized[field]
            }
            if changed:
                assignments = ",".join(f"{field}=?" for field in editable)
                db.execute(
                    f"UPDATE stock_receipts SET {assignments} WHERE id=?",
                    (*[normalized[field] for field in editable], int(row["id"])),
                )
                self._audit(
                    db, "EQUIPMENT_CARD_UPDATED", "stock_receipt", int(row["id"]),
                    {"serial_number": str(row["serial_number"]), "changed": changed,
                     "actor_id": actor["id"]},
                )
        result = self.position_card(serial_number=serial_number)["position"]
        result["updated"] = bool(changed)
        return result

    def inventory_compare(self, rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
        """Compare a scanned S/N list with positive serialized stock."""
        scanned: list[str] = []
        for source in rows:
            serial = str(source.get("serial_number", source.get("source_serial_number", ""))).strip().upper()
            if serial:
                scanned.append(serial)
        if not scanned:
            raise WarehouseError("В CSV-файле нет S/N для инвентаризации")
        counts: dict[str, int] = {}
        for serial in scanned:
            counts[serial] = counts.get(serial, 0) + 1
        balance = {
            str(row["serial_number"]).upper(): row
            for row in self.stock_balance()
            if row["serial_number"] and float(row["balance"]) > 1e-9
        }
        scanned_set = set(counts)
        found = [{"serial_number": serial, "status": "Найдено"}
                 for serial in sorted(scanned_set & set(balance))]
        not_found = [{"serial_number": serial, "status": "Не найдено в базе"}
                     for serial in sorted(scanned_set - set(balance))]
        missing = [{"serial_number": serial, "status": "Есть в базе, но не было в скане"}
                   for serial in sorted(set(balance) - scanned_set)]
        duplicates = [{"serial_number": serial, "status": "Дубль в скане", "count": count}
                      for serial, count in sorted(counts.items()) if count > 1]
        result_rows = found + not_found + missing + duplicates
        return {
            "total": len(scanned), "found": found, "not_found": not_found,
            "missing": missing, "duplicates": duplicates, "rows": result_rows,
            "stats": {"found": len(found), "not_found": len(not_found),
                      "missing": len(missing), "duplicates": len(duplicates)},
        }
