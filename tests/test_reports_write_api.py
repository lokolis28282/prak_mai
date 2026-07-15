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


class ReportsWriteApiTest(unittest.TestCase):
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

    def call_post(
        self,
        path: str,
        body: bytes,
        *,
        content_type: str = "application/json",
        author: str = "API Engineer",
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

        def send_json(status: int, payload: Any) -> None:
            handler._captured = (status, payload)

        handler._send_json = send_json
        with self.service.user_context(email, author_name=author), self.service.lock:
            handler._do_POST()
        return handler._captured

    def action(self, payload: dict[str, Any], **kwargs: Any) -> tuple[int, Any]:
        return self.call_post(
            "/api/action",
            json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            **kwargs,
        )

    def row(self, number: str = "API-1") -> dict[str, str]:
        return {
            "work_date": self.today,
            "task_source": "ITSM",
            "task_type": "ИНЦ",
            "task_number": number,
            "description": "API работа",
            "status": "Выполнено",
            "comment": "ok",
        }

    def test_admin_and_engineer_can_create_viewer_cannot(self) -> None:
        status, payload = self.action({"action": "WORK_LOG", **self.row("ADMIN")})
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])

        with self.service.user_context("lokolis"):
            self.service.create_user("View", "Only", "Viewer", "viewer-api@test", "secret1", "viewer")
        status, payload = self.action(
            {"action": "WORK_LOG", **self.row("VIEW")},
            email="viewer-api@test",
        )
        self.assertEqual(status, 400)
        self.assertIn("error", payload)

    def test_batch_json_contract_keys(self) -> None:
        status, payload = self.action({"action": "WORK_LOGS", "rows": [self.row("B1"), self.row("B2")]})
        self.assertEqual(status, 200)
        self.assertEqual(payload, {"ok": True, "saved": 2})

    def test_malformed_empty_large_and_unknown_action(self) -> None:
        for body in (b"{", b""):
            status, payload = self.call_post("/api/action", body)
            self.assertEqual(status, 400)
            self.assertIn("error", payload)
        status, payload = self.call_post("/api/action", b" " * 1_000_001)
        self.assertEqual(status, 400)
        self.assertIn("error", payload)
        status, payload = self.action({"action": "NO_SUCH_ACTION"})
        self.assertEqual(status, 400)
        self.assertIn("error", payload)

    def test_work_logs_csv_preview_confirm_and_bad_csv(self) -> None:
        csv_body = (
            "Дата;Источник задачи;Тип задачи;Номер задачи;Описание работы;Статус;Комментарий\n"
            f"{self.today};ITSM;ИНЦ;CSV-1;Работа;Выполнено;Тест\n"
        ).encode("utf-8-sig")
        status, preview = self.call_post(
            "/api/preview-csv?kind=work_logs",
            csv_body,
            content_type="text/csv",
            extra_headers={"X-Filename": "logs.csv"},
        )
        self.assertEqual(status, 200)
        self.assertTrue(preview["ok"])
        self.assertIn("preview_id", preview)
        status, confirmed = self.action({
            "action": "CONFIRM_IMPORT_PREVIEW",
            "kind": "work_logs",
            "preview_id": preview["preview_id"],
        })
        self.assertEqual(status, 200)
        self.assertEqual(confirmed["imported"], 1)

        status, payload = self.call_post(
            "/api/import-csv?kind=work_logs",
            "Дата;Описание работы\n2026-07-11;bad\n".encode("utf-8"),
            content_type="text/csv",
        )
        self.assertEqual(status, 400)
        self.assertIn("error", payload)

    def test_daily_report_csv_upload_response_keys(self) -> None:
        body = (
            "Дата;Блок отчета;Номер задачи;Описание / наименование;Количество / метраж;S/N;ФИО;Комментарий / основание\n"
            f"{self.today};Работы;D-1;Готовый отчет;1;SN;Инженер;ok\n"
        ).encode("utf-8-sig")
        status, payload = self.call_post(
            "/api/import-csv?kind=daily_report",
            body,
            content_type="text/csv",
            extra_headers={"X-Filename": "daily.csv"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["imported"], 1)
        self.assertIn("upload_id", payload)

    def test_unknown_kind_and_no_http_500(self) -> None:
        status, payload = self.call_post(
            "/api/import-csv?kind=nope",
            b"x\n1\n",
            content_type="text/csv",
        )
        self.assertEqual(status, 400)
        self.assertIn("error", payload)


if __name__ == "__main__":
    unittest.main()
