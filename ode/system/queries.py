"""Read-only system query ports consumed by the application service."""

from __future__ import annotations

from typing import Protocol

from .models import DatabaseDiagnostics, MigrationStatus


class DiagnosticsQuery(Protocol):
    def diagnostics(self) -> DatabaseDiagnostics:
        """Return a non-mutating full database diagnostic snapshot."""

    def migration_status(self) -> MigrationStatus:
        """Return a non-mutating lightweight schema registry snapshot."""
