"""Disposable approved-schema fixtures used only by Stage 0.13.1 tests."""

from __future__ import annotations

import shutil
from pathlib import Path
from tempfile import TemporaryDirectory

from ode.application.config import DatabaseConfig, Environment
from ode.infrastructure.migrations import MigrationRunner


APPLICATION_ID = 1329874225
SCHEMA_VERSION = 8


def config(path: Path, *, read_only: bool = False) -> DatabaseConfig:
    return DatabaseConfig.create(
        path,
        environment=Environment.TEST,
        read_only=read_only,
        expected_schema_version=SCHEMA_VERSION,
        expected_application_id=APPLICATION_ID,
    )


class BuiltDatabase:
    def __init__(self) -> None:
        self.temporary = TemporaryDirectory()
        self.path = Path(self.temporary.name) / "ode013.db"
        MigrationRunner(config(self.path)).create()

    def close(self) -> None:
        self.temporary.cleanup()


def copy_ddl(source: Path, destination: Path) -> None:
    destination.mkdir(parents=True)
    for path in source.glob("*.sql"):
        shutil.copy2(path, destination / path.name)
