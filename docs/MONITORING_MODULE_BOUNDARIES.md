# MONITORING_MODULE_BOUNDARIES

Monitoring is an isolated product module. Hostname routing is implemented;
operator UI and external collectors remain future work.

## Included Now

- `inventory/monitoring/facade.py`;
- `inventory/monitoring/hostname_routing.py`;
- `inventory/monitoring/models.py`;
- local ignored `data/monitoring/*.json` rules;
- offline `scripts/generate_hostname_rules.py`;
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
- `MonitoringFacade.resolve_hostname()` exposes deterministic routing without
  enabling the unfinished UI.

## Dependency Rule

Monitoring must not import:

- `inventory.service`;
- `inventory.services.warehouse_service`;
- `inventory.warehouse`;
- `inventory.reports`;
- frontend `warehouse/*` modules.

Future code from the separate Monitoring workstream should be mounted behind `MonitoringFacade` and its own frontend entrypoint.
