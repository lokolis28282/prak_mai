# Monitoring module boundaries — ODE 0.21.1

Patch 0.21.1 не меняет Monitoring flow или storage boundary.

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
- offline `scripts/integrate_recipient_rules_from_xlsx.py` для консервативного
  добавления подтверждённых project/ИС/hostname rules; source и outputs
  являются локальными корпоративными данными;
- `static/js/monitoring/index.js`;
- authenticated manual-search API and operator UI;
- optional Selenium/Microsoft Edge DCIM adapter;
- documentation for the current flow and future transports.

## Not Included

- automatic DCIM synchronization;
- Zabbix integration;
- ITSM integration;
- warehouse inventory logic;
- report generation logic;
- direct imports from Warehouse or Reports.

## Core Integration

Core exposes the Monitoring entrypoint through feature flags:

- legacy `ApplicationFeatures.FEATURE_MONITORING` metadata всё ещё равно
  `false`, но больше не является activation gate фактического экрана;
- UI exposes an explicit manual operation;
- `MonitoringFacade.module_status()` возвращает `enabled=true`, capabilities и
  safe config state;
- `MonitoringFacade.resolve_hostname()` exposes deterministic routing without
  requiring external collection.
- `MonitoringFacade.manual_search()` owns validation and DCIM enrichment.

## Runtime configuration

The module reads optional `ODE_MONITORING_*` environment variables. Internal
routing JSON, Edge profiles and browser sessions stay outside Git. Selenium is
loaded lazily; installations that do not use live DCIM collection keep the
standard-library-only core. `ODE_MONITORING_DEV_MOCK=true` is explicit and its
results are visibly marked as development data.

Полный список defaults и boolean parsing находится в
[`RUNTIME_CONFIGURATION.md`](RUNTIME_CONFIGURATION.md). DCIM использует
локальную Edge session, а не API-key ODE; transport credentials отсутствуют.

## Dependency Rule

Monitoring must not import:

- `inventory.service`;
- `inventory.services.warehouse_service`;
- `inventory.warehouse`;
- `inventory.reports`;
- frontend `warehouse/*` modules.

Future code from the separate Monitoring workstream should be mounted behind `MonitoringFacade` and its own frontend entrypoint.
