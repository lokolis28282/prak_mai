"""Employee registration persistence for Vacations."""

from __future__ import annotations

from typing import Any

from inventory.shared.db import connect


class VacationRegistrationRepository:
    def create_employee(self, values: dict[str, Any], *, actor: str) -> int:
        with connect(self.db_path) as db:
            cursor = db.execute(
                """INSERT INTO vacation_employees(
                       first_name, last_name, full_name, is_site_senior,
                       is_department_head, is_substitute
                   ) VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    values["first_name"],
                    values["last_name"],
                    values["full_name"],
                    values["is_site_senior"],
                    values["is_department_head"],
                    values["is_substitute"],
                ),
            )
            employee_id = int(cursor.lastrowid)
            assignment = db.execute(
                """INSERT INTO vacation_assignments(
                       employee_id, site, schedule_type, shift_group,
                       valid_from, note, created_by
                   ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    employee_id,
                    values["site"],
                    values["schedule_type"],
                    values["shift_group"],
                    values["valid_from"],
                    values["note"],
                    actor,
                ),
            )
            details = {
                "full_name": values["full_name"],
                "site": values["site"],
                "schedule_type": values["schedule_type"],
                "shift_group": values["shift_group"],
                "valid_from": values["valid_from"],
            }
            self._history(
                db,
                "employee",
                employee_id,
                "VACATION_EMPLOYEE_CREATED",
                actor,
                details,
            )
            self._history(
                db,
                "assignment",
                int(assignment.lastrowid),
                "VACATION_ASSIGNMENT_CREATED",
                actor,
                details,
            )
            self._audit(
                db,
                action="VACATION_EMPLOYEE_CREATED",
                entity_type="vacation_employee",
                entity_id=employee_id,
                actor=actor,
                details=details,
            )
            return employee_id
