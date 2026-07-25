from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path

from inventory.core.application import create_application_context
from inventory.monitoring.facade import MonitoringFacade
from inventory.service import WarehouseService
from inventory.webapp import make_handler


class _Headers(dict[str, str]):
    def get(self, name: str, default: str = "") -> str:
        return super().get(name, default)


class MonitoringApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "warehouse.db"
        self.service = WarehouseService(self.db_path)
        self.context = create_application_context(self.db_path, service=self.service)
        self.context.monitoring = MonitoringFacade(
            rules_dir=Path(self.tmp.name) / "rules",
            collect_dcim=False,
            development_mock=True,
        )
        self.handler_class = make_handler(self.context)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def handler(self, path: str, body: bytes = b""):
        handler = self.handler_class.__new__(self.handler_class)
        handler.path = path
        handler.rfile = io.BytesIO(body)
        handler.headers = _Headers({"Content-Length": str(len(body)), "Content-Type": "application/json"})
        handler._send_json = lambda status, payload: setattr(handler, "captured", (status, payload))
        return handler

    def test_status_and_manual_search_routes(self) -> None:
        status_handler = self.handler("/api/monitoring/status")
        with self.service.user_context("lokolis"):
            status_handler._do_GET()
        self.assertEqual(status_handler.captured[0], 200)
        self.assertTrue(status_handler.captured[1]["capabilities"]["manual_search"])

        body = json.dumps(
            {"host": "server-01", "problem": "BMC unavailable"},
            ensure_ascii=False,
        ).encode("utf-8")
        search_handler = self.handler("/api/monitoring/manual-search", body)
        with self.service.user_context("lokolis"):
            search_handler._do_POST()
        self.assertEqual(search_handler.captured[0], 200)
        self.assertTrue(search_handler.captured[1]["development_mock"])


if __name__ == "__main__":
    unittest.main()
