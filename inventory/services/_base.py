"""Base adapter for facade services."""

from __future__ import annotations

from typing import Any


class ServiceAdapter:
    def __init__(self, core: Any):
        self.core = core

    def call(self, name: str, *args: Any, **kwargs: Any) -> Any:
        return getattr(self.core, name)(*args, **kwargs)
