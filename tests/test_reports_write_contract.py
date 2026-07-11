from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from inventory.core.application import create_application_context
from inventory.importing import parse_csv_bytes
from inventory.service import WarehouseError, WarehouseService


class ReportsWriteContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "warehouse.db"
        self.service = WarehouseService(self.db_path)
        self.context = create_application_context(self.db_path, service=self.service)
        self.today = "2026-07-11"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def count(self, table: str) -> int:
        with closing(sqlite3.connect(self.db_path)) as db:
            return int(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])

    def audit_actions(self) -> list[str]:
        with closing(sqlite3.connect(self.db_path)) as db:
            return [str(row[0]) for row in db.execute("SELECT action FROM audit_log ORDER BY id")]

    def row(self, number: str = "RPT-1", date: str | None = None) -> dict[str, str]:
        return {
            "work_date": date or self.today,
            "task_source": "ITSM",
            "task_type": "ИНЦ",
            "task_number": number,
            "description": "Диагностика узла, кириллица",
            "status": "Выполнено",
            "comment": "Комментарий с пробелами",
        }

    def test_create_single_work_log_author_and_audit(self) -> None:
        with self.service.user_context("lokolis", author_name="Иванов Иван"):
            log_id = self.context.reports.create_work_log(self.row())
        self.assertGreater(log_id, 0)
        logs = self.context.reports.list_work_logs({"date_from": self.today, "date_to": self.today})
        self.assertEqual(logs[0]["task_number"], "RPT-1")
        with closing(sqlite3.connect(self.db_path)) as db:
            audit = db.execute(
                "SELECT action, author, entity_id FROM audit_log ORDER BY id DESC LIMIT 1"
            ).fetchone()
        self.assertEqual(audit, ("WORK_LOG_CREATE", "Иванов Иван", str(log_id)))

    def test_viewer_cannot_write(self) -> None:
        with self.service.user_context("lokolis"):
            self.service.create_user("View", "Only", "Viewer", "viewer@example.test", "secret1", "viewer")
        with self.service.user_context("viewer@example.test"):
            with self.assertRaises(WarehouseError):
                self.context.reports.create_work_log(self.row())

    def test_batch_create_three_rows(self) -> None:
        rows = [self.row(f"B-{index}") for index in range(1, 4)]
        with self.service.user_context("lokolis", author_name="Петров Петр"):
            saved = self.context.reports.create_work_logs(rows)
        self.assertEqual(saved, 3)
        self.assertIn("WORK_LOG_BATCH_CREATE", self.audit_actions())

    def test_import_csv_and_rollback_on_second_row_error(self) -> None:
        before_logs = self.count("work_logs")
        before_audit = self.count("audit_log")
        rows = [
            self.row("CSV-1"),
            {**self.row("CSV-2"), "task_source": "Нет такого источника"},
        ]
        with self.service.user_context("lokolis"):
            with self.assertRaisesRegex(WarehouseError, "Строка 3"):
                self.context.reports.import_work_logs(rows, soft=False)
        self.assertEqual(self.count("work_logs"), before_logs)
        self.assertEqual(self.count("audit_log"), before_audit)

    def test_preview_confirm_and_repeated_confirm(self) -> None:
        with self.service.user_context("lokolis", author_name="Сидоров Сидор"):
            preview = self.context.reports.preview_work_log_import([self.row("P-1")], "logs.csv")
            self.assertEqual(self.count("work_logs"), 0)
            self.assertFalse(preview["errors"])
            imported = self.context.reports.confirm_work_log_import(preview["preview_id"])
            self.assertEqual(imported, 1)
            with self.assertRaises(WarehouseError):
                self.context.reports.confirm_work_log_import(preview["preview_id"])
        self.assertEqual(self.count("work_logs"), 1)
        self.assertIn("WORK_LOG_IMPORT", self.audit_actions())

    def test_dates_cyrillic_empty_rows_and_duplicate_preview(self) -> None:
        rows = [
            self.row("DATE-1", "11.07.2026"),
            {key: "" for key in self.row()},
            self.row("DATE-2", "11/07/2026"),
            self.row("DATE-2", "11/07/2026"),
        ]
        with self.service.user_context("lokolis"):
            preview = self.context.reports.preview_work_log_import(rows, "dates.csv")
            self.assertEqual(preview["total"], 3)
            self.assertEqual(preview["duplicates"], 1)
            imported = self.context.reports.import_work_logs(rows, soft=False)
        self.assertEqual(imported, 3)
        self.assertEqual(self.count("work_logs"), 3)

    def test_daily_report_upload_is_separate_from_work_logs(self) -> None:
        daily_rows = [{
            "date": self.today,
            "report_block": "Работы",
            "task_number": "READY-1",
            "description": "Готовый ежедневный отчет",
            "quantity": "1",
            "serial_number": "SN-READY",
            "responsible": "Инженер",
            "comment": "CSV",
        }]
        with self.service.user_context("lokolis", author_name="Автор отчета"):
            before_logs = self.count("work_logs")
            result = self.context.reports.import_daily_report("готовый.csv", daily_rows)
        self.assertEqual(result["row_count"], 1)
        self.assertEqual(self.count("work_logs"), before_logs)
        self.assertEqual(self.count("daily_report_uploads"), 1)
        self.assertEqual(self.count("daily_report_rows"), 1)
        self.assertIn("DAILY_REPORT_UPLOAD", self.audit_actions())

    def test_daily_report_preview_does_not_write_and_confirm_writes(self) -> None:
        rows = [{
            "date": self.today,
            "description": "Preview отчет",
            "report_block": "Блок",
            "task_number": "",
            "quantity": "",
            "serial_number": "",
            "responsible": "Инженер",
            "comment": "",
        }]
        with self.service.user_context("lokolis"):
            preview = self.context.reports.preview_daily_report_import(rows, "ready.csv")
            self.assertEqual(self.count("daily_report_uploads"), 0)
            result = self.context.reports.confirm_daily_report_import(preview["preview_id"])
        self.assertEqual(result["row_count"], 1)
        self.assertEqual(self.count("daily_report_uploads"), 1)

    def test_reports_do_not_change_warehouse_tables(self) -> None:
        warehouse_tables = ("stock_receipts", "stock_issues", "equipment", "operations")
        before = {table: self.count(table) for table in warehouse_tables}
        with self.service.user_context("lokolis"):
            self.context.reports.create_work_log(self.row("WH-1"))
            self.context.reports.import_daily_report("ready.csv", [{
                "date": self.today,
                "description": "Отчет",
            }])
        after = {table: self.count(table) for table in warehouse_tables}
        self.assertEqual(after, before)

    def test_parse_import_csv_headers(self) -> None:
        text = "Дата;Источник задачи;Тип задачи;Номер задачи;Описание работы;Статус;Комментарий\n"
        text += f"{self.today};ITSM;ИНЦ;CSV;Работа;Выполнено;Тест\n"
        rows = parse_csv_bytes(text.encode("utf-8-sig"), "work_logs")
        with self.service.user_context("lokolis"):
            self.assertEqual(self.context.reports.import_work_logs(rows), 1)


if __name__ == "__main__":
    unittest.main()
