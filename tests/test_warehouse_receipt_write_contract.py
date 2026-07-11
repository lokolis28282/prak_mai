from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from inventory.core.application import create_application_context
from inventory.service import WarehouseError, WarehouseService
from inventory.warehouse.naming import build_item_name


class WarehouseReceiptWriteContractTest(unittest.TestCase):
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

    def receipt(self, serial: str = "RCPT-1", **overrides: object) -> dict[str, object]:
        row: dict[str, object] = {
            "receipt_date": self.today,
            "responsible": "Инженер Прихода",
            "category": "Оборудование",
            "item_type": "Сервер",
            "supplier": "Не указан",
            "vendor": "Dell",
            "model": "PowerEdge R740",
            "item_name": "ignored by system naming",
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

    def test_naming_rules(self) -> None:
        self.assertEqual(build_item_name("Оборудование", "Сервер", "Dell", "PowerEdge R740"), "Сервер Dell PowerEdge R740")
        self.assertEqual(build_item_name("Компоненты", "SSD", "Samsung", "PM883 1.92TB"), "SSD Samsung PM883 1.92TB")
        self.assertEqual(build_item_name("Компоненты", "RAM", "Hynix", "32GB DDR4"), "RAM Hynix 32GB DDR4")
        self.assertEqual(build_item_name("Оборудование", "Коммутатор", "Cisco", "Nexus 93180YC"), "Коммутатор Cisco Nexus 93180YC")
        self.assertEqual(build_item_name("Оборудование", "Сервер", "", ""), "Сервер")

    def test_manual_equipment_and_component_receipts_update_balance_reports_events(self) -> None:
        with self.service.user_context("lokolis", author_name="Смена Приход"):
            equipment_id = self.context.warehouse.create_receipt(self.receipt("EQ-1"))
            component_id = self.context.warehouse.create_receipt(self.receipt(
                "CMP-1", category="Компоненты", item_type="SSD", equipment_type="",
                component_type="", model="PM883", item_name="free text",
            ))
        self.assertGreater(equipment_id, 0)
        self.assertGreater(component_id, 0)
        receipts = self.context.warehouse.receipts()
        self.assertTrue(any(row["serial_number"] == "EQ-1" and row["item_name"] == "Сервер Dell PowerEdge R740" for row in receipts))
        self.assertTrue(any(row["serial_number"] == "CMP-1" and row["component_type"] == "SSD" for row in receipts))
        balance = self.context.warehouse.get_balance({"query": "EQ-1"})
        self.assertTrue(any(row["serial_number"] == "EQ-1" for row in balance))
        events = self.context.reports.warehouse_events.list_events(self.today, self.today, event_types={"RECEIPT_CREATED"})
        self.assertTrue(any(event.serial_number == "EQ-1" for event in events))
        daily = self.context.reports.get_daily_report(self.today)
        weekly = self.context.reports.get_weekly_report(self.today, self.today)
        self.assertTrue(any(row["serial_number"] == "EQ-1" for row in daily))
        self.assertGreaterEqual(weekly["summary"]["receipts"], 2)
        with closing(sqlite3.connect(self.db_path)) as db:
            audit = db.execute("SELECT action, author FROM audit_log WHERE action='RECEIPT_CREATE' ORDER BY id DESC LIMIT 1").fetchone()
        self.assertEqual(audit, ("RECEIPT_CREATE", "Смена Приход"))

    def test_batch_3_and_100_serials(self) -> None:
        with self.service.user_context("lokolis"):
            result = self.context.warehouse.create_receipt_batch([self.receipt(f"B3-{i}") for i in range(3)])
            self.assertEqual(result["created_count"], 3)
            result = self.context.warehouse.create_receipt_batch([self.receipt(f"B100-{i}") for i in range(100)])
            self.assertEqual(result["created_count"], 100)
        self.assertEqual(len([row for row in self.context.warehouse.receipts() if str(row["serial_number"]).startswith("B100-")]), 100)

    def test_duplicate_existing_case_insensitive_and_rollback(self) -> None:
        with self.service.user_context("lokolis"):
            self.context.warehouse.create_receipt(self.receipt("DUP-1"))
            before = self.count("stock_receipts")
            with self.assertRaisesRegex(WarehouseError, "уже используется"):
                self.context.warehouse.create_receipt_batch([self.receipt("OK-ROLLBACK"), self.receipt("dup-1")])
            self.assertEqual(self.count("stock_receipts"), before)
            with self.assertRaisesRegex(WarehouseError, "Строка 3"):
                self.context.warehouse.import_receipts([self.receipt("CSV-OK"), {**self.receipt("CSV-BAD"), "receipt_date": "bad"}])
            self.assertEqual(self.count("stock_receipts"), before)

    def test_preview_confirm_repeated_confirm_and_no_writes(self) -> None:
        with self.service.user_context("lokolis"):
            before = self.count("stock_receipts")
            preview = self.context.warehouse.preview_receipt_import([self.receipt("PRE-1")], "receipt.csv", soft=True)
            self.assertEqual(self.count("stock_receipts"), before)
            self.assertTrue(preview["can_confirm"])
            imported = self.context.warehouse.confirm_receipt_import(preview["preview_id"])
            self.assertEqual(imported, 1)
            with self.assertRaises(WarehouseError):
                self.context.warehouse.confirm_receipt_import(preview["preview_id"])
        self.assertEqual(self.count("stock_receipts"), before + 1)

    def test_viewer_cannot_write_and_serial_validation(self) -> None:
        with self.service.user_context("lokolis"):
            self.service.create_user("View", "Only", "Viewer", "viewer-receipt@test", "secret1", "viewer")
            self.context.warehouse.create_receipt(self.receipt("SER-1"))
            check = self.context.warehouse.validate_receipt_serial(" ser-1 ")
            self.assertFalse(check["valid"])
        with self.service.user_context("viewer-receipt@test"):
            with self.assertRaises(WarehouseError):
                self.context.warehouse.create_receipt(self.receipt("VIEW-1"))

    def test_delivery_regression_still_creates_receipt(self) -> None:
        with self.service.user_context("lokolis"):
            preview = self.service.preview_delivery_rows([
                {"serial_number": "DEL-RCPT-1", "delivery_number": "D-1", "supplier": "Не указан", "quantity": "1", "equipment_unit": "Сервер"},
            ], "delivery.csv", auto_apply=True)
            delivery_id = self.service.confirm_delivery_preview(preview["preview_id"])
        self.assertGreater(delivery_id, 0)
        self.assertTrue(any(row["serial_number"] == "DEL-RCPT-1" for row in self.context.warehouse.receipts()))


if __name__ == "__main__":
    unittest.main()
