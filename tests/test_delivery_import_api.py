from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from inventory.core.application import create_application_context
from inventory.db import connect
from inventory.service import WarehouseService
from inventory.webapp import make_handler


class _Headers(dict[str, str]):
    def get(self, name: str, default: str = "") -> str:
        return super().get(name, default)


class DeliveryImportApiTest(unittest.TestCase):
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
        headers = {"Content-Length": str(len(body)), "Content-Type": content_type}
        headers.update(extra_headers or {})
        handler.headers = _Headers(headers)

        def send_json(status: int, payload: Any) -> None:
            handler._captured = (status, payload)

        handler._send_json = send_json
        with self.service.user_context(email, author_name="API Engineer"), self.service.lock:
            handler._do_POST()
        return handler._captured

    def action(self, payload: dict[str, Any], *, email: str = "lokolis") -> tuple[int, Any]:
        return self.call_post(
            "/api/action",
            json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            content_type="application/json",
            email=email,
        )

    def counts(self) -> dict[str, int]:
        with connect(self.db_path) as db:
            return {
                name: int(db.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0])
                for name in ("stock_receipts", "deliveries", "delivery_lines")
            }

    def test_csv_encodings_delimiters_preview_confirm_and_no_receipt(self) -> None:
        cases = [
            ("utf8-bom", "S/N;Номер поставки;Поставщик;Количество\nAPI-D-1;D-1;Supplier;1\n".encode("utf-8-sig")),
            ("cp1251", "S/N;Номер поставки;Поставщик;Количество\nAPI-D-2;D-2;Поставщик;1\n".encode("cp1251")),
            ("comma", b"S/N,Delivery Number,Supplier,Quantity\nAPI-D-3,D-3,Supplier,1\n"),
            ("tab", b"S/N\tDelivery Number\tSupplier\tQuantity\nAPI-D-4\tD-4\tSupplier\t1\n"),
        ]
        for name, body in cases:
            with self.subTest(name=name):
                before = self.counts()
                status, preview = self.call_post(
                    "/api/import-csv?kind=delivery",
                    body,
                    extra_headers={"X-Filename": f"{name}.csv"},
                )
                self.assertEqual(status, 200, preview)
                for key in ("preview_id", "summary", "rows", "unknown_columns", "normalized_mapping", "can_confirm"):
                    self.assertIn(key, preview)
                self.assertEqual(self.counts(), before)
                status, confirmed = self.action({"action": "CONFIRM_DELIVERY", "preview_id": preview["preview_id"]})
                self.assertEqual(status, 200, confirmed)
                self.assertIn("delivery_id", confirmed)
                after = self.counts()
                self.assertEqual(after["stock_receipts"], before["stock_receipts"])
                self.assertEqual(after["deliveries"], before["deliveries"] + 1)
                self.assertEqual(after["delivery_lines"], before["delivery_lines"] + 1)

    def test_malformed_empty_unknown_missing_oversized_unknown_and_repeat_preview(self) -> None:
        bad_cases = [
            b"",
            b"not,a,valid,enough",
            b"Unknown\nvalue\n",
        ]
        for body in bad_cases:
            status, payload = self.call_post("/api/import-csv?kind=delivery", body)
            self.assertEqual(status, 400)
            self.assertIn("error", payload)
        status, payload = self.call_post("/api/import-csv?kind=delivery", b"x" * 50_000_001)
        self.assertEqual(status, 400)
        status, payload = self.action({"action": "CONFIRM_DELIVERY", "preview_id": "missing"})
        self.assertEqual(status, 400)
        body = b"S/N;Delivery Number;Supplier\nREPEAT-1;D;S\n"
        status, preview = self.call_post("/api/import-csv?kind=delivery", body)
        self.assertEqual(status, 200)
        status, confirmed = self.action({"action": "CONFIRM_DELIVERY", "preview_id": preview["preview_id"]})
        self.assertEqual(status, 200)
        status, repeated = self.action({"action": "CONFIRM_DELIVERY", "preview_id": preview["preview_id"]})
        self.assertEqual(status, 400)
        self.assertIn("error", repeated)

    def test_viewer_denied_admin_allowed_and_no_http_500(self) -> None:
        with self.service.user_context("lokolis"):
            self.service.create_user("View", "Only", "Viewer", "viewer-del-api@test", "secret1", "viewer")
        body = b"S/N;Delivery Number;Supplier\nVIEW-DENIED;D;S\n"
        status, payload = self.call_post("/api/import-csv?kind=delivery", body, email="viewer-del-api@test")
        self.assertEqual(status, 400)
        self.assertIn("error", payload)
        status, payload = self.call_post("/api/import-csv?kind=delivery", body)
        self.assertEqual(status, 200)


if __name__ == "__main__":
    unittest.main()
