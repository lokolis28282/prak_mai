from __future__ import annotations

import ast
import inspect
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from inventory.administration.service import AdministrationService
from inventory.core.application import create_application_context
from inventory.service import WarehouseService
from inventory.services.warehouse_service import WarehouseCore
from inventory.webapp import make_handler


class AdministrationExtractionContractTest(unittest.TestCase):
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

    def test_application_context_uses_dedicated_administration_service(self) -> None:
        administration = self.context.administration.service
        self.assertIsInstance(administration, AdministrationService)
        self.assertIs(administration, self.compat.administration_service)
        self.assertIs(administration, self.compat._core.administration)
        self.assertIsNot(administration, self.compat)
        self.assertIsNot(administration, self.compat._core)

    def test_facade_actions_do_not_call_warehouse_core_compatibility_methods(
        self,
    ) -> None:
        with (
            patch.object(
                WarehouseCore,
                "create_user",
                side_effect=AssertionError("legacy create_user was called"),
            ),
            patch.object(
                WarehouseCore,
                "check_integrity",
                side_effect=AssertionError("legacy check_integrity was called"),
            ),
            self.context.administration.user_context(
                "lokolis", author_name="Administration contract"
            ),
        ):
            user_id = self.context.administration.create_user(
                "Admin",
                "Boundary",
                "Engineer",
                "admin-boundary@example.test",
                "secret1",
                "engineer",
            )
            integrity = self.context.administration.check_integrity()

        self.assertGreater(user_id, 0)
        self.assertTrue(integrity["ok"])

    def test_legacy_service_shares_administration_actor_context(self) -> None:
        with self.context.administration.user_context(
            "lokolis",
            author_name="Shared Administration Actor",
            role_override="engineer",
        ):
            self.assertEqual(self.compat.current_user()["role"], "engineer")
            self.compat.add_category("Actor context category")
            self.compat.add_location("ACT-01", "Actor context location")
            equipment_id = self.compat.add_equipment(
                "Actor context category",
                "Actor context model",
                "ACTOR-CONTEXT-SN",
                "ACTOR-CONTEXT-INV",
                "ACT-01",
            )
        with self.context.administration.user_context("lokolis"):
            entries = self.context.administration.list_audit_entries(limit=20)
        equipment_audit = next(
            row
            for row in entries
            if row["action"] == "CREATE"
            and row["entity_id"] == str(equipment_id)
        )
        self.assertEqual(equipment_audit["author"], "Shared Administration Actor")

    def test_webapp_routes_administration_calls_through_context(self) -> None:
        source = inspect.getsource(make_handler)
        forbidden = (
            "service.authenticate(",
            "service.user_by_email(",
            "service.current_user(",
            "service.user_context(",
            "service.create_user(",
            "service.change_password(",
            "service.update_profile(",
            "service.create_backup(",
            "service.check_integrity(",
            "service.restore_backup(",
            "service.replace_production_database(",
        )
        for call in forbidden:
            with self.subTest(call=call):
                self.assertNotIn(call, source)

    def test_warehouse_core_administration_methods_are_thin_delegates(self) -> None:
        method_names = {
            "authenticate",
            "user_by_email",
            "current_user",
            "user_context",
            "_require_role",
            "_require_write",
            "users",
            "create_user",
            "change_password",
            "update_profile",
            "_audit",
            "audit_entries",
            "list_backups",
            "check_integrity",
            "create_backup",
            "restore_backup",
            "replace_production_database",
        }
        tree = ast.parse(inspect.getsource(WarehouseCore))
        methods = {
            node.name: node
            for node in tree.body[0].body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        for name in method_names:
            with self.subTest(method=name):
                method = methods[name]
                statements = [
                    item
                    for item in method.body
                    if not (
                        isinstance(item, ast.Expr)
                        and isinstance(item.value, ast.Constant)
                        and isinstance(item.value.value, str)
                    )
                ]
                self.assertLessEqual(len(statements), 2)
                self.assertIn("DEPRECATED", inspect.getsource(getattr(WarehouseCore, name)))


if __name__ == "__main__":
    unittest.main()
