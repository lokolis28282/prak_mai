"""Core application boundaries for ODE with lazy application wiring."""

from typing import Any

from .context import FeatureFlags
from .events import EventReader, EventPublisher, WarehouseEvent
from .exceptions import ODEError

__all__ = [
    "ApplicationContext",
    "EventReader",
    "EventPublisher",
    "FeatureFlags",
    "ODEError",
    "WarehouseEvent",
    "create_application_context",
]


def __getattr__(name: str) -> Any:
    """Load the composition root only when its public names are requested.

    Event contracts are imported while ``WarehouseService`` is still being
    assembled.  Eagerly importing ``application`` here re-entered the
    Warehouse facade and made fresh-process CLI commands fail with a partially
    initialized ``delivery_imports`` module.
    """
    if name in {"ApplicationContext", "create_application_context"}:
        from .application import ApplicationContext, create_application_context

        return {
            "ApplicationContext": ApplicationContext,
            "create_application_context": create_application_context,
        }[name]
    raise AttributeError(name)
