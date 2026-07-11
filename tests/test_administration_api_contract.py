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
from inventory.webapp import make_handler


def assert_semantically_equal(testcase: unittest.TestCase, old: Any, new: Any) -> None:
    testcase.assertEqual(
        json.loads(json.dumps(old, sort_keys=True, default=str)),
        json.loads(json.dumps(new, sort_keys=True, default=str)),
    )


def assert_no_secret_keys(testcase: unittest.TestCase, value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            testcase.assertNotIn(str(key), {"password", "password_hash", "token", "session", "session_token"})
            assert_no_secret_keys(testcase, item)
    elif isinstance(value, list):
        for item in value:
            assert_no_secret_keys(testcase, item)


class _Headers:
    def get(self, name: str, default: str = "") -> str:
        return default


class AdministrationReadApiContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "warehouse.db"
        self.service = WarehouseService(self.db_path)
        self.context = create_application_context(self.db_path, service=self.service)
        self.service.create_user("Иван", "Инженеров", "Инженер", "engineer", "secret1", "engineer")
        self.service.create_user("Вера", "Просмотр", "Наблюдатель", "viewer", "secret2", "viewer")
        self.backup_dir = self.db_path.parent / "backups"
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        (self.backup_dir / "manual_test.db").write_bytes(b"sqlite backup")
        (self.backup_dir / "ignore.txt").write_text("not a database", encoding="utf-8")
        self.handler_class = make_handler(self.context)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _call_get(
        self, path: str, *, email: str = "lokolis", admin_session: bool = True
    ) -> tuple[int, Any, str]:
        handler = self.handler_class.__new__(self.handler_class)
        handler.path = path
        handler.headers = _Headers()

        def send(status: int, body: bytes, content_type: str = "application/json; charset=utf-8") -> None:
            handler._captured = (status, body, content_type)

        def send_download(filename: str, body: bytes) -> None:
            handler._captured = (200, body, f'text/csv; filename="{filename}"')

        def require_admin_session() -> None:
            if not admin_session:
                raise WarehouseError("Откройте отдельный режим администратора")

        handler._send = send
        handler._send_download = send_download
        handler._require_admin_session = require_admin_session
        with self.service.user_context(email, author_name="Контракт Админ"), self.service.lock:
            handler._do_GET()
        status, body, content_type = handler._captured
        if content_type.startswith("application/json"):
            return status, json.loads(body.decode("utf-8")), content_type
        return status, body, content_type

    def test_facade_semantics_match_legacy_service(self) -> None:
        admin = self.context.administration
        with self.service.user_context("lokolis"):
            assert_semantically_equal(self, self.service.current_user(), admin.get_current_user())
            assert_semantically_equal(self, self.service.users(), admin.list_users())
            assert_semantically_equal(self, self.service.audit_entries(limit=5), admin.list_audit_entries(limit=5))
            assert_semantically_equal(self, self.service.list_backups(), admin.list_backups())

    def test_current_user_profiles_and_no_secrets(self) -> None:
        for email, role in (("lokolis", "admin"), ("engineer", "engineer"), ("viewer", "viewer")):
            with self.subTest(email=email), self.service.user_context(email):
                profile = self.context.administration.get_profile()
                self.assertEqual(profile["email"], email)
                self.assertEqual(profile["role"], role)
                assert_no_secret_keys(self, profile)

    def test_admin_endpoint_contract_and_security(self) -> None:
        status, payload, _ = self._call_get("/api/admin")
        self.assertEqual(status, 200)
        self.assertEqual(set(payload), {"backups", "audit", "users"})
        self.assertTrue(any(user["email"] == "lokolis" for user in payload["users"]))
        self.assertTrue(all("password_hash" not in user for user in payload["users"]))
        self.assertTrue(all(Path(item["name"]).name == item["name"] for item in payload["backups"]))
        self.assertTrue(all(item["name"].endswith(".db") for item in payload["backups"]))
        self.assertFalse(any(item["name"] == "ignore.txt" for item in payload["backups"]))
        assert_no_secret_keys(self, payload)

    def test_non_admin_cannot_read_admin_endpoint(self) -> None:
        for email in ("engineer", "viewer"):
            with self.subTest(email=email):
                status, payload, _ = self._call_get("/api/admin", email=email)
                self.assertEqual(status, 400)
                self.assertIn("error", payload)
                self.assertNotIn("password_hash", json.dumps(payload, ensure_ascii=False))
                status, payload, _ = self._call_get("/api/admin", email=email, admin_session=False)
                self.assertEqual(status, 400)
                self.assertIn("error", payload)

    def test_audit_csv_contract(self) -> None:
        status, data, content_type = self._call_get("/export/audit.csv")
        self.assertEqual(status, 200)
        self.assertIn("action_log.csv", content_type)
        self.assertTrue(data.startswith("\ufeff".encode("utf-8")))
        text = data.decode("utf-8-sig")
        self.assertIn("Дата и время", text)
        self.assertIn("Пользователь", text)
        self.assertIn(";", text)
        self.assertNotIn("password_hash", text)
        self.assertNotIn("secret1", text)

    def test_limits_unknown_and_disabled_users(self) -> None:
        with self.service.user_context("lokolis"):
            with self.assertRaises(WarehouseError):
                self.context.administration.list_audit_entries(limit=0)
            with self.assertRaises(WarehouseError):
                self.context.administration.list_audit_entries(limit=5001)
            with self.assertRaises(WarehouseError):
                self.context.administration.get_user("missing@example.test")
        with closing(sqlite3.connect(self.db_path)) as db, db:
            db.execute("UPDATE users SET is_active = 0 WHERE email = 'viewer'")
        with self.assertRaises(WarehouseError):
            with self.service.user_context("viewer"):
                self.context.administration.get_profile()

    def test_database_status_is_lightweight(self) -> None:
        status = self.context.administration.get_database_status()
        self.assertEqual(status["path"], "warehouse.db")
        self.assertTrue(status["exists"])
        self.assertGreater(status["size"], 0)
        self.assertNotIn("messages", status)
        summary = self.context.administration.get_diagnostics_summary()
        self.assertIn("database", summary)
        self.assertIn("backup_count", summary)


if __name__ == "__main__":
    unittest.main()
