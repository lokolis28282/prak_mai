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


class WarehouseCableApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "warehouse.db"
        self.service = WarehouseService(self.db_path)
        self.context = create_application_context(
            self.db_path, service=self.service, warehouse_contour="demo"
        )
        self.handler_class = make_handler(self.context)
        with self.service.user_context("lokolis"):
            self.service.create_user("Eng", "Cable", "Engineer", "engineer-cable@test", "secret1", "engineer")
            self.service.create_user("View", "Cable", "Viewer", "viewer-cable-api@test", "secret1", "viewer")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def call_post(
        self,
        path: str,
        body: bytes,
        *,
        email: str = "lokolis",
    ) -> tuple[int, dict[str, Any]]:
        handler = self.handler_class.__new__(self.handler_class)
        handler.path = path
        handler.rfile = io.BytesIO(body)
        handler.headers = _Headers({
            "Content-Length": str(len(body)),
            "Content-Type": "application/json",
        })

        def send_json(status: int, payload: dict[str, Any]) -> None:
            handler._captured = (status, payload)

        handler._send_json = send_json
        with self.service.user_context(email, author_name="API Cable"), self.service.lock:
            handler._do_POST()
        return handler._captured

    def action(self, payload: dict[str, Any], email: str = "lokolis") -> tuple[int, dict[str, Any]]:
        return self.call_post(
            "/api/action",
            json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            email=email,
        )

    def cable_receipt(self, quantity: str = "10") -> dict[str, Any]:
        return {
            "action": "STOCK_RECEIPT",
            "receipt_date": "2026-07-11",
            "responsible": "API Cable",
            "category": "Кабели",
            "item_type": "DAC",
            "cable_type": "DAC",
            "item_name": "DAC API",
            "supplier": "Не указан",
            "vendor": "Не указан",
            "project": "Digital",
            "datacenter": "Ixcellerate",
            "shelf": "API",
            "object_name": "Склад",
            "unit": "шт",
            "quantity": quantity,
        }

    def cable_issue(self, quantity: str = "4") -> dict[str, Any]:
        return {
            "action": "STOCK_ISSUE",
            "issue_date": "2026-07-11",
            "responsible": "API Cable",
            "source_item_name": "DAC API",
            "source_cable_type": "DAC",
            "quantity": quantity,
            "task_type": "ЗНР",
            "task_number": "77",
            "comment": "API",
        }

    def test_valid_receipt_issue_and_response_keys(self) -> None:
        status, payload = self.action(self.cable_receipt())
        self.assertEqual((status, payload), (200, {"ok": True}))
        status, payload = self.action(self.cable_issue())
        self.assertEqual((status, payload), (200, {"ok": True}))

    def test_errors_roles_and_no_http_500(self) -> None:
        status, payload = self.call_post("/api/action", b"{bad")
        self.assertEqual(status, 400)
        self.assertIn("error", payload)
        status, payload = self.call_post("/api/action", b"")
        self.assertEqual(status, 400)
        self.assertIn("error", payload)
        status, payload = self.action({**self.cable_receipt(), "item_name": ""})
        self.assertEqual(status, 400)
        self.assertIn("error", payload)
        status, payload = self.action(self.cable_issue(quantity="1"))
        self.assertEqual(status, 400)
        self.assertIn("доступно 0", payload["error"])
        status, payload = self.action(self.cable_receipt(), email="viewer-cable-api@test")
        self.assertEqual(status, 400)
        self.assertIn("Недостаточно прав", payload["error"])
        status, payload = self.action(self.cable_receipt(quantity="3"), email="engineer-cable@test")
        self.assertEqual(status, 200)
        self.assertEqual(payload, {"ok": True})


if __name__ == "__main__":
    unittest.main()
