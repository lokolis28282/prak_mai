from __future__ import annotations

import json
import tempfile
import unittest
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


class _Headers:
    def get(self, name: str, default: str = "") -> str:
        return default


class ReportsReadApiContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "warehouse.db"
        self.service = WarehouseService(self.db_path)
        self.context = create_application_context(self.db_path, service=self.service)
        self.today = "2026-07-11"
        self.service.add_work_log(
            self.today, "ЗНР", "ПНР", "RPT-1",
            "Проверка отчета; кириллица\nстрока", "Выполнено", "Комментарий; тест",
        )
        self.service.add_stock_receipt(**{
            "receipt_date": self.today, "responsible": "Инженер Отчета",
            "item_name": "Сервер отчета", "project": "Digital",
            "serial_number": "RPT-SN-1", "inventory_number": "RPT-INV-1",
            "supplier": "Поставщик", "vendor": "Dell", "model": "R650",
            "shelf": "A-01", "object_name": "Склад", "datacenter": "Ixcellerate",
            "equipment_type": "Сервер", "component_type": "", "cable_type": "",
            "unit": "шт", "quantity": "1",
        })
        self.service.add_stock_issue(
            issue_date=self.today, responsible="Инженер Отчета", task_type="ПНР",
            task_number="RPT-ISSUE-1", source_serial_number="RPT-SN-1",
            quantity="1", comment="Для отчета",
        )
        self.upload = self.service.import_daily_report_rows("готовый.csv", [{
            "date": self.today, "report_block": "Работы", "task_number": "READY-1",
            "description": "Готовый отчет", "quantity": "1", "serial_number": "READY-SN",
            "responsible": "Инженер", "comment": "CSV",
        }])
        self.handler_class = make_handler(self.context)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _call_get(self, path: str) -> tuple[int, Any, str]:
        handler = self.handler_class.__new__(self.handler_class)
        handler.path = path
        handler.headers = _Headers()

        def send(status: int, body: bytes, content_type: str = "application/json; charset=utf-8") -> None:
            handler._captured = (status, body, content_type)

        def send_download(filename: str, body: bytes) -> None:
            handler._captured = (200, body, f'text/csv; filename="{filename}"')

        handler._send = send
        handler._send_download = send_download
        with self.service.user_context("lokolis", author_name="Инженер Отчета"), self.service.lock:
            handler._do_GET()
        status, body, content_type = handler._captured
        if content_type.startswith("application/json"):
            return status, json.loads(body.decode("utf-8")), content_type
        return status, body, content_type

    def test_facade_semantics_match_legacy_service(self) -> None:
        reports = self.context.reports
        assert_semantically_equal(self, self.service.work_logs(self.today, self.today), reports.list_work_logs({"date_from": self.today, "date_to": self.today}))
        assert_semantically_equal(self, self.service.daily_report(self.today), reports.get_daily_report(self.today))
        assert_semantically_equal(self, self.service.weekly_report(self.today, self.today), reports.get_weekly_report(self.today, self.today))
        assert_semantically_equal(self, self.service.weekly_report_rows(self.today, self.today), reports.get_weekly_report_rows(self.today, self.today))
        assert_semantically_equal(self, self.service.daily_report_uploads(), reports.list_uploaded_reports())
        assert_semantically_equal(self, self.service.uploaded_daily_report(self.upload["id"]), reports.get_uploaded_report(self.upload["id"]))

    def test_work_logs_daily_weekly_json_contracts(self) -> None:
        status, logs, _ = self._call_get(f"/api/work-logs?date_from={self.today}&date_to={self.today}")
        self.assertEqual(status, 200)
        self.assertIn("logs", logs)
        self.assertEqual(logs["logs"][0]["task_number"], "RPT-1")

        status, daily, _ = self._call_get(f"/api/daily-report?date={self.today}")
        self.assertEqual(status, 200)
        self.assertIn("rows", daily)
        self.assertTrue(any(row["report_block"] == "Логи работ" for row in daily["rows"]))
        self.assertTrue(any(row["report_block"] == "Приход" for row in daily["rows"]))
        self.assertTrue(any(row["report_block"] == "Расход" for row in daily["rows"]))

        status, weekly, _ = self._call_get(f"/api/weekly-report?start_date={self.today}&end_date={self.today}")
        self.assertEqual(status, 200)
        self.assertIn("summary", weekly)
        self.assertGreaterEqual(weekly["summary"]["work_logs"], 1)
        self.assertGreaterEqual(weekly["summary"]["receipts"], 1)
        self.assertGreaterEqual(weekly["summary"]["issues"], 1)

    def test_uploaded_report_contract_and_unknown_id(self) -> None:
        status, payload, _ = self._call_get(f"/api/uploaded-daily-report?id={self.upload['id']}")
        self.assertEqual(status, 200)
        self.assertEqual(payload["rows"][0]["task_number"], "READY-1")
        status, payload, _ = self._call_get("/api/uploaded-daily-report?id=999999")
        self.assertEqual(status, 400)
        self.assertIn("error", payload)

    def test_csv_contracts_preserve_bom_headers_and_text(self) -> None:
        checks = [
            (f"/export/work-logs.csv?date_from={self.today}&date_to={self.today}", "work_logs.csv", "Номер задачи", "Проверка отчета"),
            (f"/export/daily-report.csv?date={self.today}", "daily_report.csv", "Блок отчета", "RPT-1"),
            (f"/export/weekly-report.csv?start_date={self.today}&end_date={self.today}", "period_report.csv", "Показатель", "Логи работ"),
            (f"/export/uploaded-daily-report.csv?id={self.upload['id']}", "uploaded_daily_report.csv", "Номер задачи", "READY-1"),
        ]
        for url, filename, header, marker in checks:
            with self.subTest(url=url):
                status, data, content_type = self._call_get(url)
                self.assertEqual(status, 200)
                self.assertIn(filename, content_type)
                self.assertTrue(data.startswith("\ufeff".encode("utf-8")))
                text = data.decode("utf-8-sig")
                self.assertIn(header, text)
                self.assertIn(marker, text)
                self.assertIn(";", text)

    def test_bad_dates_keep_user_errors(self) -> None:
        with self.assertRaises(WarehouseError):
            self.context.reports.get_daily_report("bad-date")
        with self.assertRaises(WarehouseError):
            self.context.reports.get_weekly_report("2026-07-12", "2026-07-11")


if __name__ == "__main__":
    unittest.main()
