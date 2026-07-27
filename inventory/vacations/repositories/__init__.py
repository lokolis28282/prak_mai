"""Focused persistence components for the Vacations module."""

from .audit import VacationAuditRepository
from .conflicts import VacationConflictRepository
from .employees import VacationEmployeeRepository
from .registrations import VacationRegistrationRepository
from .requests import VacationRequestRepository

__all__ = [
    "VacationAuditRepository",
    "VacationConflictRepository",
    "VacationEmployeeRepository",
    "VacationRegistrationRepository",
    "VacationRequestRepository",
]
