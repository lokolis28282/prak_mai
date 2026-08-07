from __future__ import annotations

import hashlib
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from inventory.core.application import create_application_context
from inventory.service import WarehouseService


class EquipmentCompositionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "warehouse.db"
        self.service = WarehouseService(self.db_path)
        self.context = create_application_context(
            self.db_path, service=self.service, warehouse_contour="demo"
        )
        self._receipt(
            "TARGET-SERVER-1", "Сервер Dell", equipment_type="Сервер",
            vendor="Dell", model="PowerEdge R650",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _receipt(
        self,
        serial_number: str,
        item_name: str,
        *,
        equipment_type: str = "",
        component_type: str = "",
        vendor: str = "",
        model: str = "",
    ) -> None:
        self.service.add_stock_receipt(**{
            "receipt_date": "2026-08-01",
            "responsible": "Тестов Инженер",
            "item_name": item_name,
            "project": "ODE",
            "serial_number": serial_number,
            "inventory_number": f"INV-{serial_number}",
            "supplier": "Поставщик",
            "vendor": vendor,
            "model": model,
            "shelf": "A-01",
            "object_name": "Склад",
            "datacenter": "Ixcellerate",
            "equipment_type": equipment_type,
            "component_type": component_type,
            "cable_type": "",
            "unit": "шт",
            "quantity": 1,
        })

    def _issue(
        self,
        serial_number: str,
        *,
        issue_date: str,
        task_type: str,
        task_number: str,
        comment: str,
    ) -> None:
        self.service.add_stock_issue(**{
            "issue_date": issue_date,
            "responsible": "Тестов Инженер",
            "task_type": task_type,
            "task_number": task_number,
            "target_serial_number": "TARGET-SERVER-1",
            "target_hostname": "srv-ode-01",
            "source_serial_number": serial_number,
            "source_item_name": "",
            "source_cable_type": "",
            "quantity": 1,
            "comment": comment,
        })

    @staticmethod
    def _sha256(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def test_card_projects_grouped_issue_evidence_without_claiming_slots(self) -> None:
        self._receipt(
            "COMP-QSFP-1", "Трансивер 100G", component_type="Трансивер",
            vendor="Cisco", model="QSFP-100G-SR4",
        )
        self._receipt(
            "COMP-SSD-1", "Накопитель SSD", component_type="SSD",
            vendor="Samsung", model="PM893 1.92TB",
        )
        self._receipt(
            "COMP-RAM-1", "Модуль памяти", component_type="RAM",
            vendor="Hynix", model="64 GB DDR4",
        )
        self._issue(
            "COMP-QSFP-1", issue_date="2026-08-02", task_type="ИЗМ",
            task_number="12345", comment="Подключение uplink",
        )
        self._issue(
            "COMP-SSD-1", issue_date="2026-08-03", task_type="ЗНР",
            task_number="67890", comment="Расширение массива",
        )
        self._issue(
            "COMP-RAM-1", issue_date="2026-08-04", task_type="ПНР",
            task_number="24680", comment="Расширение памяти",
        )

        before = self._sha256(self.db_path)
        card = self.context.warehouse.get_position_card({
            "serial_number": "TARGET-SERVER-1"
        })
        after = self._sha256(self.db_path)

        self.assertEqual(before, after)
        composition = card["composition"]
        self.assertEqual(composition["basis"], "ISSUE_HISTORY")
        self.assertFalse(composition["current_state_confirmed"])
        self.assertFalse(composition["placement_known"])
        self.assertEqual(composition["total_operations"], 3)
        self.assertEqual(composition["total_quantity"], 3)
        self.assertEqual(
            {group["key"] for group in composition["groups"]},
            {"transceivers", "drives", "memory"},
        )
        latest = composition["operations"][0]
        self.assertEqual(latest["source_serial_number"], "COMP-RAM-1")
        self.assertEqual(latest["task_reference"], "ПНР-24680")
        self.assertEqual(latest["task_reference_source"], "fields")
        self.assertEqual(latest["target_hostname"], "srv-ode-01")
        self.assertEqual(latest["current_state"], "unconfirmed")
        self.assertFalse(latest["placement_known"])
        self.assertTrue(any(
            row["event_type"] == "Компонент списан на оборудование"
            and row["task"] == "ИЗМ-12345"
            for row in card["history"]
        ))

    def test_raw_task_number_survives_when_historical_type_is_missing(self) -> None:
        self._receipt(
            "COMP-HBA-1", "HBA адаптер", component_type="HBA",
            vendor="Broadcom", model="9500-16i",
        )
        self._issue(
            "COMP-HBA-1", issue_date="2026-08-02", task_type="ИЗМ",
            task_number="RAW-ONLY-77", comment="Историческая запись",
        )
        with closing(sqlite3.connect(self.db_path)) as db, db:
            db.execute(
                "UPDATE stock_issues SET task_type='' WHERE task_number='RAW-ONLY-77'"
            )
            db.commit()

        card = self.context.warehouse.get_position_card({
            "serial_number": "TARGET-SERVER-1"
        })
        operation = card["composition"]["operations"][0]
        self.assertEqual(operation["task_reference"], "RAW-ONLY-77")
        self.assertEqual(operation["task_reference_source"], "fields")
        self.assertEqual(operation["group_key"], "adapters")

    def test_historical_task_reference_can_be_projected_from_comment(self) -> None:
        self._receipt(
            "COMP-QSFP-COMMENT", "Трансивер 400G",
            component_type="Трансивер", vendor="Huawei", model="400G-VR4",
        )
        self._issue(
            "COMP-QSFP-COMMENT", issue_date="2026-08-02", task_type="ИЗМ",
            task_number="TEMP", comment="Замена по ИЗМ-000112008",
        )
        with closing(sqlite3.connect(self.db_path)) as db, db:
            db.execute(
                "UPDATE stock_issues SET task_type='', task_number='' "
                "WHERE source_serial_number='COMP-QSFP-COMMENT'"
            )
            db.commit()

        operation = self.context.warehouse.get_position_card({
            "serial_number": "TARGET-SERVER-1"
        })["composition"]["operations"][0]
        self.assertEqual(operation["task_reference"], "ИЗМ-000112008")
        self.assertEqual(operation["task_reference_source"], "comment")

    def test_empty_projection_has_stable_explicit_contract(self) -> None:
        composition = self.context.warehouse.get_position_card({
            "serial_number": "TARGET-SERVER-1"
        })["composition"]
        self.assertEqual(composition["total_operations"], 0)
        self.assertEqual(composition["total_quantity"], 0)
        self.assertEqual(composition["groups"], [])
        self.assertEqual(composition["operations"], [])
        self.assertFalse(composition["current_state_confirmed"])
        self.assertFalse(composition["placement_known"])


if __name__ == "__main__":
    unittest.main()
