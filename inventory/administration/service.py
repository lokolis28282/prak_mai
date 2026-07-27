"""Administration application service and compatibility boundary."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Iterable

from ..shared.helpers import WarehouseError
from .audit import AdministrationAuditService
from .backup import AdministrationBackupService
from .diagnostics import AdministrationDiagnosticsService
from .multi_database_backup import MultiDatabaseBackupService
from .runtime_databases import RuntimeDatabase, RuntimeDatabaseRegistry
from .users import AdministrationUserService


class AdministrationService:
    """Own administration use cases independently from the warehouse core."""

    ROLES = ("admin", "engineer", "viewer")

    def __init__(
        self,
        db_path: str | Path,
        *,
        lock: Any,
        key_tables: set[str],
        restore_base_tables: set[str],
    ):
        self.db_path = Path(db_path)
        self.lock = lock
        self.key_tables = set(key_tables)
        self.restore_base_tables = set(restore_base_tables)
        self._actor_email: ContextVar[str | None] = ContextVar(
            f"administration_actor_{id(self)}", default=None
        )
        self._actor_name: ContextVar[str | None] = ContextVar(
            f"administration_actor_name_{id(self)}", default=None
        )
        self._actor_role_override: ContextVar[str | None] = ContextVar(
            f"administration_actor_role_{id(self)}", default=None
        )
        self._actor_user_override: ContextVar[dict[str, Any] | None] = ContextVar(
            f"administration_actor_user_{id(self)}", default=None
        )
        self.audit_service = AdministrationAuditService(self)
        self.user_service = AdministrationUserService(self)
        self.diagnostics_service = AdministrationDiagnosticsService(self)
        self.backup_service = AdministrationBackupService(self)
        self.runtime_database_registry = RuntimeDatabaseRegistry(
            (
                RuntimeDatabase(
                    "warehouse_ix",
                    "IXcellerate",
                    self.db_path,
                    "warehouse",
                    frozenset(self.key_tables),
                ),
            )
        )
        self.multi_database_backup_service = MultiDatabaseBackupService(
            self, self.runtime_database_registry
        )

    def configure_runtime_databases(
        self,
        registry: RuntimeDatabaseRegistry,
        *,
        backup_root: str | Path | None = None,
    ) -> None:
        """Configure runtime file topology at the application composition root."""
        self.runtime_database_registry = registry
        self.multi_database_backup_service.configure(
            registry, backup_root=backup_root
        )

    @staticmethod
    def _public_user(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        return AdministrationUserService.public_user(row)

    def authenticate(
        self, email: str, password: str, *, record_login: bool = True
    ) -> dict[str, Any]:
        return self.user_service.authenticate(
            email, password, record_login=record_login
        )

    def user_by_email(self, email: str) -> dict[str, Any]:
        return self.user_service.user_by_email(email)

    def current_user(self) -> dict[str, Any]:
        return self.user_service.current_user()

    @contextmanager
    def user_context(
        self,
        email: str,
        *,
        author_name: str | None = None,
        role_override: str | None = None,
    ) -> Iterable[dict[str, Any]]:
        with self.user_service.user_context(
            email,
            author_name=author_name,
            role_override=role_override,
        ) as user:
            yield user

    @contextmanager
    def delegated_user_context(
        self,
        user: dict[str, Any],
        *,
        author_name: str | None = None,
        role_override: str | None = None,
    ) -> Iterable[dict[str, Any]]:
        """Trust an already authenticated application user in another DB contour."""
        if role_override not in {None, "engineer", "viewer"}:
            raise WarehouseError("Недопустимое ограничение роли")
        public_user = self._public_user(user)
        email = str(public_user.get("email") or "").strip()
        if not email:
            raise WarehouseError("Пользователь не определён")
        effective_user = dict(public_user)
        if role_override:
            effective_user.update(role=role_override, must_change_password=0)
        email_token = self._actor_email.set(email)
        name_token = self._actor_name.set(
            author_name.strip() if author_name else None
        )
        role_token = self._actor_role_override.set(role_override)
        user_token = self._actor_user_override.set(effective_user)
        try:
            yield effective_user
        finally:
            self._actor_user_override.reset(user_token)
            self._actor_role_override.reset(role_token)
            self._actor_name.reset(name_token)
            self._actor_email.reset(email_token)

    def _require_role(self, *roles: str) -> dict[str, Any]:
        return self.user_service.require_role(*roles)

    def _require_write(self) -> dict[str, Any]:
        return self.user_service.require_write()

    def users(self) -> list[dict[str, Any]]:
        return self.user_service.users()

    def create_user(
        self,
        first_name: str,
        last_name: str,
        position: str,
        email: str,
        password: str,
        role: str,
    ) -> int:
        return self.user_service.create_user(
            first_name, last_name, position, email, password, role
        )

    def change_password(self, old_password: str, new_password: str) -> None:
        self.user_service.change_password(old_password, new_password)

    def update_profile(
        self, first_name: str, last_name: str, position: str
    ) -> dict[str, Any]:
        return self.user_service.update_profile(first_name, last_name, position)

    def _audit(
        self,
        db: sqlite3.Connection,
        action: str,
        entity_type: str,
        entity_id: int | str | None = None,
        details: dict[str, Any] | str | None = None,
    ) -> None:
        self.audit_service.write(db, action, entity_type, entity_id, details)

    def audit_entries(self, limit: int = 200) -> list[dict[str, Any]]:
        return self.audit_service.entries(limit)

    @property
    def backup_dir(self) -> Path:
        return self.backup_service.backup_dir

    def list_backups(self) -> list[dict[str, Any]]:
        return self.backup_service.list_backups()

    def _next_backup_path(self, prefix: str) -> Path:
        return self.backup_service.next_backup_path(prefix)

    def _backup_by_name(self, filename: str) -> Path:
        return self.backup_service.backup_by_name(filename)

    def create_backup(self, prefix: str = "warehouse") -> dict[str, Any]:
        return self.backup_service.create_backup(prefix)

    def restore_backup(
        self, filename: str, confirmed: bool = False
    ) -> dict[str, Any]:
        return self.backup_service.restore_backup(filename, confirmed)

    def replace_production_database(
        self, uploaded_path: str | Path, confirmed: bool = False
    ) -> dict[str, Any]:
        return self.backup_service.replace_production_database(
            uploaded_path, confirmed
        )

    def database_check(
        self,
        path: str | Path | None = None,
        required_tables: set[str] | None = None,
    ) -> dict[str, Any]:
        return self.diagnostics_service.database_check(
            Path(path) if path is not None else self.db_path,
            required_tables if required_tables is not None else self.key_tables,
        )

    def check_integrity(self) -> dict[str, Any]:
        return self.diagnostics_service.check_integrity()

    def runtime_database_statuses(self) -> list[dict[str, Any]]:
        return self.multi_database_backup_service.database_statuses()

    def runtime_database_backups(
        self, database_id: str | None = None
    ) -> list[dict[str, Any]]:
        return self.multi_database_backup_service.list_backups(database_id)

    def runtime_backup_capabilities(self) -> dict[str, Any]:
        return self.multi_database_backup_service.capabilities()

    def create_runtime_database_backup(
        self, database_id: str
    ) -> dict[str, Any]:
        return self.multi_database_backup_service.create_backup(database_id)
