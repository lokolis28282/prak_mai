from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from inventory.core.application import create_application_context
from inventory.service import WarehouseError, WarehouseService


class WarehouseIssueWriteContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "warehouse.db"
        self.service = WarehouseService(self.db_path)
        self.context = create_application_context(self.db_path, service=self.service)
        self.today = "2026-07-11"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def receipt(self, serial: str, **overrides: object) -> dict[str, object]:
        row: dict[str, object] = {
            "receipt_date": self.today,
            "responsible": "Issue Engineer",
            "category": "Оборудование",
            "item_type": "Сервер",
            "supplier": "Не указан",
            "vendor": "Dell",
            "model": "R740",
            "item_name": "Сервер Dell R740",
            "project": "Digital",
            "serial_number": serial,
            "inventory_number": f"INV-{serial}",
            "shelf": "A-01",
            "object_name": "Склад",
            "datacenter": "Ixcellerate",
            "unit": "шт",
            "quantity": "1",
        }
        row.update(overrides)
        return row

    def issue(self, serial: str, **overrides: object) -> dict[str, object]:
        row: dict[str, object] = {
            "issue_date": self.today,
            "responsible": "Issue Engineer",
            "task_type": "ЗНР",
            "task_number": "100",
            "target_serial_number": "",
            "target_hostname": "",
            "source_serial_number": serial,
            "source_item_name": "",
            "source_cable_type": "",
            "quantity": "1",
            "comment": "contract",
        }
        row.update(overrides)
        return row

    def count(self, table: str) -> int:
        with closing(sqlite3.connect(self.db_path)) as db:
            return int(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])

    def allocation_count(self) -> int:
        return self.count("stock_issue_allocations")

    def test_manual_equipment_component_allocations_reports_and_audit(self) -> None:
        with self.service.user_context("lokolis", author_name="Issue Shift"):
            self.context.warehouse.create_receipt(self.receipt("ISS-EQ-1"))
            target_id = self.context.warehouse.create_receipt(self.receipt("ISS-TARGET-1"))
            component_id = self.context.warehouse.create_receipt(self.receipt(
                "ISS-CMP-1", category="Компоненты", item_type="SSD",
                equipment_type="", component_type="", model="PM883",
            ))
            issue_id = self.context.warehouse.create_issue(self.issue("ISS-EQ-1"))
            component_issue_id = self.context.warehouse.create_issue(self.issue(
                "ISS-CMP-1", target_serial_number="ISS-TARGET-1", target_hostname="srv-1"
            ))
        self.assertGreater(target_id, 0)
        self.assertGreater(component_id, 0)
        self.assertGreater(issue_id, 0)
        self.assertGreater(component_issue_id, 0)
        self.assertEqual(self.allocation_count(), 2)
        self.assertEqual(self.context.warehouse.get_balance({"query": "ISS-EQ-1"})[0]["balance"], 0)
        events = self.context.reports.warehouse_events.list_events(self.today, self.today, event_types={"ISSUE_CREATED"})
        self.assertTrue(any(event.serial_number == "ISS-EQ-1" for event in events))
        daily = self.context.reports.get_daily_report(self.today)
        weekly = self.context.reports.get_weekly_report(self.today, self.today)
        self.assertTrue(any(row["report_block"] == "Расход" and row["serial_number"] == "ISS-EQ-1" for row in daily))
        self.assertGreaterEqual(weekly["summary"]["issues"], 2)
        with closing(sqlite3.connect(self.db_path)) as db:
            audit = db.execute("SELECT author FROM audit_log WHERE action='ISSUE_CREATE' ORDER BY id DESC LIMIT 1").fetchone()
        self.assertEqual(audit[0], "Issue Shift")

    def test_batch_duplicates_unknown_already_issued_and_rollback(self) -> None:
        with self.service.user_context("lokolis"):
            for index in range(3):
                self.context.warehouse.create_receipt(self.receipt(f"ISS-B3-{index}"))
            result = self.context.warehouse.create_issue_by_serials(
                {**self.issue(""), "source_serial_number": ""},
                ["ISS-B3-0", "ISS-B3-1", "UNKNOWN-B3"],
            )
            self.assertEqual(result, {"imported": 3, "unmatched": 1})
            with self.assertRaisesRegex(WarehouseError, "повторяющиеся"):
                self.context.warehouse.create_issue_by_serials({**self.issue(""), "source_serial_number": ""}, ["DUP", "dup"])
            before = self.count("stock_issues")
            with self.assertRaisesRegex(WarehouseError, "доступно 0"):
                self.context.warehouse.create_issue_by_serials(
                    {**self.issue(""), "source_serial_number": ""},
                    ["ISS-B3-2", "ISS-B3-0"],
                )
            self.assertEqual(self.count("stock_issues"), before)

    def test_batch_100_preview_confirm_repeat_and_viewer(self) -> None:
        with self.service.user_context("lokolis"):
            self.service.create_user("View", "Issue", "Viewer", "viewer-issue@test", "secret1", "viewer")
            rows = []
            for index in range(100):
                serial = f"ISS-100-{index:03d}"
                self.context.warehouse.create_receipt(self.receipt(serial))
                rows.append({"serial_number": serial, "comment": "bulk"})
            preview = self.context.warehouse.preview_bulk_issue_serials(rows, "bulk.csv")
            self.assertEqual(preview["valid"], 100)
            before = self.count("stock_issues")
            imported = self.context.warehouse.confirm_bulk_issue_preview(
                preview["preview_id"], self.today, "Issue Engineer", "ЗНР", "200", "bulk"
            )
            self.assertEqual(imported, 100)
            with self.assertRaises(WarehouseError):
                self.context.warehouse.confirm_bulk_issue_preview(
                    preview["preview_id"], self.today, "Issue Engineer", "ЗНР", "200"
                )
            self.assertEqual(self.count("stock_issues"), before + 100)
        with self.service.user_context("viewer-issue@test"):
            with self.assertRaises(WarehouseError):
                self.context.warehouse.create_issue(self.issue("ISS-100-000"))

    def test_csv_preview_confirm_problem_row_and_no_mutation(self) -> None:
        with self.service.user_context("lokolis"):
            self.context.warehouse.create_receipt(self.receipt("ISS-CSV-1"))
            before_issues = self.count("stock_issues")
            preview = self.context.warehouse.preview_issue_import([
                self.issue("ISS-CSV-1"),
                self.issue("ISS-UNKNOWN-1"),
            ], "issue.csv", soft=True)
            self.assertEqual(self.count("stock_issues"), before_issues)
            self.assertTrue(preview["can_confirm"])
            imported = self.context.warehouse.confirm_issue_import(preview["preview_id"])
            self.assertEqual(imported, 2)
            problems = self.context.warehouse.get_problem_issues()
            self.assertTrue(any(row["serial_number"] == "ISS-UNKNOWN-1" for row in problems))
            with self.assertRaises(WarehouseError):
                self.context.warehouse.confirm_issue_import(preview["preview_id"])

    def test_cable_receipt_delivery_and_consecutive_issue_regressions(self) -> None:
        with self.service.user_context("lokolis"):
            self.context.warehouse.create_cable_receipt({
                "receipt_date": self.today, "responsible": "Cable", "category": "Кабели",
                "item_type": "DAC", "cable_type": "DAC", "item_name": "DAC issue",
                "supplier": "Не указан", "vendor": "Не указан", "project": "Digital",
                "datacenter": "Ixcellerate", "shelf": "C-01", "object_name": "Склад",
                "unit": "шт", "quantity": "2",
            })
            self.context.warehouse.create_receipt(self.receipt("ISS-CONC-1"))
            self.context.warehouse.create_issue(self.issue("iss-conc-1"))
            with self.assertRaisesRegex(WarehouseError, "доступно 0"):
                self.context.warehouse.create_issue(self.issue("ISS-CONC-1"))
            preview = self.service.preview_delivery_rows([
                {"serial_number": "ISS-DEL-1", "delivery_number": "D-Issue", "supplier": "Не указан", "quantity": "1", "equipment_unit": "Сервер"},
            ], "delivery.csv", auto_apply=True)
            delivery_id = self.service.confirm_delivery_preview(preview["preview_id"])
        self.assertGreater(delivery_id, 0)
        self.assertTrue(any(row["item_name"] == "DAC issue" for row in self.context.warehouse.get_cable_balance()))


if __name__ == "__main__":
    unittest.main()
