from __future__ import annotations

import os
import hashlib
from pathlib import Path
import tempfile
import unittest
from zipfile import ZIP_DEFLATED, ZipFile

from inventory.warehouse.baseline.xlsx_parser import (
    FullInventoryXlsxError,
    inspect_workbook,
    template_bytes,
)
from inventory.warehouse.baseline.workspace import WorkspaceError
from tests.full_inventory_support import FullInventoryFixture


def rewrite_zip(path: Path, replacements: dict[str, tuple[str, str]]) -> None:
    temporary = path.with_suffix(".next.xlsx")
    with ZipFile(path) as source, ZipFile(temporary, "w", compression=ZIP_DEFLATED) as target:
        for info in source.infolist():
            payload = source.read(info.filename)
            if info.filename in replacements:
                old, new = replacements[info.filename]
                text = payload.decode("utf-8")
                if old not in text:
                    raise AssertionError(f"test token not found: {old}")
                payload = text.replace(old, new, 1).encode("utf-8")
            target.writestr(info, payload)
    os.replace(temporary, path)


class FullInventoryXlsxTest(FullInventoryFixture, unittest.TestCase):
    def setUp(self) -> None:
        self.create_fixture()

    def tearDown(self) -> None:
        self.cleanup_fixture()

    def test_downloadable_template_is_strict_ooxml_contract(self) -> None:
        path = self.root / "template.xlsx"
        path.write_bytes(template_bytes())
        workbook = inspect_workbook(path)
        self.assertEqual(workbook.sheets, ("Manifest", "Inventory"))
        self.assertEqual(workbook.manifest["TemplateId"].display_value, "ODE-FULL-INVENTORY")
        self.assertEqual(workbook.manifest["TemplateVersion"].display_value, "1.0")

    def test_inventory_rows_are_reiterable_stream_not_materialized_tuple(self) -> None:
        source = self.workbook(rows=[
            self.row(RowId="ROW-1", SerialNumber="STREAM-1"),
            self.row(RowId="ROW-2", SerialNumber="STREAM-2"),
        ])
        workbook = inspect_workbook(source)
        self.assertNotIsInstance(workbook.rows, tuple)
        first = [row.cells["SerialNumber"].display_value for row in workbook.rows]
        second = [row.cells["SerialNumber"].display_value for row in workbook.rows]
        self.assertEqual(first, ["STREAM-1", "STREAM-2"])
        self.assertEqual(second, first)

    def test_valid_preview_preserves_leading_zero_serial_and_reaches_ready_for_approval(self) -> None:
        session = self.create_session()
        source = self.workbook(rows=[self.row(SerialNumber="0000000123")])
        self.upload(session, source)
        summary = self.inventory.build_preview(
            session["public_id"], self.actor, correlation_id="corr_preview_01234567"
        )
        self.assertEqual(summary["session"]["session_status"], "READY_FOR_APPROVAL")
        rows = self.inventory.preview_rows(session["public_id"])["rows"]
        self.assertEqual(rows[0]["raw"]["SerialNumber"], "0000000123")
        self.assertEqual(rows[0]["normalized"]["serial_match_key"], "0000000123")

    def test_existing_source_vault_object_requires_exact_sha256(self) -> None:
        session = self.create_session()
        source = self.workbook()
        self.upload(session, source)
        _, internal = self.inventory._find_session(session["public_id"])
        vault_path = self.inventory._source_path(internal["source_opaque_key"])
        tampered = bytearray(vault_path.read_bytes())
        tampered[len(tampered) // 2] ^= 0x01
        vault_path.write_bytes(tampered)

        with self.assertRaisesRegex(WorkspaceError, "SHA-256 mismatch"):
            self.upload(session, source)

    def test_duplicate_inventory_number_blocks_and_references_first_row(self) -> None:
        session = self.create_session()
        source = self.workbook(rows=[
            self.row(RowId="ROW-1", SerialNumber="SN-1", InventoryNumber="INV-DUP"),
            self.row(RowId="ROW-2", SerialNumber="SN-2", InventoryNumber="INV-DUP"),
        ])
        self.upload(session, source)
        result = self.inventory.build_preview(
            session["public_id"], self.actor, correlation_id="corr_duplicate_inv_0001"
        )
        self.assertEqual(result["session"]["session_status"], "REVIEW_REQUIRED")
        rows = self.inventory.preview_rows(session["public_id"])["rows"]
        self.assertEqual([row["row_status"] for row in rows], ["VALID", "BLOCKED"])
        self.assertEqual(rows[1]["raw"]["InventoryNumber"], "INV-DUP")
        finding = next(
            item for item in self.inventory.preview_findings(session["public_id"])["findings"]
            if item["code"] == "DUPLICATE_INVENTORY_NUMBER"
        )
        self.assertTrue(finding["blocking"])
        self.assertEqual(finding["source_row_number"], 3)
        self.assertEqual(finding["evidence"], {
            "first_row_id": "ROW-1",
            "first_source_row_number": 2,
        })

    def test_duplicate_inventory_number_uses_exact_identity_normalization(self) -> None:
        session = self.create_session()
        first_raw = "  ＩＮＶ-００１  "
        source = self.workbook(rows=[
            self.row(RowId="ROW-1", SerialNumber="SN-1", InventoryNumber=first_raw),
            self.row(RowId="ROW-2", SerialNumber="SN-2", InventoryNumber="inv-001"),
        ])
        self.upload(session, source)
        self.inventory.build_preview(
            session["public_id"], self.actor, correlation_id="corr_duplicate_inv_0002"
        )
        rows = self.inventory.preview_rows(session["public_id"])["rows"]
        self.assertEqual(rows[0]["raw"]["InventoryNumber"], first_raw)
        self.assertEqual(
            rows[0]["normalized"]["inventory_number_match_key"],
            rows[1]["normalized"]["inventory_number_match_key"],
        )
        codes = {
            item["code"]
            for item in self.inventory.preview_findings(session["public_id"])["findings"]
        }
        self.assertIn("DUPLICATE_INVENTORY_NUMBER", codes)

    def test_distinct_and_empty_inventory_numbers_are_not_duplicates(self) -> None:
        session = self.create_session()
        source = self.workbook(rows=[
            self.row(RowId="ROW-1", SerialNumber="SN-1", InventoryNumber="INV-1"),
            self.row(RowId="ROW-2", SerialNumber="SN-2", InventoryNumber="INV-2"),
            self.row(RowId="ROW-3", SerialNumber="SN-3", InventoryNumber=""),
            self.row(RowId="ROW-4", SerialNumber="SN-4", InventoryNumber=""),
        ])
        self.upload(session, source)
        self.inventory.build_preview(
            session["public_id"], self.actor, correlation_id="corr_duplicate_inv_0003"
        )
        codes = {
            item["code"]
            for item in self.inventory.preview_findings(session["public_id"])["findings"]
        }
        self.assertNotIn("DUPLICATE_INVENTORY_NUMBER", codes)

    def test_duplicate_identity_finding_order_survives_repeated_preview(self) -> None:
        session = self.create_session()
        source = self.workbook(rows=[
            self.row(RowId="ROW-1", SerialNumber="SAME-SN", InventoryNumber="SAME-INV"),
            self.row(RowId="ROW-2", SerialNumber="same-sn", InventoryNumber="same-inv"),
        ])
        self.upload(session, source)

        def duplicate_codes() -> list[str]:
            return [
                item["code"]
                for item in self.inventory.preview_findings(session["public_id"])["findings"]
                if item["code"] in {
                    "DUPLICATE_SERIAL", "DUPLICATE_INVENTORY_NUMBER",
                }
            ]

        self.inventory.build_preview(
            session["public_id"], self.actor, correlation_id="corr_duplicate_inv_0004"
        )
        expected = ["DUPLICATE_SERIAL", "DUPLICATE_INVENTORY_NUMBER"]
        self.assertEqual(duplicate_codes(), expected)
        self.inventory.build_preview(
            session["public_id"], self.actor, correlation_id="corr_duplicate_inv_0005"
        )
        self.assertEqual(duplicate_codes(), expected)

    def test_catalog_model_similarity_is_explicitly_deferred_without_linking(self) -> None:
        self.legacy_service.add_stock_receipt(**{
            "receipt_date": "2026-07-15", "responsible": "Инженер",
            "item_name": "Сервер Dell R760", "project": "",
            "serial_number": "CATALOG-OLD", "inventory_number": "CATALOG-INV-OLD",
            "supplier": "Поставщик", "vendor": "Dell", "model": "R760",
            "shelf": "1-1", "object_name": "Склад", "datacenter": "Ixcellerate",
            "equipment_type": "Сервер", "component_type": "", "cable_type": "",
            "unit": "шт", "quantity": "1",
        })
        session = self.create_session()
        source = self.workbook(rows=[self.row(
            SerialNumber="CATALOG-NEW", InventoryNumber="CATALOG-INV-NEW",
            Vendor="Dell", Model="R760", Description="Сервер Dell R760",
        )])
        self.upload(session, source)
        summary = self.inventory.build_preview(
            session["public_id"], self.actor, correlation_id="corr_catalog_deferred_01"
        )
        self.assertEqual(summary["catalog_validation"], "DEFERRED")
        row = self.inventory.preview_rows(session["public_id"])["rows"][0]
        self.assertEqual(row["normalized"]["legacy_match_count"], 0)

    def test_numeric_and_formula_identity_cells_are_blocking(self) -> None:
        cases = {
            "numeric": (
                '<c r="E2" s="1" t="inlineStr"><is><t xml:space="preserve">0000012345</t></is></c>',
                '<c r="E2"><v>12345</v></c>',
                "IDENTIFIER_NOT_TEXT",
            ),
            "formula": (
                '<c r="E2" s="1" t="inlineStr"><is><t xml:space="preserve">0000012345</t></is></c>',
                '<c r="E2" t="str"><f>\"0000012345\"</f><v>0000012345</v></c>',
                "FORMULA_CELL",
            ),
        }
        for name, (old, new, code) in cases.items():
            with self.subTest(name=name):
                self.cleanup_fixture()
                self.create_fixture()
                session = self.create_session()
                source = self.workbook(filename=f"{name}.xlsx")
                rewrite_zip(source, {"xl/worksheets/sheet2.xml": (old, new)})
                self.upload(session, source)
                self.inventory.build_preview(
                    session["public_id"], self.actor, correlation_id=f"corr_{name}_012345678"
                )
                findings = self.inventory.preview_findings(session["public_id"])["findings"]
                self.assertIn(code, {finding["code"] for finding in findings})
                self.assertTrue(any(finding["blocking"] for finding in findings))

    def test_macro_external_payload_and_zip_traversal_are_rejected(self) -> None:
        source = self.workbook()
        with ZipFile(source, "a", compression=ZIP_DEFLATED) as archive:
            archive.writestr("xl/vbaProject.bin", b"macro")
        with self.assertRaisesRegex(FullInventoryXlsxError, "Макросы"):
            inspect_workbook(source)

        traversal = self.root / "traversal.xlsx"
        traversal.write_bytes(template_bytes())
        with ZipFile(traversal, "a", compression=ZIP_DEFLATED) as archive:
            archive.writestr("../escape.xml", b"<x/>")
        with self.assertRaisesRegex(FullInventoryXlsxError, "ZIP path"):
            inspect_workbook(traversal)

    def test_unknown_sheet_warns_and_hidden_row_blocks(self) -> None:
        session = self.create_session()
        source = self.workbook()
        rewrite_zip(source, {
            "xl/worksheets/sheet2.xml": ('<row r="2">', '<row r="2" hidden="1">')
        })
        self.upload(session, source)
        self.inventory.build_preview(
            session["public_id"], self.actor, correlation_id="corr_hidden_012345678"
        )
        codes = {
            finding["code"]
            for finding in self.inventory.preview_findings(session["public_id"])["findings"]
        }
        self.assertIn("HIDDEN_DATA_ROW", codes)

    def test_compatibility_mapping_accepts_only_approved_datacenter_and_shelf(self) -> None:
        before = hashlib.sha256(self.db_path.read_bytes()).hexdigest()
        accepted, normalized = self.inventory._mapping_findings(
            2, "Ixcellerate", "1-1"
        )
        self.assertFalse(accepted)
        self.assertEqual(normalized["warehouse_resolution"], "APPROVED_DATACENTER")
        self.assertEqual(normalized["location_resolution"], "APPROVED_SHELF")
        self.assertEqual(
            normalized["compatibility_mapping_version"],
            "COMPATIBILITY_V1_DATACENTER_SHELF",
        )

        unknown, preserved = self.inventory._mapping_findings(
            3, "Unknown DC", "Unknown Shelf"
        )
        self.assertEqual(preserved["warehouse_raw"], "Unknown DC")
        self.assertEqual(preserved["location_raw"], "Unknown Shelf")
        self.assertEqual(
            {finding.code for finding in unknown},
            {"UNKNOWN_WAREHOUSE", "UNKNOWN_LOCATION"},
        )
        candidate, _ = self.inventory._mapping_findings(
            4, "Ixcellerate", "Candidate A"
        )
        self.assertIn(
            "INACTIVE_OR_CANDIDATE_LOCATION",
            {finding.code for finding in candidate},
        )
        self.assertEqual(hashlib.sha256(self.db_path.read_bytes()).hexdigest(), before)

    def test_ambiguous_approved_shelf_alias_is_blocking(self) -> None:
        import sqlite3
        from contextlib import closing

        with closing(sqlite3.connect(self.db_path)) as db, db:
            db.execute(
                """INSERT INTO reference_values_v2 VALUES
                   (21,2,'2-2','2-2','2-2','',1,'APPROVED','test','2026','2026')"""
            )
            db.executemany(
                """INSERT INTO reference_aliases_v2(
                       id,domain_id,source_value,normalized_source_key,canonical_id,
                       source_file,source_sheet,usage_count,confidence,resolution_status
                   ) VALUES (?,?, 'AMB', 'amb', ?, 'test','test',1,'HIGH','APPROVED')""",
                ((1, 2, 20), (2, 2, 21)),
            )
        findings, normalized = self.inventory._mapping_findings(
            2, "Ixcellerate", "AMB"
        )
        self.assertEqual(normalized["location_resolution"], "AMBIGUOUS")
        self.assertIn("AMBIGUOUS_LOCATION", {finding.code for finding in findings})


if __name__ == "__main__":
    unittest.main()
