"""Deprecated import alias for Warehouse data-quality monitoring."""

from inventory.warehouse.monitoring import (
    WarehouseMonitoringService as MonitoringService,
)

__all__ = ["MonitoringService"]
