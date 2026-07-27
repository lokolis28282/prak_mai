"""Registry of independent SQLite databases used by one ODE runtime."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


DATABASE_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,63}$")


@dataclass(frozen=True, slots=True)
class RuntimeDatabase:
    """Descriptive database metadata without ownership of domain tables."""

    database_id: str
    label: str
    path: Path
    profile: str
    required_tables: frozenset[str]

    def __post_init__(self) -> None:
        if not DATABASE_ID_PATTERN.fullmatch(self.database_id):
            raise ValueError("Некорректный идентификатор runtime-базы")
        if not self.label.strip():
            raise ValueError("Название runtime-базы не может быть пустым")
        if self.profile not in {"warehouse", "vacations"}:
            raise ValueError("Неизвестный профиль runtime-базы")
        # Keep the lexical target so the backup service can reject symlinks
        # instead of silently resolving them to another database file.
        object.__setattr__(
            self,
            "path",
            Path(os.path.abspath(self.path.expanduser())),
        )
        object.__setattr__(
            self,
            "required_tables",
            frozenset(str(table) for table in self.required_tables),
        )


class RuntimeDatabaseRegistry:
    """Resolve a database id to one exact, independent filesystem target."""

    def __init__(self, databases: Iterable[RuntimeDatabase]):
        entries = tuple(databases)
        if not entries:
            raise ValueError("Registry runtime-баз не может быть пустым")
        by_id: dict[str, RuntimeDatabase] = {}
        by_path: dict[Path, str] = {}
        for database in entries:
            if database.database_id in by_id:
                raise ValueError("Идентификаторы runtime-баз должны быть уникальны")
            if database.path in by_path:
                raise ValueError("Runtime-базы должны использовать разные пути")
            by_id[database.database_id] = database
            by_path[database.path] = database.database_id
        self._databases = entries
        self._by_id = by_id

    def all(self) -> tuple[RuntimeDatabase, ...]:
        return self._databases

    def get(self, database_id: str) -> RuntimeDatabase:
        try:
            return self._by_id[str(database_id or "").strip().lower()]
        except KeyError as error:
            raise ValueError("Неизвестная runtime-база") from error


__all__ = [
    "RuntimeDatabase",
    "RuntimeDatabaseRegistry",
]
