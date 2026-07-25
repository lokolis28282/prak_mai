"""Shared immutable dependencies passed to domain route handlers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..core.application import ApplicationContext
from ..service import WarehouseService


@dataclass(frozen=True, slots=True)
class RouteRuntime:
    """Dependencies and launch-contour status used by HTTP routes."""

    app_context: ApplicationContext
    service: WarehouseService
    migration_full_status: dict[str, Any]
    migration_pilot_status: dict[str, Any]
    database_fingerprint: str
