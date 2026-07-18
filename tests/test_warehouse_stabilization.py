from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from inventory.migration.staging_schema import create_staging_schema
from inventory.service import WarehouseError, WarehouseService


ROOT = Path(__file__).resolve().parents[1]


class CanonicalReferenceRuntimeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tempdir.name) / "warehouse.db"
        WarehouseService(self.db_path)
        with closing(sqlite3.connect(self.db_path)) as db, db:
            db.execute("PRAGMA foreign_keys=ON")
            create_staging_schema(db)
            stamp = "2026-07-14T00:00:00+03:00"
            domains = [
                (1, "vendor", "Вендоры"), (2, "model", "Модели"),
                (3, "datacenter", "ЦОД"), (4, "supplier", "Поставщики"),
                (5, "shelf", "Полки"),
            ]
            db.executemany(
                """INSERT INTO reference_domains_v2(
                       id,domain_key,display_name,description,active,source,created_at,updated_at
                   ) VALUES (?,?,?,'',1,'test',?,?)""",
                [(identifier, key, label, stamp, stamp) for identifier, key, label in domains],
            )
            values = [
                (1, 1, "Dell", "Dell", "dell", "", 1, "APPROVED"),
                (2, 1, "Huawei", "Huawei", "huawei", "", 1, "APPROVED"),
                (3, 1, "xFusion", "xFusion", "xfusion", "", 1, "APPROVED"),
                (4, 1, "Unknown", "Unknown", "unknown", "", 0, "REJECTED"),
                (5, 2, "PowerEdge R650", "PowerEdge R650", "poweredge r650", "dell", 1, "APPROVED"),
                (6, 2, "2288H", "2288H", "2288h", "xfusion", 1, "APPROVED"),
                (7, 2, "candidate", "candidate", "candidate", "huawei", 0, "CANDIDATE"),
                (8, 3, "Ixcellerate", "Ixcellerate", "ixcellerate", "", 1, "APPROVED"),
                (9, 4, "Не указан", "Не указан", "не указан", "", 1, "APPROVED"),
                (10, 4, "N/A", "N/A", "n/a", "", 0, "REJECTED"),
                (11, 5, "1-1", "1-1", "1-1", "", 1, "APPROVED"),
                (12, 5, "лорпач", "лорпач", "лорпач", "", 0, "REJECTED"),
                (13, 4, "ACME  SUPPLY", "ACME  SUPPLY", "acme supply", "", 1, "APPROVED"),
                (14, 4, "Acme Supply", "Acme Supply", "acme supply canonical", "", 1, "APPROVED"),
            ]
            db.executemany(
                """INSERT INTO reference_values_v2(
                       id,domain_id,canonical_value,display_name,normalized_key,scope_key,
                       active,approval_status,source,created_at,updated_at
                   ) VALUES (?,?,?,?,?,?,?,?, 'test',?,?)""",
                [(*value, stamp, stamp) for value in values],
            )
        self.service = WarehouseService(self.db_path, initialize_database=False)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_forms_receive_only_active_approved_canonical_values(self) -> None:
        self.assertEqual([row["name"] for row in self.service.references("datacenter", active_only=True)], ["Ixcellerate"])
        self.assertNotIn("Unknown", [row["name"] for row in self.service.references("vendor", active_only=True)])
        self.assertNotIn("N/A", [row["name"] for row in self.service.references("supplier", active_only=True)])
        self.assertNotIn("лорпач", [row["name"] for row in self.service.references("shelf", active_only=True)])

    def test_vendor_scoped_models_do_not_cross_vendor_boundary(self) -> None:
        self.assertEqual([row["name"] for row in self.service.reference_models("Dell")], ["PowerEdge R650"])
        self.assertEqual([row["name"] for row in self.service.reference_models("xFusion")], ["2288H"])
        self.assertEqual(self.service.reference_models("Huawei"), [])

    def test_reference_editor_requires_backend_admin_permission(self) -> None:
        with self.service.user_context("lokolis", role_override="engineer"):
            with self.assertRaises(WarehouseError):
                self.service.reference_editor_catalog()

    def test_used_value_is_deactivated_not_physically_deleted(self) -> None:
        self.service.set_reference_active(1, False)
        with closing(sqlite3.connect(self.db_path)) as db, db:
            self.assertEqual(db.execute("SELECT active FROM reference_values_v2 WHERE id=1").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM reference_values_v2 WHERE id=1").fetchone()[0], 1)

    def test_merge_preview_reports_impact_and_preserves_operational_raw_value(self) -> None:
        with closing(sqlite3.connect(self.db_path)) as db, db:
            db.execute(
                """INSERT INTO stock_receipts(
                       receipt_date,responsible,item_name,supplier,vendor,object_name,unit,quantity
                   ) VALUES ('2026-07-14','Тестовый инженер','Тестовая позиция',
                             'ACME  SUPPLY','Dell','Склад','шт',1)"""
            )
        preview = self.service.reference_service.merge_preview(13, 14)
        self.assertEqual(preview["usage"]["stock_receipts"], 1)
        self.assertEqual(preview["usage"]["operational_rows"], 1)
        self.assertTrue(preview["operational_values_preserved"])
        self.service.reference_service.merge(13, 14)
        with closing(sqlite3.connect(self.db_path)) as db, db:
            self.assertEqual(db.execute("SELECT supplier FROM stock_receipts").fetchone()[0], "ACME  SUPPLY")
            self.assertEqual(db.execute("SELECT active FROM reference_values_v2 WHERE id=13").fetchone()[0], 0)
            self.assertEqual(db.execute(
                "SELECT canonical_id FROM reference_aliases_v2 WHERE source_value='ACME  SUPPLY'"
            ).fetchone()[0], 14)
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM audit_log WHERE action='REFERENCE_MERGE' AND entity_id='13'"
            ).fetchone()[0], 1)

    def test_pending_alias_is_not_exposed_as_canonical_form_value(self) -> None:
        with closing(sqlite3.connect(self.db_path)) as db, db:
            db.execute(
                """INSERT INTO reference_aliases_v2(
                       domain_id,source_value,normalized_source_key,canonical_id,
                       source_file,source_sheet,usage_count,confidence,resolution_status,notes
                   ) VALUES (4,'Acme legal candidate','acme legal candidate',14,
                             'test','test',2,'MEDIUM','PENDING','needs legal review')"""
            )
        names = [row["name"] for row in self.service.references("supplier", active_only=True)]
        self.assertNotIn("Acme legal candidate", names)


class FrontendStabilizationContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.router = (ROOT / "static/js/router.js").read_text(encoding="utf-8")
        cls.ui = (ROOT / "static/js/ui.js").read_text(encoding="utf-8")
        cls.product = (ROOT / "static/js/product.js").read_text(encoding="utf-8")
        cls.editor = (ROOT / "static/js/administration/references.js").read_text(encoding="utf-8")

    def test_vendor_and_model_lists_are_reference_driven(self) -> None:
        self.assertNotIn("TYPE_VENDORS", self.ui)
        self.assertNotIn("WIZARD_MODELS", self.ui)
        self.assertIn("x.kind==='model'&&x.is_active", self.ui)
        self.assertIn("parent_key", self.ui)

    def test_compact_navigation_and_placeholders(self) -> None:
        self.assertNotIn("sectionNavItems", self.router)
        self.assertIn("nav.hidden=true", self.router)
        self.assertIn("Инструменты мониторинга", self.product)
        self.assertIn("window.openMonitoringManualSearch", self.product)
        self.assertIn("УВР и отчеты смены", self.ui)

    def test_reference_editor_has_controlled_workflows(self) -> None:
        for marker in (
            "REFERENCE_RENAME", "REFERENCE_MERGE_PREVIEW", "REFERENCE_MERGE",
            "TOGGLE_REFERENCE", "PROPOSE_REFERENCE", "Raw operational values",
        ):
            self.assertIn(marker, self.editor)

    def test_search_uses_abort_and_stale_response_protection(self) -> None:
        self.assertIn("new AbortController()", self.product)
        self.assertIn("searchController.abort()", self.product)
        self.assertIn("if(sequence!==searchSequence)return", self.product)


if __name__ == "__main__":
    unittest.main()
