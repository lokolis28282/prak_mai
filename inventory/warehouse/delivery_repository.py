"""SQL repository for Warehouse-owned delivery import."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Iterable

from inventory.db import connect


def _chunks(values: list[str], size: int = 500) -> Iterable[list[str]]:
    for index in range(0, len(values), size):
        yield values[index:index + size]


class DeliveryRepository:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)

    def existing_stock_serials(self, serials: Iterable[str]) -> dict[str, dict[str, Any]]:
        keys = sorted({serial.casefold(): serial for serial in serials if serial}.values())
        result: dict[str, dict[str, Any]] = {}
        with connect(self.db_path) as db:
            for chunk in _chunks(keys):
                placeholders = ",".join("?" for _ in chunk)
                rows = db.execute(
                    f"""SELECT id, serial_number, item_name, inventory_number, vendor, model,
                               project, datacenter, shelf
                          FROM stock_receipts
                         WHERE trim(serial_number) <> ''
                           AND serial_number COLLATE NOCASE IN ({placeholders})""",
                    chunk,
                ).fetchall()
                for row in rows:
                    result[str(row["serial_number"]).casefold()] = dict(row)
        return result

    def existing_delivery_serials(self, serials: Iterable[str]) -> dict[str, list[dict[str, Any]]]:
        keys = sorted({serial.casefold(): serial for serial in serials if serial}.values())
        result: dict[str, list[dict[str, Any]]] = {}
        with connect(self.db_path) as db:
            for chunk in _chunks(keys):
                placeholders = ",".join("?" for _ in chunk)
                rows = db.execute(
                    f"""SELECT l.id, l.delivery_id, l.serial_number, l.state, l.receipt_id,
                               d.delivery_number, d.status
                          FROM delivery_lines l
                          JOIN deliveries d ON d.id = l.delivery_id
                         WHERE trim(l.serial_number) <> ''
                           AND l.serial_number COLLATE NOCASE IN ({placeholders})""",
                    chunk,
                ).fetchall()
                for row in rows:
                    result.setdefault(str(row["serial_number"]).casefold(), []).append(dict(row))
        return result

    def list_deliveries(self, query: str = "", limit: int | None = None) -> list[dict[str, Any]]:
        term = f"%{query.strip()}%"
        sql = """SELECT d.*, COUNT(l.id) AS total,
                        SUM(CASE WHEN l.state='Принято' THEN 1 ELSE 0 END) AS accepted,
                        SUM(CASE WHEN l.state IN ('Ошибка','Дубль в файле','Уже на складе') THEN 1 ELSE 0 END) AS problems
                   FROM deliveries d LEFT JOIN delivery_lines l ON l.delivery_id=d.id
                  WHERE ?='' OR d.delivery_number LIKE ? OR d.supplier LIKE ? OR d.source_filename LIKE ?
                     OR EXISTS(SELECT 1 FROM delivery_lines s WHERE s.delivery_id=d.id AND
                        (s.serial_number LIKE ? OR s.order_number LIKE ? OR s.request_number LIKE ?))
                  GROUP BY d.id ORDER BY d.uploaded_at DESC,d.id DESC"""
        params: list[Any] = [query.strip(), term, term, term, term, term, term]
        if limit is not None:
            sql += " LIMIT ?"
            params.append(max(1, min(int(limit), 5_000)))
        with connect(self.db_path) as db:
            rows = db.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def get_delivery(self, delivery_id: int) -> dict[str, Any] | None:
        with connect(self.db_path) as db:
            row = db.execute("SELECT * FROM deliveries WHERE id=?", (delivery_id,)).fetchone()
            return dict(row) if row else None

    def get_delivery_lines(self, delivery_id: int, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        filters = filters or {}
        query = str(filters.get("query") or "").strip()
        state = str(filters.get("state") or "").strip()
        sql = "SELECT * FROM delivery_lines WHERE delivery_id=?"
        params: list[Any] = [delivery_id]
        if query:
            sql += " AND (serial_number LIKE ? OR order_number LIKE ? OR request_number LIKE ? OR item_name LIKE ?)"
            term = f"%{query}%"
            params.extend([term, term, term, term])
        if state:
            sql += " AND state=?"
            params.append(state)
        sql += " ORDER BY row_number,id"
        limit = filters.get("limit")
        offset = filters.get("offset", 0)
        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            params.extend((
                max(1, min(int(limit), 5_000)),
                max(0, int(offset)),
            ))
        with connect(self.db_path) as db:
            return [dict(row) for row in db.execute(sql, params).fetchall()]

    def delivery_line_summary(self, delivery_id: int) -> dict[str, int]:
        with connect(self.db_path) as db:
            row = db.execute(
                """SELECT COUNT(*) total,
                          SUM(CASE WHEN state='Принято' THEN 1 ELSE 0 END) accepted,
                          SUM(CASE WHEN state='Уже на складе' THEN 1 ELSE 0 END) existing,
                          SUM(CASE WHEN state IN ('Ошибка','Дубль в файле') THEN 1 ELSE 0 END) errors,
                          SUM(CASE WHEN state='Ожидается' THEN 1 ELSE 0 END) waiting
                   FROM delivery_lines WHERE delivery_id=?""",
                (delivery_id,),
            ).fetchone()
        return {key: int(row[key] or 0) for key in (
            "total", "accepted", "existing", "errors", "waiting"
        )}

    def get_delivery_in_db(self, db: sqlite3.Connection, delivery_id: int) -> dict[str, Any] | None:
        row = db.execute("SELECT * FROM deliveries WHERE id=?", (delivery_id,)).fetchone()
        return dict(row) if row else None

    def get_line_by_serial_in_db(
        self,
        db: sqlite3.Connection,
        delivery_id: int,
        serial_number: str,
    ) -> dict[str, Any] | None:
        row = db.execute(
            """SELECT * FROM delivery_lines
               WHERE delivery_id=? AND serial_number=? COLLATE NOCASE
               ORDER BY id LIMIT 1""",
            (delivery_id, serial_number),
        ).fetchone()
        return dict(row) if row else None

    def get_line_by_id_in_db(
        self,
        db: sqlite3.Connection,
        delivery_id: int,
        line_id: int,
    ) -> dict[str, Any] | None:
        row = db.execute(
            "SELECT * FROM delivery_lines WHERE delivery_id=? AND id=?",
            (delivery_id, line_id),
        ).fetchone()
        return dict(row) if row else None

    def existing_stock_by_serial_in_db(
        self,
        db: sqlite3.Connection,
        serial_number: str,
    ) -> dict[str, Any] | None:
        row = db.execute(
            "SELECT * FROM stock_receipts WHERE trim(serial_number) <> '' AND trim(serial_number)=trim(?) COLLATE NOCASE",
            (serial_number,),
        ).fetchone()
        return dict(row) if row else None

    def insert_unplanned_line_in_db(
        self,
        db: sqlite3.Connection,
        delivery_id: int,
        serial_number: str,
        values: dict[str, Any],
        actor: str,
    ) -> int:
        row_number = int(db.execute(
            "SELECT COALESCE(MAX(row_number),0)+1 FROM delivery_lines WHERE delivery_id=?",
            (delivery_id,),
        ).fetchone()[0])
        cursor = db.execute(
            """INSERT INTO delivery_lines(
                   delivery_id,row_number,serial_number,delivery_number,supplier,
                   request_number,order_number,plu,quantity,asset_number,item_name,
                   model,vendor,project,datacenter,shelf,object_name,equipment_type,
                   component_type,cable_type,unit,state,is_unplanned,updated_by
               ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                delivery_id, row_number, serial_number,
                values.get("delivery_number", ""), values.get("supplier", ""),
                values.get("request_number", ""), values.get("order_number", ""),
                values.get("plu", ""), float(values.get("quantity") or 1),
                values.get("inventory_number") or values.get("asset_number", ""),
                values.get("item_name", ""), values.get("model", ""),
                values.get("vendor", ""), values.get("project", ""),
                values.get("datacenter", ""), values.get("shelf", ""),
                values.get("object_name", ""), values.get("equipment_type", ""),
                values.get("component_type", ""), values.get("cable_type", ""),
                values.get("unit", "шт"), "Ожидается", 1, actor,
            ),
        )
        return int(cursor.lastrowid)

    def link_line_in_db(
        self,
        db: sqlite3.Connection,
        line_id: int,
        receipt_id: int,
        actor: str,
        *,
        state: str = "Принято",
        error_text: str = "",
    ) -> None:
        db.execute(
            """UPDATE delivery_lines
                  SET state=?, receipt_id=?, error_text=?, updated_by=?,
                      updated_at=datetime('now','localtime')
                WHERE id=?""",
            (state, receipt_id, error_text, actor, line_id),
        )

    def update_line_metadata_in_db(
        self,
        db: sqlite3.Connection,
        delivery_id: int,
        line_id: int,
        values: dict[str, Any],
        actor: str,
        *,
        only_empty: bool = False,
        allowed_fields: set[str],
    ) -> bool:
        row = self.get_line_by_id_in_db(db, delivery_id, line_id)
        if row is None or row["state"] == "Принято" or row.get("receipt_id"):
            return False
        updates: dict[str, Any] = {}
        for field, value in values.items():
            if field not in allowed_fields:
                continue
            if only_empty and str(row.get(field) or "").strip():
                continue
            updates[field] = value
        if not updates:
            return False
        assignments = ", ".join(f"{field}=?" for field in updates)
        db.execute(
            f"""UPDATE delivery_lines
                   SET {assignments}, updated_by=?, updated_at=datetime('now','localtime')
                 WHERE id=?""",
            (*updates.values(), actor, line_id),
        )
        return True

    def refresh_status_in_db(self, db: sqlite3.Connection, delivery_id: int) -> str:
        current = db.execute("SELECT status FROM deliveries WHERE id=?", (delivery_id,)).fetchone()
        if current is None:
            raise WarehouseError("Поставка не найдена")
        if current["status"] == "Закрыта":
            return "Закрыта"
        counts = db.execute(
            """SELECT
                   SUM(CASE WHEN state='Ожидается' THEN 1 ELSE 0 END) AS waiting,
                   SUM(CASE WHEN state='Принято' OR (state='Уже на складе' AND receipt_id IS NOT NULL) THEN 1 ELSE 0 END) AS processed
                 FROM delivery_lines WHERE delivery_id=?""",
            (delivery_id,),
        ).fetchone()
        waiting = int(counts["waiting"] or 0)
        processed = int(counts["processed"] or 0)
        status = "Ожидается"
        if processed and waiting:
            status = "Частично принята"
        elif processed and not waiting:
            status = "Принята"
        db.execute("UPDATE deliveries SET status=? WHERE id=?", (status, delivery_id))
        return status

    def create_delivery_document(
        self,
        *,
        filename: str,
        delivery_number: str,
        supplier: str,
        uploaded_by: str,
        rows: list[dict[str, Any]],
        audit_details: dict[str, Any],
        audit_callback: Any,
    ) -> int:
        with connect(self.db_path) as db:
            cursor = db.execute(
                "INSERT INTO deliveries(source_filename, delivery_number, supplier, uploaded_by, status) VALUES (?,?,?,?,?)",
                (filename, delivery_number, supplier, uploaded_by, "Ожидается"),
            )
            delivery_id = int(cursor.lastrowid)
            for number, row in enumerate(rows, start=1):
                self._insert_line(db, delivery_id, number, row, uploaded_by)
            audit_callback(db, "DELIVERY_UPLOAD", "delivery", delivery_id, audit_details)
            return delivery_id

    def _insert_line(
        self,
        db: sqlite3.Connection,
        delivery_id: int,
        number: int,
        row: dict[str, Any],
        actor: str,
    ) -> None:
        quantity = float(row.get("quantity") or 1)
        item_type = str(row.get("item_type") or row.get("equipment_type") or row.get("equipment_unit") or "")
        values = (
            delivery_id, number, row.get("receipt_statement", ""), row.get("delivery_date") or row.get("order_date", ""),
            row.get("request_number", ""), row.get("order_number", ""), row.get("serial_number", ""),
            row.get("delivery_number", ""), row.get("supplier", ""), row.get("planned_date", ""),
            row.get("request_position", ""), row.get("order_position", ""), row.get("contract_number", ""),
            row.get("plu", ""), row.get("accounting_object", ""), quantity, row.get("inventory_number", ""),
            row.get("equipment_unit") or item_type, row.get("item_name") or item_type, row.get("model", ""),
            row.get("vendor", ""), row.get("project", ""), row.get("datacenter") or "Ixcellerate",
            row.get("shelf", ""), row.get("object_name", ""), row.get("equipment_type") or item_type,
            row.get("component_type", ""), row.get("cable_type", ""), row.get("unit") or "шт",
            row.get("state", "Ожидается"), row.get("error_text", ""), actor,
        )
        db.execute(
            """INSERT INTO delivery_lines(delivery_id,row_number,receipt_statement,order_date,
               request_number,order_number,serial_number,delivery_number,supplier,planned_date,
               request_position,order_position,contract_number,plu,accounting_object,quantity,
               asset_number,equipment_unit,item_name,model,vendor,project,datacenter,shelf,
               object_name,equipment_type,component_type,cable_type,unit,state,error_text,updated_by)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            values,
        )
