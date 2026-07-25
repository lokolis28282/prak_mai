"""Explicit ODE 0.13 composition root; construction never creates a schema."""

from __future__ import annotations

from dataclasses import dataclass

from ode.application.config import DatabaseConfig
from ode.infrastructure.database import SQLiteConnectionFactory
from ode.infrastructure.diagnostics import DiagnosticsService
from ode.infrastructure.migrations import MigrationRunner
from ode.system.service import SystemService


@dataclass(frozen=True)
class ApplicationContext:
    config: DatabaseConfig
    connection_factory: SQLiteConnectionFactory
    migration_runner: MigrationRunner
    diagnostics: DiagnosticsService
    system: SystemService


def build_application_context(config: DatabaseConfig) -> ApplicationContext:
    factory = SQLiteConnectionFactory(config)
    runner = MigrationRunner(config)
    diagnostics = DiagnosticsService(config, factory, runner)
    system = SystemService(diagnostics)
    return ApplicationContext(
        config=config,
        connection_factory=factory,
        migration_runner=runner,
        diagnostics=diagnostics,
        system=system,
    )
