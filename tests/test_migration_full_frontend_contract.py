from __future__ import annotations

import os
from pathlib import Path
import stat
import unittest


ROOT = Path(__file__).resolve().parent.parent


class FullMigrationFrontendContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.review_js = (ROOT / "static/js/warehouse/migration_pilot.js").read_text(
            encoding="utf-8"
        )
        cls.product_js = (ROOT / "static/js/product.js").read_text(encoding="utf-8")
        cls.webapp = (ROOT / "inventory/webapp.py").read_text(encoding="utf-8")
        cls.full_review = (
            ROOT / "inventory/warehouse/migration_full_review.py"
        ).read_text(encoding="utf-8")
        cls.css = (ROOT / "static/css/main.css").read_text(encoding="utf-8")

    def test_full_review_filters_counts_decimal_and_safe_dom(self) -> None:
        for value in (
            "TEXT_EXACT", "NUMERIC_PROVISIONAL", "SOURCE_CORRUPTED", "CONFLICT",
            "OPENING_STATE", "UNRESOLVED_ISSUE", "QUARANTINE", "EQUIPMENT",
            "COMPONENT", "VENDOR", "MODEL",
        ):
            self.assertIn(value, self.review_js)
        for value in (
            "source_rows", "imported_cards", "imported_receipts", "imported_issues",
            "provisional_numeric", "source_corrupted", "exact_duplicates", "conflicts",
            "opening_states", "unresolved_issues", "deferred_quantity",
        ):
            self.assertIn(value, self.review_js)
        self.assertIn("raw_xml_value", self.review_js)
        self.assertIn("Возможна утрата ведущих нулей", self.review_js)
        self.assertIn("full_reconciliation_id", self.review_js)
        self.assertNotIn("innerHTML", self.review_js)
        self.assertNotIn("insertAdjacentHTML", self.review_js)

    def test_full_card_and_backend_read_only_contract(self) -> None:
        self.assertIn("full_reconciliation_id", self.product_js)
        self.assertIn("Historical Source Date", self.product_js)
        self.assertIn("Raw XML Token", self.product_js)
        self.assertIn("Opening State Explanation", self.product_js)
        self.assertIn("Target S/N relationships", self.product_js)
        self.assertIn("state.migration_full?.read_only", self.product_js)
        self.assertIn('path == "/api/migration-full"', self.webapp)
        self.assertIn("get_migration_full_card", self.webapp)
        self.assertIn("validate_full_migration_database(args.db)", self.webapp)
        self.assertIn("full_migration_requested()", self.webapp)
        self.assertIn("ПОЛНАЯ КАНДИДАТНАЯ БАЗА СКЛАДА", self.webapp)
        self.assertIn("migration-full-banner", self.css)

    def test_promoted_working_database_keeps_review_diagnostic_only(self) -> None:
        self.assertIn('"working_database": not requested', self.full_review)
        self.assertIn('migration_full_status.get("read_only")', self.webapp)
        self.assertIn('"full_reconciliation_id" in query', self.webapp)
        self.assertIn("if(!reviewStatus()?.read_only", self.review_js)

    def test_full_launchers_are_marker_guarded_and_never_build(self) -> None:
        launchers = [
            ROOT / "start_full_migration_candidate_macos.command",
            ROOT / "start_full_migration_candidate_windows.bat",
        ]
        for launcher in launchers:
            text = launcher.read_text(encoding="utf-8")
            self.assertIn("warehouse_full_candidate.db", text)
            self.assertIn("ODE_FULL_MIGRATION_CANDIDATE", text)
            self.assertIn("validate_full_migration_database", text)
            self.assertIn("FULL_WAREHOUSE_CANDIDATE", text)
            self.assertIn("ПОЛНАЯ КАНДИДАТНАЯ БАЗА СКЛАДА", text)
            self.assertIn("Ctrl+C", text)
            self.assertNotIn("--overwrite", text)
            self.assertNotIn("migration_full_candidate.py", text)
            self.assertNotIn("data/warehouse.db", text)
            self.assertNotIn("data\\warehouse.db", text)
        if os.name == "posix":
            self.assertEqual(
                stat.S_IMODE(launchers[0].stat().st_mode) & stat.S_IXUSR,
                stat.S_IXUSR,
            )


if __name__ == "__main__":
    unittest.main()
