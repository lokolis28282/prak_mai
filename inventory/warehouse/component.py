"""Shared adapter for composed Warehouse domain services."""

from __future__ import annotations

from typing import Any


class WarehouseComponent:
    """Expose shared runtime state without inheriting the compatibility core."""

    def __init__(self, actor_provider: Any):
        self.actor_provider = actor_provider

    def __getattr__(self, name: str) -> Any:
        return getattr(self.actor_provider, name)
