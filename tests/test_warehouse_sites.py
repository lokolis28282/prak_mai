from __future__ import annotations

from hashlib import sha256
from contextlib import closing
import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from typing import Any

from inventory.core.application import create_application_context
from inventory.core.context import RuntimeConfig
from inventory.service import WarehouseService
from inventory.vacations.schema import install_vacations_schema
from inventory.warehouse.sites import (
    OPERATIONAL_TABLES,
    WarehouseSiteRegistry,
    bootstrap_solar_database,
)
from inventory.webapp import make_handler


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


class _Headers(dict[str, str]):
    def get(self, name: str, default: str = "") -> str:
        return super().get(name, default)


class SolarBootstrapTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.source = root / "warehouse.db"
        self.solar = root / "warehouse_solar.db"
        service = WarehouseService(self.source)
        service.add_reference("vendor", "IX Reference Vendor")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_bootstrap_copies_only_references_and_is_idempotent(self) -> None:
        source_sha = _sha256(self.source)
        result = bootstrap_solar_database(self.source, self.solar)
        self.assertTrue(result["created"])
        self.assertEqual(_sha256(self.source), source_sha)
        with closing(sqlite3.connect(self.solar)) as db:
            for table in OPERATIONAL_TABLES:
                self.assertEqual(
                    db.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0],
                    0,
                    table,
                )
            self.assertIsNotNone(db.execute(
                "SELECT 1 FROM reference_values WHERE kind='vendor' AND name=?",
                ("IX Reference Vendor",),
            ).fetchone())
            db.execute(
                "INSERT INTO reference_values(kind,name) VALUES ('vendor',?)",
                ("Solar Only Vendor",),
            )
            db.commit()

        second = bootstrap_solar_database(self.source, self.solar)
        self.assertFalse(second["created"])
        with closing(sqlite3.connect(self.solar)) as db:
            self.assertIsNotNone(db.execute(
                "SELECT 1 FROM reference_values WHERE kind='vendor' AND name=?",
                ("Solar Only Vendor",),
            ).fetchone())

    def test_bootstrap_rejects_primary_as_solar_target(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "разные БД"):
            bootstrap_solar_database(self.source, self.source)


class WarehouseSiteApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.primary = root / "warehouse.db"
        self.solar = root / "warehouse_solar.db"
        self.vacations = root / "vacations.db"
        install_vacations_schema(self.vacations)
        service = WarehouseService(self.primary)
        service.add_stock_receipt(**{
            "receipt_date": "2026-07-26",
            "responsible": "Тестов Инженер",
            "item_name": "IX Server",
            "project": "IX",
            "serial_number": "IX-ONLY-1",
            "inventory_number": "",
            "supplier": "Supplier",
            "vendor": "Vendor",
            "model": "Model",
            "shelf": "IX-01",
            "object_name": "Склад IXcellerate",
            "datacenter": "Ixcellerate",
            "equipment_type": "Сервер",
            "component_type": "",
            "cable_type": "",
            "unit": "шт",
            "quantity": "1",
        })
        context = create_application_context(
            self.primary,
            service=service,
            configuration=RuntimeConfig(
                self.primary,
                warehouse_contour="production",
                production_db_path=self.primary,
                vacations_db_path=self.vacations,
                settings={
                    "warehouse_sites_enabled": True,
                    "solar_db_path": self.solar,
                },
            ),
        )
        self.context = context
        self.handler = make_handler(context)
        status, _, headers = self._request(
            "POST",
            "/api/login",
            {
                "mode": "engineer",
                "full_name": "Тестов Тест Тестович",
            },
        )
        self.assertEqual(status, 200)
        self.cookie = headers["cookie"]

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        cookie: str = "",
    ) -> tuple[int, dict[str, Any], dict[str, str]]:
        body = (
            json.dumps(payload, ensure_ascii=False).encode("utf-8")
            if payload is not None
            else b""
        )
        handler = self.handler.__new__(self.handler)
        handler.path = path
        handler.client_address = ("127.0.0.1", 12345)
        handler.headers = _Headers({
            "Content-Length": str(len(body)),
            "Content-Type": "application/json",
            "Cookie": cookie,
        })
        handler.rfile = io.BytesIO(body)
        handler._send_json = lambda status, data: setattr(
            handler, "captured", (status, data)
        )
        if method == "GET":
            handler.do_GET()
        else:
            handler.do_POST()
        status, data = handler.captured
        pending = getattr(handler, "_pending_cookie", "")
        return status, data, {
            "cookie": pending.split(";", 1)[0] if pending else cookie
        }

    def test_selection_and_writes_are_isolated_per_session_warehouse(self) -> None:
        status, choices, _ = self._request(
            "GET", "/api/warehouses", cookie=self.cookie
        )
        self.assertEqual(status, 200)
        self.assertEqual(
            [row["key"] for row in choices["warehouses"]],
            ["ixcellerate", "solar"],
        )

        status, primary_data, _ = self._request(
            "GET", "/api/data", cookie=self.cookie
        )
        self.assertEqual(status, 200)
        self.assertEqual(primary_data["warehouse_site"]["key"], "ixcellerate")
        self.assertTrue(any(
            row["serial_number"] == "IX-ONLY-1"
            for row in primary_data["balance"]
        ))

        status, _, _ = self._request(
            "POST",
            "/api/warehouse/select",
            {"warehouse": "solar"},
            cookie=self.cookie,
        )
        self.assertEqual(status, 200)
        status, solar_data, _ = self._request(
            "GET", "/api/data", cookie=self.cookie
        )
        self.assertEqual(status, 200)
        self.assertEqual(solar_data["warehouse_site"]["key"], "solar")
        self.assertEqual(solar_data["balance"], [])
        self.assertEqual(solar_data["recent_receipts"], [])
        self.assertEqual(solar_data["recent_issues"], [])

        solar_receipt = {
            "action": "STOCK_RECEIPT",
            "receipt_date": "2026-07-26",
            "responsible": "Тестов Тест Тестович",
            "item_name": "Solar Server",
            "project": "Solar",
            "serial_number": "SOLAR-ONLY-1",
            "inventory_number": "",
            "supplier": "Supplier",
            "vendor": "Vendor",
            "model": "Model",
            "shelf": "SOLAR-01",
            "object_name": "Склад Solar",
            "datacenter": "Ixcellerate",
            "equipment_type": "Сервер",
            "component_type": "",
            "cable_type": "",
            "unit": "шт",
            "quantity": "1",
        }
        status, result, _ = self._request(
            "POST", "/api/action", solar_receipt, cookie=self.cookie
        )
        self.assertEqual((status, result.get("ok")), (200, True))

        self._request(
            "POST",
            "/api/warehouse/select",
            {"warehouse": "ixcellerate"},
            cookie=self.cookie,
        )
        _, primary_again, _ = self._request(
            "GET", "/api/data", cookie=self.cookie
        )
        primary_serials = {
            row["serial_number"] for row in primary_again["balance"]
        }
        self.assertIn("IX-ONLY-1", primary_serials)
        self.assertNotIn("SOLAR-ONLY-1", primary_serials)
        with closing(sqlite3.connect(self.solar)) as db:
            self.assertEqual(
                db.execute(
                    "SELECT COUNT(*) FROM stock_receipts WHERE serial_number=?",
                    ("SOLAR-ONLY-1",),
                ).fetchone()[0],
                1,
            )

    def test_vacations_stay_in_third_database_when_warehouse_changes(self) -> None:
        self.context.vacations.create_employee(
            {
                "first_name": "Тестовый",
                "last_name": "Инженер",
                "site": "ixcellerate",
                "schedule_type": "FIVE_TWO",
                "valid_from": "2026-07-26",
            },
            actor="Автоматический тест",
        )
        status, before, _ = self._request(
            "GET",
            "/api/vacations/bootstrap?date_from=2026-07-26&date_to=2026-07-30",
            cookie=self.cookie,
        )
        self.assertEqual(status, 200)
        self.assertEqual(len(before["employees"]), 1)
        self._request(
            "POST",
            "/api/warehouse/select",
            {"warehouse": "solar"},
            cookie=self.cookie,
        )
        status, after, _ = self._request(
            "GET",
            "/api/vacations/bootstrap?date_from=2026-07-26&date_to=2026-07-30",
            cookie=self.cookie,
        )
        self.assertEqual(status, 200)
        self.assertEqual(after["employees"], before["employees"])
        self.assertEqual(self.context.vacations.db_path, self.vacations.resolve())
        for path in (self.primary, self.solar):
            with closing(sqlite3.connect(path)) as db:
                self.assertIsNone(
                    db.execute(
                        """SELECT 1 FROM sqlite_master
                           WHERE type='table' AND name='vacation_employees'"""
                    ).fetchone()
                )

    def test_full_inventory_state_is_external_and_isolated(self) -> None:
        registry = WarehouseSiteRegistry(
            self.context,
            solar_db_path=self.solar,
            enable_solar=True,
        )
        primary_full = registry.get("ixcellerate").runtime.app_context.full_inventory
        solar_full = registry.get("solar").runtime.app_context.full_inventory
        self.assertIsNotNone(primary_full)
        self.assertIsNotNone(solar_full)
        self.assertNotEqual(primary_full.paths.root, solar_full.paths.root)
        self.assertEqual(solar_full.paths.root, primary_full.paths.root / "solar")
        self.assertEqual(solar_full._path_error, "")
