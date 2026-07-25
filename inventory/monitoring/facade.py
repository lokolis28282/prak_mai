"""Public facade for hostname routing and manual DCIM enrichment."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .hostname_routing import RoutingDecision, resolve_hostname_routing
from .manual_search import ManualSearchError, run_manual_search


class MonitoringError(RuntimeError):
    """A controlled, user-facing Monitoring failure."""


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    normalized = value.strip().casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise MonitoringError(f"Переменная {name} должна быть true или false")


class MonitoringFacade:
    def __init__(
        self,
        *,
        rules_dir: str | Path | None = None,
        collect_dcim: bool | None = None,
        headless: bool | None = None,
        development_mock: bool | None = None,
    ) -> None:
        configured_rules = rules_dir or os.environ.get("ODE_MONITORING_RULES_DIR")
        self._rules_dir = Path(configured_rules).expanduser() if configured_rules else None
        self._collect_dcim = (
            _env_bool("ODE_MONITORING_COLLECT_DCIM", True)
            if collect_dcim is None else collect_dcim
        )
        self._headless = (
            _env_bool("ODE_MONITORING_HEADLESS", False)
            if headless is None else headless
        )
        self._development_mock = (
            _env_bool("ODE_MONITORING_DEV_MOCK", False)
            if development_mock is None else development_mock
        )

    def module_status(self) -> dict[str, Any]:
        return {
            "module": "monitoring",
            "enabled": True,
            "status": "Ручной сбор по hostname доступен",
            "capabilities": {
                "hostname_routing": True,
                "manual_search": True,
                "external_collection": self._collect_dcim,
                "development_mock": self._development_mock,
            },
            "configuration": {
                "rules_configured": self._rules_dir is not None,
                "headless": self._headless,
            },
        }

    def resolve_hostname(self, hostname: Any) -> RoutingDecision:
        return resolve_hostname_routing(hostname, rules_dir=self._rules_dir)

    def manual_search(self, host: Any, problem: Any) -> dict[str, Any]:
        if not self._collect_dcim and not self._development_mock:
            raise MonitoringError(
                "Сбор DCIM отключён. Для тестового режима явно включите "
                "ODE_MONITORING_DEV_MOCK=true"
            )
        try:
            result = run_manual_search(
                host,
                problem,
                headless=self._headless,
                collect_dcim=self._collect_dcim,
                rules_dir=self._rules_dir,
            )
        except ManualSearchError as error:
            raise MonitoringError(str(error)) from error
        if self._development_mock and not self._collect_dcim:
            result["development_mock"] = True
            event = result.get("event")
            if isinstance(event, dict):
                event.setdefault("logs", []).insert(
                    0,
                    "[DEV] Использован явно включённый mock без запроса к DCIM.",
                )
        return result
