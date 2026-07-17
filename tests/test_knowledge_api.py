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


class KnowledgeApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "warehouse.db"
        self.service = WarehouseService(self.db_path)
        self.context = create_application_context(self.db_path, service=self.service)
        self.context.knowledge.upload_root = Path(self.tmp.name) / "uploads"
        self.handler_class = make_handler(self.context)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def handler(self, path: str, body: bytes = b"", content_type: str = "application/json"):
        handler = self.handler_class.__new__(self.handler_class)
        handler.path = path
        handler.rfile = io.BytesIO(body)
        handler.headers = _Headers({"Content-Length": str(len(body)), "Content-Type": content_type})
        handler._send_json = lambda status, payload: setattr(handler, "captured", (status, payload))
        return handler

    def post(self, path: str, body: bytes, *, email: str = "lokolis", content_type: str = "application/json", filename: str = "") -> tuple[int, Any]:
        handler = self.handler(path, body, content_type)
        if filename:
            handler.headers["X-Filename"] = filename
        with self.service.user_context(email, author_name="API Engineer"), self.service.lock:
            handler._do_POST()
        return handler.captured

    def get(self, path: str, *, email: str = "lokolis") -> tuple[int, Any]:
        handler = self.handler(path)
        with self.service.user_context(email, author_name="API Engineer"):
            handler._do_GET()
        return handler.captured

    def mutate(self, method: str, path: str, payload: dict[str, Any] | None = None) -> tuple[int, Any]:
        body = json.dumps(payload or {}, ensure_ascii=False).encode("utf-8")
        handler = self.handler(path, body)
        handler._session_email = lambda: "lokolis"
        handler._session_author = lambda: "API Engineer"
        handler._session_role_override = lambda: None
        handler._host_allowed = lambda _host: True
        handler._knowledge_mutation(method)
        return handler.captured

    def test_create_list_read_and_missing_article(self) -> None:
        payload = json.dumps({
            "title": "Русская инструкция",
            "summary": "Кратко",
            "content": "# Шаги\n\n- Первый",
            "category": "instructions",
        }, ensure_ascii=False).encode("utf-8")
        status, created = self.post("/api/knowledge/articles", payload)
        self.assertEqual(status, 201, created)
        article_id = created["article"]["id"]
        status, listing = self.get("/api/knowledge/articles?category=instructions")
        self.assertEqual(status, 200, listing)
        self.assertEqual(listing["articles"][0]["id"], article_id)
        status, detail = self.get(f"/api/knowledge/articles/{article_id}")
        self.assertEqual(status, 200, detail)
        self.assertIn("<h1>Шаги</h1>", detail["article"]["content_html"])
        status, updated = self.mutate("PUT", f"/api/knowledge/articles/{article_id}", {
            "title": "Обновленная инструкция",
            "summary": "Кратко",
            "content": "# Новый текст",
            "category": "instructions",
            "tags": ["Серверы"],
        })
        self.assertEqual(status, 200, updated)
        self.assertEqual(updated["article"]["tags"], ["Серверы"])
        status, deleted = self.mutate("DELETE", f"/api/knowledge/articles/{article_id}")
        self.assertEqual(status, 200, deleted)
        status, missing = self.get(f"/api/knowledge/articles/{article_id}")
        self.assertEqual(status, 404, missing)
        status, missing = self.get("/api/knowledge/articles/99999")
        self.assertEqual(status, 404, missing)

    def test_attachment_and_viewer_write_denied(self) -> None:
        payload = json.dumps({
            "title": "Спецификация", "content": "Текст", "category": "specifications"
        }, ensure_ascii=False).encode("utf-8")
        status, created = self.post("/api/knowledge/articles", payload)
        self.assertEqual(status, 201)
        article_id = created["article"]["id"]
        status, attached = self.post(
            f"/api/knowledge/articles/{article_id}/attachments",
            b"%PDF-1.7\napi",
            content_type="application/pdf",
            filename="spec.pdf",
        )
        self.assertEqual(status, 201, attached)
        with self.service.user_context("lokolis"):
            self.service.create_user(
                "API", "Viewer", "Viewer", "viewer-knowledge-api@test", "secret1", "viewer"
            )
        status, denied = self.post(
            "/api/knowledge/articles", payload, email="viewer-knowledge-api@test"
        )
        self.assertEqual(status, 403, denied)


if __name__ == "__main__":
    unittest.main()
