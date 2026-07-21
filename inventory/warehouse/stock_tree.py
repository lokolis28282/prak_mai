"""Lazy, aggregate stock tree for the warehouse balance screen."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from inventory.db import connect
from inventory.shared.validators import WarehouseError


_EPSILON = 0.0000001
_LEVELS = ("category", "item_type", "vendor", "model")
_NEXT_LEVEL = {
    "category": "item_type",
    "item_type": "vendor",
    "vendor": "model",
    "model": None,
}

_CATEGORY_SQL = """CASE
    WHEN lower(trim(cable_type)) IN ('aoc','dac') THEN 'Кабельные сборки'
    WHEN trim(cable_type) <> '' THEN 'Кабели'
    WHEN trim(COALESCE(NULLIF(trim(component_type),''),NULLIF(trim(equipment_type),''),'')) = 'Трансивер'
         OR lower(trim(COALESCE(NULLIF(trim(component_type),''),NULLIF(trim(equipment_type),''),''))) = 'transceiver'
        THEN 'Трансиверы'
    WHEN trim(COALESCE(NULLIF(trim(component_type),''),NULLIF(trim(equipment_type),''),'')) = 'Оперативная память'
         OR lower(trim(COALESCE(NULLIF(trim(component_type),''),NULLIF(trim(equipment_type),''),''))) IN ('memory','ram')
        THEN 'Память'
    WHEN lower(trim(COALESCE(NULLIF(component_type,''),NULLIF(equipment_type,''),''))) IN ('ssd','hdd')
        THEN 'Накопители'
    WHEN trim(COALESCE(NULLIF(trim(component_type),''),NULLIF(trim(equipment_type),''),''))
         IN ('Сетевой адаптер','HBA-адаптер','RAID-контроллер')
         OR lower(trim(COALESCE(NULLIF(trim(component_type),''),NULLIF(trim(equipment_type),''),'')))
         IN ('nic','hba','raid controller')
        THEN 'Адаптеры и контроллеры'
    WHEN trim(COALESCE(NULLIF(trim(component_type),''),NULLIF(trim(equipment_type),''),'')) = 'Аксессуар'
         OR lower(trim(COALESCE(NULLIF(trim(component_type),''),NULLIF(trim(equipment_type),''),''))) = 'accessory'
        THEN 'Другое оборудование'
    WHEN trim(component_type) = 'Прочий компонент' OR lower(trim(component_type)) = 'other'
        THEN 'Другое оборудование'
    WHEN trim(component_type) <> '' THEN 'Комплектующие'
    WHEN trim(equipment_type) = 'Прочее оборудование' OR lower(trim(equipment_type)) = 'other'
        THEN 'Другое оборудование'
    WHEN trim(equipment_type) <> '' THEN 'Оборудование'
    ELSE 'Другое оборудование'
END"""

_TYPE_SQL = """COALESCE(
    NULLIF(trim(equipment_type), ''),
    NULLIF(trim(component_type), ''),
    NULLIF(trim(cable_type), ''),
    'Без типа'
)"""

_GROUP_EXPRESSIONS = {
    "category": "category",
    "item_type": "item_type",
    "vendor": "COALESCE(NULLIF(trim(vendor), ''), 'Не указано')",
    "model": (
        "COALESCE(NULLIF(trim(model), ''), NULLIF(trim(item_name), ''), 'Не указано')"
    ),
}

_CATEGORY_ORDER = """CASE value
    WHEN 'Оборудование' THEN 1
    WHEN 'Трансиверы' THEN 2
    WHEN 'Память' THEN 3
    WHEN 'Накопители' THEN 4
    WHEN 'Адаптеры и контроллеры' THEN 5
    WHEN 'Комплектующие' THEN 6
    WHEN 'Аксессуары' THEN 7
    WHEN 'Кабели' THEN 8
    WHEN 'Кабельные сборки' THEN 9
    ELSE 10
END"""


def _node_id(level: str, path: dict[str, str], suffix: str = "") -> str:
    serialized = json.dumps(
        {"level": level, "path": path, "suffix": suffix},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"{level}:{hashlib.sha256(serialized.encode('utf-8')).hexdigest()[:24]}"


class WarehouseStockTreeQuery:
    """Read the stock balance as a bounded, lazily expanded tree."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)

    def fetch(
        self,
        *,
        level: str = "category",
        path: dict[str, str] | None = None,
        filters: dict[str, str] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        if level not in _LEVELS:
            raise WarehouseError("Неизвестный уровень складского дерева")
        path = {key: str(value).strip() for key, value in (path or {}).items() if value}
        filters = {
            key: str(value).strip()
            for key, value in (filters or {}).items()
            if value is not None and str(value).strip()
        }
        self._validate(level, path, filters)
        limit = max(1, min(int(limit), 200))
        offset = max(0, min(int(offset), 1_000_000))

        cte_sql, params = self._positions_cte(filters, path)
        return self._fetch_groups(level, cte_sql, params, path, filters, limit, offset)

    @staticmethod
    def _validate(level: str, path: dict[str, str], filters: dict[str, str]) -> None:
        level_index = _LEVELS.index(level)
        required = _LEVELS[:level_index]
        missing = [name for name in required if name != "position" and not path.get(name)]
        if missing:
            raise WarehouseError("Не указан родительский путь складской группы")
        if len(filters.get("query", "")) > 160:
            raise WarehouseError("Поисковый запрос слишком длинный")
        for value in (*path.values(), *filters.values()):
            if len(value) > 500:
                raise WarehouseError("Значение фильтра слишком длинное")

    def _positions_cte(
        self, filters: dict[str, str], path: dict[str, str]
    ) -> tuple[str, list[Any]]:
        receipt_filters = {
            key: filters.get(key, "")
            for key in (
                "project", "object_name", "equipment_type", "component_type",
                "cable_type", "unit", "datacenter", "supplier", "vendor",
            )
        }
        receipt_where: list[str] = []
        params: list[Any] = []
        for field, value in receipt_filters.items():
            if value:
                receipt_where.append(f"{field} = ? COLLATE NOCASE")
                params.append(value)

        query = filters.get("query", "")
        if query:
            escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            term = f"%{escaped}%"
            searchable = (
                "serial_number", "inventory_number", "item_name", "model", "vendor",
                "supplier", "project", "object_name", "shelf", "equipment_type",
                "component_type", "cable_type",
            )
            receipt_where.append(
                "(" + " OR ".join(f"{field} LIKE ? ESCAPE '\\' COLLATE NOCASE" for field in searchable) + ")"
            )
            params.extend([term] * len(searchable))
        receipt_where_sql = "WHERE " + " AND ".join(receipt_where) if receipt_where else ""

        position_where: list[str] = []
        category = filters.get("category", "")
        item_type = filters.get("item_type", "")
        if category:
            position_where.append("category = ? COLLATE NOCASE")
            params.append(category)
        if item_type:
            position_where.append("item_type = ? COLLATE NOCASE")
            params.append(item_type)
        stock_state = filters.get("stock_state", "")
        if stock_state == "positive":
            position_where.append(f"balance > {_EPSILON}")
        elif stock_state == "zero":
            position_where.append(f"abs(balance) <= {_EPSILON}")

        for parent_level in ("category", "item_type", "vendor", "model"):
            value = path.get(parent_level, "")
            if value:
                position_where.append(
                    f"{_GROUP_EXPRESSIONS[parent_level]} = ? COLLATE NOCASE"
                )
                params.append(value)
        position_where_sql = (
            "WHERE " + " AND ".join(position_where) if position_where else ""
        )

        cte_sql = f"""WITH allocations AS (
            SELECT receipt_id, SUM(quantity) AS issued
            FROM stock_issue_allocations
            GROUP BY receipt_id
        ), lots AS (
            SELECT r.id, r.project, r.item_name, r.supplier, r.vendor, r.model,
                   r.serial_number, r.inventory_number, r.shelf, r.object_name,
                   r.equipment_type, r.component_type, r.cable_type, r.unit,
                   r.datacenter, r.quantity - COALESCE(a.issued, 0) AS balance
            FROM stock_receipts r
            LEFT JOIN allocations a ON a.receipt_id = r.id
            {receipt_where_sql}
        ), positions AS (
            SELECT project, item_name, supplier, vendor, model, serial_number,
                   inventory_number, SUM(balance) AS balance, unit,
                   GROUP_CONCAT(DISTINCT NULLIF(trim(shelf), '')) AS shelf,
                   object_name, equipment_type, component_type, cable_type,
                   datacenter, {_CATEGORY_SQL} AS category, {_TYPE_SQL} AS item_type
            FROM lots
            GROUP BY project, item_name, supplier, vendor, model, serial_number,
                     inventory_number, unit, object_name, equipment_type,
                     component_type, cable_type, datacenter
        ), filtered AS (
            SELECT * FROM positions {position_where_sql}
        )"""
        return cte_sql, params

    def _fetch_groups(
        self,
        level: str,
        cte_sql: str,
        params: list[Any],
        path: dict[str, str],
        filters: dict[str, str],
        limit: int,
        offset: int,
    ) -> dict[str, Any]:
        expression = _GROUP_EXPRESSIONS[level]
        sort_desc = filters.get("sort_dir", "asc").casefold() == "desc"
        if filters.get("sort_by") == "balance":
            order_sql = f"available {'DESC' if sort_desc else 'ASC'}, value COLLATE NOCASE"
        elif level == "category":
            order_sql = f"{_CATEGORY_ORDER} {'DESC' if sort_desc else 'ASC'}, value COLLATE NOCASE"
        else:
            order_sql = f"value COLLATE NOCASE {'DESC' if sort_desc else 'ASC'}"

        sql = f"""{cte_sql}
        SELECT {expression} AS value,
               COUNT(*) AS positions,
               COALESCE(SUM(balance), 0) AS available,
               COUNT(*) OVER () AS node_count,
               SUM(COUNT(*)) OVER () AS total_positions,
               COALESCE(SUM(SUM(balance)) OVER (), 0) AS total_available
        FROM filtered
        GROUP BY {expression}
        ORDER BY {order_sql}
        LIMIT ? OFFSET ?"""
        query_params = [*params, limit + 1, offset]
        with connect(self.db_path) as db:
            raw_rows = db.execute(sql, query_params).fetchall()

        has_more = len(raw_rows) > limit
        page_rows = raw_rows[:limit]
        total = self._total_from_rows(page_rows)
        nodes: list[dict[str, Any]] = []
        for row in page_rows:
            value = str(row["value"] or "Не указано")
            node_path = {**path, level: value}
            nodes.append({
                "id": _node_id(level, node_path),
                "kind": "group",
                "level": level,
                "label": value,
                "path": node_path,
                "next_level": _NEXT_LEVEL[level],
                "has_children": _NEXT_LEVEL[level] is not None,
                "positions": int(row["positions"] or 0),
                "available": float(row["available"] or 0),
            })
        node_count = int(page_rows[0]["node_count"] or 0) if page_rows else 0
        return self._response(
            level, nodes, total, node_count, limit, offset, has_more, filters
        )

    @staticmethod
    def _total_from_rows(rows: list[Any]) -> dict[str, Any]:
        if not rows:
            return {"positions": 0, "available": 0.0}
        first = rows[0]
        return {
            "positions": int(first["total_positions"] or 0),
            "available": float(first["total_available"] or 0),
        }

    @staticmethod
    def _response(
        level: str,
        nodes: list[dict[str, Any]],
        total: dict[str, Any],
        node_count: int,
        limit: int,
        offset: int,
        has_more: bool,
        filters: dict[str, str],
    ) -> dict[str, Any]:
        return {
            "level": level,
            "nodes": nodes,
            "total": total,
            "node_count": node_count,
            "limit": limit,
            "offset": offset,
            "has_more": has_more,
            "empty_reason": "filtered" if any(
                value for key, value in filters.items()
                if key not in {"sort_by", "sort_dir"}
            ) else "warehouse",
        }
