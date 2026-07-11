from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from inventory.core.application import create_application_context
from inventory.service import WarehouseService
from inventory.webapp import REPORT_HEADERS, csv_download_bytes, _localized


def assert_semantically_equal(testcase: unittest.TestCase, old, new) -> None:
    testcase.assertEqual(
        json.loads(json.dumps(old, sort_keys=True, default=str)),
        json.loads(json.dumps(new, sort_keys=True, default=str)),
    )


class ReportsEventContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "warehouse.db"
        self.service = WarehouseService(self.db_path)
        self.context = create_application_context(self.db_path, service=self.service)
        self.day = "2026-07-11"
        self.service.add_work_log(
            self.day, "DCIM", "ПНР", "E-1", "Работа", "Выполнено", "Комментарий",
        )
        self.service.add_stock_receipt(**{
            "receipt_date": self.day, "responsible": "Инженер",
            "item_name": "Сервер", "project": "Digital",
            "serial_number": "R-EVENT-1", "inventory_number": "R-EVENT-INV-1",
            "supplier": "Поставщик", "vendor": "Dell", "model": "R650",
            "shelf": "A-01", "object_name": "Склад", "datacenter": "Ixcellerate",
            "equipment_type": "Сервер", "component_type": "", "cable_type": "",
            "unit": "шт", "quantity": "1",
        })
        self.service.add_stock_issue(
            issue_date=self.day, responsible="Инженер", task_type="ПНР",
            task_number="E-ISSUE", source_serial_number="R-EVENT-1",
            quantity="1", comment="Расход",
        )
        preview = self.service.preview_delivery_rows([
            {"serial_number": "R-DELIVERY-1", "delivery_number": "П-2", "supplier": "Поставщик", "quantity": "1", "equipment_unit": "Сервер"},
        ], "delivery.csv")
        delivery_id = self.service.confirm_delivery_preview(preview["preview_id"])
        self.service.accept_delivery_serial(delivery_id, "R-DELIVERY-1")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_daily_and_weekly_reports_match_legacy_results(self) -> None:
        reports = self.context.reports
        assert_semantically_equal(self, self.service.daily_report(self.day), reports.get_daily_report(self.day))
        assert_semantically_equal(self, self.service.weekly_report(self.day, self.day), reports.get_weekly_report(self.day, self.day))
        assert_semantically_equal(self, self.service.weekly_report_rows(self.day, self.day), reports.get_weekly_report_rows(self.day, self.day))

    def test_csv_text_contract_matches_legacy(self) -> None:
        reports = self.context.reports
        old_daily = csv_download_bytes(_localized(self.service.daily_report(self.day), REPORT_HEADERS))
        new_daily = csv_download_bytes(_localized(reports.export_daily_report_rows(self.day), REPORT_HEADERS))
        self.assertEqual(old_daily, new_daily)

        old_weekly = csv_download_bytes(self.service.weekly_report_rows(self.day, self.day))
        new_weekly = csv_download_bytes(reports.export_weekly_report_rows(self.day, self.day))
        self.assertEqual(old_weekly, new_weekly)

    def test_report_blocks_order_and_no_duplicates(self) -> None:
        rows = self.context.reports.get_daily_report(self.day)
        blocks = [row["report_block"] for row in rows]
        self.assertLess(blocks.index("Логи работ"), blocks.index("Приход"))
        self.assertLess(blocks.index("Приход"), blocks.index("Расход"))
        self.assertEqual(len(rows), len({tuple(sorted(row.items())) for row in rows}))


if __name__ == "__main__":
    unittest.main()
