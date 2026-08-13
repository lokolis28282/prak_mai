# ApplicationContext — ODE 0.21.1 current wiring and extraction history

Patch 0.21.1 сохраняет wiring и публичные facade-контракты; изменения касаются
fail-closed проверки runtime-путей и Windows packaging.

Текущая startup composition вынесена в `inventory/core/web_runtime.py`. До
создания `ApplicationContext` модуль проверяет три выбранные DB, test
marker/role, production aliases и SQLite sidecars; после успешного gate он
создаёт compatibility service, конфигурацию и context. `inventory/webapp.py`
остаётся HTTP/session shell и не дублирует эту pre-write композицию.

`ApplicationContext` is the root object for product modules.

It contains:

- `warehouse`;
- `reports`;
- `monitoring`;
- `knowledge`;
- `administration`;
- `vacations`;
- `current_actor`;
- `db_path`;
- `configuration`;
- `feature_flags`;
- `compat_service`;
- `full_inventory`.

## Stage 0.12.6

`compat_service` remains `WarehouseService`. This keeps existing API routes and tests stable while module boundaries are introduced.

`inventory.webapp.make_handler()` accepts either:

- `WarehouseService` for backwards compatibility;
- `ApplicationContext` for new wiring.

The web handler normalizes both forms to `ApplicationContext`.

## ODE 0.16.0 Stage 4 HTTP routing

`make_handler()` creates the primary immutable `RouteRuntime` from the
normalized context and launch-contour status. In the normal production launch,
`WarehouseSiteRegistry` adds an independent Solar Warehouse runtime. Domain
handlers under `inventory/routes/` receive the selected Warehouse runtime for
Warehouse routes and the primary runtime for shared modules; they do not
construct services or contexts. The common
HTTP shell retains authentication, request actor scoping, locks, validation and
response security headers. HTML assembly is provided by
`inventory/templates/webapp.py`.

Authentication, Reports, Knowledge and Administration remain in the primary
application contour. Monitoring owns no business DB, and Vacations stays on
its standalone DB independently of the selected Warehouse site. The selected
session site changes only `WarehouseFacade`, compatibility service, posting
policy, Full Inventory state root, DB lock and database fingerprint. Solar authorisation uses
`AdministrationService.delegated_user_context()` with the already
authenticated public user; no credential or password hash is copied as an
authentication source. Normative details:
[`MULTI_WAREHOUSE_ARCHITECTURE.md`](MULTI_WAREHOUSE_ARCHITECTURE.md).

## Stage 0.12.9 Administration

Administration read APIs use `context.administration` as the source for:

- current user/profile fields;
- users list;
- audit entries;
- backup list;
- light database status and diagnostics.

The preceding paragraph records Stage 0.12.9. In the current runtime,
authentication and write/admin actions use the dedicated
`AdministrationFacade → AdministrationService`; HTTP session creation/logout
remain shell operations.

## ODE 0.16.0 Stage 1 Administration extraction

`ApplicationContext.administration` is now wired to a dedicated
`AdministrationService`, not to `WarehouseService` or `WarehouseCore`.

Administration owns:

- authentication, current actor context and role checks;
- user/profile reads and writes;
- audit writes and audit queries;
- database integrity diagnostics;
- verified backup and database diagnostics;
- legacy restore/replacement control boundary, которая остаётся fail-closed до
  полного ADR-013 protocol и не является доступной UI-функцией.

The HTTP layer routes login, request actor context, administration actions and
startup database checks through `context.administration`. `compat_service`
remains available for Warehouse/Reports legacy flows. Its administration
methods are deprecated delegates to the same `AdministrationService`; they do
not contain a second implementation.

## Stage 0.12.10 Warehouse Events

The composition layer creates one `WarehouseEventReader` and injects it into
`ReportsFacade`.

Reports must not create readers inside individual report methods. This avoids
cyclic dependencies and keeps event extraction owned by Warehouse.

## ODE 0.16.0 Stage 2 Reports extraction

`WarehouseService` now composes one transitional Reports boundary:

`ReportsFacade(db_path, Administration actor provider, WarehouseEventReader)`

`ApplicationContext.reports` reuses that exact instance, including its
Reports-owned preview store. The facade no longer receives `WarehouseService`
as its implementation and does not call report methods on `WarehouseCore`.
Legacy report methods on `WarehouseService` and `WarehouseCore` are deprecated
delegates to the same facade.

Reports owns work-log CRUD/imports, uploaded daily reports, daily/weekly
presentation and work-log CSV export. Warehouse owns event extraction only;
Reports receives plain `WarehouseEvent` values.

## ODE 0.16.0 Stage 3 Warehouse extraction

`WarehouseService` creates one set of receipt, issue, cable and delivery
services. `ApplicationContext.warehouse` reuses those exact instances through
`WarehouseFacade`; preview stores, repositories and actor context are not
duplicated.

The remaining read/legacy areas are composed under `WarehouseDomainService`:
history, legacy equipment/operations, balance/search/card, data quality and
references. `WarehouseCore` is only a deprecated adapter without business SQL.
`compat_service` remains available because old CLI/Python method names are
still supported, not because it owns a second implementation.

## Stage 0.13.1/0.13.2 Inventory Number

Equipment Card assignment and bulk Inventory Number CSV are resolved through
`context.warehouse`, never by constructing a receipt service/repository in the
HTTP layer. The actor provider attached to the Warehouse receipt service supplies
role and audit author for both Preview and Confirm.

The compatibility `kind=inventory` reconciliation path remains separate. The
new write path is:

`ApplicationContext -> WarehouseFacade -> ReceiptWriteService -> ReceiptRepository`.

## Stage 0.13.3A.5 Migration Pilot

Pilot review is wired through the existing `ApplicationContext.warehouse`, not
through a second application context or a direct `inventory/migration` import:

```text
HTTP GET
 -> ApplicationContext
 -> WarehouseFacade
 -> MigrationPilotReviewService
 -> marker-validated pilot DB (read-only projection)
```

`WarehouseFacade` exposes `list_migration_pilot_rows(...)` and
`get_migration_pilot_card(selection_id)`. The latter resolves the linked exact
receipt ID and delegates the ordinary card read through the actor provider.
Only plain allowlisted data returns to Web/API.

Before `ApplicationContext` or any schema writer is created,
`inventory/core/web_runtime.py` validates the explicit review request, exact
pilot/full marker/name/stage/status, required tables, integrity/FK,
production aliases and no-sidecar condition. This prevents a partially
initialized runtime from opening an arbitrary or production DB as review.
The validated review then constructs the compatibility service with database
initialization disabled where required. This override is not accepted from
HTTP and the constructor default remains `True`; without review mode, existing
composition and behavior are unchanged. Review/test auxiliary state
(Vacations, Full Inventory state, Knowledge uploads, Monitoring rules and
backup roots) is owned by a temporary runtime directory and removed on close.

`inventory/migration` remains offline and is never imported by
`ApplicationContext`. The dedicated build script is the only orchestration
point allowed to combine offline selector/builder with the Warehouse pilot
writer.

## Feature Flags

Central flags:

- `FEATURE_WAREHOUSE = true`;
- `FEATURE_REPORTS = true`;
- `FEATURE_MONITORING = false`;
- `FEATURE_MOBILE = false`;
- `FEATURE_EXTERNAL_API = false`.

`FEATURE_MONITORING=false` — legacy metadata из раннего extraction stage, а не
runtime activation gate: текущий `MonitoringFacade.module_status()` возвращает
`enabled=true`, и manual UI/API смонтированы отдельно. `FEATURE_EXTERNAL_API`
остаётся корректным: опубликованного external API и API-key auth нет.

Отдельный settings UI для этих legacy flags не добавлен.
