"""Vacation overlap, substitute, leadership, and coverage rules."""

from __future__ import annotations

from datetime import date
from typing import Any

from inventory.shared.db import connect

from .contracts import VacationRuleError


class VacationConflictRules:
    def detect_conflicts(
        self,
        values: dict[str, Any],
        *,
        exclude_request_id: int | None = None,
    ) -> list[dict[str, Any]]:
        start = date.fromisoformat(values["date_from"])
        end = date.fromisoformat(values["date_to"])
        employee_id = int(values["employee_id"])
        employee = self.repository.employee(employee_id)
        if employee is None:
            raise VacationRuleError("Сотрудник не найден")
        assignment = self.repository.assignment_on(employee_id, start.isoformat())
        if assignment is None:
            raise VacationRuleError(
                "На дату начала отпуска у сотрудника не задана площадка и график"
            )
        conflicts: list[dict[str, Any]] = []
        with connect(self.db_path) as db:
            overlaps = self.repository.overlapping_requests(
                start.isoformat(),
                end.isoformat(),
                exclude_request_id=exclude_request_id,
                db=db,
            )
            for other in overlaps:
                overlap_day = max(
                    start, date.fromisoformat(str(other["date_from"]))
                ).isoformat()
                if int(other["employee_id"]) == employee_id:
                    conflicts.append(
                        {
                            "code": "EMPLOYEE_OVERLAP",
                            "conflict_date": overlap_day,
                            "related_employee_id": employee_id,
                            "details": (
                                f"У {employee['full_name']} уже есть отпуск "
                                f"{other['date_from']}–{other['date_to']}."
                            ),
                        }
                    )
                candidate_leader = bool(
                    employee["is_site_senior"] or employee["is_department_head"]
                )
                other_leader = bool(
                    other["is_site_senior"] or other["is_department_head"]
                )
                if (
                    candidate_leader
                    and other_leader
                    and int(other["employee_id"]) != employee_id
                ):
                    conflicts.append(
                        {
                            "code": "LEADERSHIP_OVERLAP",
                            "conflict_date": overlap_day,
                            "related_employee_id": int(other["employee_id"]),
                            "details": (
                                "Отпуска начальника отдела и старших площадок "
                                f"не должны пересекаться: {other['full_name']}."
                            ),
                        }
                    )
                other_assignment = self.repository.assignment_on(
                    int(other["employee_id"]), overlap_day, db=db
                )
                candidate_assignment = self.repository.assignment_on(
                    employee_id, overlap_day, db=db
                )
                candidate_one_three = bool(
                    candidate_assignment
                    and candidate_assignment["schedule_type"] == "ONE_THREE"
                )
                other_one_three = bool(
                    other_assignment
                    and other_assignment["schedule_type"] == "ONE_THREE"
                )
                if (
                    int(other["employee_id"]) != employee_id
                    and (
                        (bool(employee["is_substitute"]) and other_one_three)
                        or (bool(other["is_substitute"]) and candidate_one_three)
                    )
                ):
                    conflicts.append(
                        {
                            "code": "SUBSTITUTE_OVERLAP",
                            "conflict_date": overlap_day,
                            "related_employee_id": int(other["employee_id"]),
                            "details": (
                                "Отпуск подменного не должен пересекаться с "
                                f"отпуском сотрудника 1/3: {other['full_name']}."
                            ),
                        }
                    )
            conflicts.extend(
                self._coverage_conflicts(db, values, overlaps, start, end)
            )
        return self._deduplicate(conflicts)

    def _coverage_conflicts(
        self,
        db: Any,
        values: dict[str, Any],
        overlaps: list[dict[str, Any]],
        start: date,
        end: date,
    ) -> list[dict[str, Any]]:
        employee_id = int(values["employee_id"])
        substitute_id = values.get("substitute_employee_id")
        conflicts: list[dict[str, Any]] = []
        for day in self.dates(start, end):
            assignment = self.repository.assignment_on(
                employee_id, day.isoformat(), db=db
            )
            if assignment is None or assignment["schedule_type"] != "ONE_THREE":
                continue
            if self.shift_group_on(day) != int(assignment["shift_group"]):
                continue
            day_text = day.isoformat()
            scheduled = self.repository.assignments_on(
                day_text,
                site=str(assignment["site"]),
                schedule_type="ONE_THREE",
                shift_group=int(assignment["shift_group"]),
                db=db,
            )
            remaining = [
                row
                for row in scheduled
                if int(row["employee_id"]) != employee_id
                and not self._employee_absent(int(row["employee_id"]), day, overlaps)
            ]
            if remaining:
                continue
            if substitute_id is not None:
                substitute = self.repository.employee(int(substitute_id))
                substitute_assignment = self.repository.assignment_on(
                    int(substitute_id), day_text, db=db
                )
                if (
                    substitute
                    and bool(substitute["is_substitute"])
                    and substitute_assignment
                    and substitute_assignment["schedule_type"] == "ONE_THREE"
                    and not self._employee_absent(int(substitute_id), day, overlaps)
                ):
                    continue
            conflicts.append(
                {
                    "code": "DUTY_COVERAGE",
                    "conflict_date": day_text,
                    "related_employee_id": (
                        int(substitute_id) if substitute_id is not None else None
                    ),
                    "details": (
                        f"{day.strftime('%d.%m.%Y')} на площадке "
                        f"{self.site_label(str(assignment['site']))} "
                        "в дежурной смене не останется инженера. "
                        "Укажите доступного подменного или отправьте конфликт на решение."
                    ),
                }
            )
        return conflicts

    @staticmethod
    def _employee_absent(
        employee_id: int,
        day: date,
        overlaps: list[dict[str, Any]],
    ) -> bool:
        return any(
            int(request["employee_id"]) == employee_id
            and date.fromisoformat(str(request["date_from"]))
            <= day
            <= date.fromisoformat(str(request["date_to"]))
            for request in overlaps
        )

    @staticmethod
    def _deduplicate(conflicts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        seen: set[tuple[Any, ...]] = set()
        for conflict in conflicts:
            key = (
                conflict["code"],
                conflict.get("conflict_date"),
                conflict.get("related_employee_id"),
            )
            if key not in seen:
                seen.add(key)
                result.append(conflict)
        return result
