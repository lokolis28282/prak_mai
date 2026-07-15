from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from inventory.core.application import create_application_context
from inventory.service import WarehouseService
from inventory.shared.validators import WarehouseError
from inventory.warehouse.migration_pilot import (
    MIGRATION_CONFLICT_RECORDED,
    MIGRATION_EXACT_DUPLICATE_SKIPPED,
    MIGRATION_RECEIPT_IMPORTED,
    MIGRATION_SERIAL_QUARANTINED,
    MIGRATION_SOURCE_ROW_LINKED,
    MigrationPilotReceiptWriter,
    write_migration_conflict_recorded,
    write_migration_exact_duplicate_skipped,
    write_migration_serial_quarantined,
)
from inventory.warehouse.receipt_repository import ReceiptRepository


class MigrationPilotReceiptWriterTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temporary.name) / "warehouse_pilot_candidate.db"
        self.service = WarehouseService(self.db_path)
        self.context = create_application_context(
            self.db_path, service=self.service, warehouse_contour="demo"
        )
        self.connection = sqlite3.connect(self.db_path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.writer = MigrationPilotReceiptWriter(ReceiptRepository(self.db_path))
        self.source_row = 100

    def tearDown(self) -> None:
        self.connection.close()
        self.temporary.cleanup()

    def source(self, serial: object, **overrides: object) -> dict[str, object]:
        self.source_row += 1
        serial_text = serial if isinstance(serial, str) else ""
        row: dict[str, object] = {
            "source_file": "/private/migration-source/source.xlsx",
            "source_sheet": "ПРИХОД",
            "source_row": self.source_row,
            "source_row_hash": f"hash-{self.source_row}",
            "source_serial_value": serial,
            "normalized_match_value": serial_text.strip().casefold(),
            "serial_preservation_status": "TEXT_EXACT",
            "excel_cell_type": "inlineStr",
            "excel_number_format": "@",
            "raw_xml_value": serial_text,
            "canonical_item_name": "Сервер Dell PowerEdge R650",
            "source_item_name": "server Dell R650",
            "object_kind": "equipment",
            "category": "server equipment",
            "equipment_type": "Сервер",
            "component_type": "",
            "vendor": "Dell",
            "model": "PowerEdge R650",
            "part_number": "",
            "supplier": "Поставщик",
            "datacenter": "DC-1",
            "shelf": "A-01",
            "quantity": "1",
            "migration_warnings": [],
            "migration_batch_id": 1,
            "decision": "IMPORT",
            "receipt_date": "2024-03-15",
            "responsible": "Историческая миграция",
            "order_date": "",
            "request_number": "REQ-001",
            "order_number": "ORD-001",
            "plu": "0000123",
            "inventory_number": "",
            "project": "Pilot",
            "object_name": "Склад",
        }
        row.update(overrides)
        return row

    def count(self, table: str, where: str = "1=1") -> int:
        return int(
            self.connection.execute(
                f"SELECT COUNT(*) FROM {table} WHERE {where}"
            ).fetchone()[0]
        )

    def test_exact_serial_round_trip_for_preservation_variants(self) -> None:
        serials = (
            "00012345",
            "MiXeD-Case-01",
            "Серийный-Номер-01",
            "AB  CD  001",
            "ABC-001-XYZ",
            "0000000000000001",
            "2102313CKX10LC000033",
            " 001A020 ",
        )
        for serial in serials:
            with self.subTest(serial=serial):
                self.writer.write_receipt(
                    self.connection,
                    self.source(serial),
                    author="migration-pilot",
                )
        self.connection.commit()

        rows = self.connection.execute(
            """SELECT serial_number, typeof(serial_number) AS serial_type,
                      quantity, legacy_equipment_id, is_opening_balance
                 FROM stock_receipts ORDER BY id"""
        ).fetchall()
        self.assertEqual([row["serial_number"] for row in rows], list(serials))
        self.assertTrue(all(row["serial_type"] == "text" for row in rows))
        self.assertTrue(all(float(row["quantity"]) == 1 for row in rows))
        self.assertTrue(all(row["legacy_equipment_id"] is None for row in rows))
        self.assertTrue(all(row["is_opening_balance"] == 1 for row in rows))
        self.assertEqual(self.count("equipment"), 0)

    def test_numeric_unproven_corrupted_and_non_import_rows_are_rejected(self) -> None:
        invalid = (
            self.source(123456789),
            self.source(
                "1.23456789E+18",
                serial_preservation_status="NUMERIC_FORMAT_UNPROVEN",
            ),
            self.source(
                "4.225112538E15",
                serial_preservation_status="SOURCE_CORRUPTED",
                normalized_match_value="",
            ),
            self.source("QUARANTINE-01", decision="QUARANTINE"),
            self.source("NO-MATCH", normalized_match_value=""),
            self.source("QUANTITY-02", quantity="2"),
        )
        for source in invalid:
            with self.subTest(source=source):
                with self.assertRaises(WarehouseError):
                    self.writer.write_receipt(
                        self.connection, source, author="migration-pilot"
                    )
        self.assertEqual(self.count("stock_receipts"), 0)
        self.assertEqual(
            self.count(
                "audit_log",
                "action LIKE 'MIGRATION_%'",
            ),
            0,
        )

    def test_duplicate_serial_creates_one_card_and_shelf_is_not_identity(self) -> None:
        first_id = self.writer.write_receipt(
            self.connection,
            self.source("Shelf-MiXeD-0001", shelf="A-01"),
            author="migration-pilot",
        )
        with self.assertRaisesRegex(WarehouseError, "уже используется"):
            self.writer.write_receipt(
                self.connection,
                self.source(
                    "shelf-mixed-0001",
                    normalized_match_value="shelf-mixed-0001",
                    shelf="B-99",
                ),
                author="migration-pilot",
            )
        self.connection.commit()

        rows = self.connection.execute(
            "SELECT id, serial_number, shelf FROM stock_receipts"
        ).fetchall()
        self.assertEqual(
            [(row["id"], row["serial_number"], row["shelf"]) for row in rows],
            [(first_id, "Shelf-MiXeD-0001", "A-01")],
        )

    def test_models_and_vendors_remain_distinct(self) -> None:
        sources = (
            self.source(
                "VEGMAN-R200-01",
                canonical_item_name="Сервер Vegman R200",
                vendor="Vegman",
                model="R200",
            ),
            self.source(
                "VEGMAN-R220-01",
                canonical_item_name="Сервер Vegman R220",
                vendor="Vegman",
                model="R220",
            ),
            self.source(
                "HUAWEI-01",
                canonical_item_name="Коммутатор Huawei CE6865",
                vendor="Huawei",
                model="CE6865",
                equipment_type="Коммутатор",
            ),
            self.source(
                "XFUSION-01",
                canonical_item_name="Сервер xFusion 2288H V6",
                vendor="xFusion",
                model="2288H V6",
            ),
        )
        for source in sources:
            self.writer.write_receipt(
                self.connection, source, author="migration-pilot"
            )
        self.connection.commit()

        rows = self.connection.execute(
            "SELECT item_name, vendor, model FROM stock_receipts ORDER BY id"
        ).fetchall()
        self.assertEqual(
            [(row["item_name"], row["vendor"], row["model"]) for row in rows],
            [
                ("Сервер Vegman R200", "Vegman", "R200"),
                ("Сервер Vegman R220", "Vegman", "R220"),
                ("Коммутатор Huawei CE6865", "Huawei", "CE6865"),
                ("Сервер xFusion 2288H V6", "xFusion", "2288H V6"),
            ],
        )
        self.assertEqual(
            self.count(
                "reference_values",
                "kind='vendor' AND name IN ('Vegman','Huawei','xFusion')",
            ),
            0,
        )

    def test_audit_helpers_link_timeline_and_allowlist_details(self) -> None:
        source = self.source(
            "AUDIT-0001",
            source_item_name='server "></script><script>alert(1)</script>',
            migration_warnings=[
                "vendor requires review",
                "local evidence /private/migration-source/source.txt",
            ],
            password="must-not-enter-audit",
        )
        receipt_id = self.writer.write_receipt(
            self.connection, source, author="migration-pilot"
        )
        write_migration_conflict_recorded(
            self.connection,
            receipt_id=receipt_id,
            source=source,
            author="migration-pilot",
        )
        write_migration_exact_duplicate_skipped(
            self.connection,
            receipt_id=receipt_id,
            source=source,
            author="migration-pilot",
        )
        quarantined = self.source(
            "4.225112538E15",
            decision="SOURCE_CORRUPTED_REJECTED",
            serial_preservation_status="SOURCE_CORRUPTED",
            normalized_match_value="",
        )
        write_migration_serial_quarantined(
            self.connection,
            source=quarantined,
            author="migration-pilot",
            staging_row_id=77,
        )
        self.connection.commit()

        receipt_audits = self.connection.execute(
            """SELECT action, entity_type, entity_id, details
                 FROM audit_log WHERE action LIKE 'MIGRATION_%'
                 ORDER BY id"""
        ).fetchall()
        self.assertEqual(
            [row["action"] for row in receipt_audits],
            [
                MIGRATION_RECEIPT_IMPORTED,
                MIGRATION_SOURCE_ROW_LINKED,
                MIGRATION_CONFLICT_RECORDED,
                MIGRATION_EXACT_DUPLICATE_SKIPPED,
                MIGRATION_SERIAL_QUARANTINED,
            ],
        )
        for row in receipt_audits[1:4]:
            self.assertEqual(row["entity_type"], "stock_receipt")
            self.assertEqual(row["entity_id"], str(receipt_id))
            details = json.loads(row["details"])
            self.assertEqual(
                set(details),
                {
                    "source_file",
                    "source_sheet",
                    "source_row",
                    "source_item_name",
                    "canonical_item_name",
                    "warnings",
                },
            )
            self.assertEqual(details["source_file"], "source.xlsx")
            self.assertNotIn("/private/", row["details"])
            self.assertNotIn("password", details)
            self.assertEqual(
                details["source_item_name"],
                'server "></script><script>alert(1)</script>',
            )
        self.assertEqual(receipt_audits[-1]["entity_type"], "migration_staging_row")
        self.assertEqual(receipt_audits[-1]["entity_id"], "77")

        card = self.service.position_card(serial_number="AUDIT-0001")
        event_types = {event["event_type"] for event in card["history"]}
        self.assertIn(
            f"Запись журнала: {MIGRATION_RECEIPT_IMPORTED}", event_types
        )
        self.assertIn(
            f"Запись журнала: {MIGRATION_SOURCE_ROW_LINKED}", event_types
        )
        report_events = self.context.reports.warehouse_events.list_events(
            "2024-03-15", "2024-03-15"
        )
        self.assertFalse(any(event.serial_number == "AUDIT-0001" for event in report_events))

    def test_caller_owned_transaction_can_roll_back_receipt_and_audits(self) -> None:
        before_receipts = self.count("stock_receipts")
        before_audits = self.count("audit_log")
        self.connection.commit()
        self.connection.execute("BEGIN")
        self.writer.write_receipt(
            self.connection,
            self.source("ROLLBACK-0001"),
            author="migration-pilot",
        )
        self.assertTrue(self.connection.in_transaction)
        self.connection.rollback()

        self.assertEqual(self.count("stock_receipts"), before_receipts)
        self.assertEqual(self.count("audit_log"), before_audits)


if __name__ == "__main__":
    unittest.main()
