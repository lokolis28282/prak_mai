# Warehouse Receipt Architecture

Stage 0.12.12 moved equipment/component receipt write and import flows behind
`WarehouseFacade`; this living contract includes Inventory Number extensions
through source Stage 0.13.2.

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
- `assign_inventory_number(serial_number, inventory_number)`
- `preview_inventory_number_import(rows, filename)`
- `confirm_inventory_number_import(preview_id)`

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

## Inventory Number Lifecycle — Stage 0.13.1/0.13.2

S/N remains the card identity. Stage 0.13.1 fills an empty Inventory Number in
an existing Equipment Card; Stage 0.13.2 adds the Warehouse-owned bulk CSV flow
with `kind=inventory_numbers`. Both call the same transaction-aware repository
helper and never insert a receipt/card or overwrite a different number.

The route is:

`HTTP -> ApplicationContext -> WarehouseFacade -> ReceiptWriteService -> ReceiptRepository`.

Lookup is case-insensitive and exclusively by `stock_receipts.serial_number`.
The Inventory Number is used only to classify current value/ownership. A
non-empty canonical receipt value short-circuits classification to `UNCHANGED`
or `ALREADY_ASSIGNED`. Only when it is empty does the flow inspect linked
legacy/foreign ownership: an empty linked legacy value is synchronized in the
same transaction, while a conflicting legacy value blocks the row.

The older physical inventory reconciliation flow (`kind=inventory`) remains a
separate read-only/compatibility scenario and must not be confused with
Inventory Number assignment.

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

For `kind=inventory_numbers`, preview stores status, current number and receipt
identity in the existing author-bound `WarehousePreviewStore`. The token is
one-shot, has a one-hour TTL and is not bound to a specific HTTP session.
Duplicate S/N is `VALIDATION_ERROR` and blocks confirm; other conflicts are
построчными non-mutating results.

Confirm consumes the token, starts `BEGIN IMMEDIATE`, repeats the complete
analysis and rejects a changed plan. Every `SUCCESS` update, linked legacy sync
and audit entry is committed in one SQLite transaction. A mid-batch error rolls
back all of them. Direct `/api/import-csv?kind=inventory_numbers` is prohibited.

Full CSV/API/status/sequence contract:
[INVENTORY_NUMBER_IMPORT_ARCHITECTURE.md](INVENTORY_NUMBER_IMPORT_ARCHITECTURE.md).

## Audit And Events

Audit actions:

- `RECEIPT_CREATE`
- `RECEIPT_BATCH_CREATE`
- `RECEIPT_IMPORT`
- `EQUIPMENT_INVENTORY_NUMBER_ASSIGNED` — one entry per actually changed
  receipt; no entry for preview, conflicts or `UNCHANGED`.

`WarehouseEventReader` continues to expose receipt rows as `RECEIPT_CREATED`.
Reports consume receipts only through the event reader.

Inventory Number assignment is shown by Equipment Card Timeline from the
existing audit log. It is not a new `WarehouseEventReader` event type and does
not create a parallel event table.
