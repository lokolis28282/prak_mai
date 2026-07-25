"""Core exception aliases."""

from __future__ import annotations

from inventory.shared.helpers import WarehouseError


class ODEError(WarehouseError):
    """Base error for new module boundaries."""
