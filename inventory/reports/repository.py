"""Reports-owned persistence."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Iterable

from inventory.shared.audit import write_audit_entry
from inventory.shared.db import connect


WORK_LOG_FIELDS = (
    "work_date", "task_source", "task_type", "task_number",
    "description", "status", "section", "needs_review", "comment",
)

WORK_LOG_INSERT_COLUMNS = ", ".join(WORK_LOG_FIELDS)
WORK_LOG_INSERT_PLACEHOLDERS = ", ".join("?" for _ in WORK_LOG_FIELDS)


class ReportsRepository:
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
        for row in rows:
            for field, kind in fields.items():
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

    def insert_work_log(self, row: dict[str, str], *, author: str) -> int:
        with connect(self.db_path) as db:
            cursor = db.execute(
                f"""INSERT INTO work_logs({WORK_LOG_INSERT_COLUMNS})
                    VALUES ({WORK_LOG_INSERT_PLACEHOLDERS})""",
                self.work_log_values(row),
            )
            log_id = int(cursor.lastrowid)
            write_audit_entry(
                db,
                action="WORK_LOG_CREATE",
                entity_type="work_log",
                entity_id=log_id,
                author=author,
                details={"task": f"{row['task_type']}-{row['task_number']}"},
            )
            return log_id

    def insert_work_logs(self, rows: list[dict[str, str]], *, author: str) -> int:
        with connect(self.db_path) as db:
            db.executemany(
                f"""INSERT INTO work_logs({WORK_LOG_INSERT_COLUMNS})
                    VALUES ({WORK_LOG_INSERT_PLACEHOLDERS})""",
                [self.work_log_values(row) for row in rows],
            )
            write_audit_entry(
                db,
                action="WORK_LOG_BATCH_CREATE",
                entity_type="work_log",
                author=author,
                details={"count": len(rows)},
            )
        return len(rows)

    def import_work_logs(
        self,
        rows: list[dict[str, str]],
        *,
        author: str,
        collect_soft_references: bool,
    ) -> int:
        with connect(self.db_path) as db:
            self.collect_references(
                db,
                rows,
                {
                    "task_source": "task_source",
                    "task_type": "task_type",
                    "status": "work_log_status",
                },
                enabled=collect_soft_references,
                author=author,
            )
            db.executemany(
                f"""INSERT INTO work_logs({WORK_LOG_INSERT_COLUMNS})
                    VALUES ({WORK_LOG_INSERT_PLACEHOLDERS})""",
                [self.work_log_values(row) for row in rows],
            )
            write_audit_entry(
                db,
                action="WORK_LOG_IMPORT",
                entity_type="work_log",
                author=author,
                details={"count": len(rows)},
            )
        return len(rows)

    def work_logs(self, date_from: str = "", date_to: str = "") -> list[dict[str, Any]]:
        sql = """SELECT id, work_date, task_source, task_type, task_number,
                        task_type || '-' || task_number AS full_task_name,
                        description, status, section, needs_review, comment, created_at
                 FROM work_logs WHERE 1 = 1"""
        params: list[Any] = []
        if date_from:
            sql += " AND work_date >= ?"
            params.append(date_from)
        if date_to:
            sql += " AND work_date <= ?"
            params.append(date_to)
        sql += " ORDER BY work_date DESC, id DESC"
        with connect(self.db_path) as db:
            return [dict(row) for row in db.execute(sql, params).fetchall()]

    def update_work_log(self, log_id: int, row: dict[str, str], *, author: str) -> None:
        from inventory.shared.validators import WarehouseError

        assignments = ", ".join(f"{field} = ?" for field in WORK_LOG_FIELDS)
        with connect(self.db_path) as db:
            cursor = db.execute(
                f"UPDATE work_logs SET {assignments} WHERE id = ?",
                (*self.work_log_values(row), log_id),
            )
            if cursor.rowcount == 0:
                raise WarehouseError("Запись лога работ не найдена")
            write_audit_entry(
                db,
                action="WORK_LOG_UPDATE",
                entity_type="work_log",
                entity_id=log_id,
                author=author,
                details={"task": f"{row['task_type']}-{row['task_number']}"},
            )

    def delete_work_log(self, log_id: int, *, author: str) -> None:
        from inventory.shared.validators import WarehouseError

        with connect(self.db_path) as db:
            cursor = db.execute("DELETE FROM work_logs WHERE id = ?", (log_id,))
            if cursor.rowcount == 0:
                raise WarehouseError("Запись лога работ не найдена")
            write_audit_entry(
                db,
                action="WORK_LOG_DELETE",
                entity_type="work_log",
                entity_id=log_id,
                author=author,
                details={},
            )

    def insert_daily_report(
        self,
        filename: str,
        rows: list[dict[str, str]],
        *,
        uploaded_by: str,
        audit_author: str,
    ) -> dict[str, Any]:
        with connect(self.db_path) as db:
            cursor = db.execute(
                """INSERT INTO daily_report_uploads(filename, uploaded_by, row_count)
                   VALUES (?, ?, ?)""",
                (filename, uploaded_by, len(rows)),
            )
            upload_id = int(cursor.lastrowid)
            db.executemany(
                """INSERT INTO daily_report_rows(
                       upload_id, row_order, report_date, report_block, task_number,
                       description, quantity, serial_number, responsible, comment
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        upload_id, order, row["date"], row["report_block"],
                        row["task_number"], row["description"], row["quantity"],
                        row["serial_number"], row["responsible"], row["comment"],
                    )
                    for order, row in enumerate(rows, start=1)
                ],
            )
            write_audit_entry(
                db,
                action="DAILY_REPORT_UPLOAD",
                entity_type="daily_report_upload",
                entity_id=upload_id,
                author=audit_author,
                details={"filename": filename, "rows": len(rows)},
            )
        return {"id": upload_id, "filename": filename, "row_count": len(rows)}

    def daily_report_uploads(self) -> list[dict[str, Any]]:
        with connect(self.db_path) as db:
            return [dict(row) for row in db.execute(
                """SELECT id, filename, uploaded_at, uploaded_by, row_count
                   FROM daily_report_uploads ORDER BY uploaded_at DESC, id DESC"""
            )]

    def uploaded_daily_report(self, upload_id: int) -> list[dict[str, Any]]:
        from inventory.shared.validators import WarehouseError

        with connect(self.db_path) as db:
            exists = db.execute(
                "SELECT 1 FROM daily_report_uploads WHERE id = ?", (upload_id,)
            ).fetchone()
            if exists is None:
                raise WarehouseError("Загруженный отчет не найден")
            return [dict(row) for row in db.execute(
                """SELECT report_date AS date, report_block, task_number, description,
                          quantity, serial_number, responsible, comment
                   FROM daily_report_rows WHERE upload_id = ? ORDER BY row_order""",
                (upload_id,),
            )]

    @staticmethod
    def work_log_values(row: dict[str, Any]) -> tuple[Any, ...]:
        return tuple(
            int(bool(row.get(field, 0))) if field == "needs_review" else row[field]
            for field in WORK_LOG_FIELDS
        )
