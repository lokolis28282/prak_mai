"""Composition root for the extracted Warehouse domain services."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Any

from ..administration.service import AdministrationService
from ..db import DEFAULT_DB_PATH, initialize
from ..shared.helpers import STRICT_REFERENCES
from .balance import WarehouseBalanceService
from .equipment_composition import EquipmentCompositionService
from .history import WarehouseHistoryService
from .inventory import LegacyInventoryService
from .monitoring import WarehouseMonitoringService
from .reference_service import WarehouseReferenceService
from .references import ReferenceDataService


class WarehouseDomainService:
    """Own shared Warehouse runtime state and compose focused services."""

    DELIVERY_STATUSES = (
        "Загружена",
        "Ожидается",
        "Частично принята",
        "Принята",
        "Закрыта",
    )
    DELIVERY_EDITABLE_FIELDS = {
        "item_name",
        "model",
        "vendor",
        "supplier",
        "project",
        "datacenter",
        "shelf",
        "object_name",
        "equipment_type",
        "component_type",
        "cable_type",
        "unit",
        "quantity",
    }
    STRICT_REFERENCE_VALIDATION = STRICT_REFERENCES
    STRICT_REFERENCES = STRICT_REFERENCES
    ROLES = ("admin", "engineer", "viewer")
    STATUSES = (
        "IN_STOCK",
        "ISSUED",
        "RESERVED",
        "MAINTENANCE",
        "WRITTEN_OFF",
    )
    TASK_SOURCES = (
        "Rooms",
        "Outlook",
        "ITSM",
        "Zabbix",
        "DCIM",
        "Склад",
        "Другое",
    )
    TASK_TYPES = ("ЗНР", "ПНР", "ИЗМ", "ЗНО", "ИНЦ", "Другое")
    WORK_LOG_STATUSES = (
        "Выполнено",
        "В работе",
        "Ожидание",
        "Отложено",
    )
    REFERENCE_KINDS = {
        "item_name": "Наименования позиций",
        "model": "Модели",
        "supplier": "Поставщики",
        "vendor": "Вендоры",
        "shelf": "Стеллажи/полки",
        "object": "Объекты",
        "datacenter": "ЦОД",
        "project": "Проекты",
        "equipment_type": "Типы оборудования",
        "component_type": "Типы компонентов",
        "cable_type": "Типы кабеля",
        "unit": "Единицы учета",
        "task_source": "Источники задач",
        "task_type": "Типы задач",
        "work_log_status": "Статусы логов",
        "work_log_section": "Разделы работ (УВР)",
    }
    RECEIPT_REFERENCE_FIELDS = {
        "item_name": "item_name",
        "model": "model",
        "shelf": "shelf",
        "project": "project",
        "supplier": "supplier",
        "vendor": "vendor",
        "object_name": "object",
        "datacenter": "datacenter",
        "equipment_type": "equipment_type",
        "component_type": "component_type",
        "cable_type": "cable_type",
        "unit": "unit",
    }
    ISSUE_REFERENCE_FIELDS = {
        "source_item_name": "item_name",
        "source_cable_type": "cable_type",
    }
    KEY_TABLES = {
        "categories",
        "locations",
        "equipment",
        "operations",
        "work_logs",
        "reference_values",
        "stock_receipts",
        "stock_issues",
        "stock_issue_allocations",
        "audit_log",
        "users",
        "daily_report_uploads",
        "daily_report_rows",
        "deliveries",
        "delivery_lines",
    }
    RESTORE_BASE_TABLES = {
        "categories",
        "locations",
        "equipment",
        "operations",
    }

    def __init__(
        self,
        db_path: str | Path = DEFAULT_DB_PATH,
        *,
        strict_reference_validation: bool = STRICT_REFERENCE_VALIDATION,
        initialize_database: bool = True,
    ):
        self.db_path = Path(db_path)
        self.strict_reference_validation = strict_reference_validation
        self.lock = threading.RLock()
        if initialize_database:
            self.default_admin_created = initialize(self.db_path)
        else:
            if not self.db_path.is_file():
                raise FileNotFoundError(self.db_path)
            self.default_admin_created = False

        self.administration = AdministrationService(
            self.db_path,
            lock=self.lock,
            key_tables=self.KEY_TABLES,
            restore_base_tables=self.RESTORE_BASE_TABLES,
        )
        self._actor_email = self.administration._actor_email
        self._actor_name = self.administration._actor_name
        self._actor_role_override = self.administration._actor_role_override
        self.reports: Any | None = None
        self.reference_catalog = ReferenceDataService(self)

        self._history = WarehouseHistoryService(self)
        self._inventory = LegacyInventoryService(self)
        self._balance = WarehouseBalanceService(self)
        self.equipment_composition = EquipmentCompositionService(self)
        self._monitoring = WarehouseMonitoringService(self)
        self._references = WarehouseReferenceService(self)
        self._components = (
            self._history,
            self._inventory,
            self._balance,
            self.equipment_composition,
            self._monitoring,
            self._references,
        )

    def __getattr__(self, name: str) -> Any:
        for component in self._components:
            if name in vars(type(component)):
                return getattr(component, name)
        raise AttributeError(
            f"{type(self).__name__!s} has no attribute {name!r}"
        )

    def _require_role(self, *roles: str) -> dict[str, Any]:
        return self.administration._require_role(*roles)

    def current_user(self) -> dict[str, Any]:
        return self.administration.current_user()

    def _require_write(self) -> dict[str, Any]:
        return self.administration._require_write()

    def _audit(
        self,
        db: sqlite3.Connection,
        action: str,
        entity_type: str,
        entity_id: int | str | None = None,
        details: dict[str, Any] | str | None = None,
    ) -> None:
        self.administration._audit(
            db, action, entity_type, entity_id, details
        )
