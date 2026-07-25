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


class WarehouseHistoryService(WarehouseComponent):
    def warehouse_history(self, limit: int = 300) -> list[dict[str, Any]]:
        """Человекочитаемая история склада без раскрытия внутренних имён таблиц."""
        labels = {
            "RECEIPT_CREATE": "Ручной приход", "RECEIPT_IMPORT": "Приход из файла",
            "ISSUE_CREATE": "Ручной расход", "ISSUE_IMPORT": "Расход из файла",
            "DELIVERY_UPLOAD": "Загружена поставка", "DELIVERY_ACCEPT": "Принято из поставки",
            "DELIVERY_LINE_UPDATE": "Изменены данные поставки", "DELIVERY_CLOSE": "Закрыта поставка",
        }
        rows: list[dict[str, Any]] = []
        with connect(self.db_path) as db:
            for row in db.execute("""SELECT id history_id,NULLIF(trim(receipt_date),'') event_date,responsible engineer,
                    CASE WHEN is_opening_balance=1 OR trim(COALESCE(responsible,''))='Историческая миграция'
                         THEN 'Начальный остаток' ELSE 'Приход' END action,
                    serial_number,inventory_number,item_name,quantity,'' comment,
                    CASE WHEN is_opening_balance=1 OR trim(COALESCE(responsible,''))='Историческая миграция' THEN 1 ELSE 0 END is_opening_balance
                    FROM stock_receipts
                    ORDER BY CASE WHEN is_opening_balance=1 OR trim(COALESCE(responsible,''))='Историческая миграция' THEN 1 ELSE 0 END ASC,
                             NULLIF(trim(receipt_date),'') DESC,id DESC LIMIT ?""", (limit,)):
                item = dict(row)
                item["_history_source"] = "receipt"
                rows.append(item)
            for row in db.execute("SELECT id history_id,NULLIF(trim(issue_date),'') event_date,responsible engineer,'Расход' action,source_serial_number serial_number,'' inventory_number,source_item_name item_name,quantity,comment,0 is_opening_balance FROM stock_issues ORDER BY NULLIF(trim(issue_date),'') DESC,id DESC LIMIT ?", (limit,)):
                item = dict(row)
                item["_history_source"] = "issue"
                rows.append(item)
            for row in db.execute("""SELECT o.id history_id,o.operation_date event_date,
                    o.responsible engineer,'Перемещение' action,
                    e.serial_number,e.inventory_number,e.model item_name,o.quantity,
                    trim(o.basis || CASE WHEN src.code IS NOT NULL OR dst.code IS NOT NULL
                        THEN '; ' || COALESCE(src.code,'') || ' -> ' || COALESCE(dst.code,'')
                        ELSE '' END) comment,0 is_opening_balance
                    FROM operations o JOIN equipment e ON e.id=o.equipment_id
                    LEFT JOIN locations src ON src.id=o.from_location_id
                    LEFT JOIN locations dst ON dst.id=o.to_location_id
                    WHERE o.operation_type='MOVE'
                    ORDER BY o.operation_date DESC,o.id DESC LIMIT ?""", (limit,)):
                item = dict(row)
                item["_history_source"] = "movement"
                rows.append(item)
            for row in db.execute("SELECT id history_id,event_date,author engineer,action,details,entity_id FROM audit_log WHERE action LIKE 'DELIVERY_%' OR action IN ('RECEIPT_IMPORT','ISSUE_IMPORT') ORDER BY event_date DESC,id DESC LIMIT ?", (limit,)):
                details = json.loads(row["details"] or "{}") if str(row["details"] or "").startswith("{") else {}
                rows.append({"event_date": row["event_date"], "engineer": row["engineer"],
                    "action": labels.get(row["action"], "Изменение склада"),
                    "serial_number": details.get("serial_number", ""),
                    "inventory_number": details.get("inventory_number", ""),
                    "entity_id": row["entity_id"],
                    "item_name": details.get("item_name", ""), "quantity": details.get("quantity", ""),
                    "comment": details.get("filename", "") or details.get("reason", ""),
                    "is_opening_balance": 0, "history_id": row["history_id"],
                    "_history_source": "audit"})

        def sort_key(item: dict[str, Any]) -> tuple[datetime, int, str]:
            raw_date = str(item.get("event_date") or "").strip()
            try:
                event_time = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
                if event_time.tzinfo is not None:
                    event_time = event_time.replace(tzinfo=None)
            except ValueError:
                event_time = datetime.min
            return (
                event_time,
                int(item.get("history_id") or 0),
                str(item.get("_history_source") or ""),
            )

        rows.sort(key=sort_key, reverse=True)
        result = rows[:limit]
        for item in result:
            item.pop("history_id", None)
            item.pop("_history_source", None)
        return result

    def operation_log(self, operation_type: str = "", limit: int | None = 100) -> list[dict[str, Any]]:
        sql = """SELECT o.id, o.operation_date, o.operation_type, o.equipment_id,
                        e.inventory_number, e.model, o.quantity, o.basis, o.responsible,
                        src.code AS from_location, dst.code AS to_location
                 FROM operations o
                 JOIN equipment e ON e.id = o.equipment_id
                 LEFT JOIN locations src ON src.id = o.from_location_id
                 LEFT JOIN locations dst ON dst.id = o.to_location_id"""
        params: list[Any] = []
        if operation_type:
            sql += " WHERE o.operation_type = ? COLLATE NOCASE"
            params.append(operation_type)
        sql += " ORDER BY o.operation_date DESC, o.id DESC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        with connect(self.db_path) as db:
            return [dict(row) for row in db.execute(sql, params).fetchall()]
