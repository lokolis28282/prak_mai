"""Public monitoring facade.

Monitoring stays isolated and does not import Warehouse or Reports. Hostname
routing is the first production-ready capability; collection and UI remain
separate future slices.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .hostname_routing import RoutingDecision, resolve_hostname_routing


class MonitoringFacade:
    def __init__(self, *, rules_dir: str | Path | None = None) -> None:
        self._rules_dir = Path(rules_dir) if rules_dir is not None else None

    def module_status(self) -> dict[str, Any]:
        return {
            "module": "monitoring",
            "enabled": False,
            "status": "Hostname routing готов; operator UI в разработке",
            "capabilities": {
                "hostname_routing": True,
                "manual_search": False,
                "external_collection": False,
            },
            "extension_points": ["facade", "frontend_entrypoint", "future_api"],
        }

    def resolve_hostname(self, hostname: Any) -> RoutingDecision:
        return resolve_hostname_routing(hostname, rules_dir=self._rules_dir)
