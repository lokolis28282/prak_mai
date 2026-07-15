from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from inventory.core.application import create_application_context
from inventory.service import WarehouseError, WarehouseService
from inventory.webapp import make_handler


class _Headers(dict[str, str]):
    def get(self, name: str, default: str = "") -> str:
        return super().get(name, default)


class WebappSecurityTest(unittest.TestCase):
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

    def _login(
        self,
        payload: dict[str, Any],
        *,
        client: str = "127.0.0.1",
    ) -> tuple[int, dict[str, Any], str]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        handler = self.handler_class.__new__(self.handler_class)
        handler.path = "/api/login"
        handler.client_address = (client, 12345)
        handler.headers = _Headers({"Content-Length": str(len(body))})
        handler.rfile = io.BytesIO(body)
        handler._send_json = lambda status, data: setattr(
            handler, "captured", (status, data)
        )
        handler._login()
        status, data = handler.captured
        cookie = getattr(handler, "_pending_cookie", "").split(";", 1)[0]
        return status, data, cookie

    def _session_email(self, cookie: str) -> str:
        handler = self.handler_class.__new__(self.handler_class)
        handler.headers = _Headers({"Cookie": cookie})
        return handler._session_email()

    def _action(self, cookie: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        handler = self.handler_class.__new__(self.handler_class)
        handler.path = "/api/action"
        handler.headers = _Headers({
            "Cookie": cookie,
            "Content-Length": str(len(body)),
        })
        handler.rfile = io.BytesIO(body)
        handler._send_json = lambda status, data: setattr(
            handler, "captured", (status, data)
        )
        with self.service.user_context("lokolis"):
            handler._do_POST()
        return handler.captured

    def test_session_expires_after_twelve_hours_of_inactivity(self) -> None:
        with patch("inventory.webapp.time.monotonic", return_value=100.0):
            status, _, cookie = self._login({
                "mode": "engineer", "full_name": "Иванов Иван",
            })
        self.assertEqual(status, 200)
        self.assertTrue(cookie.startswith("ode_session="))

        with patch("inventory.webapp.time.monotonic", return_value=100.0 + 12 * 60 * 60 + 1):
            self.assertEqual(self._session_email(cookie), "")

    def test_session_store_is_bounded_and_evicts_oldest_session(self) -> None:
        user = self.service.user_by_email("lokolis")
        first_cookie = last_cookie = ""
        with (
            patch("inventory.webapp.time.monotonic", return_value=200.0),
            patch.object(self.service, "user_by_email", return_value=user),
        ):
            for index in range(501):
                status, _, cookie = self._login({
                    "mode": "engineer", "full_name": f"Инженер {index}",
                })
                self.assertEqual(status, 200)
                if index == 0:
                    first_cookie = cookie
                last_cookie = cookie
            self.assertEqual(self._session_email(first_cookie), "")
            self.assertEqual(self._session_email(last_cookie), "lokolis")

    def test_initial_admin_password_allows_only_password_change(self) -> None:
        status, user, cookie = self._login({
            "mode": "admin", "email": "lokolis", "password": "lokolis",
        })
        self.assertEqual(status, 200)
        self.assertEqual(user["user"]["must_change_password"], 1)

        status, blocked = self._action(cookie, {"action": "CHECK_DATABASE"})
        self.assertEqual(status, 400)
        self.assertIn("Сначала смените", blocked["error"])

        status, changed = self._action(cookie, {
            "action": "CHANGE_PASSWORD",
            "old_password": "lokolis",
            "new_password": "secure-stage-17",
        })
        self.assertEqual(status, 200)
        self.assertTrue(changed["ok"])

        status, allowed = self._action(cookie, {"action": "CHECK_DATABASE"})
        self.assertEqual(status, 200)
        self.assertTrue(allowed["integrity"]["ok"])

    def test_engineer_session_cannot_upload_production_database(self) -> None:
        status, _, cookie = self._login({
            "mode": "engineer", "full_name": "Иванов Иван",
        })
        self.assertEqual(status, 200)
        handler = self.handler_class.__new__(self.handler_class)
        handler.path = "/api/upload-prod-db?confirmed=1"
        handler.client_address = ("127.0.0.1", 12345)
        handler.headers = _Headers({
            "Cookie": cookie,
            "Content-Length": "0",
            "X-Filename": "warehouse.db",
        })
        handler.rfile = io.BytesIO(b"")
        handler._send_json = lambda response_status, data: setattr(
            handler, "captured", (response_status, data)
        )

        handler.do_POST()

        response_status, data = handler.captured
        self.assertEqual(response_status, 403)
        self.assertIn("администратора", data["error"])

    def test_engineer_session_is_downgraded_inside_service_context(self) -> None:
        with self.service.user_context(
            "lokolis", author_name="Иванов Иван", role_override="engineer"
        ) as user:
            self.assertEqual(user["role"], "engineer")
            self.assertEqual(self.service.current_user()["role"], "engineer")
            with self.assertRaisesRegex(WarehouseError, "Недостаточно прав"):
                self.service.create_backup()
        self.assertEqual(self.service.current_user()["role"], "admin")

    def test_engineer_http_context_keeps_defense_in_depth_if_route_guard_is_missed(self) -> None:
        status, _, cookie = self._login({
            "mode": "engineer", "full_name": "Иванов Иван",
        })
        self.assertEqual(status, 200)
        body = json.dumps({"action": "CHECK_DATABASE"}).encode("utf-8")
        handler = self.handler_class.__new__(self.handler_class)
        handler.path = "/api/action"
        handler.client_address = ("127.0.0.1", 12345)
        handler.headers = _Headers({
            "Cookie": cookie,
            "Content-Length": str(len(body)),
        })
        handler.rfile = io.BytesIO(body)
        handler._require_admin_session = lambda **_: None
        handler._send_json = lambda response_status, data: setattr(
            handler, "captured", (response_status, data)
        )

        handler.do_POST()

        response_status, data = handler.captured
        self.assertEqual(response_status, 400)
        self.assertIn("Недостаточно прав", data["error"])

    def test_admin_login_is_blocked_after_five_failures(self) -> None:
        user = self.service.user_by_email("lokolis")
        calls = 0

        def reject_password(email: str, password: str) -> dict[str, Any]:
            nonlocal calls
            calls += 1
            raise WarehouseError("Неверный email или пароль")

        with (
            patch("inventory.webapp.time.monotonic", return_value=400.0),
            patch.object(self.service, "authenticate", side_effect=reject_password),
        ):
            statuses = [
                self._login({
                    "mode": "admin", "email": "lokolis", "password": "wrong",
                })[0]
                for _ in range(5)
            ]
            blocked_status, blocked, _ = self._login({
                "mode": "admin", "email": "lokolis", "password": "correct",
            })

        self.assertEqual(statuses, [401, 401, 401, 401, 429])
        self.assertEqual(blocked_status, 429)
        self.assertIn("Слишком много", blocked["error"])
        self.assertEqual(calls, 5)

        with (
            patch("inventory.webapp.time.monotonic", return_value=400.0 + 15 * 60 + 1),
            patch.object(self.service, "authenticate", return_value=user),
        ):
            status, _, cookie = self._login({
                "mode": "admin", "email": "lokolis", "password": "correct",
            })
        self.assertEqual(status, 200)
        self.assertTrue(cookie.startswith("ode_session="))


if __name__ == "__main__":
    unittest.main()
