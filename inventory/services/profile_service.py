"""Deprecated profile vocabulary backed by AdministrationService."""

from __future__ import annotations

from typing import Any


class ProfileService:
    def __init__(self, actor_provider: Any):
        self.administration = actor_provider.administration

    def authenticate(self, *args: Any, **kwargs: Any) -> Any:
        return self.administration.authenticate(*args, **kwargs)

    def user_by_email(self, *args: Any, **kwargs: Any) -> Any:
        return self.administration.user_by_email(*args, **kwargs)

    def current_user(self, *args: Any, **kwargs: Any) -> Any:
        return self.administration.current_user(*args, **kwargs)

    def user_context(self, *args: Any, **kwargs: Any) -> Any:
        return self.administration.user_context(*args, **kwargs)

    def users(self, *args: Any, **kwargs: Any) -> Any:
        return self.administration.users(*args, **kwargs)

    def create_user(self, *args: Any, **kwargs: Any) -> Any:
        return self.administration.create_user(*args, **kwargs)

    def change_password(self, *args: Any, **kwargs: Any) -> Any:
        return self.administration.change_password(*args, **kwargs)

    def update_profile(self, *args: Any, **kwargs: Any) -> Any:
        return self.administration.update_profile(*args, **kwargs)
