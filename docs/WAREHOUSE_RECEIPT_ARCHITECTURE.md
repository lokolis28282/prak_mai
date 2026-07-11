# Warehouse Receipt Architecture

Stage 0.12.12 moves equipment/component receipt write and import flows behind
`WarehouseFacade`.

## Public Contract

- `validate_receipt_serial(serial_number)`
- `prepare_receipt(data)`
- `create_receipt(data)`
- `create_receipt_batch(rows)`
- `confirm_scanned_receipts(common_fields, serial_numbers)`
- `preview_receipt_import(rows, filename, unknown_columns=None, soft=False)`
- `confirm_receipt_import(preview_id)`
- `import_receipts(rows, soft=True)`
- `receipt_import_preview_rows(preview_id="")`

Inputs and outputs are plain dict/list/int values. Web/API code calls
`ApplicationContext -> WarehouseFacade`, not receipt methods on the compatibility
service.

## Internal Modules

- `inventory/warehouse/receipts.py`
- `inventory/warehouse/receipt_imports.py`
- `inventory/warehouse/receipt_repository.py`
- `inventory/warehouse/validators.py`
- `inventory/warehouse/naming.py`
- `inventory/warehouse/previews.py`

The repository writes `stock_receipts`, creates soft references when allowed,
and publishes audit through the shared audit adapter. Balance is still computed
from receipt and allocation rows; no separate balance rows are written.

## Receipt Model

This stage owns equipment and component receipts only:

- equipment: one S/N, integer quantity, `equipment_type`;
- component: one S/N, integer quantity, `component_type`;
- cable: handled by the separate cable module since Stage 0.12.13.

No schema migration was introduced. Existing partial unique indexes on non-empty
`serial_number` and `inventory_number` remain the final duplicate guard.

## Naming

Scanner/simple equipment and component flows use
`build_item_name(category, item_type, vendor, model)` to create system item
names such as `Сервер Dell PowerEdge R740` or `SSD Samsung PM883 1.92TB`.
The helper trims empty parts and avoids gratuitous duplication. Existing stored
rows are not rewritten.

## Preview

Receipt preview storage is Warehouse-owned, in memory, and author-bound. Preview
contains kind, author, filename, creation time, source rows, validation summary,
duplicates, existing S/N errors, normalized rows and unknown columns.

Preview does not write the database, audit, or references. Confirm consumes the
preview id and revalidates critical duplicate conditions before inserting.

## Audit And Events

Audit actions:

- `RECEIPT_CREATE`
- `RECEIPT_BATCH_CREATE`
- `RECEIPT_IMPORT`

`WarehouseEventReader` continues to expose receipt rows as `RECEIPT_CREATED`.
Reports consume receipts only through the event reader.
