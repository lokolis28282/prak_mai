# APPLICATION_CONTEXT

`ApplicationContext` is the root object for product modules.

It contains:

- `warehouse`;
- `reports`;
- `monitoring`;
- `administration`;
- `current_actor`;
- `db_path`;
- `configuration`;
- `feature_flags`;
- `compat_service`.

## Stage 0.12.6

`compat_service` remains `WarehouseService`. This keeps existing API routes and tests stable while module boundaries are introduced.

`inventory.webapp.make_handler()` accepts either:

- `WarehouseService` for backwards compatibility;
- `ApplicationContext` for new wiring.

The web handler normalizes both forms to `ApplicationContext`.

## Stage 0.12.9 Administration

Administration read APIs use `context.administration` as the source for:

- current user/profile fields;
- users list;
- audit entries;
- backup list;
- light database status and diagnostics.

The compatibility service is still used for authentication, sessions and
write/admin actions until those flows receive separate contract tests.

## Stage 0.12.10 Warehouse Events

`ApplicationContext.from_service()` creates one `WarehouseEventReader` and
injects it into `ReportsFacade`.

Reports must not create readers inside individual report methods. This avoids
cyclic dependencies and keeps event extraction owned by Warehouse.

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

Before `ApplicationContext` is created, `inventory/webapp.py` validates the
explicit `ODE_MIGRATION_PILOT=1` request, exact DB marker/name/stage/status,
required tables, integrity/FK and no-sidecar condition. This prevents a
partially initialized runtime from opening an arbitrary or production DB as a
pilot. The validated pilot then constructs the compatibility service with
`initialize_database=False`, preventing normal schema initialization from
touching the review artifact. This override is not accepted from HTTP and the
constructor default remains `True`; without pilot mode, existing composition
and behavior are unchanged.

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

No settings UI is added in this stage.
