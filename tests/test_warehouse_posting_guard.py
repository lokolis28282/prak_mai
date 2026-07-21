from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

from inventory.core.application import create_application_context
from inventory.service import WarehouseService
from inventory.warehouse.baseline.posting_policy import (
    PostingPolicy,
    WarehousePostingBlocked,
)


class WarehousePostingGuardTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.production = self.root / "production.db"
        self.demo = self.root / "demo.db"
        WarehouseService(self.production)
        WarehouseService(self.demo)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_production_is_writable_and_unknown_modes_fail_closed(self) -> None:
        production = PostingPolicy(
            self.production, mode="production", production_db_path=self.production
        )
        production.assert_mutation_allowed("receipt")
        self.assertTrue(production.status()["posting_allowed"])
        self.assertTrue(production.status()["provisional_balance"])
        for mode in ("unknown", ""):
            with self.subTest(mode=mode):
                policy = PostingPolicy(
                    self.production, mode=mode, production_db_path=self.production
                )
                with self.assertRaisesRegex(WarehousePostingBlocked, "WAREHOUSE_NOT_INITIALIZED"):
                    policy.assert_mutation_allowed("receipt")

    def test_demo_requires_distinct_file_and_rejects_hardlink(self) -> None:
        allowed = PostingPolicy(
            self.demo, mode="demo", production_db_path=self.production
        )
        allowed.assert_mutation_allowed("scanner")
        hardlink = self.root / "hardlink.db"
        os.link(self.production, hardlink)
        blocked = PostingPolicy(
            hardlink, mode="demo", production_db_path=self.production
        )
        with self.assertRaises(WarehousePostingBlocked):
            blocked.assert_mutation_allowed("scanner")

    def test_facade_allows_production_and_explicit_demo(self) -> None:
        production_service = WarehouseService(self.production)
        production_context = create_application_context(
            self.production, service=production_service, warehouse_contour="production"
        )
        production_context.warehouse.assert_posting_allowed("receipt")
        self.assertTrue(production_context.warehouse.get_system_status()["posting_allowed"])
        receipt_id = production_context.warehouse.create_receipt({
            "receipt_date": "2026-07-18",
            "responsible": "Production contour test",
            "item_name": "Test server",
            "serial_number": "PRODUCTION-CONTOUR-1",
            "supplier": "Не указан",
            "vendor": "Не указан",
            "object_name": "Test warehouse",
            "datacenter": "Ixcellerate",
            "equipment_type": "Сервер",
            "unit": "шт",
            "quantity": 1,
        })
        self.assertGreater(receipt_id, 0)
        demo_service = WarehouseService(self.demo)
        demo_context = create_application_context(
            self.demo, service=demo_service, warehouse_contour="demo"
        )
        self.assertTrue(demo_context.warehouse.get_system_status()["contour"]["demo"])


if __name__ == "__main__":
    unittest.main()
