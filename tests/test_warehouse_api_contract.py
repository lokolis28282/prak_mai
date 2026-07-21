from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from inventory.core.application import create_application_context
from inventory.service import WarehouseService
from inventory.webapp import make_handler


def assert_semantically_equal(testcase: unittest.TestCase, old: Any, new: Any) -> None:
    testcase.assertEqual(
        json.loads(json.dumps(old, sort_keys=True, default=str)),
        json.loads(json.dumps(new, sort_keys=True, default=str)),
    )


class _Headers:
    def get(self, name: str, default: str = "") -> str:
        return default


class WarehouseReadApiContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "warehouse.db"
        self.service = WarehouseService(self.db_path)
        self.context = create_application_context(
            self.db_path, service=self.service, warehouse_contour="demo"
        )
        receipt = {
            "receipt_date": "2026-07-11", "responsible": "Тестов Инженер",
            "item_name": "Сервер тестовый", "project": "Digital",
            "serial_number": "API-CONTRACT-1", "inventory_number": "INV-API-1",
            "supplier": "Поставщик", "vendor": "Dell", "model": "R650",
            "shelf": "A-01", "object_name": "Склад", "datacenter": "Ixcellerate",
            "equipment_type": "Сервер", "component_type": "", "cable_type": "",
            "unit": "шт", "quantity": "1",
        }
        self.service.add_stock_receipt(**receipt)
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
        with self.service.user_context("lokolis", author_name="Тестов Инженер"), self.service.lock:
            handler._do_GET()
        status, body, content_type = handler._captured
        if content_type.startswith("application/json"):
            return status, json.loads(body.decode("utf-8")), content_type
        return status, body, content_type

    def test_facade_semantics_match_legacy_service(self) -> None:
        facade = self.context.warehouse
        assert_semantically_equal(self, self.service.stock_balance(), facade.get_balance())
        assert_semantically_equal(self, self.service.warehouse_history(), facade.get_warehouse_history())
        assert_semantically_equal(self, self.service.deliveries(), facade.list_deliveries())
        assert_semantically_equal(self, self.service.search_stock_positions("API-CONTRACT-1"), facade.search_warehouse("API-CONTRACT-1"))
        assert_semantically_equal(
            self,
            self.service.position_card(serial_number="API-CONTRACT-1"),
            facade.get_position_card({"serial_number": "API-CONTRACT-1"}),
        )

    def test_api_data_contract_keys_and_plain_json(self) -> None:
        status, payload, _ = self._call_get("/api/data")
        self.assertEqual(status, 200)
        for key in ("stats", "equipment", "operations", "categories", "locations", "balance", "deliveries", "warehouse_history", "warehouse_model_options", "current_user"):
            self.assertIn(key, payload)
        self.assertIsInstance(payload["balance"], list)
        self.assertTrue(any(row["serial_number"] == "API-CONTRACT-1" for row in payload["balance"]))
        self.assertTrue(any(
            row["vendor"] == "Dell" and row["item_type"] == "Сервер" and row["model"] == "R650"
            for row in payload["warehouse_model_options"]
        ))
        json.dumps(payload)

    def test_recent_receipts_exclude_system_opening_balance_rows(self) -> None:
        with closing(sqlite3.connect(self.db_path)) as db:
            db.execute(
                "UPDATE stock_receipts SET is_opening_balance=1 WHERE serial_number=?",
                ("API-CONTRACT-1",),
            )
            db.commit()
        self.service.add_stock_receipt(**{
            "receipt_date": "2026-07-12", "responsible": "Тестов Инженер",
            "item_name": "Трансивер тестовый", "project": "Digital",
            "serial_number": "API-RECENT-2", "inventory_number": "INV-RECENT-2",
            "supplier": "Поставщик", "vendor": "Cisco", "model": "QSFP-100G",
            "shelf": "A-02", "object_name": "Склад", "datacenter": "Ixcellerate",
            "equipment_type": "", "component_type": "Трансивер", "cable_type": "",
            "unit": "шт", "quantity": "1",
        })
        self.service.add_stock_receipt(**{
            "receipt_date": "2026-07-13", "responsible": "Историческая миграция",
            "item_name": "Историческая позиция", "project": "Digital",
            "serial_number": "API-HISTORICAL-3", "inventory_number": "",
            "supplier": "", "vendor": "", "model": "", "shelf": "",
            "object_name": "", "datacenter": "", "equipment_type": "",
            "component_type": "Трансивер", "cable_type": "", "unit": "шт", "quantity": "1",
        })
        self.service.add_stock_issue(
            issue_date="2026-07-13", responsible="Тестов Инженер",
            task_type="ПНР", task_number="API-DATE",
            target_serial_number="API-CONTRACT-1", target_hostname="",
            source_serial_number="API-RECENT-2", source_item_name="",
            source_cable_type="", quantity="1", comment="",
        )
        overview = self.context.warehouse.get_overview()
        serials = [row["serial_number"] for row in overview["recent_receipts"]]
        self.assertIn("API-RECENT-2", serials)
        self.assertNotIn("API-CONTRACT-1", serials)
        self.assertNotIn("API-HISTORICAL-3", serials)
        self.assertTrue(any(
            row["serial_number"] == "API-RECENT-2" and not row["is_opening_balance"]
            for row in overview["warehouse_history"]
        ))
        self.assertTrue(any(
            row["serial_number"] == "API-RECENT-2" and row["event_date"] == "2026-07-12"
            for row in overview["warehouse_history"]
        ))
        self.assertTrue(any(
            row["serial_number"] == "API-RECENT-2" and row["action"] == "Расход"
            and row["event_date"] == "2026-07-13"
            for row in overview["warehouse_history"]
        ))
        self.assertTrue(any(
            row["serial_number"] == "API-HISTORICAL-3" and row["is_opening_balance"]
            for row in overview["warehouse_history"]
        ))

    def test_warehouse_history_is_sorted_by_date_then_newest_id(self) -> None:
        for serial in ("API-ORDER-1", "API-ORDER-2"):
            self.service.add_stock_receipt(**{
                "receipt_date": "2026-07-14", "responsible": "Тестов Инженер",
                "item_name": "Тест порядка", "project": "Digital",
                "serial_number": serial, "inventory_number": "INV-" + serial,
                "supplier": "Поставщик", "vendor": "Dell", "model": "R650",
                "shelf": "A-01", "object_name": "Склад", "datacenter": "Ixcellerate",
                "equipment_type": "Сервер", "component_type": "", "cable_type": "",
                "unit": "шт", "quantity": "1",
            })

        rows = [
            row for row in self.context.warehouse.get_overview()["warehouse_history"]
            if row.get("serial_number") in {"API-ORDER-1", "API-ORDER-2"}
        ]
        self.assertEqual(
            [row["serial_number"] for row in rows],
            ["API-ORDER-2", "API-ORDER-1"],
        )

    def test_empty_warehouse_history_is_returned_as_an_empty_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "empty.db"
            service = WarehouseService(db_path)
            context = create_application_context(
                db_path, service=service, warehouse_contour="demo"
            )
            self.assertEqual(context.warehouse.get_overview()["warehouse_history"], [])

    def test_balance_endpoint_filters_and_csv_contract(self) -> None:
        status, payload, _ = self._call_get("/api/balance?query=API-CONTRACT-1")
        self.assertEqual(status, 200)
        self.assertIn("rows", payload)
        self.assertTrue(any(row["serial_number"] == "API-CONTRACT-1" for row in payload["rows"]))
        status, data, content_type = self._call_get("/export/balance.csv?query=API-CONTRACT-1")
        self.assertEqual(status, 200)
        self.assertIn("text/csv", content_type)
        text = data.decode("utf-8-sig")
        self.assertIn("SN", text)
        self.assertIn("API-CONTRACT-1", text)

    def test_balance_combined_filters_sort_and_pagination(self) -> None:
        self.service.add_stock_receipt(**{
            "receipt_date": "2026-07-12", "responsible": "Тестов Инженер",
            "item_name": "SSD тестовый", "project": "Digital",
            "serial_number": "API-CONTRACT-2", "inventory_number": "INV-API-2",
            "supplier": "Поставщик", "vendor": "Samsung", "model": "PM1733",
            "shelf": "A-02", "object_name": "Склад", "datacenter": "Ixcellerate",
            "equipment_type": "", "component_type": "SSD", "cable_type": "",
            "unit": "шт", "quantity": "1",
        })
        query = urlencode({
            "query": "SSD", "project": "Digital", "supplier": "Поставщик",
            "vendor": "Samsung", "category": "Накопители", "item_type": "SSD",
            "stock_state": "positive", "sort_by": "model", "sort_dir": "desc",
            "limit": "1", "offset": "0",
        })
        status, payload, _ = self._call_get("/api/balance?" + query)
        self.assertEqual(status, 200)
        self.assertEqual([row["serial_number"] for row in payload["rows"]], ["API-CONTRACT-2"])
        self.assertEqual(payload["offset"], 0)
        self.assertFalse(payload["has_previous"])
        self.assertFalse(payload["has_more"])

        status, first, _ = self._call_get(
            "/api/balance?" + urlencode({"limit": "1", "offset": "0", "sort_by": "serial_number"})
        )
        status, second, _ = self._call_get(
            "/api/balance?" + urlencode({"limit": "1", "offset": "1", "sort_by": "serial_number"})
        )
        self.assertTrue(first["has_more"])
        self.assertTrue(second["has_previous"])
        self.assertNotEqual(first["rows"][0]["serial_number"], second["rows"][0]["serial_number"])

    def test_delivery_contract_empty_and_unknown_id(self) -> None:
        status, payload, _ = self._call_get("/api/deliveries")
        self.assertEqual(status, 200)
        self.assertIn("deliveries", payload)
        self.assertIsInstance(payload["deliveries"], list)
        status, payload, _ = self._call_get("/api/delivery?id=999999")
        self.assertEqual(status, 400)
        self.assertIn("error", payload)

    def test_position_search_and_card_contract(self) -> None:
        status, payload, _ = self._call_get("/api/position-search?query=API-CONTRACT-1")
        self.assertEqual(status, 200)
        self.assertIn("rows", payload)
        self.assertTrue(payload["rows"])
        status, card, _ = self._call_get("/api/position-card?serial_number=API-CONTRACT-1")
        self.assertEqual(status, 200)
        self.assertIn("position", card)
        self.assertIn("history", card)
        self.assertEqual(card["position"]["serial_number"], "API-CONTRACT-1")

    def test_legacy_serial_outer_whitespace_is_searchable_without_mutation(self) -> None:
        with closing(sqlite3.connect(self.db_path)) as db, db:
            db.execute(
                "UPDATE stock_receipts SET serial_number=' API-CONTRACT-1 ' "
                "WHERE serial_number='API-CONTRACT-1'"
            )
        status, card, _ = self._call_get(
            "/api/position-card?serial_number=API-CONTRACT-1"
        )
        self.assertEqual(status, 200)
        self.assertEqual(card["position"]["serial_number"], " API-CONTRACT-1 ")


if __name__ == "__main__":
    unittest.main()
