"""Employee roster and effective-dated assignment persistence."""

from __future__ import annotations

import sqlite3
from typing import Any

from inventory.shared.db import connect


class VacationEmployeeRepository:
    def employees(self, *, active_only: bool = True) -> list[dict[str, Any]]:
        condition = "WHERE employee.is_active = 1" if active_only else ""
        with connect(self.db_path) as db:
            return [
                dict(row)
                for row in db.execute(
                    f"""SELECT employee.*,
                               assignment.site, assignment.schedule_type,
                               assignment.shift_group, assignment.valid_from,
                               assignment.valid_to
                        FROM vacation_employees employee
                        LEFT JOIN vacation_assignments assignment
                          ON assignment.id = (
                              SELECT candidate.id
                              FROM vacation_assignments candidate
                              WHERE candidate.employee_id = employee.id
                                AND candidate.valid_from <= date('now', 'localtime')
                                AND (
                                    candidate.valid_to IS NULL
                                    OR candidate.valid_to >= date('now', 'localtime')
                                )
                              ORDER BY candidate.valid_from DESC, candidate.id DESC
                              LIMIT 1
                          )
                        {condition}
                        ORDER BY employee.last_name COLLATE NOCASE,
                                 employee.first_name COLLATE NOCASE"""
                ).fetchall()
            ]

    def employee(self, employee_id: int) -> dict[str, Any] | None:
        with connect(self.db_path) as db:
            row = db.execute(
                "SELECT * FROM vacation_employees WHERE id = ?",
                (employee_id,),
            ).fetchone()
            return dict(row) if row else None

    def assignment_on(
        self,
        employee_id: int,
        on_date: str,
        *,
        db: sqlite3.Connection | None = None,
    ) -> dict[str, Any] | None:
        sql = """SELECT * FROM vacation_assignments
                 WHERE employee_id = ? AND valid_from <= ?
                   AND (valid_to IS NULL OR valid_to >= ?)
                 ORDER BY valid_from DESC, id DESC LIMIT 1"""
        if db is not None:
            row = db.execute(sql, (employee_id, on_date, on_date)).fetchone()
            return dict(row) if row else None
        with connect(self.db_path) as connection:
            row = connection.execute(
                sql, (employee_id, on_date, on_date)
            ).fetchone()
            return dict(row) if row else None

    def assignments_on(
        self,
        on_date: str,
        *,
        site: str | None = None,
        schedule_type: str | None = None,
        shift_group: int | None = None,
        db: sqlite3.Connection | None = None,
    ) -> list[dict[str, Any]]:
        sql = """SELECT assignment.*, employee.full_name,
                        employee.is_substitute, employee.is_site_senior,
                        employee.is_department_head
                 FROM vacation_assignments assignment
                 JOIN vacation_employees employee ON employee.id = assignment.employee_id
                 WHERE employee.is_active = 1
                   AND assignment.valid_from <= ?
                   AND (assignment.valid_to IS NULL OR assignment.valid_to >= ?)"""
        params: list[Any] = [on_date, on_date]
        if site:
            sql += " AND assignment.site = ?"
            params.append(site)
        if schedule_type:
            sql += " AND assignment.schedule_type = ?"
            params.append(schedule_type)
        if shift_group is not None:
            sql += " AND assignment.shift_group = ?"
            params.append(shift_group)
        sql += " ORDER BY employee.full_name COLLATE NOCASE"
        if db is not None:
            return [dict(row) for row in db.execute(sql, params).fetchall()]
        with connect(self.db_path) as connection:
            return [dict(row) for row in connection.execute(sql, params).fetchall()]

    def add_assignment(
        self,
        employee_id: int,
        site: str,
        schedule_type: str,
        shift_group: int | None,
        valid_from: str,
        note: str,
        *,
        actor: str,
    ) -> int:
        with connect(self.db_path) as db:
            employee = db.execute(
                "SELECT full_name FROM vacation_employees WHERE id = ? AND is_active = 1",
                (employee_id,),
            ).fetchone()
            if employee is None:
                raise LookupError("employee")
            same_date = db.execute(
                """SELECT id FROM vacation_assignments
                   WHERE employee_id = ? AND valid_from = ?""",
                (employee_id, valid_from),
            ).fetchone()
            previous = db.execute(
                """SELECT * FROM vacation_assignments
                   WHERE employee_id = ? AND valid_from < ?
                     AND (valid_to IS NULL OR valid_to >= ?)
                   ORDER BY valid_from DESC, id DESC LIMIT 1""",
                (employee_id, valid_from, valid_from),
            ).fetchone()
            if previous is not None:
                db.execute(
                    """UPDATE vacation_assignments
                       SET valid_to = date(?, '-1 day')
                       WHERE id = ?""",
                    (valid_from, previous["id"]),
                )
            following = db.execute(
                """SELECT valid_from FROM vacation_assignments
                   WHERE employee_id = ? AND valid_from > ?
                   ORDER BY valid_from, id LIMIT 1""",
                (employee_id, valid_from),
            ).fetchone()
            valid_to = (
                str(
                    db.execute(
                        "SELECT date(?, '-1 day')", (following["valid_from"],)
                    ).fetchone()[0]
                )
                if following is not None
                else None
            )
            if same_date is not None:
                assignment_id = int(same_date["id"])
                db.execute(
                    """UPDATE vacation_assignments
                       SET site = ?, schedule_type = ?, shift_group = ?,
                           valid_to = ?, note = ?, created_by = ?,
                           created_at = datetime('now', 'localtime')
                       WHERE id = ?""",
                    (
                        site,
                        schedule_type,
                        shift_group,
                        valid_to,
                        note,
                        actor,
                        assignment_id,
                    ),
                )
            else:
                cursor = db.execute(
                    """INSERT INTO vacation_assignments(
                           employee_id, site, schedule_type, shift_group,
                           valid_from, valid_to, note, created_by
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        employee_id,
                        site,
                        schedule_type,
                        shift_group,
                        valid_from,
                        valid_to,
                        note,
                        actor,
                    ),
                )
                assignment_id = int(cursor.lastrowid)
            details = {
                "employee_id": employee_id,
                "site": site,
                "schedule_type": schedule_type,
                "shift_group": shift_group,
                "valid_from": valid_from,
            }
            self._history(
                db,
                "assignment",
                assignment_id,
                "VACATION_ASSIGNMENT_CHANGED",
                actor,
                details,
            )
            self._audit(
                db,
                action="VACATION_ASSIGNMENT_CHANGED",
                entity_type="vacation_assignment",
                entity_id=assignment_id,
                actor=actor,
                details=details,
            )
            return assignment_id
