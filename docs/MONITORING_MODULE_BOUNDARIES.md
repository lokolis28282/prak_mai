# MONITORING_MODULE_BOUNDARIES

Monitoring is an isolated product module. Hostname routing and an explicit
manual DCIM enrichment workflow are implemented. Automatic alert ingestion,
email sending and warehouse coupling remain out of scope.

## Included Now

- `inventory/monitoring/facade.py`;
- `inventory/monitoring/hostname_routing.py`;
- `inventory/monitoring/manual_search.py`;
- `inventory/monitoring/models.py`;
- local ignored `data/monitoring/*.json` rules;
- offline `scripts/generate_hostname_rules.py`;
- `static/js/monitoring/index.js`;
- authenticated manual-search API and operator UI;
- optional Selenium/Microsoft Edge DCIM adapter;
- documentation for future integration.

## Not Included

- automatic DCIM synchronization;
- Zabbix integration;
- ITSM integration;
- warehouse inventory logic;
- report generation logic;
- direct imports from Warehouse or Reports.

## Core Integration

Core exposes the Monitoring entrypoint through feature flags:

- `FEATURE_MONITORING = false`;
- UI exposes an explicit manual operation;
- `MonitoringFacade.module_status()` returns capabilities and safe config state.
- `MonitoringFacade.resolve_hostname()` exposes deterministic routing without
  requiring external collection.
- `MonitoringFacade.manual_search()` owns validation and DCIM enrichment.

## Runtime configuration

The module reads optional `ODE_MONITORING_*` environment variables. Internal
routing JSON, Edge profiles and browser sessions stay outside Git. Selenium is
loaded lazily; installations that do not use live DCIM collection keep the
standard-library-only core. `ODE_MONITORING_DEV_MOCK=true` is explicit and its
results are visibly marked as development data.

## Dependency Rule

Monitoring must not import:

- `inventory.service`;
- `inventory.services.warehouse_service`;
- `inventory.warehouse`;
- `inventory.reports`;
- frontend `warehouse/*` modules.

Future code from the separate Monitoring workstream should be mounted behind `MonitoringFacade` and its own frontend entrypoint.
