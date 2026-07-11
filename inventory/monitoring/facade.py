"""Public monitoring facade.

Stage 0.12.6 intentionally keeps monitoring isolated and without Warehouse
or Reports imports.
"""

from __future__ import annotations

from typing import Any


class MonitoringFacade:
    def module_status(self) -> dict[str, Any]:
        return {
            "module": "monitoring",
            "enabled": False,
            "status": "В разработке",
            "extension_points": ["facade", "frontend_entrypoint", "future_api"],
        }
