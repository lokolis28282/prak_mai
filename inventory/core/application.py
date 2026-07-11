"""Application context that wires ODE product modules."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from inventory.db import DEFAULT_DB_PATH
from inventory.service import WarehouseService

from .context import FeatureFlags, RuntimeConfig
from .events import AuditLogEventReader, NoopEventPublisher
from inventory.administration.facade import AdministrationFacade
from inventory.monitoring.facade import MonitoringFacade
from inventory.reports.facade import ReportsFacade
from inventory.warehouse.events import WarehouseEventReader
from inventory.warehouse.facade import WarehouseFacade


@dataclass
class ApplicationContext:
    db_path: Path
    warehouse: WarehouseFacade
    reports: ReportsFacade
    monitoring: MonitoringFacade
    administration: AdministrationFacade
    current_actor: str = ""
    feature_flags: FeatureFlags | None = None
    configuration: RuntimeConfig | None = None
    compat_service: WarehouseService | None = None

    @classmethod
    def from_service(
        cls,
        service: WarehouseService,
        *,
        current_actor: str = "",
        feature_flags: FeatureFlags | None = None,
    ) -> "ApplicationContext":
        flags = feature_flags or FeatureFlags()
        event_reader = WarehouseEventReader(service)
        event_publisher = NoopEventPublisher()
        return cls(
            db_path=service.db_path,
            warehouse=WarehouseFacade(service, event_publisher=event_publisher),
            reports=ReportsFacade(service, warehouse_events=event_reader),
            monitoring=MonitoringFacade(),
            administration=AdministrationFacade(service),
            current_actor=current_actor,
            feature_flags=flags,
            configuration=RuntimeConfig(service.db_path, flags),
            compat_service=service,
        )

    def service_adapter(self) -> WarehouseService:
        if self.compat_service is None:
            raise RuntimeError("ApplicationContext has no compatibility service")
        return self.compat_service


def create_application_context(
    db_path: str | Path = DEFAULT_DB_PATH,
    *,
    service: WarehouseService | None = None,
    current_actor: str = "",
    feature_flags: FeatureFlags | None = None,
) -> ApplicationContext:
    compat = service or WarehouseService(db_path)
    return ApplicationContext.from_service(
        compat, current_actor=current_actor, feature_flags=feature_flags
    )


def ensure_application_context(value: Any) -> ApplicationContext:
    if isinstance(value, ApplicationContext):
        return value
    if isinstance(value, WarehouseService):
        return ApplicationContext.from_service(value)
    raise TypeError("make_handler expects WarehouseService or ApplicationContext")
