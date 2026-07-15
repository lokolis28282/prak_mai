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
from inventory.warehouse.baseline.posting_policy import PostingPolicy
from inventory.warehouse.baseline.service import FullInventoryService


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
    full_inventory: FullInventoryService | None = None

    @classmethod
    def from_service(
        cls,
        service: WarehouseService,
        *,
        current_actor: str = "",
        feature_flags: FeatureFlags | None = None,
        configuration: RuntimeConfig | None = None,
    ) -> "ApplicationContext":
        flags = feature_flags or FeatureFlags()
        runtime = configuration or RuntimeConfig(
            service.db_path,
            flags,
            warehouse_contour="unknown",
            production_db_path=DEFAULT_DB_PATH,
        )
        production_path = runtime.production_db_path or DEFAULT_DB_PATH
        posting_policy = PostingPolicy(
            service.db_path,
            mode=runtime.warehouse_contour,
            production_db_path=production_path,
        )
        full_inventory = FullInventoryService(
            service.db_path,
            state_root=runtime.full_inventory_state_root,
        )
        event_reader = WarehouseEventReader(service)
        event_publisher = NoopEventPublisher()
        return cls(
            db_path=service.db_path,
            warehouse=WarehouseFacade(
                service,
                event_publisher=event_publisher,
                posting_policy=posting_policy,
                full_inventory=full_inventory,
            ),
            reports=ReportsFacade(service, warehouse_events=event_reader),
            monitoring=MonitoringFacade(),
            administration=AdministrationFacade(service),
            current_actor=current_actor,
            feature_flags=flags,
            configuration=runtime,
            compat_service=service,
            full_inventory=full_inventory,
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
    configuration: RuntimeConfig | None = None,
    warehouse_contour: str | None = None,
    full_inventory_state_root: str | Path | None = None,
) -> ApplicationContext:
    compat = service or WarehouseService(db_path)
    if configuration is None and warehouse_contour is not None:
        configuration = RuntimeConfig(
            compat.db_path,
            feature_flags or FeatureFlags(),
            warehouse_contour=warehouse_contour,
            production_db_path=DEFAULT_DB_PATH,
            full_inventory_state_root=(
                Path(full_inventory_state_root)
                if full_inventory_state_root is not None
                else None
            ),
        )
    return ApplicationContext.from_service(
        compat,
        current_actor=current_actor,
        feature_flags=feature_flags,
        configuration=configuration,
    )


def ensure_application_context(value: Any) -> ApplicationContext:
    if isinstance(value, ApplicationContext):
        return value
    if isinstance(value, WarehouseService):
        return ApplicationContext.from_service(value)
    raise TypeError("make_handler expects WarehouseService or ApplicationContext")
