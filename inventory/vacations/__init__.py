"""Vacation planning module."""

from .facade import (
    VacationError,
    VacationFacade,
    VacationNotFound,
)

__all__ = ["VacationError", "VacationFacade", "VacationNotFound"]
