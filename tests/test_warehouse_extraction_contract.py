from __future__ import annotations

import ast
import inspect
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from inventory.core.application import create_application_context
from inventory.service import WarehouseService
from inventory.services.warehouse_service import WarehouseCore
from inventory.warehouse.balance import WarehouseBalanceService
from inventory.warehouse.history import WarehouseHistoryService
from inventory.warehouse.inventory import LegacyInventoryService
from inventory.warehouse.monitoring import WarehouseMonitoringService
from inventory.warehouse.reference_service import WarehouseReferenceService
from inventory.warehouse.service import WarehouseDomainService


class WarehouseExtractionContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "warehouse.db"
        self.compat = WarehouseService(self.db_path)
        self.context = create_application_context(
            self.db_path,
            service=self.compat,
            warehouse_contour="demo",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def receipt(self, serial: str) -> dict[str, object]:
        return {
            "receipt_date": "2026-07-25",
            "responsible": "Warehouse extraction",
            "item_name": "Сервер",
            "serial_number": serial,
            "inventory_number": "",
            "supplier": "Не указан",
            "vendor": "Dell",
            "model": "R760",
            "project": "",
            "shelf": "A-01",
            "object_name": "Склад",
            "datacenter": "Ixcellerate",
            "equipment_type": "Сервер",
            "component_type": "",
            "cable_type": "",
            "unit": "шт",
            "quantity": 1,
        }

    def test_core_and_domain_root_contain_no_business_sql(self) -> None:
        core_source = inspect.getsource(WarehouseCore)
        domain_source = inspect.getsource(WarehouseDomainService)
        for source in (core_source, domain_source):
            self.assertNotIn("SELECT ", source)
            self.assertNotIn("INSERT ", source)
            self.assertNotIn("UPDATE ", source)
            self.assertNotIn("DELETE ", source)
            self.assertNotIn("connect(", source)

        tree = ast.parse(domain_source)
        methods = {
            node.name
            for node in tree.body[0].body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        self.assertEqual(
            methods,
            {
                "__init__",
                "__getattr__",
                "_require_role",
                "current_user",
                "_require_write",
                "_audit",
            },
        )

    def test_remaining_warehouse_logic_is_composed_by_domain(self) -> None:
        domain = self.compat._core._warehouse
        self.assertIsInstance(domain._history, WarehouseHistoryService)
        self.assertIsInstance(domain._inventory, LegacyInventoryService)
        self.assertIsInstance(domain._balance, WarehouseBalanceService)
        self.assertIsInstance(domain._monitoring, WarehouseMonitoringService)
        self.assertIsInstance(domain._references, WarehouseReferenceService)
        self.assertIs(self.compat.history_service, domain._history)
        self.assertIs(self.compat.inventory_service, domain._inventory)
        self.assertIs(self.compat.balance_service, domain._balance)
        self.assertIs(self.compat.monitoring_service, domain._monitoring)
        self.assertIs(self.compat.reference_service, domain._references)

    def test_facade_reuses_compatibility_write_services(self) -> None:
        facade = self.context.warehouse
        self.assertIs(
            facade.receipt_writer, self.compat.receipt_service.writer
        )
        self.assertIs(facade.cables, self.compat.receipt_service.cables)
        self.assertIs(facade.issue_writer, self.compat.issue_service.writer)
        self.assertIs(
            facade.delivery_importer, self.compat.delivery_service.importer
        )
        self.assertIs(
            facade.delivery_reader, self.compat.delivery_service.reader
        )
        self.assertIs(
            facade.delivery_acceptance,
            self.compat.delivery_service.acceptance,
        )

    def test_old_and_new_receipt_names_use_one_implementation(self) -> None:
        writer = self.compat.receipt_service.writer
        original = writer.create_receipt
        with (
            patch.object(writer, "create_receipt", wraps=original) as create,
            self.context.administration.user_context("lokolis"),
        ):
            self.compat.add_stock_receipt(**self.receipt("ODE-016-COMPAT"))
            self.context.warehouse.create_receipt(
                self.receipt("ODE-016-FACADE")
            )
        self.assertEqual(create.call_count, 2)

    def test_removed_core_workflows_have_no_second_implementation(self) -> None:
        removed = {
            "preview_stock_receipt_rows",
            "confirm_stock_receipt_preview",
            "add_stock_receipt",
            "import_stock_receipt_rows",
            "preview_stock_issue_rows",
            "confirm_stock_issue_preview",
            "add_stock_issue",
            "import_stock_issue_rows",
            "preview_delivery_rows",
            "confirm_delivery_preview",
            "accept_delivery_serial",
            "close_delivery",
            "stock_balance",
            "global_search",
            "data_quality_problems",
        }
        for name in removed:
            with self.subTest(method=name):
                self.assertNotIn(name, vars(WarehouseCore))
                self.assertNotIn(name, vars(WarehouseDomainService))


if __name__ == "__main__":
    unittest.main()
