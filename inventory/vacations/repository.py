"""Public repository composed from focused Vacations persistence components."""

from __future__ import annotations

from pathlib import Path

from .repositories import (
    VacationAuditRepository,
    VacationConflictRepository,
    VacationEmployeeRepository,
    VacationRegistrationRepository,
    VacationRequestRepository,
)


class VacationRepository(
    VacationRegistrationRepository,
    VacationEmployeeRepository,
    VacationRequestRepository,
    VacationConflictRepository,
    VacationAuditRepository,
):
    """Stable facade for module persistence; implementation is domain-split."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
