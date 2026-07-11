# MODULE_MIGRATION_PLAN

## A. Core Boundaries

- Keep `ApplicationContext` as the only module wiring point.
- Move global state, feature flags and navigation contracts into Core.
- Keep web routes stable.

## B. Warehouse Boundaries

- Stage 0.12.7: read-only Warehouse API is partially migrated to `WarehouseFacade`.
  Migrated routes include balance, deliveries list/card, position search/card,
  warehouse-owned `/api/data` fields and warehouse CSV exports. Write routes
  remain on the compatibility service.
- Stage 0.12.12: equipment/component receipt write and import flows are migrated
  to `WarehouseFacade`. Migrated routes include manual receipt, scanned S/N
  confirm, receipt serial validation, receipt CSV preview/confirm and direct
  receipt CSV import. Cable receipt, issue, deliveries and legacy
  equipment/operations receipt remain compatibility flows.
- Stage 0.12.13: cable receipt and cable issue business logic is migrated to
  `WarehouseFacade` and `inventory/warehouse/cables.py`. Cables are separated
  from S/N receipt/issue validation. Generic equipment/component issue,
  deliveries, inventory write and legacy equipment/operations remain
  compatibility flows.
- Stage 0.12.14: serialized equipment/component issue write and import flows
  are migrated to `WarehouseFacade`. Migrated routes include manual issue,
  issue scanner validation, scanned S/N confirm, issue CSV preview/confirm,
  direct issue CSV import and bulk S/N issue preview/confirm. Deliveries,
  inventory write and legacy equipment/operations remain compatibility flows.
- Stage 0.12.15: delivery document import and matching are migrated to
  `WarehouseFacade`. Migrated routes include delivery CSV preview, explicit
  column mapping, S/N expansion, duplicate/existing-stock/other-delivery
  matching, confirm document, list/card/lines/search/export and template
  download. Confirm creates only `deliveries` and `delivery_lines`; scanner
  acceptance, unplanned acceptance, close delivery and receipt creation from
  delivery remain compatibility flows for Stage 0.12.16.
- Stage 0.12.16: physical delivery acceptance is migrated to `WarehouseFacade`.
  Migrated routes include inspect, planned accept, unplanned accept, batch
  accept, safe line metadata edit, summary/conflicts read and delivery status
  refresh. Close delivery, destructive override/admin correction, inventory
  write, moves and DB migration remain out of scope.
- Move receipt methods behind `WarehouseFacade`.
- Move issue methods behind `WarehouseFacade`.
- Move balance, delivery, history and inventory analysis behind Warehouse submodules.
- Keep `WarehouseCore` until parity tests cover each extracted method.

## C. Reports Extraction

- Stage 0.12.8: read-only Reports API is migrated to `ReportsFacade`.
  Migrated routes include work logs read, daily/weekly report read, uploaded
  reports read and report CSV exports. Work log writes and CSV imports remain
  on the compatibility service.
- Stage 0.12.10: daily report, weekly report, weekly rows and report CSV exports
  consume warehouse facts through `WarehouseEventReader`. Work logs remain
  Reports-owned. The EventReader implementation is still compatibility-backed
  inside Warehouse.
- Stage 0.12.11: Reports write/import routes are migrated to `ReportsFacade`.
  Migrated flows include single work-log creation, batch daily task creation,
  work-log CSV direct import, work-log CSV preview/confirm and uploaded daily
  report import. Update/delete work-log flows are not migrated because no legacy
  implementation exists.
- Keep work logs in Reports.
- Read warehouse events through `WarehouseEventReader`.
- Prevent report code from writing stock tables.
- Move daily/weekly/export implementations behind `ReportsFacade`.

## D. Administration Extraction

- Stage 0.12.9: read-only Administration API is migrated to
  `AdministrationFacade`. Migrated routes include current user/profile read
  through `/api/data`, `/api/admin` aggregation and audit CSV export. User
  creation, password/profile writes, backup/restore, production DB upload and
  explicit integrity-check actions remain on the compatibility service.
- Move users, backup, restore, audit and integrity checks behind `AdministrationFacade`.
- Keep audit as infrastructure-owned until event storage is separated.

## E. Monitoring Integration Point

- Keep `FEATURE_MONITORING = false`.
- Mount future monitoring code behind `MonitoringFacade`.
- Keep Monitoring independent from Warehouse and Reports.

## F. Removal of WarehouseCore

- Remove only after all facade methods have direct module implementations.
- Remaining legacy includes Warehouse writes/imports, Administration writes/auth,
  backup/restore, Monitoring placeholder and compatibility helpers still used
  outside Reports write/import.
- Require unit tests, smoke UI, SQLite checks and architecture audit before each removal batch.

## G. Removal of legacy ui.js

- Continue screen-by-screen migration.
- Do not mass-rewrite template strings.
- Remove `legacy ui.js` only after all routes have module entrypoints and component renderers.
