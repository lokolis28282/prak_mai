"""Conflict inbox and decision persistence."""

from __future__ import annotations

from typing import Any

from inventory.shared.db import connect


class VacationConflictRepository:
    def conflicts(self, *, decision: str = "PENDING") -> list[dict[str, Any]]:
        with connect(self.db_path) as db:
            return [
                dict(row)
                for row in db.execute(
                    """SELECT conflict.*, request.employee_id, request.date_from,
                              request.date_to, request.calendar_days,
                              request.sfera_status, request.conflict_status,
                              employee.full_name,
                              related.full_name AS related_employee_name
                       FROM vacation_conflicts conflict
                       JOIN vacation_requests request ON request.id = conflict.request_id
                       JOIN vacation_employees employee ON employee.id = request.employee_id
                       LEFT JOIN vacation_employees related
                         ON related.id = conflict.related_employee_id
                       WHERE (? = '' OR conflict.decision = ?)
                       ORDER BY request.date_from, conflict.request_id, conflict.id""",
                    (decision, decision),
                ).fetchall()
            ]

    def resolve_conflicts(
        self,
        request_id: int,
        decision: str,
        comment: str,
        *,
        actor: str,
    ) -> None:
        with connect(self.db_path) as db:
            request = self.request(request_id, db=db)
            if request is None:
                raise LookupError("request")
            pending_count = int(
                db.execute(
                    """SELECT count(*) FROM vacation_conflicts
                       WHERE request_id = ? AND decision = 'PENDING'""",
                    (request_id,),
                ).fetchone()[0]
            )
            if pending_count == 0:
                raise ValueError("resolved")
            db.execute(
                """UPDATE vacation_conflicts
                   SET decision = ?, resolved_by = ?, resolution_comment = ?,
                       resolved_at = datetime('now', 'localtime')
                   WHERE request_id = ? AND decision = 'PENDING'""",
                (decision, actor, comment, request_id),
            )
            if decision == "REJECTED":
                db.execute(
                    """UPDATE vacation_requests
                       SET conflict_status = 'REJECTED', sfera_status = 'REJECTED',
                           updated_by = ?, updated_at = datetime('now', 'localtime')
                       WHERE id = ?""",
                    (actor, request_id),
                )
            else:
                db.execute(
                    """UPDATE vacation_requests
                       SET conflict_status = 'APPROVED_EXCEPTION',
                           updated_by = ?, updated_at = datetime('now', 'localtime')
                       WHERE id = ?""",
                    (actor, request_id),
                )
            action = (
                "VACATION_CONFLICT_APPROVED"
                if decision == "APPROVED"
                else "VACATION_CONFLICT_REJECTED"
            )
            details = {
                "decision": decision,
                "comment": comment,
                "conflict_count": pending_count,
            }
            self._history(db, "conflict", request_id, action, actor, details)
            self._audit(
                db,
                action=action,
                entity_type="vacation_request",
                entity_id=request_id,
                actor=actor,
                details=details,
            )
