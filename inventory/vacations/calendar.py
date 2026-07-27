"""Duty rotation and combined vacation calendar projection."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Iterable

from .contracts import SHIFT_ANCHOR, VacationRuleError


class VacationCalendarRules:
    @staticmethod
    def dates(start: date, end: date) -> Iterable[date]:
        current = start
        while current <= end:
            yield current
            current += timedelta(days=1)

    @staticmethod
    def shift_group_on(day: date) -> int:
        return (day - SHIFT_ANCHOR).days % 4

    def calendar(self, date_from: str, date_to: str) -> list[dict[str, Any]]:
        start = self.parse_date(date_from, "Начало периода")
        end = self.parse_date(date_to, "Окончание периода")
        if end < start:
            raise VacationRuleError("Конец периода раньше начала")
        if (end - start).days > 365:
            raise VacationRuleError("Период календаря не может быть длиннее 366 дней")
        requests = self.repository.requests(start.isoformat(), end.isoformat())
        requests = [
            request
            for request in requests
            if request["sfera_status"] not in {"REJECTED", "CANCELLED"}
            and request["conflict_status"] != "REJECTED"
        ]
        result: list[dict[str, Any]] = []
        for day in self.dates(start, end):
            day_text = day.isoformat()
            duty = self.repository.assignments_on(
                day_text,
                site="ixcellerate",
                schedule_type="ONE_THREE",
                shift_group=self.shift_group_on(day),
            )
            vacations = [
                request
                for request in requests
                if str(request["date_from"]) <= day_text <= str(request["date_to"])
            ]
            result.append(
                {
                    "date": day_text,
                    "weekday": day.weekday(),
                    "duty_shift_group": self.shift_group_on(day),
                    "duty_employees": [
                        {
                            "id": int(row["employee_id"]),
                            "full_name": row["full_name"],
                        }
                        for row in duty
                    ],
                    "vacations": [
                        {
                            "id": int(row["id"]),
                            "employee_id": int(row["employee_id"]),
                            "full_name": row["full_name"],
                            "site": row.get("site"),
                            "sfera_status": row["sfera_status"],
                            "conflict_status": row["conflict_status"],
                        }
                        for row in vacations
                    ],
                }
            )
        return result

    @staticmethod
    def site_label(site: str) -> str:
        return {
            "ixcellerate": "IXcellerate",
            "solar": "Solar",
            "hybrid": "Гибрид",
        }.get(site, site)
