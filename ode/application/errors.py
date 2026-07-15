"""Stable application and infrastructure errors exposed by the ODE 0.13 CLI."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


ErrorDetail = str | int | bool | None


@dataclass(frozen=True)
class ErrorBody:
    code: str
    message: str
    details: Mapping[str, ErrorDetail]

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "message": self.message,
            "details": dict(self.details),
        }


class OdeError(Exception):
    """Expected failure with a stable, non-secret error contract."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Mapping[str, ErrorDetail] | None = None,
    ) -> None:
        super().__init__(message)
        self.body = ErrorBody(code, message, details or {})

    @property
    def code(self) -> str:
        return self.body.code

    def to_envelope(self) -> dict[str, object]:
        return {"ok": False, "error": self.body.to_dict()}


class ConfigurationError(OdeError):
    """Configuration or path policy failure."""


class DatabaseError(OdeError):
    """SQLite connection, transaction or verification failure."""


class MigrationError(OdeError):
    """Versioned migration manifest or build failure."""


class UnitOfWorkError(OdeError):
    """Unit-of-work lifecycle violation."""


class UnitOfWorkBeginError(UnitOfWorkError):
    """A Unit of Work could not start its SQLite transaction."""


class UnitOfWorkCommitError(UnitOfWorkError):
    """A Unit of Work could not commit its SQLite transaction."""


class UnitOfWorkRollbackError(UnitOfWorkError):
    """A Unit of Work could not roll back its SQLite transaction."""


class UnitOfWorkCloseError(UnitOfWorkError):
    """A Unit of Work could not close its SQLite connection cleanly."""


class ReadOnlyMutationError(UnitOfWorkError):
    """A mutation was attempted through a read-only Unit of Work."""


class NestedUnitOfWorkError(UnitOfWorkError):
    """A nested write Unit of Work was attempted in one execution context."""
