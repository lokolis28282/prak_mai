from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from inventory.core.application import create_application_context
from inventory.service import WarehouseError, WarehouseService


class WarehouseCableContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "warehouse.db"
        self.service = WarehouseService(self.db_path)
        self.context = create_application_context(self.db_path, service=self.service)
        self.today = "2026-07-11"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def cable_receipt(self, **overrides: object) -> dict[str, object]:
        row: dict[str, object] = {
            "receipt_date": self.today,
            "responsible": "Кабельный инженер",
            "category": "Кабели",
            "item_type": "DAC",
            "cable_type": "DAC",
            "item_name": "DAC 3m",
            "supplier": "Не указан",
            "vendor": "Не указан",
            "project": "Digital",
            "datacenter": "Ixcellerate",
            "shelf": "C-01",
            "object_name": "Склад",
            "unit": "шт",
            "quantity": "10",
            "comment": "Партия",
        }
        row.update(overrides)
        return row

    def cable_issue(self, **overrides: object) -> dict[str, object]:
        row: dict[str, object] = {
            "issue_date": self.today,
            "responsible": "Кабельный инженер",
            "source_item_name": "DAC 3m",
            "source_cable_type": "DAC",
            "quantity": "4",
            "task_type": "ЗНР",
            "task_number": "42",
            "comment": "Монтаж",
        }
        row.update(overrides)
        return row

    def count(self, table: str) -> int:
        with closing(sqlite3.connect(self.db_path)) as db:
            return int(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])

    def test_receipt_aggregation_issue_events_reports_and_audit(self) -> None:
        with self.service.user_context("lokolis", author_name="Кабельная смена"):
            first = self.context.warehouse.create_cable_receipt(self.cable_receipt(quantity="10"))
            second = self.context.warehouse.create_cable_receipt(self.cable_receipt(quantity="5"))
            issue = self.context.warehouse.create_cable_issue(self.cable_issue(quantity="12"))
        self.assertGreater(first, 0)
        self.assertGreater(second, 0)
        self.assertGreater(issue, 0)
        balance = self.context.warehouse.get_cable_balance({"cable_type": "DAC"})
        row = next(item for item in balance if item["item_name"] == "DAC 3m")
        self.assertEqual(float(row["balance"]), 3.0)
        self.assertEqual(row["serial_number"], "")
        events = self.context.reports.warehouse_events.list_events(
            self.today, self.today, event_types={"CABLE_RECEIVED", "CABLE_ISSUED"}
        )
        self.assertEqual([event.event_type for event in events].count("CABLE_RECEIVED"), 2)
        self.assertEqual([event.event_type for event in events].count("CABLE_ISSUED"), 1)
        daily = self.context.reports.get_daily_report(self.today)
        weekly = self.context.reports.get_weekly_report(self.today, self.today)
        self.assertTrue(any(row["report_block"] == "Приход" and row["serial_number"] == "" for row in daily))
        self.assertEqual(weekly["summary"]["cable_received"], 15.0)
        self.assertEqual(weekly["summary"]["cable_issued"], 12.0)
        with closing(sqlite3.connect(self.db_path)) as db:
            actions = [row[0] for row in db.execute("SELECT action FROM audit_log ORDER BY id")]
        self.assertIn("CABLE_RECEIPT_CREATE", actions)
        self.assertIn("CABLE_ISSUE_CREATE", actions)

    def test_balance_key_and_insufficient_stock(self) -> None:
        with self.service.user_context("lokolis"):
            self.context.warehouse.create_cable_receipt(self.cable_receipt(cable_type="DAC", item_type="DAC", item_name="Cable A", project="P1", shelf="S1", quantity="3"))
            self.context.warehouse.create_cable_receipt(self.cable_receipt(cable_type="DAC", item_type="DAC", item_name="Cable A", project="P2", shelf="S2", quantity="4"))
            self.context.warehouse.create_cable_receipt(self.cable_receipt(cable_type="OPT", item_type="OPT", item_name="Cable A", project="P1", shelf="S1", quantity="5"))
            self.context.warehouse.create_cable_issue(self.cable_issue(source_item_name="Cable A", source_cable_type="DAC", quantity="7"))
            with self.assertRaisesRegex(WarehouseError, "доступно 0"):
                self.context.warehouse.create_cable_issue(self.cable_issue(source_item_name="Cable A", source_cable_type="DAC", quantity="1"))
        balances = self.context.warehouse.get_cable_balance()
        self.assertTrue(any(row["cable_type"] == "OPT" and float(row["balance"]) == 5.0 for row in balances))
        self.assertTrue(all(float(row["balance"]) >= 0 for row in balances))

    def test_validation_roles_and_no_sn_required(self) -> None:
        with self.service.user_context("lokolis"):
            self.service.create_user("View", "Cable", "Viewer", "viewer-cable@test", "secret1", "viewer")
            for quantity in ("0", "-1", "1.5", "bad"):
                with self.assertRaises(WarehouseError):
                    self.context.warehouse.create_cable_receipt(self.cable_receipt(quantity=quantity))
            receipt_id = self.context.warehouse.create_cable_receipt(self.cable_receipt(serial_number="IGNORED"))
        self.assertGreater(receipt_id, 0)
        self.assertEqual(next(row for row in self.context.warehouse.get_cable_balance() if row["item_name"] == "DAC 3m")["serial_number"], "")
        with self.service.user_context("viewer-cable@test"):
            with self.assertRaises(WarehouseError):
                self.context.warehouse.create_cable_receipt(self.cable_receipt())

    def test_equipment_receipt_and_batch_still_work(self) -> None:
        equipment = {
            "receipt_date": self.today,
            "responsible": "Инженер",
            "category": "Оборудование",
            "item_type": "Сервер",
            "supplier": "Не указан",
            "vendor": "Dell",
            "model": "R740",
            "item_name": "Сервер Dell R740",
            "project": "Digital",
            "serial_number": "EQ-CABLE-1",
            "inventory_number": "INV-EQ-CABLE-1",
            "shelf": "A-01",
            "object_name": "Склад",
            "datacenter": "Ixcellerate",
            "unit": "шт",
            "quantity": "1",
        }
        with self.service.user_context("lokolis"):
            self.context.warehouse.create_receipt(equipment)
            result = self.context.warehouse.create_receipt_batch([
                {**equipment, "serial_number": "EQ-CABLE-B1", "inventory_number": "INV-EQ-CABLE-B1"},
                {**equipment, "serial_number": "EQ-CABLE-B2", "inventory_number": "INV-EQ-CABLE-B2"},
            ])
        self.assertEqual(result["created_count"], 2)
        self.assertEqual(self.count("stock_receipts"), 3)


if __name__ == "__main__":
    unittest.main()
