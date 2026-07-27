"""Stable values and validation errors for vacation planning."""

from datetime import date


SHIFT_ANCHOR = date(2026, 7, 26)
SITES = {"ixcellerate", "solar", "hybrid"}
SCHEDULE_TYPES = {"FIVE_TWO", "ONE_THREE"}
SFERA_STATUSES = {"PLANNED", "SUBMITTED", "APPROVED", "REJECTED", "CANCELLED"}


class VacationRuleError(ValueError):
    """Validated user input violates the vacation planning contract."""
