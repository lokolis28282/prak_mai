"""Immutable and validated runtime database configuration."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from ode.application.errors import ConfigurationError
from ode.infrastructure.paths import canonical_database_path


class Environment(str, Enum):
    DEVELOPMENT = "DEVELOPMENT"
    TEST = "TEST"


@dataclass(frozen=True)
class DatabaseConfig:
    db_path: Path
    environment: Environment
    busy_timeout_ms: int
    read_only: bool
    expected_schema_version: int
    expected_application_id: int
    external_path_override: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.environment, Environment):
            raise ConfigurationError(
                "INVALID_ENVIRONMENT", "Only DEVELOPMENT and TEST are supported"
            )
        if not isinstance(self.read_only, bool) or not isinstance(
            self.external_path_override, bool
        ):
            raise ConfigurationError(
                "INVALID_DATABASE_CONFIG", "Boolean configuration fields are malformed"
            )
        if (
            not isinstance(self.busy_timeout_ms, int)
            or isinstance(self.busy_timeout_ms, bool)
            or self.busy_timeout_ms <= 0
        ):
            raise ConfigurationError(
                "INVALID_BUSY_TIMEOUT", "busy_timeout_ms must be greater than zero"
            )
        if (
            not isinstance(self.expected_schema_version, int)
            or isinstance(self.expected_schema_version, bool)
            or not isinstance(self.expected_application_id, int)
            or isinstance(self.expected_application_id, bool)
            or self.expected_schema_version <= 0
            or self.expected_application_id <= 0
        ):
            raise ConfigurationError(
                "INVALID_SCHEMA_EXPECTATION",
                "Expected schema version and application ID must be positive",
            )
        canonical, external = canonical_database_path(
            self.db_path,
            allow_external_dev_path=self.external_path_override,
        )
        object.__setattr__(self, "db_path", canonical)
        object.__setattr__(self, "external_path_override", external)

    @classmethod
    def create(
        cls,
        db_path: str | Path,
        *,
        environment: Environment,
        read_only: bool,
        expected_schema_version: int,
        expected_application_id: int,
        busy_timeout_ms: int = 10_000,
        allow_external_dev_path: bool = False,
    ) -> "DatabaseConfig":
        canonical, external = canonical_database_path(
            db_path, allow_external_dev_path=allow_external_dev_path
        )
        return cls(
            db_path=canonical,
            environment=environment,
            busy_timeout_ms=busy_timeout_ms,
            read_only=read_only,
            expected_schema_version=expected_schema_version,
            expected_application_id=expected_application_id,
            external_path_override=external,
        )
