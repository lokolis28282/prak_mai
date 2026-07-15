from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from inventory.core.application import create_application_context
from inventory.db import connect
from inventory.service import WarehouseService
from inventory.shared.validators import WarehouseError


class DeliveryImportContractTest(unittest.TestCase):
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

    def counts(self) -> dict[str, int]:
        with connect(self.db_path) as db:
            return {
                name: int(db.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0])
                for name in ("stock_receipts", "stock_issues", "stock_issue_allocations", "deliveries", "delivery_lines", "audit_log")
            }

    def add_stock(self, serial: str = "DEL-STOCK-1") -> None:
        self.service.add_stock_receipt(
            receipt_date="2026-07-11", responsible="Engineer", item_name="Server",
            project="Digital", serial_number=serial, inventory_number=f"INV-{serial}",
            supplier="Supplier", vendor="Dell", model="R760", shelf="A-01",
            object_name="Warehouse", datacenter="DC1", equipment_type="Server",
            component_type="", cable_type="", unit="шт", quantity="1",
        )

    def preview(self, rows: list[dict[str, str]], filename: str = "delivery.csv") -> dict:
        with self.service.user_context("lokolis"):
            return self.facade.preview_delivery_import(rows, filename)

    def confirm(self, preview_id: str) -> int:
        with self.service.user_context("lokolis"):
            return self.facade.confirm_delivery_import(preview_id)

    def test_canonical_and_legacy_columns_sn_split_and_duplicates(self) -> None:
        preview = self.preview([
            {
                "Дата": "2026-01-10", "Поставщик": "Supplier", "Номер поставки": "D-1",
                "Заявка": "REQ-1", "Заказ": "ORD-1", "Серийный номер": "SN-1, SN-2, SN-1",
                "Инвентарный номер": "INV-1", "Вендор": "Dell", "Модель": "R760",
                "Тип оборудования": "Server", "Количество": "3",
            },
            {"SN": "SN-3\nSN-4", "Delivery Number": "D-1", "Supplier": "Supplier", "Qty": "2"},
        ])
        self.assertEqual(preview["summary"]["source_rows"], 2)
        self.assertEqual(preview["summary"]["expanded_rows"], 5)
        self.assertEqual(preview["summary"]["duplicates"], 1)
        self.assertEqual(preview["summary"]["ready_rows"], 4)
        self.assertIn("Серийный номер", preview["normalized_mapping"])

    def test_unknown_ambiguous_empty_sn_and_bad_quantity(self) -> None:
        preview = self.preview([
            {"S/N": "", "Номер ОС": "A-1", "Лишняя": "x", "Количество": "1"},
            {"S/N": "QTY-1 QTY-2 QTY-3", "Количество": "1"},
        ])
        self.assertGreaterEqual(preview["summary"]["rows_without_serial"], 1)
        self.assertGreaterEqual(preview["summary"]["errors"], 1)
        self.assertIn("Лишняя", preview["unknown_columns"])
        self.assertTrue(preview["ambiguous_columns"])

    def test_existing_stock_and_other_delivery_are_document_only(self) -> None:
        self.add_stock("EXISTING-SN")
        before = self.counts()
        first = self.preview([{"S/N": "OTHER-DEL", "Номер поставки": "D-OLD", "Поставщик": "Supplier"}])
        first_id = self.confirm(first["preview_id"])
        preview = self.preview([
            {"S/N": "EXISTING-SN", "Номер поставки": "D-HIST", "Поставщик": "Supplier"},
            {"S/N": "OTHER-DEL", "Номер поставки": "D-HIST", "Поставщик": "Supplier"},
            {"S/N": "", "Номер поставки": "D-HIST", "Поставщик": "Supplier"},
        ])
        self.assertEqual(preview["summary"]["existing_stock"], 1)
        other = next(row for row in preview["rows"] if row["serial_number"] == "OTHER-DEL")
        self.assertIn("другой поставке", other["error_text"])
        after_preview = self.counts()
        self.assertEqual(after_preview["stock_receipts"], before["stock_receipts"])
        delivery_id = self.confirm(preview["preview_id"])
        self.assertGreater(delivery_id, first_id)
        after = self.counts()
        self.assertEqual(after["stock_receipts"], before["stock_receipts"])
        self.assertEqual(after["stock_issues"], before["stock_issues"])
        self.assertEqual(after["stock_issue_allocations"], before["stock_issue_allocations"])
        self.assertEqual(after["deliveries"], before["deliveries"] + 2)
        self.assertEqual(after["audit_log"], before["audit_log"] + 2)

    def test_repeat_confirm_viewer_denied_and_audit(self) -> None:
        with self.service.user_context("lokolis"):
            self.service.create_user("View", "Only", "Viewer", "viewer-del@test", "secret1", "viewer")
        with self.service.user_context("viewer-del@test"):
            with self.assertRaises(WarehouseError):
                self.facade.preview_delivery_import([{"S/N": "DENIED"}], "denied.csv")
        preview = self.preview([{"S/N": "ONCE-1", "Номер поставки": "D-ONCE", "Поставщик": "Supplier"}])
        delivery_id = self.confirm(preview["preview_id"])
        with self.assertRaises(WarehouseError):
            self.confirm(preview["preview_id"])
        card = self.facade.get_delivery(delivery_id)
        self.assertEqual(card["delivery"]["status"], "Ожидается")
        self.assertEqual(card["lines"][0]["receipt_id"], None)
        with connect(self.db_path) as db:
            action = db.execute("SELECT action FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()[0]
        self.assertEqual(action, "DELIVERY_UPLOAD")


if __name__ == "__main__":
    unittest.main()
