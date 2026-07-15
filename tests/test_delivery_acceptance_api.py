from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from inventory.core.application import create_application_context
from inventory.service import WarehouseService
from inventory.webapp import make_handler


class _Headers(dict[str, str]):
    def get(self, name: str, default: str = "") -> str:
        return super().get(name, default)


class DeliveryAcceptanceApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "warehouse.db"
        self.service = WarehouseService(self.db_path)
        self.context = create_application_context(
            self.db_path, service=self.service, warehouse_contour="demo"
        )
        self.handler_class = make_handler(self.context)
        with self.service.user_context("lokolis"):
            preview = self.context.warehouse.preview_delivery_import([
                {"S/N": "API-A-1", "Номер поставки": "D-API", "Поставщик": "Supplier", "Вендор": "Dell", "Тип оборудования": "Server"},
                {"S/N": "API-A-2", "Номер поставки": "D-API", "Поставщик": "Supplier", "Вендор": "Dell", "Тип оборудования": "Server"},
            ], "api.csv")
            self.delivery_id = self.context.warehouse.confirm_delivery_import(preview["preview_id"])

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def call_action(self, payload: dict[str, Any], *, email: str = "lokolis") -> tuple[int, Any]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        return self.call_post("/api/action", body, email=email)

    def call_post(self, path: str, body: bytes, *, email: str = "lokolis") -> tuple[int, Any]:
        handler = self.handler_class.__new__(self.handler_class)
        handler.path = path
        handler.rfile = io.BytesIO(body)
        handler.headers = _Headers({"Content-Length": str(len(body)), "Content-Type": "application/json"})

        def send_json(status: int, payload: Any) -> None:
            handler._captured = (status, payload)

        handler._send_json = send_json
        with self.service.user_context(email, author_name="API Engineer"), self.service.lock:
            handler._do_POST()
        return handler._captured

    def test_valid_inspect_accept_repeat_unplanned_batch_and_response_keys(self) -> None:
        status, inspect = self.call_action({"action": "INSPECT_DELIVERY_SERIAL", "delivery_id": self.delivery_id, "serial_number": "api-a-1"})
        self.assertEqual(status, 200)
        for key in ("found_in_delivery", "allowed_actions", "exists_in_warehouse", "delivery_line_id"):
            self.assertIn(key, inspect)
        status, accepted = self.call_action({"action": "ACCEPT_DELIVERY_SERIAL", "delivery_id": self.delivery_id, "serial_number": "API-A-1"})
        self.assertEqual(status, 200)
        self.assertTrue(accepted["accepted"])
        self.assertIn("receipt_id", accepted)
        status, repeat = self.call_action({"action": "ACCEPT_DELIVERY_SERIAL", "delivery_id": self.delivery_id, "serial_number": "API-A-1"})
        self.assertEqual(status, 400)
        self.assertIn("error", repeat)
        status, unplanned = self.call_action({
            "action": "ACCEPT_DELIVERY_SERIAL", "delivery_id": self.delivery_id,
            "serial_number": "API-UNP-1", "unplanned": True,
            "values": {"supplier": "Supplier", "vendor": "Dell", "model": "R760", "project": "P", "datacenter": "DC1", "shelf": "A-01", "equipment_type": "Server", "item_name": "Server Dell"},
        })
        self.assertEqual(status, 200)
        self.assertTrue(unplanned["accepted"])
        status, summary = self.call_action({"action": "DELIVERY_ACCEPTANCE_SUMMARY", "delivery_id": self.delivery_id})
        self.assertEqual(status, 200)
        self.assertIn("summary", summary)

    def test_invalid_unknown_malformed_oversized_roles_and_no_500(self) -> None:
        status, payload = self.call_action({"action": "INSPECT_DELIVERY_SERIAL", "delivery_id": 999999, "serial_number": "X"})
        self.assertEqual(status, 400)
        status, payload = self.call_post("/api/action", b"{")
        self.assertEqual(status, 400)
        status, payload = self.call_post("/api/action", b"")
        self.assertEqual(status, 400)
        status, payload = self.call_post("/api/action", b" " * 1_000_001)
        self.assertEqual(status, 400)
        with self.service.user_context("lokolis"):
            self.service.create_user("View", "Only", "Viewer", "viewer-api-accept@test", "secret1", "viewer")
        status, denied = self.call_action({"action": "ACCEPT_DELIVERY_SERIAL", "delivery_id": self.delivery_id, "serial_number": "API-A-2"}, email="viewer-api-accept@test")
        self.assertEqual(status, 400)
        self.assertIn("error", denied)
        status, unknown = self.call_action({"action": "INSPECT_DELIVERY_SERIAL", "delivery_id": self.delivery_id, "serial_number": "NOT-IN-DOC"})
        self.assertEqual(status, 200)
        self.assertFalse(unknown["found_in_delivery"])


if __name__ == "__main__":
    unittest.main()
