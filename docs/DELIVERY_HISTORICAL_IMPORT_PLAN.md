# Delivery Historical Import Plan

The importer is prepared for document-only historical loads for 2025-2026.
Historical files may contain serial numbers that already exist on stock because
the physical receipt happened earlier. Such rows are saved as delivery document
lines with state `Уже на складе`; no receipt is created and no stock row is
updated.

For each confirmed file the system stores:

- source filename;
- upload date from `deliveries.uploaded_at`;
- uploader from `deliveries.uploaded_by`;
- delivery number and supplier where available;
- request/order numbers on lines;
- source-to-canonical mapping in preview response and compact audit details;
- line warnings through `state` and `error_text`.

The original binary file is not stored in the database in this stage. If later
required, use a Warehouse-owned file area such as
`data/delivery_imports/YYYY/MM/<delivery_id>/source.csv` with checksum metadata in
a future schema migration.

Stage 0.12.16 note: historical existing-S/N documents can be reconciled by
linking delivery lines to existing warehouse receipts and filling empty fields
only. This does not create a new receipt and does not rewrite historical receipt
date/responsible values.
