from __future__ import annotations

import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from typing import Any

from inventory.core.application import create_application_context
from inventory.service import WarehouseError, WarehouseService
from inventory.webapp import make_handler


class EquipmentCardInventoryWorkflowTest(unittest.TestCase):
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
    def receipt(serial_number: str, inventory_number: str = "") -> dict[str, Any]:
        return {
            "receipt_date": "2026-07-13",
            "responsible": "Инженер Карточки",
            "category": "Оборудование",
            "item_type": "Серверы",
            "supplier": "Не указан",
            "vendor": "Не указан",
            "model": "ODE-013",
            "item_name": "Сервер ODE 0.13",
            "project": "",
            "serial_number": serial_number,
            "inventory_number": inventory_number,
            "shelf": "",
            "object_name": "Не указано",
            "datacenter": "Ixcellerate",
            "unit": "шт",
            "quantity": 1,
        }

    def count(self, table: str) -> int:
        with closing(sqlite3.connect(self.db_path)) as db:
            return int(db.execute(f"SELECT count(*) FROM {table}").fetchone()[0])

    def test_assignment_updates_same_card_once_and_enters_timeline(self) -> None:
        with self.service.user_context("lokolis", author_name="Инженер Карточки"):
            receipt_id = self.context.warehouse.create_receipt(self.receipt("ode-013-card-1"))
            before = self.count("stock_receipts")
            assigned = self.context.warehouse.assign_inventory_number(
                " ode-013-card-1 ", " inv-ode-013-1 "
            )
            repeated = self.context.warehouse.assign_inventory_number(
                "ODE-013-CARD-1", "INV-ODE-013-1"
            )

        self.assertEqual(assigned, {
            "receipt_id": receipt_id,
            "serial_number": "ODE-013-CARD-1",
            "inventory_number": "INV-ODE-013-1",
            "updated": True,
        })
        self.assertFalse(repeated["updated"])
        self.assertEqual(self.count("stock_receipts"), before)

        card = self.context.warehouse.get_position_card({
            "serial_number": "ODE-013-CARD-1"
        })
        self.assertEqual(card["position"]["inventory_number"], "INV-ODE-013-1")
        self.assertTrue(any(
            row["event_type"]
            == "Запись журнала: EQUIPMENT_INVENTORY_NUMBER_ASSIGNED"
            for row in card["history"]
        ))
        with closing(sqlite3.connect(self.db_path)) as db:
            audits = db.execute(
                """SELECT author, details FROM audit_log
                   WHERE action = 'EQUIPMENT_INVENTORY_NUMBER_ASSIGNED'"""
            ).fetchall()
            plan = " ".join(
                str(row[3]) for row in db.execute(
                    """EXPLAIN QUERY PLAN
                       SELECT id, serial_number, inventory_number, legacy_equipment_id
                       FROM stock_receipts
                       WHERE trim(serial_number) <> ''
                         AND serial_number = ? COLLATE NOCASE""",
                    ("ODE-013-CARD-1",),
                )
            )
        self.assertEqual(len(audits), 1)
        self.assertEqual(audits[0][0], "Инженер Карточки")
        self.assertEqual(json.loads(audits[0][1])["inventory_number"], "INV-ODE-013-1")
        self.assertIn("idx_stock_receipts_serial_unique", plan)

    def test_assignment_rejects_overwrite_duplicates_missing_and_viewer(self) -> None:
        with self.service.user_context("lokolis"):
            self.context.warehouse.create_receipt(self.receipt("ODE-013-EMPTY"))
            self.context.warehouse.create_receipt(
                self.receipt("ODE-013-FILLED", "INV-ODE-013-USED")
            )
            self.service.create_user(
                "View", "Only", "Viewer", "viewer-card@test", "secret1", "viewer"
            )
            with self.assertRaisesRegex(WarehouseError, "уже используется"):
                self.context.warehouse.assign_inventory_number(
                    "ODE-013-EMPTY", "INV-ODE-013-USED"
                )
            with self.assertRaisesRegex(WarehouseError, "уже указан"):
                self.context.warehouse.assign_inventory_number(
                    "ODE-013-FILLED", "INV-ODE-013-OTHER"
                )
            with self.assertRaisesRegex(WarehouseError, "не найдена"):
                self.context.warehouse.assign_inventory_number(
                    "ODE-013-MISSING", "INV-MISSING"
                )
            with self.assertRaisesRegex(WarehouseError, "255"):
                self.context.warehouse.assign_inventory_number(
                    "ODE-013-EMPTY", "X" * 256
                )
        with self.service.user_context("viewer-card@test"):
            with self.assertRaisesRegex(WarehouseError, "Недостаточно прав"):
                self.context.warehouse.assign_inventory_number(
                    "ODE-013-EMPTY", "INV-VIEWER"
                )

        empty_card = self.context.warehouse.get_position_card({
            "serial_number": "ODE-013-EMPTY"
        })
        self.assertEqual(empty_card["position"]["inventory_number"], "")
        self.assertEqual(self.count("stock_receipts"), 2)

    def test_assignment_synchronizes_linked_legacy_card(self) -> None:
        with self.service.user_context("lokolis"):
            receipt_id = self.context.warehouse.create_receipt(
                self.receipt("ODE-013-LEGACY")
            )
        with closing(sqlite3.connect(self.db_path)) as db, db:
            db.execute(
                "INSERT OR IGNORE INTO categories(name, description) VALUES ('Legacy 0.13', '')"
            )
            db.execute(
                "INSERT OR IGNORE INTO locations(code, name, description) VALUES ('L-013', 'Legacy', '')"
            )
            category_id = int(db.execute(
                "SELECT id FROM categories WHERE name = 'Legacy 0.13'"
            ).fetchone()[0])
            location_id = int(db.execute(
                "SELECT id FROM locations WHERE code = 'L-013'"
            ).fetchone()[0])
            legacy_id = int(db.execute(
                """INSERT INTO equipment(
                       category_id, model, serial_number, inventory_number,
                       location_id, quantity
                   ) VALUES (?, 'ODE-013', 'ODE-013-LEGACY', '', ?, 1)""",
                (category_id, location_id),
            ).lastrowid)
            db.execute(
                "UPDATE stock_receipts SET legacy_equipment_id = ? WHERE id = ?",
                (legacy_id, receipt_id),
            )

        with self.service.user_context("lokolis", author_name="Legacy Engineer"):
            result = self.context.warehouse.assign_inventory_number(
                "ODE-013-LEGACY", "INV-ODE-013-LEGACY"
            )
        self.assertTrue(result["updated"])
        with closing(sqlite3.connect(self.db_path)) as db:
            legacy_inventory = db.execute(
                "SELECT inventory_number FROM equipment WHERE id = ?", (legacy_id,)
            ).fetchone()[0]
        self.assertEqual(legacy_inventory, "INV-ODE-013-LEGACY")


class _Headers(dict[str, str]):
    def get(self, name: str, default: str = "") -> str:
        return super().get(name, default)


class EquipmentCardInventoryApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "warehouse.db"
        self.service = WarehouseService(self.db_path)
        self.context = create_application_context(
            self.db_path, service=self.service, warehouse_contour="demo"
        )
        self.handler_class = make_handler(self.context)
        with self.service.user_context("lokolis"):
            self.context.warehouse.create_receipt(
                EquipmentCardInventoryWorkflowTest.receipt("ODE-013-API")
            )
            self.service.create_user(
                "View", "API", "Viewer", "viewer-card-api@test", "secret1", "viewer"
            )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def action(
        self, payload: dict[str, Any], *, email: str = "lokolis"
    ) -> tuple[int, Any]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        handler = self.handler_class.__new__(self.handler_class)
        handler.path = "/api/action"
        handler.rfile = io.BytesIO(body)
        handler.headers = _Headers({
            "Content-Length": str(len(body)), "Content-Type": "application/json"
        })
        handler._send_json = lambda status, value: setattr(
            handler, "captured", (status, value)
        )
        with self.service.user_context(
            email, author_name="API Equipment Engineer"
        ), self.service.lock:
            handler._do_POST()
        return handler.captured

    def test_action_contract_and_idempotence(self) -> None:
        payload = {
            "action": "ASSIGN_INVENTORY_NUMBER",
            "serial_number": "ode-013-api",
            "inventory_number": "inv-ode-013-api",
        }
        status, assigned = self.action(payload)
        self.assertEqual(status, 200)
        self.assertEqual(assigned["position"]["serial_number"], "ODE-013-API")
        self.assertEqual(assigned["position"]["inventory_number"], "INV-ODE-013-API")
        self.assertTrue(assigned["position"]["updated"])

        status, repeated = self.action(payload)
        self.assertEqual(status, 200)
        self.assertFalse(repeated["position"]["updated"])

    def test_action_validation_role_denial_and_no_traceback_leak(self) -> None:
        cases = (
            ({
                "action": "ASSIGN_INVENTORY_NUMBER",
                "serial_number": "ODE-013-API",
                "inventory_number": ["bad"],
            }, "lokolis"),
            ({
                "action": "ASSIGN_INVENTORY_NUMBER",
                "serial_number": "UNKNOWN",
                "inventory_number": "INV-UNKNOWN",
            }, "lokolis"),
            ({
                "action": "ASSIGN_INVENTORY_NUMBER",
                "serial_number": "ODE-013-API",
                "inventory_number": "INV-VIEWER",
            }, "viewer-card-api@test"),
        )
        for payload, email in cases:
            with self.subTest(payload=payload, email=email):
                status, error = self.action(payload, email=email)
                self.assertEqual(status, 400)
                self.assertIn("error", error)
                self.assertNotIn("Traceback", error["error"])
                self.assertNotIn("sqlite3", error["error"])


if __name__ == "__main__":
    unittest.main()
