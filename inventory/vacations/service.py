"""Composed vacation planning service with focused rule components."""

from __future__ import annotations

from pathlib import Path

from .calendar import VacationCalendarRules
from .conflict_rules import VacationConflictRules
from .contracts import VacationRuleError
from .repository import VacationRepository
from .validation import VacationValidationRules


class VacationService(
    VacationValidationRules,
    VacationCalendarRules,
    VacationConflictRules,
):
    """Stable application service composed from independent rule groups."""

    def __init__(self, db_path: str | Path):
        self.repository = VacationRepository(db_path)
        self.db_path = Path(db_path)


__all__ = ["VacationRuleError", "VacationService"]
