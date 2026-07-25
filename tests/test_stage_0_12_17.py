from __future__ import annotations

import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import date
from pathlib import Path
from typing import Any

from inventory.core.application import create_application_context
from inventory.service import WarehouseError, WarehouseService
from inventory.importing import parse_csv_bytes
from inventory.webapp import csv_download_bytes, make_handler


class _Headers:
    def __init__(self, values: dict[str, str] | None = None):
        self.values = values or {}

    def get(self, name: str, default: str = "") -> str:
        return self.values.get(name, default)


class Stage01217Test(unittest.TestCase):
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

    @staticmethod
    def receipt(**overrides: Any) -> dict[str, Any]:
        row = {
            "receipt_date": date.today().isoformat(), "responsible": "Иванов Инженер",
            "order_date": "", "request_number": "REQ-17", "order_number": "ORD-17",
            "plu": "", "item_name": "Сервер ODE", "project": "Digital",
            "serial_number": "ODE-17-SRV", "inventory_number": "ODE-17-INV",
            "supplier": "Поставщик ODE", "vendor": "Dell", "model": "R760",
            "shelf": "A-01", "object_name": "Стойка", "datacenter": "Ixcellerate",
            "equipment_type": "Сервер", "component_type": "", "cable_type": "",
            "unit": "шт", "quantity": 1,
        }
        row.update(overrides)
        return row

    @staticmethod
    def issue(**overrides: Any) -> dict[str, Any]:
        row = {
            "issue_date": date.today().isoformat(), "responsible": "Петров Инженер",
            "task_type": "ПНР", "task_number": "17", "target_serial_number": "",
            "target_hostname": "", "source_serial_number": "", "source_item_name": "",
            "source_cable_type": "", "quantity": 1, "comment": "Stage 0.12.17",
        }
        row.update(overrides)
        return row

    def _call_get(self, path: str, *, admin_session: bool = True) -> tuple[int, Any]:
        handler = self.handler_class.__new__(self.handler_class)
        handler.path = path
        handler.headers = _Headers()
        handler._send = lambda status, body, content_type="application/json": setattr(
            handler, "captured", (status, body, content_type)
        )
        handler._send_download = lambda filename, body: setattr(
            handler, "captured", (200, body, "text/csv")
        )
        if not admin_session:
            handler._require_admin_session = lambda: (_ for _ in ()).throw(
                WarehouseError("Откройте отдельный режим администратора")
            )
        with self.service.user_context("lokolis", author_name="Тестовый Инженер"):
            handler._do_GET()
        status, body, content_type = handler.captured
        return status, json.loads(body.decode("utf-8")) if content_type.startswith("application/json") else body

    def _call_json(self, method: str, path: str, value: Any) -> tuple[int, dict[str, Any]]:
        body = json.dumps(value).encode("utf-8")
        handler = self.handler_class.__new__(self.handler_class)
        handler.path = path
        handler.headers = _Headers({"Content-Length": str(len(body))})
        handler.rfile = io.BytesIO(body)
        handler._send = lambda status, payload, content_type="application/json": setattr(
            handler, "captured", (status, payload)
        )
        with self.service.user_context("lokolis", author_name="Тестовый Инженер"):
            getattr(handler, method)()
        status, payload = handler.captured
        return status, json.loads(payload.decode("utf-8"))

    def test_global_search_and_equipment_card_cover_operational_fields(self) -> None:
        self.service.add_stock_receipt(**self.receipt())
        self.service.add_stock_receipt(**self.receipt(
            serial_number="ODE-17-RAM", inventory_number="ODE-17-RAM-INV",
            item_name="Модуль RAM", equipment_type="", component_type="RAM",
            model="64 GB", quantity=1,
        ))
        self.service.add_stock_issue(**self.issue(
            source_serial_number="ODE-17-RAM", target_serial_number="ODE-17-SRV",
            target_hostname="ode-prod-17",
        ))

        exact = self.service.global_search("ODE-17-SRV")
        self.assertEqual(exact[0]["position"]["serial_number"], "ODE-17-SRV")
        hostname = self.service.global_search("ode-prod-17")
        self.assertEqual(hostname[0]["position"]["serial_number"], "ODE-17-SRV")
        card = self.service.position_card(serial_number="ODE-17-SRV")
        for key in (
            "serial_number", "inventory_number", "item_type", "category", "vendor", "model",
            "hostname", "project", "datacenter", "shelf", "rack_row", "rack_unit", "status",
            "supplier", "delivery_number", "order_number", "receipt_date", "responsible", "comment",
        ):
            self.assertIn(key, card["position"])
        self.assertEqual(card["position"]["hostname"], "ode-prod-17")
        self.assertTrue(any(row["event_type"] == "Установлен компонент" for row in card["history"]))

    def test_exact_serial_search_uses_an_identifier_index(self) -> None:
        self.service.add_stock_receipt(**self.receipt())
        with closing(sqlite3.connect(self.db_path)) as db, db:
            plan = " ".join(str(row[3]) for row in db.execute(
                """EXPLAIN QUERY PLAN SELECT id FROM stock_receipts
                   WHERE trim(serial_number)<>'' AND serial_number=? COLLATE NOCASE LIMIT 30""",
                ("ODE-17-SRV",),
            ))
        self.assertIn("INDEX", plan.upper())
        result = self.service.global_search("ODE-17-SRV")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["position"]["serial_number"], "ODE-17-SRV")

    def test_warehouse_categories_are_aggregated_without_position_materialization(self) -> None:
        self.service.add_stock_receipt(**self.receipt())
        self.service.add_stock_receipt(**self.receipt(
            serial_number="ODE-17-NET", inventory_number="ODE-17-NET-INV",
            item_name="Коммутатор ODE", equipment_type="Сетевое оборудование",
            quantity=1,
        ))
        self.service.add_stock_receipt(**self.receipt(
            serial_number="", inventory_number="", item_name="Патч-корд",
            equipment_type="", cable_type="Оптика", unit="м", quantity=25,
        ))
        categories = {
            row["name"]: row["quantity"] for row in self.service.warehouse_categories()
        }
        self.assertEqual(categories["Серверы"], 1)
        self.assertEqual(categories["Сетевое оборудование"], 1)
        self.assertEqual(categories["Кабели"], 25)

    def test_warehouse_type_summary_and_balance_type_filter_use_full_dataset(self) -> None:
        self.service.add_stock_receipt(**self.receipt())
        self.service.add_stock_receipt(**self.receipt(
            serial_number="ODE-17-SRV-2", inventory_number="ODE-17-SRV-2-INV",
            model="R750", quantity=1,
        ))
        self.service.add_stock_receipt(**self.receipt(
            serial_number="ODE-17-SFP", inventory_number="ODE-17-SFP-INV",
            item_name="Трансивер 100G", equipment_type="Трансивер",
            vendor="Cisco", model="QSFP-100G", quantity=1,
        ))
        self.service.add_stock_receipt(**self.receipt(
            serial_number="ODE-17-RAM", inventory_number="ODE-17-RAM-INV",
            item_name="Модуль памяти", equipment_type="", component_type="RAM",
            model="64 GB", quantity=1,
        ))

        summary = {
            (row["category"], row["item_type"]): row
            for row in self.service.warehouse_type_summary()
        }
        self.assertEqual(summary[("Оборудование", "Сервер")]["positions"], 2)
        self.assertEqual(summary[("Трансиверы", "Трансивер")]["positions"], 1)
        self.assertEqual(summary[("Память", "RAM")]["quantity"], 1)
        model_options = {
            (row["vendor"], row["item_type"], row["model"])
            for row in self.service.warehouse_model_options()
        }
        self.assertIn(("Dell", "Сервер", "R760"), model_options)
        self.assertIn(("Cisco", "Трансивер", "QSFP-100G"), model_options)
        self.assertNotIn(("Cisco", "Сервер", "QSFP-100G"), model_options)

        self.service.add_stock_receipt(**self.receipt(
            serial_number="ODE-17-UNKNOWN", inventory_number="ODE-17-UNKNOWN-INV",
            item_name="Неизвестный компонент", equipment_type="",
            component_type="Прочий компонент", model="Unknown", quantity=1,
        ))
        summary = {
            (row["category"], row["item_type"]): row
            for row in self.service.warehouse_type_summary()
        }
        self.assertEqual(summary[("Другое оборудование", "Прочий компонент")]["quantity"], 1)
        self.assertEqual(
            self.service.stock_balance(category="Другое оборудование")[0]["serial_number"],
            "ODE-17-UNKNOWN",
        )

        # Filtering is performed in SQL before LIMIT, so a type outside the
        # first unfiltered row remains discoverable in a large warehouse.
        filtered = self.service.stock_balance(item_type="Трансивер", limit=1)
        self.assertEqual([row["serial_number"] for row in filtered], ["ODE-17-SFP"])
        sorted_rows = self.service.stock_balance(sort_by="item_type", sort_dir="asc")
        self.assertEqual(
            [row["item_type"] for row in sorted_rows],
            sorted([row["item_type"] for row in sorted_rows], key=str.casefold),
        )

    def test_problem_summary_combines_bounded_rows_and_exact_counts(self) -> None:
        self.service.add_stock_receipt(**self.receipt(project="", shelf=""))
        self.service.import_stock_issue_rows([self.issue(
            source_serial_number="UNKNOWN-ODE-17", task_type="ПНР", task_number="17"
        )])
        summary = self.service.data_quality_summary(limit=1)
        counts = self.service.data_quality_problem_counts()
        rows = self.service.data_quality_problems(limit=1)
        self.assertEqual(summary["counts"], counts)
        self.assertEqual(summary["problems"], rows)
        self.assertEqual(summary["counts"]["unmatched_issues"], 1)
        self.assertEqual(summary["counts"]["incomplete_rows"], 1)

    def test_missing_project_alone_is_not_an_incomplete_row(self) -> None:
        # project is an optional operational tag (Digital/Tech/HGX), not a
        # required field in either receipt form; historical/migrated stock
        # never carries it. Counting it toward incompleteness previously made
        # "problems" flag effectively every receipt.
        self.service.add_stock_receipt(**self.receipt(
            serial_number="ODE-17-NOPROJECT", project="",
        ))
        counts = self.service.data_quality_problem_counts()
        self.assertEqual(counts["incomplete_rows"], 0)

    def test_invalid_numeric_queries_are_400_and_never_leak_trace_details(self) -> None:
        for path in (
            "/api/delivery?id=abc", "/api/global-search?query=server&limit=abc",
            "/api/uploaded-daily-report?id=abc", "/export/uploaded-daily-report.csv?id=abc",
            "/export/delivery.csv?id=abc",
        ):
            with self.subTest(path=path):
                status, payload = self._call_get(path)
                self.assertEqual(status, 400)
                self.assertIn("должен быть целым числом", payload["error"])
                self.assertNotIn("invalid literal", payload["error"])

    def test_json_root_must_be_object_for_action_and_login(self) -> None:
        for value in ([], None, "text", 123):
            with self.subTest(value=value, endpoint="action"):
                status, payload = self._call_json("_do_POST", "/api/action", value)
                self.assertEqual(status, 400)
                self.assertIn("объектом", payload["error"])
            with self.subTest(value=value, endpoint="login"):
                status, payload = self._call_json("_login", "/api/login", value)
                self.assertEqual(status, 401)
                self.assertIn("объектом", payload["error"])

    def test_invalid_field_types_are_user_errors(self) -> None:
        status, payload = self._call_json(
            "_do_POST", "/api/action", {"action": "ADD", "category": {"bad": True}}
        )
        self.assertEqual(status, 400)
        self.assertIn("category", payload["error"])
        status, payload = self._call_json(
            "_login", "/api/login", {"mode": "admin", "email": {"bad": True}, "password": "x"}
        )
        self.assertEqual(status, 401)
        self.assertIn("email", payload["error"])

    def test_action_collection_and_scalar_types_never_reach_http_500(self) -> None:
        cases = (
            {"action": "ADD", "category": 17},
            {"action": "ADD", "category": True},
            {"action": "WORK_LOGS", "rows": ["not-an-object"]},
            {
                "action": "CONFIRM_SCANNED_RECEIPTS",
                "common_fields": {"item_name": {"nested": "value"}},
                "serial_numbers": ["OK"],
            },
            {
                "action": "CONFIRM_SCANNED_ISSUES",
                "common_fields": {},
                "serial_numbers": [False],
            },
            {
                "action": "UPDATE_DELIVERY_LINES", "delivery_id": 1,
                "line_ids": [1], "values": {}, "only_empty": "sometimes",
            },
        )
        for payload in cases:
            with self.subTest(payload=payload):
                status, result = self._call_json("_do_POST", "/api/action", payload)
                self.assertEqual(status, 400)
                self.assertIn("Поле", result["error"])

    def test_boolean_compatibility_and_large_csv_fail_cleanly(self) -> None:
        handler = self.handler_class.__new__(self.handler_class)
        for value, expected in (
            (True, True), (1, True), ("true", True), ("on", True),
            (False, False), (0, False), ("false", False), ("off", False),
        ):
            with self.subTest(value=value):
                self.assertIs(handler._json_boolean(value, "flag"), expected)
        with self.assertRaisesRegex(WarehouseError, "логическим"):
            handler._json_boolean("sometimes", "flag")

        body = "S/N\n" + "\n".join(f"SN-{index}" for index in range(100_000)) + "\n"
        with self.assertRaisesRegex(ValueError, "больше 40,000 строк"):
            parse_csv_bytes(body.encode("utf-8"), "inventory")

    def test_host_allowlist_rejects_dns_names_and_accepts_private_addresses(self) -> None:
        handler = self.handler_class.__new__(self.handler_class)
        self.assertFalse(handler._host_allowed("attacker.example:8765"))
        self.assertTrue(handler._host_allowed("127.0.0.1:8765"))
        self.assertTrue(handler._host_allowed("192.168.10.20:8765"))

    def test_existing_receipt_cannot_be_linked_to_two_deliveries(self) -> None:
        self.service.add_stock_receipt(**self.receipt())
        with closing(sqlite3.connect(self.db_path)) as db, db:
            first = int(db.execute(
                "INSERT INTO deliveries(source_filename,delivery_number,uploaded_by) VALUES ('one.csv','D-ONE','lokolis')"
            ).lastrowid)
            second = int(db.execute(
                "INSERT INTO deliveries(source_filename,delivery_number,uploaded_by) VALUES ('two.csv','D-TWO','lokolis')"
            ).lastrowid)
            for delivery_id in (first, second):
                db.execute(
                    """INSERT INTO delivery_lines(
                           delivery_id,row_number,serial_number,item_name,quantity,updated_by
                       ) VALUES (?,1,'ODE-17-SRV','Сервер ODE',1,'lokolis')""",
                    (delivery_id,),
                )
        with self.service.user_context("lokolis", author_name="Тестовый Инженер"):
            self.context.warehouse.accept_delivery_serial(first, "ODE-17-SRV")
            with self.assertRaisesRegex(WarehouseError, "другой поставкой D-ONE"):
                self.context.warehouse.accept_delivery_serial(second, "ODE-17-SRV")
        with closing(sqlite3.connect(self.db_path)) as db:
            row = db.execute(
                "SELECT state,receipt_id FROM delivery_lines WHERE delivery_id=?", (second,)
            ).fetchone()
        self.assertEqual(row, ("Ожидается", None))

    def test_database_check_rejects_foreign_key_corruption(self) -> None:
        with closing(sqlite3.connect(self.db_path)) as db, db:
            db.execute("PRAGMA foreign_keys = OFF")
            db.execute(
                "INSERT INTO stock_issue_allocations(issue_id, receipt_id, quantity) VALUES (999, 999, 1)"
            )
        result = self.service._database_check(self.db_path, self.service.KEY_TABLES)
        self.assertFalse(result["ok"])
        self.assertTrue(result["foreign_key_errors"])

    def test_audit_export_requires_admin_session(self) -> None:
        status, payload = self._call_get("/export/audit.csv", admin_session=False)
        self.assertEqual(status, 400)
        self.assertIn("администратора", payload["error"])

    def test_csv_download_neutralizes_spreadsheet_formulas(self) -> None:
        text = csv_download_bytes([{"Комментарий": "=HYPERLINK(\"bad\")", "Количество": -1}]).decode("utf-8-sig")
        self.assertIn("'=HYPERLINK", text)
        self.assertIn("-1", text)


if __name__ == "__main__":
    unittest.main()
