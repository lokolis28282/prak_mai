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
from inventory.core.context import RuntimeConfig
from inventory.service import WarehouseService
from inventory.vacations.schema import install_vacations_schema
from inventory.webapp import make_handler
from tests.vacations_test_data import seed_test_roster


class _Headers(dict[str, str]):
    def get(self, name: str, default: str = "") -> str:
        return super().get(name, default)


class VacationsApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "warehouse.db"
        self.vacations_path = Path(self.tmp.name) / "vacations.db"
        self.service = WarehouseService(self.db_path)
        install_vacations_schema(self.vacations_path)
        self.context = create_application_context(
            self.db_path,
            service=self.service,
            configuration=RuntimeConfig(
                self.db_path,
                vacations_db_path=self.vacations_path,
            ),
        )
        self.employees = seed_test_roster(self.context.vacations)
        self.handler_class = make_handler(self.context)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def handler(self, path: str, payload: dict[str, Any] | None = None):
        body = (
            json.dumps(payload, ensure_ascii=False).encode("utf-8")
            if payload is not None
            else b""
        )
        handler = self.handler_class.__new__(self.handler_class)
        handler.path = path
        handler.rfile = io.BytesIO(body)
        handler.headers = _Headers(
            {"Content-Length": str(len(body)), "Content-Type": "application/json"}
        )
        handler._send_json = lambda status, response: setattr(
            handler, "captured", (status, response)
        )
        return handler

    def get(self, path: str) -> tuple[int, Any]:
        handler = self.handler(path)
        with self.service.user_context("lokolis", author_name="API Engineer"):
            handler._do_GET()
        return handler.captured

    def post(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        email: str = "lokolis",
    ) -> tuple[int, Any]:
        handler = self.handler(path, payload)
        with self.service.user_context(email, author_name="API Engineer"), self.service.lock:
            handler._do_POST()
        return handler.captured

    def test_bootstrap_create_and_resolve_conflict(self) -> None:
        status, bootstrap = self.get(
            "/api/vacations/bootstrap?date_from=2026-07-26&date_to=2026-07-30"
        )
        self.assertEqual(status, 200, bootstrap)
        self.assertEqual(len(bootstrap["employees"]), 8)
        employee = next(
            row for row in bootstrap["employees"] if row["full_name"] == "Дежурный Один"
        )
        status, created = self.post(
            "/api/vacations/requests",
            {
                "employee_id": employee["id"],
                "date_from": "2026-07-26",
                "date_to": "2026-07-26",
                "sfera_status": "PLANNED",
            },
        )
        self.assertEqual(status, 201, created)
        self.assertEqual(created["request"]["conflict_status"], "PENDING")
        request_id = created["request"]["id"]
        status, resolved = self.post(
            f"/api/vacations/conflicts/{request_id}/resolve",
            {"decision": "APPROVED", "comment": "Проверено"},
        )
        self.assertEqual(status, 200, resolved)
        self.assertEqual(
            resolved["request"]["conflict_status"], "APPROVED_EXCEPTION"
        )
        with closing(sqlite3.connect(self.db_path)) as db:
            self.assertIsNone(
                db.execute(
                    """SELECT 1 FROM sqlite_master
                       WHERE type='table' AND name='vacation_requests'"""
                ).fetchone()
            )
        with closing(sqlite3.connect(self.vacations_path)) as db:
            self.assertGreater(
                db.execute("SELECT count(*) FROM vacation_audit_log").fetchone()[0],
                0,
            )

    def test_engineer_and_viewer_have_same_vacation_planning_access(self) -> None:
        with self.service.user_context("lokolis"):
            self.service.create_user(
                "API",
                "Viewer",
                "Наблюдатель",
                "vacation-viewer@test",
                "secret1",
                "viewer",
            )
        _, bootstrap = self.get(
            "/api/vacations/bootstrap?date_from=2026-08-01&date_to=2026-08-10"
        )
        employee = next(
            row for row in bootstrap["employees"] if row["full_name"] == "Инженер Solar"
        )
        status, created = self.post(
            "/api/vacations/requests",
            {
                "employee_id": employee["id"],
                "date_from": "2026-08-01",
                "date_to": "2026-08-02",
                "sfera_status": "PLANNED",
            },
            email="vacation-viewer@test",
        )
        self.assertEqual(status, 201, created)

    def test_employee_can_be_created_through_public_api(self) -> None:
        status, created = self.post(
            "/api/vacations/employees",
            {
                "first_name": "Новый",
                "last_name": "Инженер",
                "site": "solar",
                "schedule_type": "FIVE_TWO",
                "shift_group": None,
                "valid_from": "2026-07-26",
                "note": "",
            },
        )
        self.assertEqual(status, 201, created)
        self.assertEqual(created["employee"]["full_name"], "Инженер Новый")
        self.assertEqual(created["employee"]["site"], "solar")

        status, duplicate = self.post(
            "/api/vacations/employees",
            {
                "first_name": "Новый",
                "last_name": "Инженер",
                "site": "solar",
                "schedule_type": "FIVE_TWO",
                "valid_from": "2026-07-26",
            },
        )
        self.assertEqual(status, 409, duplicate)
        self.assertEqual(
            duplicate["error"], "Сотрудник с таким ФИО уже существует"
        )
        self.assertNotIn("UNIQUE constraint", duplicate["error"])


if __name__ == "__main__":
    unittest.main()
