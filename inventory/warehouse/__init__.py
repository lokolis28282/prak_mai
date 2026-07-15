"""Warehouse product module with lazy public-facade loading."""

from typing import Any

__all__ = ["WarehouseFacade"]


def __getattr__(name: str) -> Any:
    # ReferenceDataService is imported while the compatibility service is
    # being assembled.  Keeping this package initializer lazy prevents the
    # facade -> application -> service cycle without changing the public API.
    if name == "WarehouseFacade":
        from .facade import WarehouseFacade

        return WarehouseFacade
    raise AttributeError(name)
