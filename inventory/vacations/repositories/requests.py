"""Vacation request query and mutation persistence."""

from __future__ import annotations

import sqlite3
from typing import Any, Iterable

from inventory.shared.db import connect


class VacationRequestRepository:
    def requests(
        self,
        date_from: str,
        date_to: str,
        *,
        include_cancelled: bool = False,
    ) -> list[dict[str, Any]]:
        sql = """SELECT request.*, employee.full_name,
                        employee.is_site_senior, employee.is_department_head,
                        substitute.full_name AS substitute_name,
                        assignment.site, assignment.schedule_type,
                        assignment.shift_group
                 FROM vacation_requests request
                 JOIN vacation_employees employee ON employee.id = request.employee_id
                 LEFT JOIN vacation_employees substitute
                   ON substitute.id = request.substitute_employee_id
                 LEFT JOIN vacation_assignments assignment
                   ON assignment.id = (
                       SELECT candidate.id
                       FROM vacation_assignments candidate
                       WHERE candidate.employee_id = request.employee_id
                         AND candidate.valid_from <= request.date_from
                         AND (
                             candidate.valid_to IS NULL
                             OR candidate.valid_to >= request.date_from
                         )
                       ORDER BY candidate.valid_from DESC, candidate.id DESC
                       LIMIT 1
                   )
                 WHERE request.date_from <= ? AND request.date_to >= ?"""
        params: list[Any] = [date_to, date_from]
        if not include_cancelled:
            sql += " AND request.sfera_status <> 'CANCELLED'"
        sql += " ORDER BY request.date_from, employee.full_name COLLATE NOCASE, request.id"
        with connect(self.db_path) as db:
            return [dict(row) for row in db.execute(sql, params).fetchall()]

    def request(
        self,
        request_id: int,
        *,
        db: sqlite3.Connection | None = None,
    ) -> dict[str, Any] | None:
        sql = """SELECT request.*, employee.full_name,
                        employee.is_site_senior, employee.is_department_head,
                        employee.is_substitute,
                        substitute.full_name AS substitute_name
                 FROM vacation_requests request
                 JOIN vacation_employees employee ON employee.id = request.employee_id
                 LEFT JOIN vacation_employees substitute
                   ON substitute.id = request.substitute_employee_id
                 WHERE request.id = ?"""
        if db is not None:
            row = db.execute(sql, (request_id,)).fetchone()
            return dict(row) if row else None
        with connect(self.db_path) as connection:
            row = connection.execute(sql, (request_id,)).fetchone()
            return dict(row) if row else None

    def overlapping_requests(
        self,
        date_from: str,
        date_to: str,
        *,
        exclude_request_id: int | None = None,
        db: sqlite3.Connection,
    ) -> list[dict[str, Any]]:
        sql = """SELECT request.*, employee.full_name,
                        employee.is_site_senior, employee.is_department_head,
                        employee.is_substitute
                 FROM vacation_requests request
                 JOIN vacation_employees employee ON employee.id = request.employee_id
                 WHERE request.date_from <= ? AND request.date_to >= ?
                   AND request.sfera_status NOT IN ('REJECTED', 'CANCELLED')
                   AND request.conflict_status <> 'REJECTED'"""
        params: list[Any] = [date_to, date_from]
        if exclude_request_id is not None:
            sql += " AND request.id <> ?"
            params.append(exclude_request_id)
        return [dict(row) for row in db.execute(sql, params).fetchall()]

    def create_request(
        self,
        values: dict[str, Any],
        conflicts: Iterable[dict[str, Any]],
        *,
        actor: str,
    ) -> int:
        conflicts = list(conflicts)
        with connect(self.db_path) as db:
            cursor = db.execute(
                """INSERT INTO vacation_requests(
                       employee_id, date_from, date_to, calendar_days,
                       sfera_status, sfera_reference, substitute_employee_id,
                       comment, conflict_status, created_by, updated_by
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    values["employee_id"],
                    values["date_from"],
                    values["date_to"],
                    values["calendar_days"],
                    values["sfera_status"],
                    values["sfera_reference"],
                    values["substitute_employee_id"],
                    values["comment"],
                    "PENDING" if conflicts else "NONE",
                    actor,
                    actor,
                ),
            )
            request_id = int(cursor.lastrowid)
            self._replace_conflicts(db, request_id, conflicts)
            self._history(
                db,
                "request",
                request_id,
                "VACATION_REQUEST_CREATED",
                actor,
                {**values, "conflict_count": len(conflicts)},
            )
            self._audit(
                db,
                action="VACATION_REQUEST_CREATED",
                entity_type="vacation_request",
                entity_id=request_id,
                actor=actor,
                details={
                    "employee_id": values["employee_id"],
                    "date_from": values["date_from"],
                    "date_to": values["date_to"],
                    "conflict_count": len(conflicts),
                },
            )
            return request_id

    def update_request(
        self,
        request_id: int,
        values: dict[str, Any],
        conflicts: Iterable[dict[str, Any]],
        *,
        actor: str,
    ) -> None:
        conflicts = list(conflicts)
        with connect(self.db_path) as db:
            cursor = db.execute(
                """UPDATE vacation_requests
                   SET employee_id = ?, date_from = ?, date_to = ?,
                       calendar_days = ?, sfera_status = ?, sfera_reference = ?,
                       substitute_employee_id = ?, comment = ?,
                       conflict_status = ?, updated_by = ?,
                       updated_at = datetime('now', 'localtime')
                   WHERE id = ?""",
                (
                    values["employee_id"],
                    values["date_from"],
                    values["date_to"],
                    values["calendar_days"],
                    values["sfera_status"],
                    values["sfera_reference"],
                    values["substitute_employee_id"],
                    values["comment"],
                    "PENDING" if conflicts else "NONE",
                    actor,
                    request_id,
                ),
            )
            if cursor.rowcount == 0:
                raise LookupError("request")
            db.execute(
                "DELETE FROM vacation_conflicts WHERE request_id = ?",
                (request_id,),
            )
            self._replace_conflicts(db, request_id, conflicts)
            self._history(
                db,
                "request",
                request_id,
                "VACATION_REQUEST_UPDATED",
                actor,
                {**values, "conflict_count": len(conflicts)},
            )
            self._audit(
                db,
                action="VACATION_REQUEST_UPDATED",
                entity_type="vacation_request",
                entity_id=request_id,
                actor=actor,
                details={"conflict_count": len(conflicts)},
            )
