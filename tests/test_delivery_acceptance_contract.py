from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

from inventory.core.application import create_application_context
from inventory.db import connect
from inventory.service import WarehouseService
from inventory.shared.validators import WarehouseError


class DeliveryAcceptanceContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "warehouse.db"
        self.service = WarehouseService(self.db_path)
        self.context = create_application_context(
            self.db_path, service=self.service, warehouse_contour="demo"
        )
        self.facade = self.context.warehouse

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def create_delivery(self, rows: list[dict[str, str]]) -> int:
        with self.service.user_context("lokolis"):
            preview = self.facade.preview_delivery_import(rows, "accept.csv")
            return self.facade.confirm_delivery_import(preview["preview_id"])

    def add_existing(self, serial: str = "EXIST-A", **overrides: str) -> None:
        row = {
            "receipt_date": "2026-01-01", "responsible": "Old Engineer",
            "item_name": "Existing item", "project": "", "serial_number": serial,
            "inventory_number": "", "supplier": "Old Supplier", "vendor": "Dell",
            "model": "", "shelf": "", "object_name": "Warehouse",
            "datacenter": "DC1", "equipment_type": "Server", "component_type": "",
            "cable_type": "", "unit": "шт", "quantity": "1",
        }
        row.update(overrides)
        self.service.add_stock_receipt(**row)

    def counts(self) -> dict[str, int]:
        with connect(self.db_path) as db:
            return {
                table: int(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                for table in ("stock_receipts", "stock_issues", "stock_issue_allocations", "audit_log")
            }

    def test_inspect_accept_new_balance_line_audit_and_repeat_blocked(self) -> None:
        delivery_id = self.create_delivery([
            {"S/N": "NEW-A", "Номер поставки": "D-A", "Поставщик": "Supplier", "Вендор": "Dell", "Модель": "R760", "Тип оборудования": "Server"},
        ])
        before = self.counts()
        with self.service.user_context("lokolis"):
            inspect = self.facade.inspect_delivery_serial(delivery_id, " new-a ")
            self.assertEqual(inspect["allowed_actions"], ["accept_new"])
            result = self.facade.accept_delivery_serial(delivery_id, "new-a")
        self.assertTrue(result["accepted"])
        self.assertTrue(result["created_receipt"])
        with connect(self.db_path) as db:
            line = db.execute("SELECT state, receipt_id FROM delivery_lines WHERE delivery_id=?", (delivery_id,)).fetchone()
            status = db.execute("SELECT status FROM deliveries WHERE id=?", (delivery_id,)).fetchone()[0]
        self.assertEqual(line["state"], "Принято")
        self.assertIsNotNone(line["receipt_id"])
        self.assertEqual(status, "Принята")
        self.assertEqual(self.counts()["stock_receipts"], before["stock_receipts"] + 1)
        with self.service.user_context("lokolis"):
            with self.assertRaises(WarehouseError):
                self.facade.accept_delivery_serial(delivery_id, "NEW-A")

    def test_existing_sn_fills_empty_fields_without_overwrite_and_reports_conflict(self) -> None:
        self.add_existing("EXIST-A", supplier="Old Supplier", model="", inventory_number="")
        delivery_id = self.create_delivery([
            {"S/N": "EXIST-A", "Номер поставки": "D-E", "Поставщик": "New Supplier", "Вендор": "Dell", "Модель": "R760", "Инвентарный номер": "INV-E", "Тип оборудования": "Server"},
        ])
        before = self.counts()
        with self.service.user_context("lokolis"):
            inspect = self.facade.inspect_delivery_serial(delivery_id, "EXIST-A")
            self.assertIn("fill_empty_existing", inspect["allowed_actions"])
            self.assertIn("supplier", inspect["conflicting_fields"])
            result = self.facade.accept_delivery_serial(delivery_id, "EXIST-A")
        self.assertFalse(result["created_receipt"])
        self.assertEqual(self.counts()["stock_receipts"], before["stock_receipts"])
        with connect(self.db_path) as db:
            receipt = db.execute("SELECT supplier, model, inventory_number FROM stock_receipts WHERE serial_number='EXIST-A'").fetchone()
            line = db.execute("SELECT state, receipt_id FROM delivery_lines WHERE delivery_id=?", (delivery_id,)).fetchone()
        self.assertEqual(receipt["supplier"], "Old Supplier")
        self.assertEqual(receipt["model"], "R760")
        self.assertEqual(receipt["inventory_number"], "INV-E")
        self.assertEqual(line["state"], "Уже на складе")
        self.assertIsNotNone(line["receipt_id"])

    def test_unplanned_batch_status_viewer_and_edit_accepted_readonly(self) -> None:
        delivery_id = self.create_delivery([
            {"S/N": "B-1", "Номер поставки": "D-B", "Поставщик": "Supplier", "Вендор": "Dell", "Тип оборудования": "Server"},
            {"S/N": "B-2", "Номер поставки": "D-B", "Поставщик": "Supplier", "Вендор": "Dell", "Тип оборудования": "Server"},
            {"S/N": "B-3", "Номер поставки": "D-B", "Поставщик": "Supplier", "Вендор": "Dell", "Тип оборудования": "Server"},
        ])
        with self.service.user_context("lokolis"):
            self.service.create_user("View", "Only", "Viewer", "viewer-accept@test", "secret1", "viewer")
        with self.service.user_context("viewer-accept@test"):
            with self.assertRaises(WarehouseError):
                self.facade.accept_delivery_serial(delivery_id, "B-1")
        with connect(self.db_path) as db:
            ids = [row[0] for row in db.execute("SELECT id FROM delivery_lines WHERE delivery_id=? ORDER BY id", (delivery_id,))]
        with self.service.user_context("lokolis"):
            batch = self.facade.accept_delivery_batch(delivery_id, ids[:2])
            self.assertEqual(batch["accepted_new"], 2)
            summary = self.facade.get_delivery_acceptance_summary(delivery_id)
            self.assertEqual(summary["status"], "Частично принята")
            changed = self.facade.update_delivery_line_metadata(delivery_id, [ids[0]], {"serial_number": "BAD", "model": "BAD"})
            self.assertEqual(changed, 0)
            unplanned = self.facade.accept_unplanned_delivery_serial(delivery_id, "UNP-A", {
                "supplier": "Supplier", "vendor": "Dell", "model": "R760",
                "project": "P", "datacenter": "DC1", "shelf": "A-01",
                "equipment_type": "Server", "item_name": "Server Dell",
            })
        self.assertTrue(unplanned["accepted"])
        with connect(self.db_path) as db:
            self.assertEqual(db.execute("SELECT is_unplanned FROM delivery_lines WHERE serial_number='UNP-A'").fetchone()[0], 1)

    def test_batch_rollback_and_reports(self) -> None:
        delivery_id = self.create_delivery([
            {"S/N": "R-1", "Номер поставки": "D-R", "Поставщик": "Supplier", "Вендор": "Dell", "Тип оборудования": "Server"},
            {"S/N": "R-2", "Номер поставки": "D-R", "Поставщик": "Supplier", "Вендор": "Dell", "Тип оборудования": "Server"},
        ])
        with connect(self.db_path) as db:
            ids = [row[0] for row in db.execute("SELECT id FROM delivery_lines WHERE delivery_id=? ORDER BY id", (delivery_id,))]
        before = self.counts()
        with self.service.user_context("lokolis"):
            with self.assertRaises(WarehouseError):
                self.facade.accept_delivery_batch(delivery_id, [ids[0], 999999])
        self.assertEqual(self.counts()["stock_receipts"], before["stock_receipts"])
        with self.service.user_context("lokolis"):
            self.facade.accept_delivery_batch(delivery_id, ids)
        today = date.today().isoformat()
        report = self.context.reports.get_weekly_report(today, today)
        self.assertGreaterEqual(report["summary"]["accepted_delivery_items"], 2)


if __name__ == "__main__":
    unittest.main()
