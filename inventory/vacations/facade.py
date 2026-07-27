"""Public application boundary for vacation planning."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any

from inventory.shared.helpers import WarehouseError

from .repository import VacationRepository
from .schema import vacations_schema_ready
from .service import VacationRuleError, VacationService


class VacationError(WarehouseError):
    """User-facing vacation planning error."""


class VacationNotFound(VacationError):
    """Requested vacation entity does not exist."""


class VacationFacade:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.repository = VacationRepository(self.db_path)
        self.service = VacationService(self.db_path)

    def is_ready(self) -> bool:
        return vacations_schema_ready(self.db_path)

    def _require_ready(self) -> None:
        if not self.is_ready():
            raise VacationError(
                "Модуль отпусков не инициализирован. Выполните проверяемую "
                "миграцию runtime-модулей с внешним backup."
            )

    def bootstrap(self, date_from: str = "", date_to: str = "") -> dict[str, Any]:
        self._require_ready()
        today = date.today()
        start = (
            self.service.parse_date(date_from, "Начало периода")
            if date_from
            else today.replace(day=1)
        )
        end = (
            self.service.parse_date(date_to, "Окончание периода")
            if date_to
            else start + timedelta(days=41)
        )
        requests = self.repository.requests(start.isoformat(), end.isoformat())
        active_requests = [
            row
            for row in requests
            if row["sfera_status"] not in {"REJECTED", "CANCELLED"}
            and row["conflict_status"] != "REJECTED"
        ]
        pending = self.repository.conflicts(decision="PENDING")
        return {
            "employees": self._employees_payload(),
            "requests": requests,
            "conflicts": pending,
            "calendar": self.service.calendar(start.isoformat(), end.isoformat()),
            "period": {"date_from": start.isoformat(), "date_to": end.isoformat()},
            "summary": {
                "employees": len(self.repository.employees()),
                "vacations": len(active_requests),
                "pending_conflicts": len({int(row["request_id"]) for row in pending}),
            },
            "options": {
                "sites": [
                    {"value": "ixcellerate", "label": "IXcellerate"},
                    {"value": "solar", "label": "Solar"},
                    {"value": "hybrid", "label": "Гибрид"},
                ],
                "schedules": [
                    {"value": "FIVE_TWO", "label": "5/2"},
                    {"value": "ONE_THREE", "label": "1/3 (24 часа)"},
                ],
                "sfera_statuses": [
                    {"value": "PLANNED", "label": "Запланирован"},
                    {"value": "SUBMITTED", "label": "Отправлен в Сферу"},
                    {"value": "APPROVED", "label": "Согласован в Сфере"},
                    {"value": "REJECTED", "label": "Отклонен в Сфере"},
                    {"value": "CANCELLED", "label": "Отменен"},
                ],
            },
        }

    def _employees_payload(self) -> list[dict[str, Any]]:
        employees = self.repository.employees()
        for employee in employees:
            employee["site_label"] = self.service.site_label(
                str(employee.get("site") or "")
            )
            employee["schedule_label"] = (
                "1/3 (24 часа)"
                if employee.get("schedule_type") == "ONE_THREE"
                else "5/2"
            )
            if employee.get("shift_group") is not None:
                employee["shift_label"] = f"Смена {int(employee['shift_group']) + 1}"
            else:
                employee["shift_label"] = ""
            roles: list[str] = []
            if employee["is_department_head"]:
                roles.append("Начальник отдела")
            if employee["is_site_senior"]:
                roles.append("Старший на площадке")
            if employee["is_substitute"]:
                roles.append("Подменный")
            employee["role_labels"] = roles or ["Инженер"]
        return employees

    def create_employee(
        self,
        payload: dict[str, Any],
        *,
        actor: str,
    ) -> dict[str, Any]:
        self._require_ready()
        try:
            values = self.service.employee_values(payload)
            employee_id = self.repository.create_employee(
                values, actor=self._actor(actor)
            )
            return next(
                row
                for row in self._employees_payload()
                if int(row["id"]) == employee_id
            )
        except VacationRuleError as error:
            raise VacationError(str(error)) from error

    def create_request(self, payload: dict[str, Any], *, actor: str) -> dict[str, Any]:
        self._require_ready()
        try:
            values = self.service.request_values(payload)
            conflicts = (
                []
                if values["sfera_status"] in {"REJECTED", "CANCELLED"}
                else self.service.detect_conflicts(values)
            )
            request_id = self.repository.create_request(
                values, conflicts, actor=self._actor(actor)
            )
            return {
                "request": self.repository.request(request_id),
                "conflicts": self._conflicts_for(request_id),
            }
        except VacationRuleError as error:
            raise VacationError(str(error)) from error

    def update_request(
        self,
        request_id: int,
        payload: dict[str, Any],
        *,
        actor: str,
    ) -> dict[str, Any]:
        self._require_ready()
        if self.repository.request(request_id) is None:
            raise VacationNotFound("Отпуск не найден")
        try:
            values = self.service.request_values(payload)
            conflicts = (
                []
                if values["sfera_status"] in {"REJECTED", "CANCELLED"}
                else self.service.detect_conflicts(
                    values, exclude_request_id=request_id
                )
            )
            self.repository.update_request(
                request_id, values, conflicts, actor=self._actor(actor)
            )
            return {
                "request": self.repository.request(request_id),
                "conflicts": self._conflicts_for(request_id),
            }
        except LookupError as error:
            raise VacationNotFound("Отпуск не найден") from error
        except VacationRuleError as error:
            raise VacationError(str(error)) from error

    def resolve_conflicts(
        self,
        request_id: int,
        decision: str,
        comment: str,
        *,
        actor: str,
    ) -> dict[str, Any]:
        self._require_ready()
        normalized = str(decision or "").strip().upper()
        if normalized not in {"APPROVED", "REJECTED"}:
            raise VacationError("Выберите: подтвердить исключение или отклонить")
        clean_comment = self.service.text(comment, "Комментарий к решению", 2_000)
        try:
            self.repository.resolve_conflicts(
                request_id,
                normalized,
                clean_comment,
                actor=self._actor(actor),
            )
        except LookupError as error:
            raise VacationNotFound("Отпуск не найден") from error
        except ValueError as error:
            raise VacationError("По этому отпуску уже принято решение") from error
        return {"request": self.repository.request(request_id)}

    def change_assignment(
        self,
        employee_id: int,
        payload: dict[str, Any],
        *,
        actor: str,
    ) -> dict[str, Any]:
        self._require_ready()
        try:
            values = self.service.assignment_values(employee_id, payload)
            self.service.validate_assignment_change(values)
            assignment_id = self.repository.add_assignment(
                **values, actor=self._actor(actor)
            )
            return {
                "assignment_id": assignment_id,
                "employee": next(
                    (
                        row
                        for row in self._employees_payload()
                        if int(row["id"]) == int(employee_id)
                    ),
                    None,
                ),
            }
        except LookupError as error:
            raise VacationNotFound("Сотрудник не найден") from error
        except VacationRuleError as error:
            raise VacationError(str(error)) from error

    def history(self, limit: int = 200) -> list[dict[str, Any]]:
        self._require_ready()
        return self.repository.history(min(max(int(limit), 1), 1_000))

    def _conflicts_for(self, request_id: int) -> list[dict[str, Any]]:
        return [
            row
            for row in self.repository.conflicts(decision="")
            if int(row["request_id"]) == int(request_id)
        ]

    @staticmethod
    def _actor(actor: str) -> str:
        return " ".join(str(actor or "").split()) or "Пользователь ODE"
