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
from inventory.service import WarehouseService
from inventory.webapp import make_handler


class _Headers(dict[str, str]):
    def get(self, name: str, default: str = "") -> str:
        return super().get(name, default)


class InventoryNumberImportApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "warehouse.db"
        self.service = WarehouseService(self.db_path)
        self.context = create_application_context(
            self.db_path, service=self.service, warehouse_contour="demo"
        )
        self.handler_class = make_handler(self.context)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    @staticmethod
    def receipt(serial_number: str) -> dict[str, Any]:
        return {
            "receipt_date": "2026-07-13",
            "responsible": "API Inventory Fixture",
            "category": "Оборудование",
            "item_type": "Сервер",
            "supplier": "Не указан",
            "vendor": "Dell",
            "model": "R760",
            "item_name": "Сервер Dell R760",
            "project": "Digital",
            "serial_number": serial_number,
            "inventory_number": "",
            "shelf": "A-01",
            "object_name": "Склад",
            "datacenter": "Ixcellerate",
            "unit": "шт",
            "quantity": 1,
        }

    def add_receipt(self, serial_number: str) -> None:
        with self.service.user_context("lokolis"):
            self.context.warehouse.create_receipt(self.receipt(serial_number))

    def call_post(
        self,
        path: str,
        body: bytes,
        *,
        content_type: str = "text/csv",
        email: str = "lokolis",
        extra_headers: dict[str, str] | None = None,
    ) -> tuple[int, Any]:
        handler = self.handler_class.__new__(self.handler_class)
        handler.path = path
        handler.rfile = io.BytesIO(body)
        headers = {
            "Content-Length": str(len(body)),
            "Content-Type": content_type,
        }
        headers.update(extra_headers or {})
        handler.headers = _Headers(headers)
        handler._send_json = lambda status, payload: setattr(
            handler, "captured", (status, payload)
        )
        with self.service.user_context(
            email, author_name="API Inventory Engineer"
        ), self.service.lock:
            handler._do_POST()
        return handler.captured

    def action(
        self, payload: dict[str, Any], *, email: str = "lokolis"
    ) -> tuple[int, Any]:
        return self.call_post(
            "/api/action",
            json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            content_type="application/json",
            email=email,
        )

    def inventory_number(self, serial_number: str) -> str:
        with closing(sqlite3.connect(self.db_path)) as db:
            row = db.execute(
                """SELECT inventory_number FROM stock_receipts
                   WHERE serial_number = ? COLLATE NOCASE""",
                (serial_number,),
            ).fetchone()
        self.assertIsNotNone(row)
        return str(row[0] or "")

    def assert_controlled_error(self, status: int, payload: Any) -> None:
        self.assertGreaterEqual(status, 400)
        self.assertLess(status, 500)
        self.assertIsInstance(payload, dict)
        self.assertIn("error", payload)
        serialized = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("Traceback", serialized)
        self.assertNotIn("sqlite3", serialized)

    def test_utf8_semicolon_and_comma_preview_then_confirm(self) -> None:
        cases = (
            (
                "semicolon",
                "API-INV-SEMICOLON",
                "INV-API-SEMICOLON",
                (
                    "Serial Number;Inventory Number\n"
                    "API-INV-SEMICOLON;INV-API-SEMICOLON\n"
                ).encode("utf-8-sig"),
            ),
            (
                "comma",
                "API-INV-COMMA",
                "INV-API-COMMA",
                (
                    "Serial Number,Inventory Number\n"
                    "API-INV-COMMA,INV-API-COMMA\n"
                ).encode("utf-8"),
            ),
        )
        for name, serial, inventory, body in cases:
            with self.subTest(name=name):
                self.add_receipt(serial)
                before = self.inventory_number(serial)
                status, preview = self.call_post(
                    "/api/preview-csv?kind=inventory_numbers",
                    body,
                    extra_headers={"X-Filename": f"{name}.csv"},
                )

                self.assertEqual(status, 200, preview)
                for key in (
                    "ok",
                    "preview_id",
                    "summary",
                    "rows",
                    "errors",
                    "can_confirm",
                ):
                    self.assertIn(key, preview)
                self.assertTrue(preview["can_confirm"])
                self.assertEqual(preview["rows"][0]["status"], "SUCCESS")
                self.assertEqual(preview["summary"]["SUCCESS"], 1)
                self.assertEqual(self.inventory_number(serial), before)

                status, confirmed = self.action(
                    {
                        "action": "CONFIRM_IMPORT_PREVIEW",
                        "kind": "inventory_numbers",
                        "preview_id": preview["preview_id"],
                    }
                )
                self.assertEqual(status, 200, confirmed)
                self.assertTrue(confirmed["ok"])
                self.assertEqual(confirmed["imported"], 1)
                self.assertEqual(confirmed["changed_count"], 1)
                self.assertEqual(confirmed["summary"]["SUCCESS"], 1)
                self.assertEqual(self.inventory_number(serial), inventory)

    def test_duplicate_serial_preview_blocks_confirm_without_writes(self) -> None:
        self.add_receipt("API-INV-DUPLICATE")
        body = (
            "Serial Number;Inventory Number\n"
            "API-INV-DUPLICATE;INV-API-FIRST\n"
            "api-inv-duplicate;INV-API-SECOND\n"
        ).encode("utf-8")

        status, preview = self.call_post(
            "/api/preview-csv?kind=inventory_numbers", body
        )

        self.assertEqual(status, 200, preview)
        self.assertFalse(preview["can_confirm"])
        self.assertEqual(preview["summary"]["VALIDATION_ERROR"], 2)
        self.assertEqual(self.inventory_number("API-INV-DUPLICATE"), "")
        status, error = self.action(
            {
                "action": "CONFIRM_IMPORT_PREVIEW",
                "kind": "inventory_numbers",
                "preview_id": preview["preview_id"],
            }
        )
        self.assert_controlled_error(status, error)
        self.assertEqual(self.inventory_number("API-INV-DUPLICATE"), "")

    def test_invalid_csv_token_repeat_and_viewer_are_controlled_4xx(self) -> None:
        bad_csv_cases = (
            b"",
            b"Unknown\nvalue\n",
            b"Serial Number\nAPI-MISSING-INVENTORY-COLUMN\n",
        )
        for body in bad_csv_cases:
            with self.subTest(body=body):
                status, payload = self.call_post(
                    "/api/preview-csv?kind=inventory_numbers", body
                )
                self.assert_controlled_error(status, payload)

        status, payload = self.action(
            {
                "action": "CONFIRM_IMPORT_PREVIEW",
                "kind": "inventory_numbers",
                "preview_id": "missing-preview-token",
            }
        )
        self.assert_controlled_error(status, payload)

        self.add_receipt("API-INV-ONCE")
        status, preview = self.call_post(
            "/api/preview-csv?kind=inventory_numbers",
            (
                "Serial Number;Inventory Number\n"
                "API-INV-ONCE;INV-API-ONCE\n"
            ).encode("utf-8"),
        )
        self.assertEqual(status, 200, preview)
        confirm_payload = {
            "action": "CONFIRM_IMPORT_PREVIEW",
            "kind": "inventory_numbers",
            "preview_id": preview["preview_id"],
        }
        status, confirmed = self.action(confirm_payload)
        self.assertEqual(status, 200, confirmed)
        status, repeated = self.action(confirm_payload)
        self.assert_controlled_error(status, repeated)

        with self.service.user_context("lokolis"):
            self.service.create_user(
                "View",
                "Inventory",
                "Viewer",
                "viewer-inventory-import@test",
                "secret1",
                "viewer",
            )
        status, denied = self.call_post(
            "/api/preview-csv?kind=inventory_numbers",
            (
                "Serial Number;Inventory Number\n"
                "API-VIEWER;INV-API-VIEWER\n"
            ).encode("utf-8"),
            email="viewer-inventory-import@test",
        )
        self.assert_controlled_error(status, denied)


if __name__ == "__main__":
    unittest.main()
