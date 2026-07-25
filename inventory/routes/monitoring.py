"""Monitoring HTTP routes."""

from __future__ import annotations

from typing import Any

from .runtime import RouteRuntime


def handle_get(
    handler: Any,
    runtime: RouteRuntime,
    path: str,
    _query: dict[str, list[str]],
) -> bool:
    """Return Monitoring module state."""
    if path != "/api/monitoring/status":
        return False
    handler._send_json(200, runtime.app_context.monitoring.module_status())
    return True


def handle_post(handler: Any, runtime: RouteRuntime, path: str) -> bool:
    """Execute the intentionally lock-free manual Monitoring search."""
    if path != "/api/monitoring/manual-search":
        return False
    data = handler._read_json_object(100_000)
    handler._send_json(
        200,
        runtime.app_context.monitoring.manual_search(
            data.get("host", ""), data.get("problem", "")
        ),
    )
    return True
