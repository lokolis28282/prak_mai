from __future__ import annotations

import os
from pathlib import Path
import stat
import unittest


ROOT = Path(__file__).resolve().parent.parent


class MigrationPilotFrontendContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.pilot_js = (ROOT / "static/js/warehouse/migration_pilot.js").read_text(
            encoding="utf-8"
        )
        cls.product_js = (ROOT / "static/js/product.js").read_text(encoding="utf-8")
        cls.webapp = (ROOT / "inventory/webapp.py").read_text(encoding="utf-8")
        cls.css = (ROOT / "static/css/main.css").read_text(encoding="utf-8")

    def test_pilot_ui_uses_safe_dom_rendering_and_required_filters(self) -> None:
        self.assertIn("renderElement", self.pilot_js)
        self.assertIn("textContent", self.pilot_js)
        self.assertNotIn("innerHTML", self.pilot_js)
        self.assertNotIn("insertAdjacentHTML", self.pilot_js)
        self.assertNotIn("eval(", self.pilot_js)
        for value in ("IMPORT", "QUARANTINE", "CONFLICT", "CORRUPTED"):
            self.assertIn(value, self.pilot_js)
        self.assertIn("source_serial_value", self.pilot_js)
        self.assertIn("canonical_item_name", self.pilot_js)
        self.assertIn("source_item_name", self.pilot_js)
        self.assertIn("migration_warnings", self.pilot_js)
        self.assertIn("modal.parentNode===main", self.pilot_js)

    def test_equipment_card_uses_selection_id_and_safe_migration_section(self) -> None:
        self.assertIn("pilot_selection_id", self.product_js)
        self.assertIn("Migration provenance", self.product_js)
        self.assertIn("Original Item Name", self.product_js)
        self.assertIn("Canonical Item Name", self.product_js)
        self.assertIn("Preservation Status", self.product_js)
        for label in (
            "Object Kind",
            "Equipment Category",
            "Equipment Type",
            "Component Type",
            "Vendor",
            "Model",
            "Part Number",
            "Supplier",
            "Shelf (optional)",
        ):
            self.assertIn(label, self.product_js)
        self.assertIn("source_rows", self.product_js)
        self.assertIn("state.migration_pilot?.enabled", self.product_js)
        migration_block = self.product_js.split(
            "if(response.migration&&technicalContext){", 1
        )[1].split(
            "byId('positionDetails')", 1
        )[0]
        self.assertNotIn("innerHTML", migration_block)

    def test_web_routes_use_facade_and_deny_pilot_mutations(self) -> None:
        self.assertIn('path == "/api/migration-pilot"', self.webapp)
        self.assertIn("app_context.warehouse.list_migration_pilot_rows", self.webapp)
        self.assertIn("app_context.warehouse.get_migration_pilot_card", self.webapp)
        self.assertIn("migration_pilot_status.get(\"enabled\") and path != \"/api/logout\"", self.webapp)
        self.assertIn("validate_migration_pilot_database(args.db)", self.webapp)
        self.assertLess(
            self.webapp.index("validate_migration_pilot_database(args.db)"),
            self.webapp.index("app_context = create_application_context("),
        )
        self.assertIn(
            'initialize_database=not migration_pilot_status.get("enabled")',
            self.webapp,
        )
        self.assertIn(
            'and not migration_full_status.get("read_only")', self.webapp
        )
        self.assertIn("МИГРАЦИОННЫЙ ПИЛОТ", self.webapp)
        self.assertIn("migration-pilot-banner", self.css)
        self.assertIn(".migration-pilot-active .app{padding-top:34px}", self.css)

    def test_pilot_script_loads_before_product_shell(self) -> None:
        self.assertLess(
            self.webapp.index('"warehouse/migration_pilot.js"'),
            self.webapp.index('"product.js"'),
        )

    def test_launchers_never_build_or_select_production_database(self) -> None:
        launchers = [
            ROOT / "start_migration_pilot_macos.command",
            ROOT / "start_migration_pilot_windows.bat",
        ]
        for launcher in launchers:
            text = launcher.read_text(encoding="utf-8")
            self.assertIn("warehouse_pilot_candidate.db", text)
            self.assertIn("ODE_MIGRATION_PILOT", text)
            self.assertIn("validate_migration_pilot_database", text)
            self.assertIn("import inventory.core.application", text)
            self.assertNotIn("data/warehouse.db", text.replace("migration_inputs/workspace/", ""))
            self.assertNotIn("data\\warehouse.db", text)
            self.assertNotIn("--overwrite", text)
            self.assertNotIn("create_clean_test_db", text)
        if os.name == "posix":
            mode = stat.S_IMODE(launchers[0].stat().st_mode)
            self.assertTrue(mode & stat.S_IXUSR)


if __name__ == "__main__":
    unittest.main()
