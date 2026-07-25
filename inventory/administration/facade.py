"""Public administration facade."""

from __future__ import annotations

from pathlib import Path
from typing import Any


class AdministrationFacade:
    SECRET_KEYS = {"password", "password_hash", "token", "session", "session_token"}

    def __init__(self, service: Any):
        self.service = service

    def _plain(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {
                str(key): self._plain(item)
                for key, item in value.items()
                if str(key) not in self.SECRET_KEYS
            }
        if isinstance(value, list):
            return [self._plain(item) for item in value]
        if hasattr(value, "keys"):
            return self._plain(dict(value))
        return value

    def current_user(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self.get_current_user(*args, **kwargs)

    def get_current_user(self) -> dict[str, Any]:
        return self._plain(self.service.current_user())

    def get_profile(self) -> dict[str, Any]:
        return self.get_current_user()

    def users(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return self.list_users(*args, **kwargs)

    def list_users(self) -> list[dict[str, Any]]:
        return self._plain(self.service.users())

    def get_user(self, email: str) -> dict[str, Any]:
        return self._plain(self.service.user_by_email(email))

    def audit(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return self.list_audit_entries(*args, **kwargs)

    def list_audit_entries(
        self, limit: int = 200, filters: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        rows = self._plain(self.service.audit_entries(limit=limit))
        if not filters:
            return rows
        action = str(filters.get("action") or "")
        author = str(filters.get("author") or "")
        if action:
            rows = [row for row in rows if str(row.get("action") or "") == action]
        if author:
            rows = [row for row in rows if author.lower() in str(row.get("author") or "").lower()]
        return rows

    def backup(self, *args: Any, **kwargs: Any) -> Any:
        return self.service.create_backup(*args, **kwargs)

    def backups(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return self.list_backups(*args, **kwargs)

    def list_backups(self) -> list[dict[str, Any]]:
        rows = self._plain(self.service.list_backups())
        return [
            {
                "name": Path(str(row.get("name", ""))).name,
                "size": row.get("size", 0),
                "modified": row.get("modified", ""),
            }
            for row in rows
            if str(row.get("name", "")).endswith(".db")
        ]

    def restore(self, *args: Any, **kwargs: Any) -> Any:
        return self.service.restore_backup(*args, **kwargs)

    def integrity_check(self, *args: Any, **kwargs: Any) -> Any:
        return self.service.check_integrity(*args, **kwargs)

    def get_database_status(self) -> dict[str, Any]:
        db_path = Path(self.service.db_path)
        return {
            "path": db_path.name,
            "exists": db_path.exists(),
            "size": db_path.stat().st_size if db_path.exists() else 0,
        }

    def get_diagnostics_summary(self) -> dict[str, Any]:
        return {
            "database": self.get_database_status(),
            "backup_count": len(self.list_backups()),
        }

    def get_administration_overview(self) -> dict[str, Any]:
        return {
            "backups": self.list_backups(),
            "audit": self.list_audit_entries(),
            "users": self.list_users(),
        }
