"""Users, authentication, actor context, and role policy."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Any, Iterable, Protocol

from ..db import connect, hash_password, verify_password
from ..shared.helpers import WarehouseError


class AdministrationContext(Protocol):
    db_path: Any
    ROLES: tuple[str, ...]
    _actor_email: Any
    _actor_name: Any
    _actor_role_override: Any
    _actor_user_override: Any

    def _audit(
        self,
        db: sqlite3.Connection,
        action: str,
        entity_type: str,
        entity_id: int | str | None = None,
        details: dict[str, Any] | str | None = None,
    ) -> None: ...


class AdministrationUserService:
    def __init__(self, context: AdministrationContext):
        self.context = context

    @staticmethod
    def public_user(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        data = dict(row)
        data.pop("password_hash", None)
        return data

    @staticmethod
    def _required(value: str, field: str) -> str:
        value = value.strip()
        if not value:
            raise WarehouseError(f"Поле «{field}» не может быть пустым")
        return value

    def authenticate(
        self, email: str, password: str, *, record_login: bool = True
    ) -> dict[str, Any]:
        email = self._required(email, "email")
        with connect(self.context.db_path) as db:
            row = db.execute(
                "SELECT * FROM users WHERE email = ? COLLATE NOCASE AND is_active = 1",
                (email,),
            ).fetchone()
            if row is None or not verify_password(password, str(row["password_hash"])):
                raise WarehouseError("Неверный email или пароль")
            if record_login:
                token = self.context._actor_email.set(str(row["email"]))
                try:
                    self.context._audit(db, "LOGIN", "user", row["id"])
                finally:
                    self.context._actor_email.reset(token)
            return self.public_user(row)

    def user_by_email(self, email: str) -> dict[str, Any]:
        with connect(self.context.db_path) as db:
            row = db.execute(
                "SELECT * FROM users WHERE email = ? COLLATE NOCASE AND is_active = 1",
                (email,),
            ).fetchone()
        if row is None:
            raise WarehouseError("Пользователь не найден или отключён")
        return self.public_user(row)

    def current_user(self) -> dict[str, Any]:
        delegated = self.context._actor_user_override.get()
        user = (
            dict(delegated)
            if delegated is not None
            else self.user_by_email(self.context._actor_email.get() or "lokolis")
        )
        role_override = self.context._actor_role_override.get()
        if role_override:
            user = {**user, "role": role_override, "must_change_password": 0}
        return user

    @contextmanager
    def user_context(
        self,
        email: str,
        *,
        author_name: str | None = None,
        role_override: str | None = None,
    ) -> Iterable[dict[str, Any]]:
        if role_override not in {None, "engineer", "viewer"}:
            raise WarehouseError("Недопустимое ограничение роли")
        user = self.user_by_email(email)
        token = self.context._actor_email.set(str(user["email"]))
        name_token = self.context._actor_name.set(
            author_name.strip() if author_name else None
        )
        role_token = self.context._actor_role_override.set(role_override)
        try:
            yield self.current_user()
        finally:
            self.context._actor_role_override.reset(role_token)
            self.context._actor_name.reset(name_token)
            self.context._actor_email.reset(token)

    def require_role(self, *roles: str) -> dict[str, Any]:
        user = self.current_user()
        if user["role"] not in roles:
            raise WarehouseError("Недостаточно прав для выполнения операции")
        return user

    def require_write(self) -> dict[str, Any]:
        return self.require_role("admin", "engineer")

    def users(self) -> list[dict[str, Any]]:
        self.require_role("admin")
        with connect(self.context.db_path) as db:
            return [
                self.public_user(row)
                for row in db.execute(
                    """SELECT * FROM users
                       ORDER BY last_name COLLATE NOCASE, first_name COLLATE NOCASE, email"""
                )
            ]

    def create_user(
        self,
        first_name: str,
        last_name: str,
        position: str,
        email: str,
        password: str,
        role: str,
    ) -> int:
        self.require_role("admin")
        if role not in self.context.ROLES:
            raise WarehouseError("Неизвестная роль")
        values = (
            self._required(first_name, "имя"),
            self._required(last_name, "фамилия"),
            self._required(position, "должность"),
            self._required(email, "email"),
            hash_password(self._required(password, "пароль")),
            role,
        )
        try:
            with connect(self.context.db_path) as db:
                cursor = db.execute(
                    """INSERT INTO users(
                           first_name, last_name, position, email, password_hash, role
                       ) VALUES (?, ?, ?, ?, ?, ?)""",
                    values,
                )
                self.context._audit(
                    db,
                    "USER_CREATE",
                    "user",
                    cursor.lastrowid,
                    {"email": email, "role": role},
                )
                return int(cursor.lastrowid)
        except sqlite3.IntegrityError as error:
            raise WarehouseError(
                "Пользователь с таким email уже существует"
            ) from error

    def change_password(self, old_password: str, new_password: str) -> None:
        user = self.current_user()
        if len(new_password) < 6:
            raise WarehouseError(
                "Новый пароль должен содержать не менее 6 символов"
            )
        with connect(self.context.db_path) as db:
            row = db.execute(
                "SELECT password_hash FROM users WHERE id = ?", (user["id"],)
            ).fetchone()
            if row is None or not verify_password(
                old_password, str(row["password_hash"])
            ):
                raise WarehouseError("Текущий пароль указан неверно")
            db.execute(
                "UPDATE users SET password_hash = ?, must_change_password = 0 WHERE id = ?",
                (hash_password(new_password), user["id"]),
            )
            self.context._audit(db, "PASSWORD_CHANGE", "user", user["id"])

    def update_profile(
        self, first_name: str, last_name: str, position: str
    ) -> dict[str, Any]:
        user = self.current_user()
        values = (
            self._required(first_name, "имя"),
            self._required(last_name, "фамилия"),
            self._required(position, "должность"),
        )
        with connect(self.context.db_path) as db:
            db.execute(
                "UPDATE users SET first_name = ?, last_name = ?, position = ? WHERE id = ?",
                (*values, user["id"]),
            )
            self.context._audit(db, "PROFILE_UPDATE", "user", user["id"])
        return self.current_user()
