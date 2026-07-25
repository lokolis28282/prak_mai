from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from typing import Any

from inventory.core.application import create_application_context
from inventory.service import WarehouseError, WarehouseService


STATUSES = (
    "SUCCESS",
    "UNCHANGED",
    "NOT_FOUND",
    "ALREADY_ASSIGNED",
    "DUPLICATE_INVENTORY_NUMBER",
    "VALIDATION_ERROR",
)


class InventoryNumberImportContractTest(unittest.TestCase):
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

    @staticmethod
    def receipt(serial_number: str, inventory_number: str = "") -> dict[str, Any]:
        return {
            "receipt_date": "2026-07-13",
            "responsible": "Inventory Import Fixture",
            "category": "Оборудование",
            "item_type": "Сервер",
            "supplier": "Не указан",
            "vendor": "Dell",
            "model": "R760",
            "item_name": "Сервер Dell R760",
            "project": "Digital",
            "serial_number": serial_number,
            "inventory_number": inventory_number,
            "shelf": "A-01",
            "object_name": "Склад",
            "datacenter": "Ixcellerate",
            "unit": "шт",
            "quantity": 1,
        }

    def add_receipt(self, serial_number: str, inventory_number: str = "") -> int:
        with self.service.user_context("lokolis"):
            return self.facade.create_receipt(
                self.receipt(serial_number, inventory_number)
            )

    def preview(
        self, rows: list[dict[str, str]], filename: str = "inventory_numbers.csv"
    ) -> dict[str, Any]:
        with self.service.user_context(
            "lokolis", author_name="CSV Inventory Engineer"
        ):
            return self.facade.preview_inventory_number_import(rows, filename)

    def confirm(self, preview_id: str) -> dict[str, Any]:
        with self.service.user_context(
            "lokolis", author_name="CSV Inventory Engineer"
        ):
            return self.facade.confirm_inventory_number_import(preview_id)

    def count(self, table: str, where: str = "", params: tuple[Any, ...] = ()) -> int:
        with closing(sqlite3.connect(self.db_path)) as db:
            query = f"SELECT COUNT(*) FROM {table}"
            if where:
                query += f" WHERE {where}"
            return int(db.execute(query, params).fetchone()[0])

    def inventory_numbers(self) -> dict[str, str]:
        with closing(sqlite3.connect(self.db_path)) as db:
            return {
                str(serial): str(inventory or "")
                for serial, inventory in db.execute(
                    "SELECT serial_number, inventory_number FROM stock_receipts"
                )
            }

    @staticmethod
    def rows_by_serial(result: dict[str, Any]) -> dict[str, dict[str, Any]]:
        return {str(row["serial_number"]): row for row in result["rows"]}

    def test_preview_status_matrix_is_read_only_and_confirm_changes_only_success(self) -> None:
        success_id = self.add_receipt("CSV-SUCCESS")
        self.add_receipt("CSV-UNCHANGED", "INV-SAME")
        self.add_receipt("CSV-ASSIGNED", "INV-OLD")
        self.add_receipt("CSV-OWNER", "INV-TAKEN")
        self.add_receipt("CSV-DUPLICATE")
        source_rows = [
            {"serial_number": " csv-success ", "inventory_number": " inv-new "},
            {"serial_number": "csv-unchanged", "inventory_number": "inv-same"},
            {"serial_number": "CSV-MISSING", "inventory_number": "INV-MISSING"},
            {"serial_number": "CSV-ASSIGNED", "inventory_number": "INV-OTHER"},
            {"serial_number": "CSV-DUPLICATE", "inventory_number": "inv-taken"},
        ]
        before_receipts = self.count("stock_receipts")
        before_legacy_cards = self.count("equipment")
        before_values = self.inventory_numbers()
        before_events = self.count(
            "audit_log", "action = ?", ("EQUIPMENT_INVENTORY_NUMBER_ASSIGNED",)
        )

        preview = self.preview(source_rows)

        self.assertTrue(preview["can_confirm"])
        self.assertFalse(preview["errors"])
        self.assertEqual(preview["summary"]["total"], 5)
        for status in STATUSES:
            self.assertIn(status, preview["summary"])
        self.assertEqual(
            {status: preview["summary"][status] for status in STATUSES},
            {
                "SUCCESS": 1,
                "UNCHANGED": 1,
                "NOT_FOUND": 1,
                "ALREADY_ASSIGNED": 1,
                "DUPLICATE_INVENTORY_NUMBER": 1,
                "VALIDATION_ERROR": 0,
            },
        )
        preview_rows = self.rows_by_serial(preview)
        self.assertEqual(preview_rows["CSV-SUCCESS"]["status"], "SUCCESS")
        self.assertEqual(preview_rows["CSV-UNCHANGED"]["status"], "UNCHANGED")
        self.assertEqual(preview_rows["CSV-MISSING"]["status"], "NOT_FOUND")
        self.assertEqual(
            preview_rows["CSV-ASSIGNED"]["status"], "ALREADY_ASSIGNED"
        )
        self.assertEqual(
            preview_rows["CSV-DUPLICATE"]["status"],
            "DUPLICATE_INVENTORY_NUMBER",
        )
        self.assertEqual(self.count("stock_receipts"), before_receipts)
        self.assertEqual(self.inventory_numbers(), before_values)
        self.assertEqual(
            self.count(
                "audit_log",
                "action = ?",
                ("EQUIPMENT_INVENTORY_NUMBER_ASSIGNED",),
            ),
            before_events,
        )

        confirmed = self.confirm(preview["preview_id"])

        self.assertEqual(confirmed["changed_count"], 1)
        self.assertEqual(confirmed["summary"]["SUCCESS"], 1)
        self.assertEqual(self.count("stock_receipts"), before_receipts)
        self.assertEqual(self.count("equipment"), before_legacy_cards)
        values = self.inventory_numbers()
        self.assertEqual(values["CSV-SUCCESS"], "INV-NEW")
        self.assertEqual(values["CSV-UNCHANGED"], "INV-SAME")
        self.assertEqual(values["CSV-ASSIGNED"], "INV-OLD")
        self.assertEqual(values["CSV-OWNER"], "INV-TAKEN")
        self.assertEqual(values["CSV-DUPLICATE"], "")

        card = self.facade.get_position_card({"serial_number": "CSV-SUCCESS"})
        matching_events = [
            row
            for row in card["history"]
            if row["event_type"]
            == "Запись журнала: EQUIPMENT_INVENTORY_NUMBER_ASSIGNED"
        ]
        self.assertEqual(len(matching_events), 1)
        self.assertEqual(matching_events[0]["responsible"], "CSV Inventory Engineer")
        with closing(sqlite3.connect(self.db_path)) as db:
            audits = db.execute(
                """SELECT entity_id, author, details FROM audit_log
                   WHERE action = 'EQUIPMENT_INVENTORY_NUMBER_ASSIGNED'"""
            ).fetchall()
        self.assertEqual(len(audits), before_events + 1)
        entity_id, author, details = audits[-1]
        self.assertEqual(entity_id, str(success_id))
        self.assertEqual(author, "CSV Inventory Engineer")
        self.assertEqual(json.loads(details)["inventory_number"], "INV-NEW")

    def test_duplicate_serial_is_validation_error_and_blocks_confirm(self) -> None:
        self.add_receipt("CSV-DUPLICATE-SERIAL")
        before = self.inventory_numbers()
        preview = self.preview(
            [
                {
                    "serial_number": " CSV-DUPLICATE-SERIAL ",
                    "inventory_number": "INV-FIRST",
                },
                {
                    "serial_number": "csv-duplicate-serial",
                    "inventory_number": "INV-SECOND",
                },
            ]
        )

        self.assertFalse(preview["can_confirm"])
        self.assertTrue(preview["errors"])
        self.assertEqual(preview["summary"]["VALIDATION_ERROR"], 2)
        self.assertEqual(
            [row["status"] for row in preview["rows"]],
            ["VALIDATION_ERROR", "VALIDATION_ERROR"],
        )
        with self.assertRaises(WarehouseError):
            self.confirm(preview["preview_id"])
        self.assertEqual(self.inventory_numbers(), before)
        self.assertEqual(
            self.count(
                "audit_log",
                "action = ?",
                ("EQUIPMENT_INVENTORY_NUMBER_ASSIGNED",),
            ),
            0,
        )

    def test_same_free_inventory_number_inside_csv_is_a_non_mutating_conflict(self) -> None:
        self.add_receipt("CSV-INFILE-A")
        self.add_receipt("CSV-INFILE-B")
        preview = self.preview(
            [
                {
                    "serial_number": "CSV-INFILE-A",
                    "inventory_number": "INV-INFILE",
                },
                {
                    "serial_number": "CSV-INFILE-B",
                    "inventory_number": "inv-infile",
                },
            ]
        )

        self.assertTrue(preview["can_confirm"])
        self.assertEqual(preview["summary"]["DUPLICATE_INVENTORY_NUMBER"], 2)
        self.assertEqual(
            {row["status"] for row in preview["rows"]},
            {"DUPLICATE_INVENTORY_NUMBER"},
        )
        confirmed = self.confirm(preview["preview_id"])
        self.assertEqual(confirmed["changed_count"], 0)
        values = self.inventory_numbers()
        self.assertEqual(values["CSV-INFILE-A"], "")
        self.assertEqual(values["CSV-INFILE-B"], "")

    def test_matching_is_exclusively_by_serial_number_and_never_creates_card(self) -> None:
        self.add_receipt("CSV-LOOKUP-OWNER", "CSV-LOOKUP-BY-INVENTORY")
        before_receipts = self.count("stock_receipts")
        before_legacy_cards = self.count("equipment")
        preview = self.preview(
            [
                {
                    "serial_number": "CSV-LOOKUP-BY-INVENTORY",
                    "inventory_number": "INV-MUST-NOT-ASSIGN",
                }
            ]
        )

        self.assertEqual(preview["rows"][0]["status"], "NOT_FOUND")
        confirmed = self.confirm(preview["preview_id"])
        self.assertEqual(confirmed["changed_count"], 0)
        self.assertEqual(self.count("stock_receipts"), before_receipts)
        self.assertEqual(self.count("equipment"), before_legacy_cards)
        self.assertNotIn("CSV-LOOKUP-BY-INVENTORY", self.inventory_numbers())

    def test_repeat_import_is_unchanged_and_preview_token_is_one_shot(self) -> None:
        self.add_receipt("CSV-REPEAT")
        rows = [
            {"serial_number": "CSV-REPEAT", "inventory_number": "INV-REPEAT"}
        ]
        first = self.preview(rows)
        self.assertEqual(self.confirm(first["preview_id"])["changed_count"], 1)
        audit_count = self.count(
            "audit_log", "action = ?", ("EQUIPMENT_INVENTORY_NUMBER_ASSIGNED",)
        )

        repeated = self.preview(rows)
        self.assertEqual(repeated["rows"][0]["status"], "UNCHANGED")
        self.assertEqual(self.confirm(repeated["preview_id"])["changed_count"], 0)
        with self.assertRaises(WarehouseError):
            self.confirm(repeated["preview_id"])
        self.assertEqual(
            self.count(
                "audit_log",
                "action = ?",
                ("EQUIPMENT_INVENTORY_NUMBER_ASSIGNED",),
            ),
            audit_count,
        )

    def test_every_successful_row_creates_its_own_timeline_event(self) -> None:
        self.add_receipt("CSV-TIMELINE-A")
        self.add_receipt("CSV-TIMELINE-B")
        preview = self.preview(
            [
                {
                    "serial_number": "CSV-TIMELINE-A",
                    "inventory_number": "INV-TIMELINE-A",
                },
                {
                    "serial_number": "CSV-TIMELINE-B",
                    "inventory_number": "INV-TIMELINE-B",
                },
            ]
        )

        confirmed = self.confirm(preview["preview_id"])

        self.assertEqual(confirmed["changed_count"], 2)
        self.assertEqual(
            self.count(
                "audit_log",
                "action = ?",
                ("EQUIPMENT_INVENTORY_NUMBER_ASSIGNED",),
            ),
            2,
        )
        for serial in ("CSV-TIMELINE-A", "CSV-TIMELINE-B"):
            with self.subTest(serial=serial):
                card = self.facade.get_position_card({"serial_number": serial})
                self.assertEqual(
                    sum(
                        row["event_type"]
                        == "Запись журнала: EQUIPMENT_INVENTORY_NUMBER_ASSIGNED"
                        for row in card["history"]
                    ),
                    1,
                )

    def test_confirm_rolls_back_all_updates_and_audits_on_mid_batch_failure(self) -> None:
        self.add_receipt("CSV-ATOMIC-A")
        self.add_receipt("CSV-ATOMIC-B")
        preview = self.preview(
            [
                {
                    "serial_number": "CSV-ATOMIC-A",
                    "inventory_number": "INV-ATOMIC-A",
                },
                {
                    "serial_number": "CSV-ATOMIC-B",
                    "inventory_number": "INV-ATOMIC-B",
                },
            ]
        )
        self.assertEqual(preview["summary"]["SUCCESS"], 2)
        with closing(sqlite3.connect(self.db_path)) as db, db:
            db.execute(
                """CREATE TRIGGER inventory_number_import_atomic_failure
                   BEFORE UPDATE OF inventory_number ON stock_receipts
                   WHEN OLD.serial_number = 'CSV-ATOMIC-B'
                   BEGIN
                       SELECT RAISE(ABORT, 'forced inventory import failure');
                   END"""
            )

        with self.assertRaises((WarehouseError, sqlite3.DatabaseError)):
            self.confirm(preview["preview_id"])

        values = self.inventory_numbers()
        self.assertEqual(values["CSV-ATOMIC-A"], "")
        self.assertEqual(values["CSV-ATOMIC-B"], "")
        self.assertEqual(
            self.count(
                "audit_log",
                "action = ?",
                ("EQUIPMENT_INVENTORY_NUMBER_ASSIGNED",),
            ),
            0,
        )


if __name__ == "__main__":
    unittest.main()
