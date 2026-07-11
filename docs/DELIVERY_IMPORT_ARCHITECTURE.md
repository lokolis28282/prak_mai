# Delivery Import Architecture

Stage 0.12.15 introduces a Warehouse-owned delivery import layer:

- `inventory/warehouse/deliveries.py` for read/export operations.
- `inventory/warehouse/delivery_imports.py` for preview and confirm orchestration.
- `inventory/warehouse/delivery_repository.py` for SQL over delivery tables.
- `inventory/warehouse/delivery_mapping.py` for explicit column mapping.
- `inventory/warehouse/delivery_validators.py` for S/N and quantity rules.
- `inventory/warehouse/delivery_models.py` for constants and plain structures.
- `inventory/warehouse/delivery_previews.py` for preview storage.

`WarehouseFacade` is the public entry point for web/API delivery document import.
The webapp must not call `WarehouseService.preview_delivery_rows` or
`WarehouseService.confirm_delivery_preview` for document import after this stage.

Confirm creates only `deliveries`, `delivery_lines`, and a compact audit row.
It never creates `stock_receipts`, `stock_issues`, `stock_issue_allocations`,
allocations, or balance changes. Physical acceptance remains legacy until
Stage 0.12.16.

Reports consume delivery import facts through warehouse events/read contracts and
must not write delivery tables. Monitoring must not import delivery modules.

## Stress Snapshot

Temporary SQLite database, no production data mutation:

- seeded 100,000 `stock_receipts` rows in 3.486 sec;
- preview 1,000 delivery rows in 0.006 sec;
- preview 10,000 delivery rows in 0.053 sec;
- confirm 10,000 normalized delivery rows in 0.370 sec;
- 100 files x 100 rows preview+confirm in 0.623 sec;
- search delivery in 0.002 sec;
- open 10,000-line delivery card in 0.098 sec;
- database size after stress: 26.36 MB;
- resulting counts: 100,000 receipts, 101 deliveries, 20,000 delivery lines,
  zero stock issues and zero allocations.

Existing-S/N matching uses batched `IN (...)` lookups through
`DeliveryRepository`, not one SELECT per serial.

Stage 0.12.16 adds physical acceptance as a separate Warehouse layer. Document
import remains document-only and still must not create receipts.
