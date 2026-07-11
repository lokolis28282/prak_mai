"""Cable warehouse persistence."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Iterable

from inventory.shared.audit import write_audit_entry
from inventory.shared.db import connect
from inventory.shared.validators import WarehouseError

from .cable_validators import CABLE_ISSUE_REFERENCE_FIELDS, CABLE_REFERENCE_FIELDS
from .receipt_repository import RECEIPT_FIELDS


class CableRepository:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)

    def reference_sets(self, db: sqlite3.Connection) -> dict[str, set[str]]:
        result: dict[str, set[str]] = {}
        for row in db.execute("SELECT kind, name FROM reference_values WHERE is_active = 1"):
            result.setdefault(str(row["kind"]), set()).add(str(row["name"]).casefold())
        return result

    def collect_references(
        self,
        db: sqlite3.Connection,
        rows: Iterable[dict[str, Any]],
        fields: dict[str, str],
        *,
        enabled: bool,
        author: str,
    ) -> None:
        if not enabled:
            return
        for field, kind in fields.items():
            for value in {str(row.get(field, "")).strip() for row in rows if str(row.get(field, "")).strip()}:
                cursor = db.execute(
                    "INSERT OR IGNORE INTO reference_values(kind, name) VALUES (?, ?)",
                    (kind, value),
                )
                if cursor.rowcount:
                    write_audit_entry(
                        db,
                        action="REFERENCE_AUTO_CREATE",
                        entity_type="reference_value",
                        entity_id=cursor.lastrowid,
                        author=author,
                        details={"kind": kind, "name": value},
                    )

    def insert_receipt(self, row: dict[str, Any], *, author: str, collect_refs: bool) -> int:
        with connect(self.db_path) as db:
            self.collect_references(db, [row], CABLE_REFERENCE_FIELDS, enabled=collect_refs, author=author)
            cursor = db.execute(
                """INSERT INTO stock_receipts(
                       receipt_date, responsible, order_date, request_number, order_number,
                       plu, item_name, project, serial_number, inventory_number, supplier,
                       vendor, model, shelf, object_name, datacenter, equipment_type,
                       component_type, cable_type, unit, quantity
                   ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                tuple(row[field] for field in RECEIPT_FIELDS),
            )
            receipt_id = int(cursor.lastrowid)
            write_audit_entry(
                db,
                action="CABLE_RECEIPT_CREATE",
                entity_type="stock_receipt",
                entity_id=receipt_id,
                author=author,
                details={
                    "cable_type": row["cable_type"],
                    "item_name": row["item_name"],
                    "quantity": row["quantity"],
                    "project": row["project"],
                    "shelf": row["shelf"],
                    "comment": row.get("comment", ""),
                },
            )
            return receipt_id

    def insert_receipts(self, rows: list[dict[str, Any]], *, author: str, collect_refs: bool) -> list[int]:
        with connect(self.db_path) as db:
            self.collect_references(db, rows, CABLE_REFERENCE_FIELDS, enabled=collect_refs, author=author)
            ids: list[int] = []
            for row in rows:
                cursor = db.execute(
                    """INSERT INTO stock_receipts(
                           receipt_date, responsible, order_date, request_number, order_number,
                           plu, item_name, project, serial_number, inventory_number, supplier,
                           vendor, model, shelf, object_name, datacenter, equipment_type,
                           component_type, cable_type, unit, quantity
                       ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    tuple(row[field] for field in RECEIPT_FIELDS),
                )
                ids.append(int(cursor.lastrowid))
            write_audit_entry(
                db,
                action="CABLE_RECEIPT_BATCH",
                entity_type="stock_receipt",
                author=author,
                details={"count": len(rows), "receipt_ids": ids[:100]},
            )
            return ids

    def available_cable_lots(self, db: sqlite3.Connection, row: dict[str, Any]) -> list[sqlite3.Row]:
        where = [
            "r.item_name = ? COLLATE NOCASE",
            "r.cable_type = ? COLLATE NOCASE",
        ]
        params: list[Any] = [row["source_item_name"], row["source_cable_type"]]
        for field in ("project", "datacenter", "shelf"):
            if row.get(field):
                where.append(f"r.{field} = ? COLLATE NOCASE")
                params.append(row[field])
        return db.execute(
            f"""SELECT r.*, r.quantity - COALESCE(SUM(a.quantity), 0) AS available
                FROM stock_receipts r
                LEFT JOIN stock_issue_allocations a ON a.receipt_id = r.id
                WHERE {' AND '.join(where)}
                GROUP BY r.id HAVING available > 0.0000001
                ORDER BY r.receipt_date, r.id""",
            params,
        ).fetchall()

    def insert_issue(self, row: dict[str, Any], *, author: str, collect_refs: bool) -> int:
        with connect(self.db_path) as db:
            self.collect_references(
                db, [row], CABLE_ISSUE_REFERENCE_FIELDS, enabled=collect_refs, author=author
            )
            candidates = self.available_cable_lots(db, row)
            available = sum(float(candidate["available"]) for candidate in candidates)
            if available + 1e-9 < float(row["quantity"]):
                label = f"{row['source_item_name']} / {row['source_cable_type']}"
                raise WarehouseError(f"недостаточный остаток для «{label}»: доступно {available:g}")
            cursor = db.execute(
                """INSERT INTO stock_issues(
                       issue_date, responsible, task_type, task_number, target_serial_number,
                       target_hostname, source_serial_number, source_item_name,
                       source_cable_type, quantity, comment
                   ) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                tuple(row[key] for key in (
                    "issue_date", "responsible", "task_type", "task_number",
                    "target_serial_number", "target_hostname", "source_serial_number",
                    "source_item_name", "source_cable_type", "quantity", "comment",
                )),
            )
            issue_id = int(cursor.lastrowid)
            remaining = float(row["quantity"])
            for candidate in candidates:
                allocated = min(remaining, float(candidate["available"]))
                if allocated > 1e-9:
                    db.execute(
                        "INSERT INTO stock_issue_allocations(issue_id, receipt_id, quantity) VALUES (?, ?, ?)",
                        (issue_id, candidate["id"], allocated),
                    )
                    remaining -= allocated
                if remaining <= 1e-9:
                    break
            write_audit_entry(
                db,
                action="CABLE_ISSUE_CREATE",
                entity_type="stock_issue",
                entity_id=issue_id,
                author=author,
                details={
                    "cable_type": row["source_cable_type"],
                    "item_name": row["source_item_name"],
                    "quantity": row["quantity"],
                    "project": row.get("project", ""),
                    "shelf": row.get("shelf", ""),
                    "task_number": row.get("task_number", ""),
                    "comment": row.get("comment", ""),
                },
            )
            return issue_id

    def cable_balance(self, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        filters = filters or {}
        where = ["cable_type <> ''"]
        params: list[Any] = []
        for field in ("project", "object_name", "cable_type", "unit", "datacenter"):
            value = str(filters.get(field, "") or "").strip()
            if value:
                where.append(f"{field} = ? COLLATE NOCASE")
                params.append(value)
        query = str(filters.get("query", "") or "").strip()
        if query:
            term = f"%{query}%"
            where.append(
                "(item_name LIKE ? OR supplier LIKE ? OR project LIKE ? OR object_name LIKE ? OR shelf LIKE ?)"
            )
            params.extend([term] * 5)
        with connect(self.db_path) as db:
            rows = db.execute(
                f"""WITH lots AS (
                       SELECT r.id, r.project, r.item_name, r.supplier, r.vendor, r.model,
                              r.shelf, r.object_name, r.cable_type, r.unit, r.datacenter,
                              r.quantity - COALESCE(SUM(a.quantity), 0) AS balance
                       FROM stock_receipts r
                       LEFT JOIN stock_issue_allocations a ON a.receipt_id = r.id
                       GROUP BY r.id
                   )
                   SELECT GROUP_CONCAT(id) AS receipt_ids,
                          project, item_name, supplier, vendor, model, SUM(balance) AS balance,
                          unit, GROUP_CONCAT(DISTINCT NULLIF(shelf, '')) AS shelf,
                          object_name, '' AS equipment_type, '' AS component_type,
                          cable_type, datacenter
                     FROM lots
                    WHERE {' AND '.join(where)}
                    GROUP BY project, item_name, supplier, vendor, model, unit,
                             object_name, cable_type, datacenter
                    ORDER BY item_name COLLATE NOCASE""",
                params,
            ).fetchall()
        result = [dict(row) for row in rows]
        for row in result:
            row["category"] = "Кабели"
            row["item_type"] = row["cable_type"]
            row["serial_number"] = ""
            row["inventory_number"] = ""
            row["position_key"] = "cable:" + "|".join(str(row.get(key) or "") for key in (
                "item_name", "cable_type", "project", "datacenter"
            ))
        return result

    def cable_types(self) -> list[str]:
        with connect(self.db_path) as db:
            return [str(row[0]) for row in db.execute(
                """SELECT DISTINCT cable_type FROM stock_receipts
                   WHERE cable_type <> '' ORDER BY cable_type COLLATE NOCASE"""
            )]

    def cable_items(self, cable_type: str = "") -> list[dict[str, Any]]:
        filters = {"cable_type": cable_type} if cable_type else {}
        return [
            row for row in self.cable_balance(filters)
            if float(row.get("balance") or 0) > 1e-9
        ]
