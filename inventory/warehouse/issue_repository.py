"""Serialized equipment/component issue persistence."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Iterable

from inventory.shared.audit import write_audit_entry
from inventory.shared.db import connect
from inventory.shared.validators import WarehouseError

from .issue_validators import ISSUE_REFERENCE_FIELDS


ISSUE_FIELDS = (
    "issue_date", "responsible", "task_type", "task_number", "target_serial_number",
    "target_hostname", "source_serial_number", "source_item_name",
    "source_cable_type", "quantity", "comment",
)


class IssueRepository:
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
        row: dict[str, Any],
        *,
        enabled: bool,
        author: str,
    ) -> None:
        if not enabled:
            return
        for field, kind in ISSUE_REFERENCE_FIELDS.items():
            value = str(row.get(field, "")).strip()
            if not value:
                continue
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

    def available_by_serial(self, db: sqlite3.Connection, serial: str) -> list[sqlite3.Row]:
        return db.execute(
            """SELECT r.*, r.quantity - COALESCE(SUM(a.quantity), 0) AS available
                 FROM stock_receipts r
                 LEFT JOIN stock_issue_allocations a ON a.receipt_id = r.id
                WHERE trim(r.serial_number) <> '' AND trim(r.serial_number) = trim(?) COLLATE NOCASE
                GROUP BY r.id HAVING available > 0.0000001
                ORDER BY r.receipt_date, r.id""",
            (serial,),
        ).fetchall()

    def serial_exists(self, db: sqlite3.Connection, serial: str) -> bool:
        return db.execute(
            "SELECT 1 FROM stock_receipts WHERE trim(serial_number) <> '' AND trim(serial_number) = trim(?) COLLATE NOCASE",
            (serial,),
        ).fetchone() is not None

    def list_rows(self, limit: int | None = None) -> list[dict[str, Any]]:
        """Return one operator-facing row per issue operation.

        Allocations remain the source of receipt attributes and matched
        quantity, but must not multiply one issue into several export/history
        rows when a cable write-off spans multiple FIFO lots.  LEFT JOIN keeps
        unmatched problem issues visible in the complete history as well.
        """
        sql = """WITH allocation_summary AS (
                     SELECT a.issue_id,
                            SUM(a.quantity) AS matched_quantity,
                            MIN(r.item_name) AS item_name,
                            MIN(r.model) AS component_model,
                            MIN(r.serial_number) AS serial_number,
                            MIN(r.inventory_number) AS inventory_number,
                            GROUP_CONCAT(DISTINCT NULLIF(trim(r.shelf), '')) AS shelf,
                            MIN(r.object_name) AS object_name,
                            MIN(r.equipment_type) AS equipment_type,
                            MIN(r.component_type) AS component_type,
                            MIN(r.cable_type) AS cable_type,
                            MIN(r.project) AS project,
                            MIN(r.unit) AS unit
                       FROM stock_issue_allocations a
                       JOIN stock_receipts r ON r.id = a.receipt_id
                      GROUP BY a.issue_id
                 )
                 SELECT i.id, i.issue_date, i.responsible, i.task_type,
                        i.task_number AS task_id,
                        CASE WHEN trim(i.task_type) <> ''
                             THEN i.task_type || '-' || i.task_number
                             ELSE i.task_number END AS task_number,
                        i.target_serial_number, i.target_hostname,
                        COALESCE(target.item_name, '') AS target_item_name,
                        COALESCE(target.model, '') AS target_model,
                        COALESCE(target.inventory_number, '') AS target_inventory_number,
                        COALESCE(target.equipment_type, '') AS target_equipment_type,
                        COALESCE(NULLIF(i.source_item_name, ''), allocations.item_name, '')
                            AS item_name,
                        COALESCE(allocations.component_model, '') AS component_model,
                        i.quantity,
                        COALESCE(NULLIF(i.source_serial_number, ''), allocations.serial_number, '')
                            AS serial_number,
                        COALESCE(allocations.inventory_number, '') AS inventory_number,
                        COALESCE(allocations.shelf, '') AS shelf,
                        COALESCE(allocations.object_name, '') AS object_name,
                        COALESCE(allocations.equipment_type, '') AS equipment_type,
                        COALESCE(allocations.component_type, '') AS component_type,
                        COALESCE(NULLIF(i.source_cable_type, ''), allocations.cable_type, '')
                            AS cable_type,
                        COALESCE(allocations.project, '') AS project,
                        COALESCE(allocations.unit, '') AS unit,
                        COALESCE(allocations.matched_quantity, 0) AS matched_quantity,
                        CASE
                            WHEN i.quantity > COALESCE(allocations.matched_quantity, 0)
                            THEN i.quantity - COALESCE(allocations.matched_quantity, 0)
                            ELSE 0
                        END AS unmatched_quantity,
                        CASE
                            WHEN i.quantity > COALESCE(allocations.matched_quantity, 0) + 0.0000001
                            THEN 'Не сопоставлено'
                            ELSE 'Проведено'
                        END AS status,
                        i.comment
                   FROM stock_issues i
                   LEFT JOIN allocation_summary allocations ON allocations.issue_id = i.id
                   LEFT JOIN stock_receipts target
                     ON target.id = (
                         SELECT MIN(candidate.id)
                           FROM stock_receipts candidate
                          WHERE trim(candidate.serial_number) <> ''
                            AND candidate.serial_number = i.target_serial_number COLLATE NOCASE
                     )
                  ORDER BY NULLIF(trim(i.issue_date), '') DESC, i.id DESC"""
        params: tuple[int, ...] = ()
        if limit is not None:
            sql += " LIMIT ?"
            params = (max(1, min(int(limit), 10_000)),)
        with connect(self.db_path) as db:
            return [dict(row) for row in db.execute(sql, params)]

    def create_issue(
        self,
        db: sqlite3.Connection,
        row: dict[str, Any],
        *,
        author: str,
        line_number: int | None = None,
        collect_refs: bool = False,
    ) -> int:
        prefix = f"Строка {line_number}: " if line_number is not None else ""
        serial = row["source_serial_number"]
        if not serial:
            raise WarehouseError(prefix + "S/N списываемой позиции не может быть пустым")
        if row["source_item_name"] or row["source_cable_type"]:
            raise WarehouseError(prefix + "кабель списывается через отдельный кабельный сценарий")
        if not self.serial_exists(db, serial):
            raise WarehouseError(prefix + f"позиция с S/N «{serial}» не найдена")
        candidates = self.available_by_serial(db, serial)
        if not candidates:
            raise WarehouseError(prefix + f"недостаточный остаток для S/N «{serial}»: доступно 0")
        source = candidates[0]
        if source["cable_type"]:
            raise WarehouseError(prefix + "кабель списывается по наименованию и типу кабеля")
        if not row["task_type"] or not row["task_number"]:
            raise WarehouseError(prefix + "для оборудования и компонентов обязательна задача")
        if row["target_serial_number"] == serial:
            raise WarehouseError(prefix + "оборудование нельзя списать само на себя")
        if source["component_type"] and not row["target_serial_number"]:
            raise WarehouseError(prefix + "компонент должен списываться на целевое оборудование")
        if source["component_type"]:
            target = db.execute(
                """SELECT id FROM stock_receipts
                   WHERE trim(serial_number) <> '' AND trim(serial_number) = trim(?) COLLATE NOCASE AND equipment_type <> ''""",
                (row["target_serial_number"],),
            ).fetchone()
            if target is None:
                raise WarehouseError(prefix + "целевое оборудование с указанным S/N не найдено")
        if not float(row["quantity"]).is_integer():
            raise WarehouseError(prefix + "оборудование и компоненты списываются целыми штуками")
        available = sum(float(candidate["available"]) for candidate in candidates)
        if available + 1e-9 < float(row["quantity"]):
            raise WarehouseError(prefix + f"недостаточный остаток для «{serial}»: доступно {available:g}")
        self.collect_references(db, row, enabled=collect_refs, author=author)
        cursor = db.execute(
            """INSERT INTO stock_issues(
                   issue_date, responsible, task_type, task_number, target_serial_number,
                   target_hostname, source_serial_number, source_item_name,
                   source_cable_type, quantity, comment
               ) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            tuple(row[key] for key in ISSUE_FIELDS),
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
            action="ISSUE_CREATE",
            entity_type="stock_issue",
            entity_id=issue_id,
            author=author,
            details={
                "quantity": row["quantity"],
                "source_serial_number": row["source_serial_number"],
                "task_number": row["task_number"],
                "target_serial_number": row["target_serial_number"],
            },
        )
        return issue_id

    def create_unmatched_issue(
        self,
        db: sqlite3.Connection,
        row: dict[str, Any],
        reason: str,
        *,
        author: str,
    ) -> int:
        comment = row["comment"]
        marker = f"Не сопоставлено: {reason}"
        row = {**row, "comment": f"{comment}; {marker}".strip("; ")}
        cursor = db.execute(
            """INSERT INTO stock_issues(
                   issue_date, responsible, task_type, task_number, target_serial_number,
                   target_hostname, source_serial_number, source_item_name,
                   source_cable_type, quantity, comment
               ) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            tuple(row[key] for key in ISSUE_FIELDS),
        )
        issue_id = int(cursor.lastrowid)
        write_audit_entry(
            db,
            action="ISSUE_UNMATCHED",
            entity_type="stock_issue",
            entity_id=issue_id,
            author=author,
            details={"reason": reason},
        )
        return issue_id

    def is_unmatched_issue(self, db: sqlite3.Connection, row: dict[str, Any], reason: str) -> bool:
        if "не найдена" in reason:
            return True
        if "для кабеля укажите наименование и тип кабеля" in reason:
            return True
        if not row["source_serial_number"] and row["source_item_name"] and row["source_cable_type"]:
            exists = db.execute(
                """SELECT 1 FROM stock_receipts
                   WHERE item_name = ? COLLATE NOCASE AND cable_type = ? COLLATE NOCASE""",
                (row["source_item_name"], row["source_cable_type"]),
            ).fetchone()
            return exists is None
        return False

    def insert_one(self, row: dict[str, Any], *, author: str, collect_refs: bool = False) -> int:
        with connect(self.db_path) as db:
            return self.create_issue(db, row, author=author, collect_refs=collect_refs)

    def insert_many(
        self,
        rows: list[dict[str, Any]],
        *,
        author: str,
        collect_refs: bool = False,
        soft: bool = False,
        audit_action: str = "ISSUE_IMPORT",
    ) -> int:
        with connect(self.db_path) as db:
            count = 0
            unmatched_count = 0
            for row in rows:
                line = row.get("_line")
                self.collect_references(db, row, enabled=collect_refs, author=author)
                try:
                    self.create_issue(db, row, author=author, line_number=line)
                except WarehouseError as error:
                    reason = str(error)
                    unmatched = self.is_unmatched_issue(db, row, reason)
                    if not soft or not unmatched:
                        raise
                    self.create_unmatched_issue(db, row, reason, author=author)
                    unmatched_count += 1
                count += 1
            write_audit_entry(
                db,
                action=audit_action,
                entity_type="stock_issue",
                author=author,
                details={"count": count, "unmatched": unmatched_count},
            )
            return count

    def available_position(self, serial_number: str) -> dict[str, Any] | None:
        serial = serial_number.strip().upper()
        with connect(self.db_path) as db:
            row = db.execute(
                """SELECT r.*,
                          r.quantity - COALESCE(SUM(a.quantity), 0) AS available
                   FROM stock_receipts r
                   LEFT JOIN stock_issue_allocations a ON a.receipt_id = r.id
                   WHERE trim(r.serial_number) <> '' AND trim(r.serial_number) = trim(?) COLLATE NOCASE
                   GROUP BY r.id""",
                (serial,),
            ).fetchone()
        return dict(row) if row is not None else None
