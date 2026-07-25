# Stage 0.12.12 Warehouse Receipt Write Migration Map

## Scope

This stage migrates only equipment/component receipt write and import flows to
`ApplicationContext -> WarehouseFacade`. Issue, cable-specific flows,
deliveries, inventory, Administration writes, backup/restore and Monitoring stay
out of scope.

## Current Receipt Flows

| Flow | User scenario | Endpoint/action | Current function | Target WarehouseFacade method | Tables | Transaction | Response | Errors | Risk |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Manual stock receipt | Warehouse -> Receipt -> manual form | `POST /api/action`, `action=STOCK_RECEIPT` | `WarehouseService.add_stock_receipt(**data) -> ReceiptService -> WarehouseCore.add_stock_receipt` | `create_receipt(data)` | `stock_receipts`, `reference_values`, `audit_log` | One connection; validate, collect refs, insert receipt, audit | `{"ok": true}` | missing date/FIO/item/SN/type/reference, duplicate S/N/inventory, invalid quantity | Medium: must preserve broad legacy form fields and messages |
| Scan receipt serial validation | Warehouse -> Receipt wizard scanner, before adding S/N | `GET /api/scan-serial?kind=receipt&serial_number=...` | `WarehouseService.scan_receipt_serial(serial)` | `validate_receipt_serial(serial_number)` | reads `stock_receipts` | Read-only | `{"serial_number": "...", "valid": bool, "error": "..."}` | empty S/N, existing S/N | Low: isolated read check, but server-side confirm must still enforce uniqueness |
| Scanned S/N batch confirm | Warehouse -> Receipt wizard -> temporary S/N list -> confirm | `POST /api/action`, `action=CONFIRM_SCANNED_RECEIPTS` | `WarehouseService.confirm_scanned_receipts(common_fields, serial_numbers)` -> `import_stock_receipt_rows(rows, soft=False)` | `create_receipt_batch(rows)` or `confirm_scanned_receipts(common_fields, serial_numbers)` | `stock_receipts`, `reference_values`, `audit_log` | Validate serial list and all rows, duplicate check, insert all in one transaction | `{"ok": true, "imported": <count>}` | empty list, empty S/N, duplicate in batch, existing S/N, invalid common field | High: UI depends on temporary S/N behavior and atomic rollback |
| Receipt CSV preview | Warehouse -> Receipt -> choose CSV | `POST /api/preview-csv?kind=receipt&mode=<soft|strict>` | `WarehouseService.preview_stock_receipt_rows(rows, soft=...)` | `preview_receipt_import(rows, filename, unknown_columns, soft=...)` | reads `stock_receipts`, `reference_values`; current shared in-memory preview | Read-only DB; stores preview in process memory; no audit | `{"ok": true, "total": ..., "valid": ..., "new": ..., "duplicates": ..., "error_count": ..., "errors": [...], "rows": [...], "mode": "...", "preview_id": "...", "can_confirm": ...}` | row validation errors, duplicates, existing S/N/inventory, empty CSV | High: preview must become Warehouse-owned and must not mutate refs/audit |
| Receipt CSV confirm | Receipt CSV preview -> confirm | `POST /api/action`, `action=CONFIRM_IMPORT_PREVIEW`, `kind=receipt` | `WarehouseService.confirm_stock_receipt_preview(preview_id)` | `confirm_receipt_import(preview_id)` | `stock_receipts`, `reference_values`, `audit_log` | Re-preview critical checks, then import atomically; current contract consumes preview and repeated confirm fails | `{"ok": true, "imported": <count>}` | stale preview, wrong author, validation failure after preview, duplicate S/N/inventory | High: must revalidate to prevent double receipt |
| Receipt direct CSV import | Warehouse receipt import without preview, if UI/API calls `/api/import-csv?kind=receipt` | `POST /api/import-csv?kind=receipt&mode=<soft|strict>` | `WarehouseService.import_stock_receipt_rows(rows, soft=...)` | `import_receipts(rows, soft=...)` | `stock_receipts`, `reference_values`, `audit_log` | Validate all rows, duplicate/existing check, collect refs, executemany insert, audit | `{"ok": true, "imported": <count>}` | same as confirm; empty CSV | Medium: direct import not main UI path but public API remains |
| Legacy equipment receipt | Old equipment card quantity receipt | `POST /api/action`, `action=RECEIPT` | `WarehouseService.receipt(equipment_id, quantity, basis, responsible)` | Not migrated in this stage | `equipment`, `operations`, `stock_receipts`, `audit_log` | Legacy quantity update and sync | `{"ok": true}` | missing equipment, invalid quantity, stock card errors | Out of scope: legacy equipment/operations flow |
| Delivery upload auto-apply | Warehouse -> Deliveries -> CSV upload with auto_apply | `POST /api/preview-csv?kind=delivery`, then `action=CONFIRM_DELIVERY` | `preview_delivery_rows` / `confirm_delivery_preview` inserts `stock_receipts` internally | Delivery endpoint not migrated; optional internal receipt helper only if needed | `deliveries`, `delivery_lines`, `stock_receipts`, `reference_values`, `audit_log` | Delivery transaction owns upload and optional receipt rows | `{"ok": true, "delivery_id": <id>}` | delivery-specific row states, duplicate S/N, invalid quantity | Keep behavior unchanged; add regression only |
| Delivery scanner accept | Warehouse -> Delivery card -> scan serial | `POST /api/action`, `action=ACCEPT_DELIVERY_SERIAL` | `WarehouseService.accept_delivery_serial(...)` inserts `stock_receipts` internally | Not migrated in this stage | `delivery_lines`, `stock_receipts`, `reference_values`, `audit_log` | One delivery acceptance transaction | `{"ok": true, "found": true, "accepted": true, "receipt_id": ..., "line_id": ...}` | existing S/N, closed delivery, missing/unplanned serial | Out of scope; regression required |

## Frontend Callers

- `stockReceiptForm.onsubmit` sends `action=STOCK_RECEIPT`.
- `receiptScanner` calls `/api/scan-serial?kind=receipt&serial_number=...`.
- `confirmScanReceipts.onclick` sends `action=CONFIRM_SCANNED_RECEIPTS` with
  `common_fields` and `serial_numbers`.
- `.preview-input[data-kind="receipt"]` sends `POST /api/preview-csv?kind=receipt`.
- `confirmPreview("receipt", preview_id)` sends
  `action=CONFIRM_IMPORT_PREVIEW`, `kind=receipt`.
- `/api/import-csv?kind=receipt` remains a public direct import path.
- Delivery UI uses `kind=delivery`, `CONFIRM_DELIVERY`, `ACCEPT_DELIVERY_SERIAL`;
  these are not migrated in this stage.

## Current Validation Rules To Preserve

- Dates accept `YYYY-MM-DD`, `DD.MM.YYYY`, `DD/MM/YYYY`.
- Required: `receipt_date`, `responsible`, `item_name`, `supplier`, `vendor`,
  `object_name`, `datacenter`, exactly one of `equipment_type`,
  `component_type`, `cable_type`, `unit`, positive `quantity`.
- Equipment/components require non-empty S/N and integer quantity.
- Cable rows do not require S/N, but cable-specific receipt migration is out of
  scope for this stage.
- `serial_number` and `inventory_number` are trimmed and uppercased.
- In strict reference mode, active references are required.
- In soft mode, missing non-critical fields are defaulted and unknown reference
  values are collected during import/confirm, not during preview.
- Empty CSV rows are skipped.
- Duplicate S/N or inventory numbers inside the incoming batch fail the entire
  operation.
- Existing S/N/inventory numbers are checked case-insensitively.

## SQL And Audit

Receipt writes currently use:

- `INSERT INTO stock_receipts(...)`;
- `SELECT serial_number FROM stock_receipts WHERE ...`;
- `SELECT inventory_number FROM stock_receipts WHERE ...`;
- `INSERT OR IGNORE INTO reference_values(kind, name)` in soft mode;
- `INSERT INTO audit_log(...)`.

Audit actions:

- single manual receipt: `RECEIPT_CREATE`;
- CSV/import/batch receipt: `RECEIPT_IMPORT`;
- proposed batch scan summary: keep response contract, may audit
  `RECEIPT_IMPORT` or add `RECEIPT_BATCH_CREATE` if tests/documentation cover it;
- delivery acceptance uses `DELIVERY_ACCEPT` / `DELIVERY_UPLOAD` and remains
  delivery-owned.

## Target Notes

- New implementation belongs in `inventory/warehouse/receipts.py`,
  `receipt_imports.py`, `receipt_repository.py`, `validators.py`,
  `naming.py`, `previews.py`.
- Public entrypoint is `WarehouseFacade`.
- Preview storage must be Warehouse-owned, in-memory, author-bound, and isolated
  from Reports previews.
- The DB schema already includes partial unique indexes for non-empty
  `stock_receipts.serial_number` and `inventory_number`. Server-side duplicate
  checks must still run before insert for stable user errors; the DB unique
  indexes remain the final race guard.

## Appendix: Stage 0.13.1/0.13.2 Inventory Number Assignment

Этот appendix фиксирует последующее расширение receipt write boundary; таблицы
Stage 0.12.12 выше остаются исторической картой своего этапа.

| Flow | HTTP contract | Facade/service | Transaction and response |
|---|---|---|---|
| Template | `GET /import/inventory-numbers-template.csv` | static user template | UTF-8 BOM, `Serial Number;Inventory Number` |
| Single card assignment | `POST /api/action`, `ASSIGN_INVENTORY_NUMBER` | `WarehouseFacade.assign_inventory_number` -> receipt service/repository | fills one existing S/N card; idempotent for same value; one audit on update |
| Bulk preview | `POST /api/preview-csv?kind=inventory_numbers` | `preview_inventory_number_import(rows, filename)` | read-only DB; author-bound in-memory preview; returns six status counters, first 100 rows, up to 200 errors, `preview_id`, `can_confirm` |
| Bulk confirm | `POST /api/action`, `CONFIRM_IMPORT_PREVIEW`, `kind=inventory_numbers` | `confirm_inventory_number_import(preview_id)` | one-shot consume, `BEGIN IMMEDIATE`, revalidation, atomic updates/legacy sync/audit; returns `imported` and `changed_count` |
| Direct bulk import | `POST /api/import-csv?kind=inventory_numbers` | intentionally unsupported | controlled HTTP 400; Preview/Confirm cannot be bypassed |

Assignment lookup is exclusively case-insensitive S/N lookup in
`stock_receipts`. It creates no receipt/equipment card and never overwrites a
different number. The older `kind=inventory` endpoint remains physical
read-only reconciliation by S/N and is not an alias for this write flow.

Full contract: [INVENTORY_NUMBER_IMPORT_ARCHITECTURE.md](INVENTORY_NUMBER_IMPORT_ARCHITECTURE.md).
