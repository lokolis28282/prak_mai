"""Fictional roster used only by Vacations tests."""

from __future__ import annotations

from typing import Any


TEST_ROSTER = (
    ("Один", "Дежурный", "ixcellerate", "ONE_THREE", 0, False, False, False),
    ("Два", "Дежурный", "ixcellerate", "ONE_THREE", 1, False, False, False),
    ("Три", "Дежурный", "ixcellerate", "ONE_THREE", 2, False, False, False),
    ("Четыре", "Дежурный", "ixcellerate", "ONE_THREE", 3, False, False, False),
    ("Подменный", "Инженер", "ixcellerate", "ONE_THREE", 3, False, False, True),
    ("Площадки", "Старший", "solar", "FIVE_TWO", None, True, False, False),
    ("Отдела", "Начальник", "hybrid", "FIVE_TWO", None, False, True, False),
    ("Solar", "Инженер", "solar", "FIVE_TWO", None, False, False, False),
)


def seed_test_roster(facade: Any) -> dict[str, dict[str, Any]]:
    for (
        first_name,
        last_name,
        site,
        schedule_type,
        shift_group,
        is_site_senior,
        is_department_head,
        is_substitute,
    ) in TEST_ROSTER:
        facade.create_employee(
            {
                "first_name": first_name,
                "last_name": last_name,
                "site": site,
                "schedule_type": schedule_type,
                "shift_group": shift_group,
                "valid_from": "2026-07-26",
                "note": "Фиктивные данные автоматического теста",
                "is_site_senior": is_site_senior,
                "is_department_head": is_department_head,
                "is_substitute": is_substitute,
            },
            actor="Автоматический тест",
        )
    return {
        row["full_name"]: row
        for row in facade.bootstrap("2026-07-26", "2026-08-10")["employees"]
    }
