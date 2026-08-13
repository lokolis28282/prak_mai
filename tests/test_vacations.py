from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock

from inventory.vacations import VacationError, VacationFacade
from inventory.vacations.schema import (
    install_vacations_schema,
    prepare_vacations_database,
    vacations_schema_ready,
)
from tests.vacations_test_data import seed_test_roster


class VacationPlanningTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "vacations.db"
        install_vacations_schema(self.db_path)
        self.facade = VacationFacade(self.db_path)
        self.employees = seed_test_roster(self.facade)
        self.bootstrap = self.facade.bootstrap("2026-07-26", "2026-08-10")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def create(self, employee: str, start: str, end: str, **extra):
        return self.facade.create_request(
            {
                "employee_id": self.employees[employee]["id"],
                "date_from": start,
                "date_to": end,
                "sfera_status": "PLANNED",
                **extra,
            },
            actor="Тестовый инженер",
        )

    def test_fresh_database_installs_vacations_idempotently(self) -> None:
        self.assertTrue(vacations_schema_ready(self.db_path))
        before = self.db_path.read_bytes()
        install_vacations_schema(self.db_path)
        employees = self.facade.repository.employees()
        self.assertEqual(len(employees), len(self.employees))
        self.assertTrue(self.db_path.is_file())
        self.assertGreaterEqual(len(self.db_path.read_bytes()), len(before))

        empty = Path(self.tmp.name) / "empty-vacations.db"
        install_vacations_schema(empty)
        self.assertEqual(VacationFacade(empty).bootstrap()["employees"], [])

    def test_prepare_uses_separate_database_and_preserves_warehouse_bytes(self) -> None:
        warehouse = Path(self.tmp.name) / "warehouse.db"
        with closing(sqlite3.connect(warehouse)) as db:
            db.execute("CREATE TABLE warehouse_marker(id INTEGER PRIMARY KEY)")
            db.commit()
        before = warehouse.read_bytes()
        vacations = prepare_vacations_database(warehouse)
        self.assertEqual(
            vacations,
            (Path(self.tmp.name) / "vacations.db").resolve(),
        )
        self.assertEqual(warehouse.read_bytes(), before)
        with closing(sqlite3.connect(warehouse)) as db:
            self.assertIsNone(
                db.execute(
                    """SELECT 1 FROM sqlite_master
                       WHERE type='table' AND name='vacation_employees'"""
                ).fetchone()
            )
        with self.assertRaisesRegex(RuntimeError, "отдельна"):
            prepare_vacations_database(warehouse, warehouse)
        hardlink = Path(self.tmp.name) / "vacations-hardlink.db"
        os.link(warehouse, hardlink)
        with self.assertRaisesRegex(RuntimeError, "hardlink"):
            prepare_vacations_database(warehouse, hardlink)

    def test_installation_warehouse_databases_are_always_forbidden_for_vacations(self) -> None:
        from inventory.shared import runtime_paths

        custom_primary = Path(self.tmp.name) / "custom-primary.db"
        with closing(sqlite3.connect(custom_primary)) as db:
            db.execute("CREATE TABLE custom_marker(id INTEGER PRIMARY KEY)")
        protected_paths = {
            "IXcellerate": Path(self.tmp.name) / "installation-warehouse.db",
            "Solar": Path(self.tmp.name) / "installation-solar.db",
            "Vacations": Path(self.tmp.name) / "installation-vacations.db",
        }
        for protected in protected_paths.values():
            with closing(sqlite3.connect(protected)) as db:
                db.execute("CREATE TABLE protected_marker(id INTEGER PRIMARY KEY)")
        with mock.patch.dict(
            runtime_paths.RUNTIME_DATABASE_PATHS, protected_paths, clear=True
        ):
            for label in ("IXcellerate", "Solar"):
                protected = protected_paths[label]
                before = protected.read_bytes()
                with self.subTest(protected=label), self.assertRaisesRegex(
                    RuntimeError, "отдельна"
                ):
                    prepare_vacations_database(custom_primary, protected)
                self.assertEqual(protected.read_bytes(), before)

                hardlink = Path(self.tmp.name) / f"{protected.stem}-hardlink.db"
                os.link(protected, hardlink)
                with self.assertRaisesRegex(RuntimeError, "hardlink"):
                    prepare_vacations_database(custom_primary, hardlink)
                self.assertEqual(protected.read_bytes(), before)

    def test_fictional_roster_and_one_three_cycle_match_schedule(self) -> None:
        self.assertEqual(len(self.bootstrap["employees"]), 8)
        expected = [
            ("2026-07-26", ["Дежурный Один"]),
            ("2026-07-27", ["Дежурный Два"]),
            ("2026-07-28", ["Дежурный Три"]),
            ("2026-07-29", ["Дежурный Четыре", "Инженер Подменный"]),
        ]
        actual = [
            (day["date"], [item["full_name"] for item in day["duty_employees"]])
            for day in self.bootstrap["calendar"][:4]
        ]
        self.assertEqual(actual, expected)
        self.assertEqual(self.employees["Начальник Отдела"]["site"], "hybrid")
        self.assertTrue(self.employees["Начальник Отдела"]["is_department_head"])
        self.assertTrue(self.employees["Инженер Подменный"]["is_substitute"])

    def test_uncovered_duty_shift_waits_for_conflict_decision(self) -> None:
        result = self.create("Дежурный Один", "2026-07-26", "2026-07-26")
        self.assertEqual(result["request"]["calendar_days"], 1)
        self.assertEqual(result["request"]["conflict_status"], "PENDING")
        self.assertEqual(
            {item["code"] for item in result["conflicts"]},
            {"DUTY_COVERAGE"},
        )
        resolved = self.facade.resolve_conflicts(
            result["request"]["id"],
            "APPROVED",
            "Подтверждено начальником вручную",
            actor="Решающий инженер",
        )
        self.assertEqual(
            resolved["request"]["conflict_status"], "APPROVED_EXCEPTION"
        )

    def test_confirmed_substitute_preserves_duty_coverage(self) -> None:
        result = self.create(
            "Дежурный Один",
            "2026-08-03",
            "2026-08-03",
            substitute_employee_id=self.employees["Инженер Подменный"]["id"],
        )
        self.assertEqual(result["request"]["conflict_status"], "NONE")
        self.assertEqual(result["conflicts"], [])

    def test_department_head_and_site_senior_vacations_cannot_overlap(self) -> None:
        first = self.create("Старший Площадки", "2026-08-01", "2026-08-10")
        self.assertEqual(first["request"]["conflict_status"], "NONE")
        second = self.create("Начальник Отдела", "2026-08-05", "2026-08-12")
        self.assertEqual(second["request"]["conflict_status"], "PENDING")
        self.assertIn(
            "LEADERSHIP_OVERLAP",
            {item["code"] for item in second["conflicts"]},
        )

    def test_substitute_vacation_cannot_overlap_one_three_employee(self) -> None:
        self.create("Дежурный Один", "2026-08-01", "2026-08-01")
        result = self.create("Инженер Подменный", "2026-08-01", "2026-08-01")
        self.assertIn(
            "SUBSTITUTE_OVERLAP",
            {item["code"] for item in result["conflicts"]},
        )

    def test_rejected_conflict_rejects_request_and_records_history(self) -> None:
        result = self.create("Дежурный Два", "2026-07-27", "2026-07-27")
        request_id = int(result["request"]["id"])
        resolved = self.facade.resolve_conflicts(
            request_id,
            "REJECTED",
            "",
            actor="Решающий инженер",
        )
        self.assertEqual(resolved["request"]["conflict_status"], "REJECTED")
        self.assertEqual(resolved["request"]["sfera_status"], "REJECTED")
        calendar = self.facade.bootstrap("2026-07-27", "2026-07-27")["calendar"]
        self.assertEqual(calendar[0]["vacations"], [])
        actions = {row["action"] for row in self.facade.history()}
        self.assertIn("VACATION_CONFLICT_REJECTED", actions)

    def test_site_and_schedule_change_is_effective_dated(self) -> None:
        employee_id = self.employees["Инженер Solar"]["id"]
        self.facade.change_assignment(
            employee_id,
            {
                "site": "ixcellerate",
                "schedule_type": "ONE_THREE",
                "shift_group": 0,
                "valid_from": "2026-08-01",
                "note": "Перевод на площадку",
            },
            actor="Тестовый инженер",
        )
        old = self.facade.repository.assignment_on(employee_id, "2026-07-31")
        new = self.facade.repository.assignment_on(employee_id, "2026-08-01")
        self.assertEqual(old["site"], "solar")
        self.assertEqual(old["valid_to"], "2026-07-31")
        self.assertEqual(new["site"], "ixcellerate")
        self.assertEqual(new["schedule_type"], "ONE_THREE")
        self.assertEqual(new["shift_group"], 0)

        self.facade.change_assignment(
            employee_id,
            {
                "site": "ixcellerate",
                "schedule_type": "ONE_THREE",
                "shift_group": 1,
                "valid_from": "2026-08-01",
                "note": "Исправлена смена",
            },
            actor="Тестовый инженер",
        )
        corrected = self.facade.repository.assignment_on(employee_id, "2026-08-01")
        self.assertEqual(corrected["shift_group"], 1)

    def test_last_ix_duty_engineer_cannot_leave_shift_group(self) -> None:
        duty_id = self.employees["Дежурный Один"]["id"]
        replacement_id = self.employees["Инженер Solar"]["id"]
        transfer = {
            "site": "solar",
            "schedule_type": "FIVE_TWO",
            "shift_group": None,
            "valid_from": "2026-08-01",
            "note": "Перевод на другую площадку",
        }
        with self.assertRaisesRegex(VacationError, "без дежурного"):
            self.facade.change_assignment(
                duty_id, transfer, actor="Тестовый инженер"
            )

        self.facade.change_assignment(
            replacement_id,
            {
                "site": "ixcellerate",
                "schedule_type": "ONE_THREE",
                "shift_group": 0,
                "valid_from": "2026-08-01",
                "note": "Сначала назначена замена",
            },
            actor="Тестовый инженер",
        )
        self.facade.change_assignment(duty_id, transfer, actor="Тестовый инженер")
        assignment = self.facade.repository.assignment_on(duty_id, "2026-08-01")
        self.assertEqual(assignment["site"], "solar")


if __name__ == "__main__":
    unittest.main()
