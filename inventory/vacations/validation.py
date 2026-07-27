"""Input normalization and effective-dated assignment safeguards."""

from __future__ import annotations

from datetime import date
from typing import Any

from .contracts import (
    SCHEDULE_TYPES,
    SFERA_STATUSES,
    SITES,
    VacationRuleError,
)


class VacationValidationRules:
    @staticmethod
    def parse_date(value: Any, label: str) -> date:
        try:
            parsed = date.fromisoformat(str(value or ""))
        except ValueError as error:
            raise VacationRuleError(f"Укажите корректную дату: {label}") from error
        if parsed.year < 2020 or parsed.year > 2100:
            raise VacationRuleError(f"Дата «{label}» вне допустимого диапазона")
        return parsed

    @staticmethod
    def text(value: Any, label: str, maximum: int) -> str:
        if value is None:
            return ""
        if not isinstance(value, str):
            raise VacationRuleError(f"Поле «{label}» должно содержать текст")
        result = " ".join(value.split())
        if len(result) > maximum:
            raise VacationRuleError(
                f"Поле «{label}» не должно превышать {maximum} символов"
            )
        return result

    def request_values(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise VacationRuleError("Данные отпуска должны быть объектом")
        try:
            employee_id = int(payload.get("employee_id"))
        except (TypeError, ValueError) as error:
            raise VacationRuleError("Выберите сотрудника") from error
        employee = self.repository.employee(employee_id)
        if employee is None or not int(employee["is_active"]):
            raise VacationRuleError("Сотрудник не найден или отключен")
        start = self.parse_date(payload.get("date_from"), "Начало отпуска")
        end = self.parse_date(payload.get("date_to"), "Окончание отпуска")
        if end < start:
            raise VacationRuleError(
                "Дата окончания отпуска не может быть раньше даты начала"
            )
        if (end - start).days > 365:
            raise VacationRuleError("Один отпуск не может быть длиннее 366 дней")
        status = str(payload.get("sfera_status") or "PLANNED").strip().upper()
        if status not in SFERA_STATUSES:
            raise VacationRuleError("Выберите корректный статус согласования в Сфере")
        substitute_id: int | None = None
        if payload.get("substitute_employee_id") not in (None, "", 0, "0"):
            try:
                substitute_id = int(payload["substitute_employee_id"])
            except (TypeError, ValueError) as error:
                raise VacationRuleError("Выберите корректного подменного") from error
            substitute = self.repository.employee(substitute_id)
            if substitute is None or not int(substitute["is_active"]):
                raise VacationRuleError("Подменный сотрудник не найден или отключен")
            if substitute_id == employee_id:
                raise VacationRuleError("Сотрудник не может подменять сам себя")
        return {
            "employee_id": employee_id,
            "date_from": start.isoformat(),
            "date_to": end.isoformat(),
            "calendar_days": (end - start).days + 1,
            "sfera_status": status,
            "sfera_reference": self.text(
                payload.get("sfera_reference"), "Ссылка или номер в Сфере", 500
            ),
            "substitute_employee_id": substitute_id,
            "comment": self.text(payload.get("comment"), "Комментарий", 2_000),
        }

    @staticmethod
    def flag(value: Any) -> int:
        if isinstance(value, bool):
            return int(value)
        return int(str(value or "").strip().casefold() in {"1", "true", "on", "yes"})

    def _assignment_fields(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise VacationRuleError("Данные сотрудника должны быть объектом")
        site = str(payload.get("site") or "").strip().casefold()
        if site not in SITES:
            raise VacationRuleError("Выберите площадку IXcellerate, Solar или Гибрид")
        schedule_type = str(payload.get("schedule_type") or "").strip().upper()
        if schedule_type not in SCHEDULE_TYPES:
            raise VacationRuleError("Выберите график 5/2 или 1/3")
        shift_group: int | None = None
        if schedule_type == "ONE_THREE":
            try:
                shift_group = int(payload.get("shift_group"))
            except (TypeError, ValueError) as error:
                raise VacationRuleError("Для графика 1/3 выберите смену 1–4") from error
            if shift_group not in range(4):
                raise VacationRuleError("Для графика 1/3 выберите смену 1–4")
            if site == "hybrid":
                raise VacationRuleError("Дежурную смену 1/3 нужно привязать к площадке")
        return {
            "site": site,
            "schedule_type": schedule_type,
            "shift_group": shift_group,
            "valid_from": self.parse_date(
                payload.get("valid_from"), "Дата начала графика"
            ).isoformat(),
            "note": self.text(payload.get("note"), "Комментарий", 1_000),
        }

    def employee_values(self, payload: dict[str, Any]) -> dict[str, Any]:
        assignment = self._assignment_fields(payload)
        first_name = self.text(payload.get("first_name"), "Имя", 100)
        last_name = self.text(payload.get("last_name"), "Фамилия", 100)
        if not first_name or not last_name:
            raise VacationRuleError("Укажите имя и фамилию сотрудника")
        return {
            "first_name": first_name,
            "last_name": last_name,
            "full_name": f"{last_name} {first_name}",
            "is_site_senior": self.flag(payload.get("is_site_senior")),
            "is_department_head": self.flag(payload.get("is_department_head")),
            "is_substitute": self.flag(payload.get("is_substitute")),
            **assignment,
        }

    def assignment_values(
        self,
        employee_id: Any,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            normalized_employee_id = int(employee_id)
        except (TypeError, ValueError) as error:
            raise VacationRuleError("Сотрудник не найден") from error
        if self.repository.employee(normalized_employee_id) is None:
            raise VacationRuleError("Сотрудник не найден")
        return {"employee_id": normalized_employee_id, **self._assignment_fields(payload)}

    def validate_assignment_change(self, values: dict[str, Any]) -> None:
        """Do not let an effective-dated change empty an IXcellerate duty group."""
        employee_id = int(values["employee_id"])
        valid_from = str(values["valid_from"])
        current = self.repository.assignment_on(employee_id, valid_from)
        if (
            current is None
            or current["site"] != "ixcellerate"
            or current["schedule_type"] != "ONE_THREE"
        ):
            return
        target_keeps_group = (
            values["site"] == "ixcellerate"
            and values["schedule_type"] == "ONE_THREE"
            and values["shift_group"] == current["shift_group"]
        )
        if target_keeps_group:
            return
        remaining = [
            row
            for row in self.repository.assignments_on(
                valid_from,
                site="ixcellerate",
                schedule_type="ONE_THREE",
                shift_group=int(current["shift_group"]),
            )
            if int(row["employee_id"]) != employee_id
        ]
        if not remaining:
            raise VacationRuleError(
                f"Нельзя оставить смену {int(current['shift_group']) + 1} "
                "IXcellerate без дежурного. Сначала назначьте замену в эту смену."
            )
