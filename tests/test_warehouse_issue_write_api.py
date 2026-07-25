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


class WarehouseIssueWriteApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "warehouse.db"
        self.service = WarehouseService(self.db_path)
        self.context = create_application_context(
            self.db_path, service=self.service, warehouse_contour="demo"
        )
        self.handler_class = make_handler(self.context)
        self.today = "2026-07-11"
        with self.service.user_context("lokolis"):
            self.service.create_user("Eng", "Issue", "Engineer", "engineer-issue@test", "secret1", "engineer")
            self.service.create_user("View", "Issue", "Viewer", "viewer-issue-api@test", "secret1", "viewer")
            self.context.warehouse.create_receipt(self.receipt("API-ISS-1"))
            self.context.warehouse.create_receipt(self.receipt("API-ISS-2"))

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def receipt(self, serial: str) -> dict[str, Any]:
        return {
            "receipt_date": self.today,
            "responsible": "API Issue",
            "category": "Оборудование",
            "item_type": "Сервер",
            "supplier": "Не указан",
            "vendor": "Dell",
            "model": "R740",
            "item_name": "Сервер Dell R740",
            "project": "Digital",
            "serial_number": serial,
            "inventory_number": f"INV-{serial}",
            "shelf": "A-01",
            "object_name": "Склад",
            "datacenter": "Ixcellerate",
            "unit": "шт",
            "quantity": "1",
        }

    def issue(self, serial: str) -> dict[str, Any]:
        return {
            "action": "STOCK_ISSUE",
            "issue_date": self.today,
            "responsible": "API Issue",
            "task_type": "ЗНР",
            "task_number": "API-1",
            "target_serial_number": "",
            "target_hostname": "",
            "source_serial_number": serial,
            "source_item_name": "",
            "source_cable_type": "",
            "quantity": "1",
            "comment": "api",
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
        with self.service.user_context(email, author_name="API Issue"), self.service.lock:
            handler._do_POST()
        return handler._captured

    def action(self, payload: dict[str, Any], **kwargs: Any) -> tuple[int, Any]:
        return self.call_post(
            "/api/action",
            json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            **kwargs,
        )

    def test_valid_json_batch_and_roles(self) -> None:
        status, payload = self.action(self.issue("api-iss-1"))
        self.assertEqual((status, payload), (200, {"ok": True}))
        status, payload = self.action({
            "action": "CONFIRM_SCANNED_ISSUES",
            "common_fields": {**self.issue(""), "action": "", "source_serial_number": ""},
            "serial_numbers": ["API-ISS-2", "API-UNKNOWN"],
        })
        self.assertEqual(status, 400)
        self.assertIn("не найдена", payload["error"])
        with self.service.user_context("lokolis"):
            self.context.warehouse.create_receipt(self.receipt("API-ENG-1"))
        status, payload = self.action(self.issue("API-ENG-1"), email="engineer-issue@test")
        self.assertEqual(status, 200)
        status, payload = self.action(self.issue("NOPE"), email="viewer-issue-api@test")
        self.assertEqual(status, 400)
        self.assertIn("Недостаточно прав", payload["error"])

    def test_scanned_issue_pairs_are_strict_and_atomic(self) -> None:
        with self.service.user_context("lokolis"):
            self.context.warehouse.create_receipt({
                **self.receipt("PAIR-COMP-1"),
                "category": "Компоненты", "item_type": "Трансивер",
                "equipment_type": "", "component_type": "Трансивер",
            })
            self.context.warehouse.create_receipt(self.receipt("PAIR-SERVER-1"))
        common = {**self.issue(""), "action": "", "source_serial_number": ""}
        status, payload = self.action({
            "action": "CONFIRM_SCANNED_ISSUE_PAIRS",
            "common_fields": common,
            "pairs": [{
                "source_serial_number": "PAIR-COMP-1",
                "target_serial_number": "PAIR-SERVER-1",
            }],
        })
        self.assertEqual(payload, {"ok": True, "imported": 1})
        self.assertEqual(status, 200)

        with self.service.user_context("lokolis"):
            self.context.warehouse.create_receipt({
                **self.receipt("PAIR-COMP-2"),
                "category": "Компоненты", "item_type": "Трансивер",
                "equipment_type": "", "component_type": "Трансивер",
            })
        before = len(self.service.stock_issue_rows())
        status, payload = self.action({
            "action": "CONFIRM_SCANNED_ISSUE_PAIRS",
            "common_fields": common,
            "pairs": [
                {"source_serial_number": "PAIR-COMP-2", "target_serial_number": "PAIR-SERVER-1"},
                {"source_serial_number": "PAIR-UNKNOWN", "target_serial_number": "PAIR-SERVER-1"},
            ],
        })
        self.assertEqual(status, 400)
        self.assertIn("не найдена", payload["error"])
        self.assertEqual(len(self.service.stock_issue_rows()), before)

    def test_scanned_issue_pairs_process_one_hundred_component_server_links(self) -> None:
        pairs = []
        with self.service.user_context("lokolis"):
            for index in range(10):
                self.context.warehouse.create_receipt(self.receipt(f"LOAD-SERVER-{index:03d}"))
            for index in range(100):
                source = f"LOAD-TRANSCEIVER-{index:03d}"
                target = f"LOAD-SERVER-{index % 10:03d}"
                self.context.warehouse.create_receipt({
                    **self.receipt(source),
                    "category": "Компоненты", "item_type": "Трансивер",
                    "equipment_type": "", "component_type": "Трансивер",
                })
                pairs.append({
                    "source_serial_number": source,
                    "target_serial_number": target,
                })
        common = {**self.issue(""), "action": "", "source_serial_number": ""}
        status, payload = self.action({
            "action": "CONFIRM_SCANNED_ISSUE_PAIRS",
            "common_fields": common,
            "pairs": pairs,
        })
        self.assertEqual(status, 200)
        self.assertEqual(payload, {"ok": True, "imported": 100})
        for serial in ("LOAD-TRANSCEIVER-000", "LOAD-TRANSCEIVER-050", "LOAD-TRANSCEIVER-099"):
            self.assertEqual(self.service.search_stock_positions(serial)[0]["balance"], 0)

    def test_malformed_empty_large_unknown_required_and_insufficient(self) -> None:
        for body in (b"{", b""):
            status, payload = self.call_post("/api/action", body)
            self.assertEqual(status, 400)
            self.assertIn("error", payload)
        status, payload = self.call_post("/api/action", b" " * 1_000_001)
        self.assertEqual(status, 400)
        status, payload = self.action({"action": "UNKNOWN"})
        self.assertEqual(status, 400)
        status, payload = self.action({**self.issue("API-ISS-1"), "task_number": ""})
        self.assertEqual(status, 400)
        self.assertIn("обязательна задача", payload["error"])
        status, payload = self.action(self.issue("API-NOT-FOUND"))
        self.assertEqual(status, 400)
        self.assertIn("не найдена", payload["error"])

    def test_csv_preview_confirm_duplicate_and_no_500(self) -> None:
        with self.service.user_context("lokolis"):
            self.context.warehouse.create_receipt(self.receipt("API-CSV-1"))
        body = (
            "Дата;ФИО;Тип задачи;Номер задачи;S/N списываемого;Кол-во;Комментарий\n"
            f"{self.today};API Issue;ЗНР;CSV;API-CSV-1;1;ok\n"
            f"{self.today};API Issue;ЗНР;CSV;API-CSV-UNKNOWN;1;problem\n"
        ).encode("utf-8-sig")
        status, preview = self.call_post(
            "/api/preview-csv?kind=issue",
            body,
            content_type="text/csv",
            extra_headers={"X-Filename": "issue.csv"},
        )
        self.assertEqual(status, 200)
        self.assertTrue(preview["ok"])
        self.assertIn("preview_id", preview)
        status, confirmed = self.action({
            "action": "CONFIRM_IMPORT_PREVIEW",
            "kind": "issue",
            "preview_id": preview["preview_id"],
        })
        self.assertEqual(status, 200)
        self.assertEqual(confirmed["imported"], 2)
        status, duplicate = self.action({
            "action": "CONFIRM_SCANNED_ISSUES",
            "common_fields": {**self.issue(""), "source_serial_number": ""},
            "serial_numbers": ["DUP", "dup"],
        })
        self.assertEqual(status, 400)
        self.assertIn("повторяющиеся", duplicate["error"])


if __name__ == "__main__":
    unittest.main()
