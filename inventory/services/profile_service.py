"""User profile and access service."""

from __future__ import annotations

from typing import Any

from ._base import ServiceAdapter


class ProfileService(ServiceAdapter):
    def authenticate(self, *args: Any, **kwargs: Any) -> Any: return self.call("authenticate", *args, **kwargs)
    def user_by_email(self, *args: Any, **kwargs: Any) -> Any: return self.call("user_by_email", *args, **kwargs)
    def current_user(self, *args: Any, **kwargs: Any) -> Any: return self.call("current_user", *args, **kwargs)
    def user_context(self, *args: Any, **kwargs: Any) -> Any: return self.call("user_context", *args, **kwargs)
    def users(self, *args: Any, **kwargs: Any) -> Any: return self.call("users", *args, **kwargs)
    def create_user(self, *args: Any, **kwargs: Any) -> Any: return self.call("create_user", *args, **kwargs)
    def change_password(self, *args: Any, **kwargs: Any) -> Any: return self.call("change_password", *args, **kwargs)
    def update_profile(self, *args: Any, **kwargs: Any) -> Any: return self.call("update_profile", *args, **kwargs)
