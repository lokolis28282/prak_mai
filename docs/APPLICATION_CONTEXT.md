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

## Feature Flags

Central flags:

- `FEATURE_WAREHOUSE = true`;
- `FEATURE_REPORTS = true`;
- `FEATURE_MONITORING = false`;
- `FEATURE_MOBILE = false`;
- `FEATURE_EXTERNAL_API = false`.

No settings UI is added in this stage.
