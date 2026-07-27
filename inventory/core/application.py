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
from inventory.administration.runtime_databases import (
    RuntimeDatabase,
    RuntimeDatabaseRegistry,
)
from inventory.knowledge.facade import KnowledgeFacade
from inventory.monitoring.facade import MonitoringFacade
from inventory.reports.facade import ReportsFacade
from inventory.vacations.facade import VacationFacade
from inventory.vacations.schema import VACATION_TABLES
from inventory.warehouse.facade import WarehouseFacade
from inventory.warehouse.baseline.posting_policy import PostingPolicy
from inventory.warehouse.baseline.service import FullInventoryService


@dataclass
class ApplicationContext:
    db_path: Path
    warehouse: WarehouseFacade
    reports: ReportsFacade
    monitoring: MonitoringFacade
    knowledge: KnowledgeFacade
    administration: AdministrationFacade
    vacations: VacationFacade
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
        vacations_candidate = Path(
            runtime.vacations_db_path or service.db_path.with_name("vacations.db")
        ).expanduser().absolute()
        vacations_path = vacations_candidate.resolve()
        database_entries = [
            RuntimeDatabase(
                "warehouse_ix",
                "IXcellerate",
                service.db_path,
                "warehouse",
                frozenset(service.KEY_TABLES),
            )
        ]
        if runtime.settings.get("warehouse_sites_enabled"):
            database_entries.append(
                RuntimeDatabase(
                    "warehouse_solar",
                    "Solar",
                    Path(
                        runtime.settings.get(
                            "solar_db_path",
                            service.db_path.with_name("warehouse_solar.db"),
                        )
                    ),
                    "warehouse",
                    frozenset(service.KEY_TABLES),
                )
            )
        database_entries.append(
            RuntimeDatabase(
                "vacations",
                "Vacations",
                vacations_candidate,
                "vacations",
                frozenset(VACATION_TABLES),
            )
        )
        service.administration_service.configure_runtime_databases(
            RuntimeDatabaseRegistry(database_entries),
            backup_root=runtime.settings.get("backup_root"),
        )
        event_publisher = NoopEventPublisher()
        return cls(
            db_path=service.db_path,
            warehouse=WarehouseFacade(
                service,
                event_publisher=event_publisher,
                posting_policy=posting_policy,
                full_inventory=full_inventory,
            ),
            reports=service.reports_service,
            monitoring=MonitoringFacade(),
            knowledge=KnowledgeFacade(service),
            administration=AdministrationFacade(service.administration_service),
            vacations=VacationFacade(vacations_path),
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
    vacations_db_path: str | Path | None = None,
) -> ApplicationContext:
    compat = service or WarehouseService(db_path)
    if configuration is None:
        configuration = RuntimeConfig(
            compat.db_path,
            feature_flags or FeatureFlags(),
            warehouse_contour=warehouse_contour or "unknown",
            production_db_path=DEFAULT_DB_PATH,
            full_inventory_state_root=(
                Path(full_inventory_state_root)
                if full_inventory_state_root is not None
                else None
            ),
            vacations_db_path=(
                Path(vacations_db_path) if vacations_db_path is not None else None
            ),
        )
    elif vacations_db_path is not None:
        configuration.vacations_db_path = Path(vacations_db_path)
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
