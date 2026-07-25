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


class WarehouseDataQualityFixTest(unittest.TestCase):
    """"Контроль качества данных": заполнение неполных строк и правка
    дублей S/N. Both operations are fill-empty / uniqueness-checked and
    write their own audit_log entry — see receipt_repository.fill_fields
    and receipt_repository.correct_duplicate_serial."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "warehouse.db"
        self.service = WarehouseService(self.db_path)
        self.context = create_application_context(
            self.db_path, service=self.service, warehouse_contour="demo"
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    @staticmethod
    def receipt(serial_number: str, **overrides: Any) -> dict[str, Any]:
        row: dict[str, Any] = {
            "receipt_date": "2026-07-18",
            "responsible": "Инженер Смены",
            "category": "Оборудование",
            "item_type": "Серверы",
            "supplier": "Не указан",
            "vendor": "",
            "model": "",
            "item_name": "Сервер ODE DQ",
            "project": "",
            "serial_number": serial_number,
            "inventory_number": "",
            "shelf": "",
            "object_name": "Не указано",
            "datacenter": "Ixcellerate",
            "unit": "шт",
            "quantity": 1,
        }
        row.update(overrides)
        return row

    def audit_rows(self, action: str) -> list[tuple[str, str]]:
        with closing(sqlite3.connect(self.db_path)) as db:
            return db.execute(
                "SELECT author, details FROM audit_log WHERE action = ?", (action,)
            ).fetchall()

    def blank_receipt_date(self, receipt_id: int) -> None:
        """Simulate a migrated historical row without a proven source date.
        The normal receipt validator requires a date, so an empty receipt_date
        only exists in migrated data and must be reproduced with raw SQL."""
        with closing(sqlite3.connect(self.db_path)) as db, db:
            db.execute(
                "UPDATE stock_receipts SET receipt_date = '' WHERE id = ?",
                (receipt_id,),
            )

    def attach_writeoff(self, receipt_id: int, serial_number: str) -> None:
        """Simulate a write-off allocation referencing a specific receipt, so
        the delete guard can be tested deterministically without FIFO ambiguity."""
        with closing(sqlite3.connect(self.db_path)) as db, db:
            cursor = db.execute(
                """INSERT INTO stock_issues
                       (issue_date, responsible, source_serial_number, quantity)
                   VALUES ('2026-07-18', 'Инженер Смены', ?, 1)""",
                (serial_number,),
            )
            db.execute(
                """INSERT INTO stock_issue_allocations (issue_id, receipt_id, quantity)
                   VALUES (?, ?, 1)""",
                (cursor.lastrowid, receipt_id),
            )

    def force_duplicate_serial(self, receipt_id: int, serial_number: str) -> None:
        """Simulate the legacy production shape: the promoted historical
        database intentionally has no hard UNIQUE constraint on
        serial_number (see CLAUDE.md "Production S/N uniqueness remains
        COLLATE NOCASE"), which is how real duplicate cards exist. A freshly
        seeded test database enforces the newer idx_stock_receipts_serial_unique
        index, so it must be dropped to reproduce that legacy state."""
        with closing(sqlite3.connect(self.db_path)) as db, db:
            db.execute("DROP INDEX IF EXISTS idx_stock_receipts_serial_unique")
            db.execute(
                "UPDATE stock_receipts SET serial_number = ? WHERE id = ?",
                (serial_number, receipt_id),
            )

    # -- fill_receipt_fields ------------------------------------------------

    def test_fill_receipt_fields_fills_empty_and_skips_filled(self) -> None:
        with self.service.user_context("lokolis", author_name="Инженер Смены"):
            receipt_id = self.context.warehouse.create_receipt(
                self.receipt("ODE-DQ-1", vendor="Dell")
            )
            result = self.context.warehouse.fill_receipt_fields(
                receipt_id,
                {"vendor": "HPE", "model": "R740", "shelf": "R1-S1", "project": "УВР"},
            )

        self.assertEqual(set(result["updated_fields"]), {"model", "shelf", "project"})
        self.assertIn("vendor", result["conflicts"])
        self.assertEqual(result["conflicts"]["vendor"], {"current": "Dell", "incoming": "HPE"})

        card = self.context.warehouse.get_position_card({"serial_number": "ODE-DQ-1"})
        position = card["position"]
        self.assertEqual(position["vendor"], "Dell")
        self.assertEqual(position["model"], "R740")
        self.assertEqual(position["shelf"], "R1-S1")
        self.assertEqual(position["project"], "УВР")

        audits = self.audit_rows("RECEIPT_FIELDS_FILLED")
        self.assertEqual(len(audits), 1)
        self.assertEqual(audits[0][0], "Инженер Смены")
        self.assertEqual(
            set(json.loads(audits[0][1])["updated_fields"]), {"model", "shelf", "project"}
        )

    def test_fill_receipt_fields_no_op_writes_no_audit(self) -> None:
        with self.service.user_context("lokolis"):
            receipt_id = self.context.warehouse.create_receipt(
                self.receipt("ODE-DQ-2", vendor="Dell", model="R640")
            )
            result = self.context.warehouse.fill_receipt_fields(
                receipt_id, {"vendor": "HPE", "model": "R740"}
            )
        self.assertEqual(result["updated_fields"], {})
        self.assertEqual(self.audit_rows("RECEIPT_FIELDS_FILLED"), [])

    def test_fill_receipt_fields_rejects_viewer_and_missing_card(self) -> None:
        with self.service.user_context("lokolis"):
            receipt_id = self.context.warehouse.create_receipt(self.receipt("ODE-DQ-3"))
            self.service.create_user(
                "View", "Only", "Viewer", "viewer-dq@test", "secret1", "viewer"
            )
            with self.assertRaisesRegex(WarehouseError, "не найдена"):
                self.context.warehouse.fill_receipt_fields(receipt_id + 999, {"vendor": "HPE"})
        with self.service.user_context("viewer-dq@test"):
            with self.assertRaisesRegex(WarehouseError, "Недостаточно прав"):
                self.context.warehouse.fill_receipt_fields(receipt_id, {"vendor": "HPE"})

    # -- fill_receipt_date ---------------------------------------------------

    def test_fill_receipt_date_fills_empty_validates_and_audits(self) -> None:
        with self.service.user_context("lokolis", author_name="Инженер Смены"):
            receipt_id = self.context.warehouse.create_receipt(
                self.receipt("ODE-DATE-1")
            )
            self.blank_receipt_date(receipt_id)
            # Некорректный формат отклоняется.
            with self.assertRaisesRegex(WarehouseError, "формате"):
                self.context.warehouse.fill_receipt_date(receipt_id, "18-07-2026")
            with self.assertRaisesRegex(WarehouseError, "пустой"):
                self.context.warehouse.fill_receipt_date(receipt_id, "   ")
            # Заполнение пустой даты (принимается и ДД.ММ.ГГГГ, нормализуется).
            result = self.context.warehouse.fill_receipt_date(receipt_id, "15.06.2026")

        self.assertTrue(result["updated"])
        self.assertEqual(result["receipt_date"], "2026-06-15")
        card = self.context.warehouse.get_position_card({"serial_number": "ODE-DATE-1"})
        self.assertEqual(card["position"]["receipt_date"], "2026-06-15")
        audits = self.audit_rows("RECEIPT_DATE_FILLED")
        self.assertEqual(len(audits), 1)
        self.assertEqual(audits[0][0], "Инженер Смены")
        self.assertTrue(json.loads(audits[0][1])["manual"])

    def test_fill_receipt_date_never_overwrites_proven_date(self) -> None:
        with self.service.user_context("lokolis"):
            receipt_id = self.context.warehouse.create_receipt(
                self.receipt("ODE-DATE-2", receipt_date="2026-06-01")
            )
            result = self.context.warehouse.fill_receipt_date(receipt_id, "2026-07-18")
        self.assertFalse(result["updated"])
        self.assertEqual(result["receipt_date"], "2026-06-01")
        self.assertEqual(self.audit_rows("RECEIPT_DATE_FILLED"), [])

    def test_fill_receipt_date_rejects_viewer(self) -> None:
        with self.service.user_context("lokolis"):
            receipt_id = self.context.warehouse.create_receipt(
                self.receipt("ODE-DATE-3")
            )
            self.blank_receipt_date(receipt_id)
            self.service.create_user(
                "View", "Date", "Viewer", "viewer-date@test", "secret1", "viewer"
            )
        with self.service.user_context("viewer-date@test"):
            with self.assertRaisesRegex(WarehouseError, "Недостаточно прав"):
                self.context.warehouse.fill_receipt_date(receipt_id, "2026-06-15")

    # -- correct_duplicate_serial --------------------------------------------

    def test_correct_duplicate_serial_renames_to_unique_value(self) -> None:
        with self.service.user_context("lokolis", author_name="Инженер Смены"):
            self.context.warehouse.create_receipt(self.receipt("ODE-DUP-1"))
            second_id = self.context.warehouse.create_receipt(
                self.receipt("ODE-DUP-1-TYPO")
            )
            self.force_duplicate_serial(second_id, "ODE-DUP-1")
            result = self.context.warehouse.correct_duplicate_serial(
                second_id, "ODE-DUP-1-FIXED"
            )

        self.assertEqual(result, {
            "receipt_id": second_id,
            "old_serial_number": "ODE-DUP-1",
            "new_serial_number": "ODE-DUP-1-FIXED",
        })
        card = self.context.warehouse.get_position_card({
            "serial_number": "ODE-DUP-1-FIXED"
        })
        self.assertEqual(card["position"]["serial_number"], "ODE-DUP-1-FIXED")

        audits = self.audit_rows("RECEIPT_SERIAL_CORRECTED")
        self.assertEqual(len(audits), 1)
        details = json.loads(audits[0][1])
        self.assertEqual(details["old_serial_number"], "ODE-DUP-1")
        self.assertEqual(details["new_serial_number"], "ODE-DUP-1-FIXED")

    def test_correct_duplicate_serial_rejects_collision_same_value_and_empty(self) -> None:
        with self.service.user_context("lokolis"):
            first_id = self.context.warehouse.create_receipt(self.receipt("ODE-DUP-2"))
            second_id = self.context.warehouse.create_receipt(self.receipt("ODE-DUP-2-B"))
            with self.assertRaisesRegex(WarehouseError, "уже используется"):
                self.context.warehouse.correct_duplicate_serial(second_id, "ODE-DUP-2")
            with self.assertRaisesRegex(WarehouseError, "совпадает с текущим"):
                self.context.warehouse.correct_duplicate_serial(second_id, "ODE-DUP-2-B")
            with self.assertRaisesRegex(WarehouseError, "не может быть пустым"):
                self.context.warehouse.correct_duplicate_serial(second_id, "   ")
            self.service.create_user(
                "View", "Only", "Viewer", "viewer-dup@test", "secret1", "viewer"
            )
        with self.service.user_context("viewer-dup@test"):
            with self.assertRaisesRegex(WarehouseError, "Недостаточно прав"):
                self.context.warehouse.correct_duplicate_serial(second_id, "ODE-DUP-2-FIXED")
        self.assertEqual(first_id and True, True)

    # -- delete_duplicate_receipt --------------------------------------------

    def test_delete_duplicate_receipt_removes_redundant_card_and_audits(self) -> None:
        with self.service.user_context("lokolis", author_name="Инженер Смены"):
            first_id = self.context.warehouse.create_receipt(self.receipt("ODE-DEL-1"))
            second_id = self.context.warehouse.create_receipt(
                self.receipt("ODE-DEL-1-TYPO")
            )
            self.force_duplicate_serial(second_id, "ODE-DEL-1")
            result = self.context.warehouse.delete_duplicate_receipt(second_id)

        self.assertTrue(result["deleted"])
        self.assertEqual(result["serial_number"], "ODE-DEL-1")
        with closing(sqlite3.connect(self.db_path)) as db:
            remaining = db.execute(
                "SELECT id FROM stock_receipts WHERE serial_number = 'ODE-DEL-1'"
            ).fetchall()
        self.assertEqual([row[0] for row in remaining], [first_id])
        audits = self.audit_rows("RECEIPT_DELETED")
        self.assertEqual(len(audits), 1)
        snapshot = json.loads(audits[0][1])
        self.assertEqual(snapshot["serial_number"], "ODE-DEL-1")
        self.assertEqual(snapshot["deleted_row"]["id"], second_id)

    def test_delete_duplicate_receipt_refuses_unique_card(self) -> None:
        with self.service.user_context("lokolis"):
            unique_id = self.context.warehouse.create_receipt(self.receipt("ODE-DEL-2"))
            with self.assertRaisesRegex(WarehouseError, "дублирующихся"):
                self.context.warehouse.delete_duplicate_receipt(unique_id)
        with closing(sqlite3.connect(self.db_path)) as db:
            self.assertEqual(
                db.execute(
                    "SELECT COUNT(*) FROM stock_receipts WHERE id = ?", (unique_id,)
                ).fetchone()[0],
                1,
            )

    def test_delete_duplicate_receipt_refuses_when_written_off(self) -> None:
        with self.service.user_context("lokolis"):
            self.context.warehouse.create_receipt(self.receipt("ODE-DEL-3"))
            second_id = self.context.warehouse.create_receipt(
                self.receipt("ODE-DEL-3-TYPO")
            )
            self.force_duplicate_serial(second_id, "ODE-DEL-3")
            # Списание (allocation) на карточку блокирует её удаление —
            # иначе потерялась бы история расхода.
            self.attach_writeoff(second_id, "ODE-DEL-3")
            with self.assertRaisesRegex(WarehouseError, "списания"):
                self.context.warehouse.delete_duplicate_receipt(second_id)
            self.service.create_user(
                "View", "Del", "Viewer", "viewer-del@test", "secret1", "viewer"
            )
        with self.service.user_context("viewer-del@test"):
            with self.assertRaisesRegex(WarehouseError, "Недостаточно прав"):
                self.context.warehouse.delete_duplicate_receipt(second_id)

    # -- data_quality_summary shape ------------------------------------------

    def test_duplicate_serial_rows_expose_full_card_detail(self) -> None:
        with self.service.user_context("lokolis"):
            first_id = self.context.warehouse.create_receipt(
                self.receipt("ODE-DUP-3", vendor="Dell", model="R740")
            )
            second_id = self.context.warehouse.create_receipt(
                self.receipt("ODE-DUP-3-B", vendor="Dell", model="R740")
            )
            self.force_duplicate_serial(second_id, "ODE-DUP-3")
        overview = self.context.warehouse.get_overview()
        rows = overview["problems"]["duplicate_serials"]
        matched = [row for row in rows if row["serial_number"] == "ODE-DUP-3"]
        self.assertEqual({row["id"] for row in matched}, {first_id, second_id})
        for row in matched:
            self.assertEqual(row["vendor"], "Dell")
            self.assertEqual(row["model"], "R740")
        self.assertGreaterEqual(overview["problem_counts"]["duplicate_serials"], 1)
        self.assertEqual(
            overview["stats"]["data_quality_review"],
            overview["problem_counts"]["duplicate_serials"]
            + overview["problem_counts"]["incomplete_rows"],
        )
        self.assertEqual(
            overview["stats"]["data_quality_blockers"],
            overview["problem_counts"]["unmatched_issues"]
            + overview["problem_counts"]["negative_balances"],
        )


if __name__ == "__main__":
    unittest.main()
