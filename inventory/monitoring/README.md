# Monitoring Module

Monitoring is an isolated product module. Its first implemented capability is
deterministic hostname routing through `MonitoringFacade.resolve_hostname()`.

Current scope provides:

- `MonitoringFacade`;
- local Tech/Digital hostname routing and prepared email fields;
- a frontend entrypoint placeholder;
- documentation for future integration.

It must not import Warehouse, Reports, `WarehouseService`, or `WarehouseCore`.
It does not yet collect DCIM/Zabbix data, send email, or expose an operator UI.
