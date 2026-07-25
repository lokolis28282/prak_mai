from __future__ import annotations

import ast
import inspect
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from inventory.core.application import create_application_context
from inventory.reports.facade import ReportsFacade
from inventory.service import WarehouseService
from inventory.services.warehouse_service import WarehouseCore
from inventory.webapp import make_handler


class ReportsExtractionContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "warehouse.db"
        self.compat = WarehouseService(self.db_path)
        self.context = create_application_context(
            self.db_path,
            service=self.compat,
            warehouse_contour="demo",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def row(self) -> dict[str, str]:
        return {
            "work_date": "2026-07-25",
            "task_source": "ITSM",
            "task_type": "ИНЦ",
            "task_number": "REPORTS-BOUNDARY",
            "description": "Reports extraction contract",
            "status": "Выполнено",
            "comment": "",
        }

    def test_application_context_reuses_one_reports_boundary(self) -> None:
        reports = self.context.reports
        self.assertIsInstance(reports, ReportsFacade)
        self.assertIs(reports, self.compat.reports_service)
        self.assertIs(reports, self.compat.report_service)
        self.assertIs(reports, self.compat._core.reports)
        self.assertIs(
            reports.actor_provider,
            self.compat.administration_service,
        )
        self.assertIs(
            reports.warehouse_events,
            self.compat.warehouse_event_reader,
        )

    def test_reports_facade_does_not_call_core_report_implementations(self) -> None:
        with (
            patch.object(
                WarehouseCore,
                "add_work_log",
                side_effect=AssertionError("legacy add_work_log was called"),
            ),
            patch.object(
                WarehouseCore,
                "daily_report",
                side_effect=AssertionError("legacy daily_report was called"),
            ),
            self.context.administration.user_context(
                "lokolis", author_name="Reports boundary"
            ),
        ):
            log_id = self.context.reports.create_work_log(self.row())
            report = self.context.reports.get_daily_report("2026-07-25")

        self.assertGreater(log_id, 0)
        self.assertTrue(
            any(row["description"] == self.row()["description"] for row in report)
        )

    def test_compatibility_service_delegates_to_same_reports_instance(self) -> None:
        with self.context.administration.user_context("lokolis"):
            log_id = self.compat.add_work_log(
                "2026-07-25",
                "ITSM",
                "ИНЦ",
                "REPORTS-COMPAT",
                "Compatibility delegate",
                "Выполнено",
            )
        self.assertGreater(log_id, 0)
        self.assertEqual(
            self.compat.work_logs("2026-07-25", "2026-07-25"),
            self.context.reports.list_work_logs(
                {"date_from": "2026-07-25", "date_to": "2026-07-25"}
            ),
        )

    def test_webapp_routes_reports_calls_through_context(self) -> None:
        source = inspect.getsource(make_handler)
        forbidden = (
            "service.add_work_log(",
            "service.add_work_logs(",
            "service.work_logs(",
            "service.import_work_log_rows(",
            "service.preview_work_log_rows(",
            "service.confirm_work_log_preview(",
            "service.daily_report(",
            "service.weekly_report(",
            "service.import_daily_report_rows(",
            "service.daily_report_uploads(",
            "service.uploaded_daily_report(",
        )
        for call in forbidden:
            with self.subTest(call=call):
                self.assertNotIn(call, source)

    def test_core_report_methods_are_thin_deprecated_delegates(self) -> None:
        method_names = {
            "add_work_log",
            "add_work_logs",
            "work_logs",
            "import_work_log_rows",
            "preview_work_log_rows",
            "confirm_work_log_preview",
            "daily_report",
            "weekly_report",
            "weekly_report_rows",
            "import_daily_report_rows",
            "daily_report_uploads",
            "uploaded_daily_report",
            "export_work_logs_csv",
        }
        source = inspect.getsource(WarehouseCore)
        tree = ast.parse(source)
        methods = {
            node.name: node
            for node in tree.body[0].body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        for name in method_names:
            with self.subTest(method=name):
                method_source = inspect.getsource(getattr(WarehouseCore, name))
                self.assertIn("DEPRECATED", method_source)
                self.assertLessEqual(len(methods[name].body), 2)

        self.assertNotIn("INSERT INTO work_logs", source)
        self.assertNotIn("FROM work_logs", source)
        self.assertNotIn("INSERT INTO daily_report_uploads", source)
        self.assertNotIn("FROM daily_report_rows", source)


if __name__ == "__main__":
    unittest.main()
