# Warehouse Issue Architecture

Stage 0.12.14 moves serialized equipment/component issue write and import flows
behind `WarehouseFacade`.

## Public Contract

`WarehouseFacade` exposes:

- `validate_issue_serial(serial_number, context=None)`
- `prepare_issue(data)`
- `create_issue(data)`
- `create_issue_batch(rows)`
- `create_issue_by_serials(common_fields, serial_numbers)`
- `preview_issue_import(rows, filename, ...)`
- `confirm_issue_import(preview_id)`
- `import_issues(rows)`
- `preview_bulk_issue_serials(rows, filename)`
- `confirm_bulk_issue_preview(...)`
- `find_issue_candidates(query, filters=None)`
- `get_available_position(serial_number)`
- `get_problem_issues(filters=None)`

Inputs and outputs are plain dict/list/int values. Web/API routes call
`ApplicationContext -> WarehouseFacade`.

## Internal Modules

- `inventory/warehouse/issues.py`
- `inventory/warehouse/issue_imports.py`
- `inventory/warehouse/issue_repository.py`
- `inventory/warehouse/issue_validators.py`
- `inventory/warehouse/issue_models.py`
- `inventory/warehouse/issue_previews.py`

Cable issue remains in `inventory/warehouse/cables.py`.

## Model

Serialized equipment and components are issued by `source_serial_number`.
Equipment requires a task type/number. Components keep the current contract:
`target_serial_number` is required and must point to an equipment receipt;
`target_hostname` is stored when supplied but is not a CMDB relationship.

Each successful issue writes one `stock_issues` row and one or more
`stock_issue_allocations` rows in the same transaction. Balance remains computed
from receipts minus allocations; no balance row is written manually.

## Preview And Problem Mode

Issue preview storage is Warehouse-owned, in memory and actor-bound. Preview does
not write the database or audit. Confirm consumes the preview and revalidates
stock.

Problem row behavior is preserved:

- scanned issue confirm and soft issue CSV import can create unmatched issue rows
  for unknown S/N;
- strict bulk issue preview/confirm blocks unknown or unavailable S/N;
- known S/N with insufficient stock blocks and rolls back;
- problem rows do not create allocations and therefore do not reduce balance.

## Audit And Events

Successful matched rows write `ISSUE_CREATE`. Batch/import summaries write
`ISSUE_BATCH_CREATE`, `ISSUE_IMPORT`, `SCANNED_ISSUE_IMPORT` or
`BULK_ISSUE_IMPORT` depending on the flow. Soft unmatched rows write
`ISSUE_UNMATCHED`.

`WarehouseEventReader` continues to expose matched rows as `ISSUE_CREATED` and
unmatched/problem rows as `DATA_PROBLEM_FOUND`.
