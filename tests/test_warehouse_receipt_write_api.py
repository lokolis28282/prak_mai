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


class WarehouseReceiptWriteApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "warehouse.db"
        self.service = WarehouseService(self.db_path)
        self.context = create_application_context(
            self.db_path, service=self.service, warehouse_contour="demo"
        )
        self.handler_class = make_handler(self.context)
        self.today = "2026-07-11"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def row(self, serial: str = "API-RCPT-1") -> dict[str, Any]:
        return {
            "receipt_date": self.today,
            "responsible": "API Engineer",
            "category": "Оборудование",
            "item_type": "Сервер",
            "supplier": "Не указан",
            "vendor": "Dell",
            "model": "PowerEdge R740",
            "item_name": "Сервер Dell PowerEdge R740",
            "project": "Digital",
            "serial_number": serial,
            "inventory_number": f"INV-{serial}",
            "shelf": "A-01",
            "object_name": "Склад",
            "datacenter": "Ixcellerate",
            "unit": "шт",
            "quantity": "1",
        }

    def call_post(
        self,
        path: str,
        body: bytes,
        *,
        content_type: str = "application/json",
        email: str = "lokolis",
        extra_headers: dict[str, str] | None = None,
    ) -> tuple[int, Any]:
        handler = self.handler_class.__new__(self.handler_class)
        handler.path = path
        handler.rfile = io.BytesIO(body)
        headers = {"Content-Length": str(len(body)), "Content-Type": content_type}
        headers.update(extra_headers or {})
        handler.headers = _Headers(headers)

        def send_json(status: int, payload: Any) -> None:
            handler._captured = (status, payload)

        handler._send_json = send_json
        with self.service.user_context(email, author_name="API Engineer"), self.service.lock:
            handler._do_POST()
        return handler._captured

    def action(self, payload: dict[str, Any], **kwargs: Any) -> tuple[int, Any]:
        return self.call_post(
            "/api/action",
            json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            **kwargs,
        )

    def test_valid_json_manual_and_batch_response_keys(self) -> None:
        status, payload = self.action({"action": "STOCK_RECEIPT", **self.row("API-1")})
        self.assertEqual(status, 200)
        self.assertEqual(payload, {"ok": True})
        status, payload = self.action({
            "action": "CONFIRM_SCANNED_RECEIPTS",
            "common_fields": {**self.row(""), "serial_number": "", "inventory_number": ""},
            "serial_numbers": ["API-SCAN-1", "API-SCAN-2"],
        })
        self.assertEqual(status, 200)
        self.assertEqual(payload, {"ok": True, "imported": 2})

    def test_malformed_empty_large_unknown_and_required_fields(self) -> None:
        for body in (b"{", b""):
            status, payload = self.call_post("/api/action", body)
            self.assertEqual(status, 400)
            self.assertIn("error", payload)
        status, payload = self.call_post("/api/action", b" " * 1_000_001)
        self.assertEqual(status, 400)
        status, payload = self.action({"action": "UNKNOWN"})
        self.assertEqual(status, 400)
        status, payload = self.action({"action": "STOCK_RECEIPT", **{**self.row("BAD"), "serial_number": ""}})
        self.assertEqual(status, 400)
        self.assertIn("error", payload)

    def test_viewer_duplicate_csv_preview_confirm_and_no_500(self) -> None:
        with self.service.user_context("lokolis"):
            self.service.create_user("View", "Only", "Viewer", "viewer-api-rcpt@test", "secret1", "viewer")
        status, payload = self.action({"action": "STOCK_RECEIPT", **self.row("VIEW")}, email="viewer-api-rcpt@test")
        self.assertEqual(status, 400)
        self.assertIn("error", payload)

        body = (
            "Дата;ФИО;Поставщик;Вендор;Модель;Наименование;Проект;SN;Инв.№;Стеллаж/Полка;Объект;ЦОД;Тип оборудования;Единица учета;Кол-во\n"
            f"{self.today};API Engineer;Не указан;Dell;PowerEdge R740;Сервер Dell PowerEdge R740;Digital;CSV-1;INV-CSV-1;A-01;Склад;Ixcellerate;Сервер;шт;1\n"
        ).encode("utf-8-sig")
        status, preview = self.call_post(
            "/api/preview-csv?kind=receipt",
            body,
            content_type="text/csv",
            extra_headers={"X-Filename": "receipt.csv"},
        )
        self.assertEqual(status, 200)
        self.assertTrue(preview["ok"])
        self.assertIn("preview_id", preview)
        status, confirmed = self.action({
            "action": "CONFIRM_IMPORT_PREVIEW",
            "kind": "receipt",
            "preview_id": preview["preview_id"],
        })
        self.assertEqual(status, 200)
        self.assertEqual(confirmed["imported"], 1)

        status, duplicate = self.action({"action": "STOCK_RECEIPT", **self.row("csv-1")})
        self.assertEqual(status, 400)
        self.assertIn("error", duplicate)


if __name__ == "__main__":
    unittest.main()
