# MODULE_ARCHITECTURE

Stage 0.12.6 defines product module boundaries without removing `WarehouseCore` or `legacy ui.js`.

## Modules

Core:

- starts and wires modules through `ApplicationContext`;
- owns navigation, current actor context, feature flags and shared runtime configuration;
- does not own business tables.

Warehouse:

- owns stock operations, balance, deliveries, warehouse history and inventory analysis;
- writes equipment/component receipts through `WarehouseFacade`;
- writes cable receipt/issue operations through `WarehouseFacade`;
- writes serialized equipment/component issues through `WarehouseFacade`;
- imports delivery documents through `WarehouseFacade` without creating receipts;
- does not import Reports or Monitoring;
- publishes/readies warehouse events through the Core event contract.

Reports:

- owns work logs and report generation;
- reads warehouse events through `EventReader`;
- writes work logs and uploaded daily reports through `ReportsFacade`;
- must not write stock receipts, stock issues or delivery tables.

Monitoring:

- isolated placeholder in Stage 0.12.6;
- does not import Warehouse, Reports, `WarehouseService` or `WarehouseCore`;
- exposes `MonitoringFacade.module_status()`.

Administration:

- owns users, backup, restore, audit view and diagnostics;
- must not contain warehouse or report business rules.

## Transitional State

`WarehouseCore` remains the compatibility core. New facades delegate to the existing `WarehouseService` facade, which still delegates to specialized services and `WarehouseCore`. This is intentional for ODE 0.12.6: it creates boundaries without a data migration or behavior change.

Web/API receives `ApplicationContext` via `make_handler()`. The handler still uses a compatibility service adapter internally for write endpoints while module calls are extracted gradually.

Stage 0.12.7 routes read-only Warehouse GET/CSV paths through:

`web/API -> ApplicationContext -> WarehouseFacade -> compatibility service -> WarehouseCore`

Stage 0.12.8 routes read-only Reports GET/CSV paths through:

`web/API -> ApplicationContext -> ReportsFacade -> compatibility service`

Stage 0.12.9 routes read-only Administration GET/CSV paths through:

`web/API -> ApplicationContext -> AdministrationFacade -> compatibility service`

This includes current user/profile read, `/api/admin` aggregation and audit CSV
export. Authentication, session writes and admin actions remain compatibility
flows.

Stage 0.12.10 wires warehouse events through:

`ApplicationContext -> WarehouseEventReader -> ReportsFacade`

Reports owns work logs and report presentation. Warehouse owns event extraction
from warehouse tables. Reports must not import `WarehouseCore` or query
warehouse-owned tables directly.

Stage 0.12.11 routes Reports write/import flows through:

`web/API -> ApplicationContext -> ReportsFacade -> inventory/reports services`

The migrated flows are `WORK_LOG`, `WORK_LOGS`, work-log CSV import, work-log
CSV preview/confirm and uploaded daily report import. Preview storage for these
flows is Reports-owned and in memory.

Stage 0.12.12 routes equipment/component receipt writes through:

`web/API -> ApplicationContext -> WarehouseFacade -> inventory/warehouse receipt services`

Cable receipt, issue, delivery and legacy equipment/operations writes are still
compatibility flows. Delivery endpoints are not migrated in this stage, though
regression coverage ensures delivery acceptance still creates receipts.

Stage 0.12.13 routes cable receipt and cable issue writes through:

`web/API -> ApplicationContext -> WarehouseFacade -> inventory/warehouse cable services`

Cables are quantity-based, do not require S/N and do not use scanner/S/N
receipt validation. Generic equipment/component issue and deliveries remain
compatibility flows.

Stage 0.12.14 routes serialized equipment/component issue writes through:

`web/API -> ApplicationContext -> WarehouseFacade -> inventory/warehouse issue services`

The migrated flows include scanner validation, scanned S/N confirm, manual
issue, generic issue CSV preview/confirm/import and strict bulk S/N issue.
Deliveries, inventory write and legacy equipment/operations remain
compatibility flows.

Stage 0.12.15 routes delivery document import and matching through:

`web/API -> ApplicationContext -> WarehouseFacade -> inventory/warehouse delivery import services`

The migrated flows include delivery CSV preview, explicit mapping, S/N
expansion, duplicate and existing-stock matching, confirm document,
list/card/lines/search/export and template download. Confirm writes only
`deliveries`, `delivery_lines` and compact audit. Physical delivery acceptance,
unplanned acceptance, receipt creation from delivery and close delivery remain
compatibility flows.

Stage 0.12.16 routes physical delivery acceptance through:

`web/API -> ApplicationContext -> WarehouseFacade -> inventory/warehouse delivery acceptance services`

The migrated flows include inspect, planned/unplanned accept, batch accept,
safe line metadata update, conflicts/summary read and status refresh. New S/N
acceptance creates receipts through the receipt repository transaction
contract; existing S/N acceptance fills only empty fields. Close delivery
remains compatibility.

`WarehouseCore` must not be referenced directly by `inventory/webapp.py`. New read-only Warehouse endpoints must be added to `WarehouseFacade` first.

## Public Facades

- `WarehouseFacade`
- `ReportsFacade`
- `MonitoringFacade`
- `AdministrationFacade`

The web layer must not call `WarehouseCore` directly. Future extraction should move endpoint groups to facade methods first, then move implementation behind each facade.
