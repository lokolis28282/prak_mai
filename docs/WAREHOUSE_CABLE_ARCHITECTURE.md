# Warehouse Cable Architecture

Stage 0.12.13 separates cable warehouse logic from serialized
equipment/component receipt and issue flows.

Stage 0.12.14 moves serialized equipment/component issue into its own issue
module. Cable issue remains isolated here and still does not use S/N scanner
validation.

## Public Contract

`WarehouseFacade` exposes:

- `create_cable_receipt(data)`
- `create_cable_issue(data)`
- `create_cable_receipt_batch(rows)`
- `validate_cable_receipt(data)`
- `validate_cable_issue(data)`
- `get_cable_balance(filters=None)`
- `get_cable_types()`
- `get_cable_items(cable_type=None)`
- `preview_cable_import(...)`
- `confirm_cable_import(preview_id)`

Inputs and outputs are plain dict/list/int values. Web/API routes enter through
`ApplicationContext -> WarehouseFacade`.

## Internal Modules

- `inventory/warehouse/cables.py`
- `inventory/warehouse/cable_repository.py`
- `inventory/warehouse/cable_validators.py`
- `inventory/warehouse/cable_models.py`

The module writes current compatibility tables, not a new schema:

- cable receipt: `stock_receipts` row with `cable_type <> ''`, empty S/N fields;
- cable issue: `stock_issues` plus `stock_issue_allocations`;
- audit: shared audit adapter.

## Cable Model

Cables do not require S/N and are not identified by S/N. Quantity must be a
positive whole number because the current UI process counts cable items as
`шт`; cable length remains part of `item_name` when users need it.

The public cable balance key keeps the current API behavior:

`item_name + cable_type + project + datacenter + object_name + supplier + vendor + model + unit`

Shelves are combined for display, matching the existing balance contract.

## Atomicity

Cable issue validates the row, reads available cable lots, checks the requested
quantity, inserts the issue and inserts allocations in one SQLite transaction.
Audit is written only after the successful issue insert/allocation sequence.

## Events And Reports

`WarehouseEventReader` continues to expose:

- `CABLE_RECEIVED` from cable receipt rows;
- `CABLE_ISSUED` from cable issue allocations.

Reports consume cable movements through `WarehouseEventReader`; Reports does not
write or query cable tables directly.
