from __future__ import annotations

import sqlite3
import tempfile
import time
import unittest
from contextlib import closing
from datetime import date
from pathlib import Path

from inventory.core.application import create_application_context
from inventory.service import WarehouseService
from inventory.warehouse.events import WarehouseEvent


def receipt(**overrides):
    data = {
        "receipt_date": "2026-07-11", "responsible": "Инженер",
        "item_name": "Сервер", "project": "Digital",
        "serial_number": "EV-SN-1", "inventory_number": "EV-INV-1",
        "supplier": "Поставщик", "vendor": "Dell", "model": "R650",
        "shelf": "A-01", "object_name": "Склад", "datacenter": "Ixcellerate",
        "equipment_type": "Сервер", "component_type": "", "cable_type": "",
        "unit": "шт", "quantity": "1",
    }
    data.update(overrides)
    return data


class WarehouseEventReaderTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "warehouse.db"
        self.service = WarehouseService(self.db_path)
        self.context = create_application_context(
            self.db_path, service=self.service, warehouse_contour="demo"
        )
        self.reader = self.context.reports.warehouse_events

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_receipt_issue_cable_delivery_and_problem_events(self) -> None:
        today = date.today().isoformat()
        self.service.add_stock_receipt(**receipt(receipt_date=today))
        self.service.import_stock_receipt_rows([receipt(
            receipt_date=today, serial_number="EV-SN-2", inventory_number="EV-INV-2",
            item_name="Массовый сервер",
        )])
        self.service.add_stock_receipt(**receipt(
            receipt_date=today, serial_number="", inventory_number="",
            item_name="Кабель DAC", equipment_type="", cable_type="DAC",
            unit="м", quantity="10",
        ))
        self.service.add_stock_issue(
            issue_date=today, responsible="Инженер", task_type="ПНР",
            task_number="1", source_serial_number="EV-SN-1", quantity="1",
            comment="Расход",
        )
        self.service.add_stock_issue(
            issue_date=today, responsible="Инженер", task_type="ПНР",
            task_number="2", source_item_name="Кабель DAC",
            source_cable_type="DAC", quantity="2", comment="Кабель",
        )
        self.service.import_stock_issue_rows([{
            "issue_date": today, "responsible": "Инженер",
            "task_type": "ПНР", "task_number": "404",
            "source_serial_number": "EV-NOT-FOUND", "quantity": "1",
        }])
        preview = self.service.preview_delivery_rows([
            {"serial_number": "EV-DEL-1", "delivery_number": "П-1", "supplier": "Поставщик", "quantity": "1", "equipment_unit": "Сервер"},
        ], "delivery.csv")
        delivery_id = self.service.confirm_delivery_preview(preview["preview_id"])
        self.service.accept_delivery_serial(delivery_id, "EV-DEL-1")

        events = self.reader.list_report_events(today, today)
        types = {event.event_type for event in events}
        self.assertIn("RECEIPT_CREATED", types)
        self.assertIn("ISSUE_CREATED", types)
        self.assertIn("CABLE_RECEIVED", types)
        self.assertIn("CABLE_ISSUED", types)
        self.assertIn("DELIVERY_IMPORTED", types)
        self.assertIn("DELIVERY_ACCEPTED", types)
        self.assertIn("DATA_PROBLEM_FOUND", types)
        self.assertEqual(len({event.event_id for event in events}), len(events))
        self.assertTrue(all(isinstance(event, WarehouseEvent) for event in events))
        self.assertFalse(any(hasattr(event.metadata, "keys") and event.metadata.__class__.__name__ == "Row" for event in events))

    def test_empty_period_filter_types_order_get_event_and_legacy_missing_fields(self) -> None:
        self.service.add_stock_receipt(**receipt(receipt_date="2026-07-11"))
        with closing(sqlite3.connect(self.db_path)) as db, db:
            db.execute(
                "UPDATE stock_receipts SET responsible='', supplier='', project='' WHERE serial_number='EV-SN-1'"
            )
        self.assertEqual(self.reader.list_report_events("2026-07-01", "2026-07-02"), [])
        events = self.reader.list_events("2026-07-11", "2026-07-11", event_types={"RECEIPT_CREATED"})
        self.assertEqual([event.event_type for event in events], ["RECEIPT_CREATED"])
        self.assertEqual(events[0].actor, "")
        self.assertEqual(events[0].supplier, "")
        self.assertIsNotNone(self.reader.get_event(events[0].event_id))

    def test_problem_events_include_unmatched_issue(self) -> None:
        self.service.import_stock_issue_rows([{
            "issue_date": "2026-07-11", "responsible": "Инженер",
            "task_type": "ПНР", "task_number": "404",
            "source_serial_number": "EV-MISSING", "quantity": "1",
        }])
        problems = self.reader.list_problem_events("2026-07-11", "2026-07-11")
        self.assertTrue(any(event.serial_number == "EV-MISSING" for event in problems))
        self.assertTrue(all(event.event_type == "DATA_PROBLEM_FOUND" for event in problems))

    def test_reads_1000_events_without_n_plus_one_contract(self) -> None:
        rows = [
            receipt(
                receipt_date="2026-07-11", serial_number=f"PERF-{index}",
                inventory_number=f"PERF-INV-{index}",
            )
            for index in range(1000)
        ]
        self.service.import_stock_receipt_rows(rows)
        started = time.monotonic()
        events = self.reader.list_events("2026-07-11", "2026-07-11", event_types={"RECEIPT_CREATED"})
        elapsed = time.monotonic() - started
        self.assertEqual(len(events), 1000)
        self.assertLess(elapsed, 5.0)


if __name__ == "__main__":
    unittest.main()
