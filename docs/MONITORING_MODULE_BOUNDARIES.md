# MONITORING_MODULE_BOUNDARIES

Monitoring is an isolated future product module.

## Included Now

- `inventory/monitoring/facade.py`;
- `inventory/monitoring/models.py`;
- `static/js/monitoring/index.js`;
- existing UI placeholder `В разработке`;
- documentation for future integration.

## Not Included

- DCIM integration;
- Zabbix integration;
- ITSM integration;
- warehouse inventory logic;
- report generation logic;
- direct imports from Warehouse or Reports.

## Core Integration

Core exposes the Monitoring entrypoint through feature flags:

- `FEATURE_MONITORING = false`;
- UI remains a placeholder;
- `MonitoringFacade.module_status()` returns module status.

## Dependency Rule

Monitoring must not import:

- `inventory.service`;
- `inventory.services.warehouse_service`;
- `inventory.warehouse`;
- `inventory.reports`;
- frontend `warehouse/*` modules.

Future code from the separate Monitoring workstream should be mounted behind `MonitoringFacade` and its own frontend entrypoint.
