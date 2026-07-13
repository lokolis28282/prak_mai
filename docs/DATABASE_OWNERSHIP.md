# DATABASE_OWNERSHIP

Boundary introduced in ODE 0.12.6 and verified for source Stage 0.13.2. ODE
keeps one SQLite file; ownership is logical, not physical.

| Table | Owner | Readers | Writers | Legacy | Future migration |
|---|---|---|---|---|---|
| `stock_receipts` | Warehouse | Warehouse, Reports via facade/events | WarehouseFacade receipt services for equipment/components/cables; compatibility service for delivery legacy flows | partial compatibility | stay Warehouse; expose event stream; add DB-level unique migration later if needed |
| `stock_issues` | Warehouse | Warehouse, Reports via facade/events | WarehouseFacade issue and cable services | no for current stock issue flows | stay Warehouse; expose event stream |
| `stock_issue_allocations` | Warehouse | Warehouse | WarehouseFacade issue and cable services | no for current stock issue flows | keep with issue lifecycle |
| `deliveries` | Warehouse | Warehouse, Reports via events | Warehouse | no | keep with delivery lifecycle |
| `delivery_lines` | Warehouse | Warehouse, Reports via events | Warehouse | no | keep with delivery lifecycle |

Stage 0.12.15 note: delivery document import writes `deliveries` and
`delivery_lines` only. It may batch-read `stock_receipts` for S/N matching but
must not insert or update `stock_receipts`, `stock_issues` or
`stock_issue_allocations`. Historical delivery documents with existing stock
serials are stored as document rows with compatible state metadata, not as new
receipts.

Stage 0.12.16 note: delivery acceptance may create `stock_receipts` only through
the Warehouse receipt repository transaction contract. It may fill empty fields
on an existing `stock_receipts` row according to the delivery conflict policy
and may link `delivery_lines.receipt_id`. It must not write issues or
allocations.

Stage 0.13.1/0.13.2 note: Inventory Number assignment is a Warehouse receipt
write. It updates only `stock_receipts.inventory_number` for an existing S/N.
When `legacy_equipment_id` links a legacy `equipment` row whose number is
empty, `equipment.inventory_number` is synchronized in the same transaction.
The same transaction writes one `audit_log` entry per actually changed receipt
through the shared audit adapter. Preview, conflicts and `UNCHANGED` write
nothing; no receipt/equipment card is inserted. Ownership and schema do not
change.

| `equipment` | Warehouse | Warehouse | Warehouse | legacy stock card source | replace with normalized item/card model later |
| `operations` | Warehouse | Warehouse | Warehouse | legacy operation log | replace with normalized warehouse events |
| `reference_values` | Warehouse/shared | Warehouse, Reports, Administration | Administration/Warehouse/Reports soft import until split | mixed ownership | split global vs warehouse references later |
| `work_logs` | Reports | Reports | Reports | no | stay Reports |
| `daily_report_uploads` | Reports | Reports | Reports | no | stay Reports |
| `daily_report_rows` | Reports | Reports | Reports | no | stay Reports |
| `users` | Administration | Administration, Core current user | Administration | no | stay Administration |
| `audit_log` | Administration | Administration, Core EventReader, Reports read-only events | Administration/Core infrastructure via shared audit adapter | temporary event source | separate module events later |

Core owns no business table. Monitoring owns no table in Stage 0.12.6. Future Monitoring tables must use `monitoring_` prefix or a separate migration mechanism.

Reports does not own Warehouse tables. When daily/weekly reports include
receipts, issues, deliveries or warehouse problem rows, those records are
read-only inputs exposed through `WarehouseEventReader`. Stage 0.12.10 keeps the
reader implementation inside Warehouse as a compatibility adapter over the
current SQLite schema.

Stage 0.12.11 makes Reports the only module writing `work_logs`,
`daily_report_uploads` and `daily_report_rows`. Reports write/import code may
write `audit_log` through the shared audit adapter and may create missing
work-log reference values in soft import mode until reference ownership is split.

Stage 0.12.12 moves equipment/component receipt writes and imports to
`WarehouseFacade` and the `inventory/warehouse` receipt modules. The table owner
does not change, no schema migration is introduced, and cable/delivery receipt
paths remain compatibility-backed until their own stages.

Stage 0.12.13 moves cable receipt and cable issue writes to `WarehouseFacade`
and the `inventory/warehouse` cable modules. Physical storage remains the same:
cable receipt rows use `stock_receipts.cable_type`, and cable issue allocations
use `stock_issues` plus `stock_issue_allocations`.

Stage 0.12.14 moves serialized equipment/component issue writes and imports to
`WarehouseFacade` and the `inventory/warehouse` issue modules. Physical storage
remains `stock_issues` plus `stock_issue_allocations`; unmatched problem rows
still have no allocation and therefore do not change balance.

Backup files under the configured backup directory are owned by Administration.
Read APIs expose only safe file metadata (`name`, `size`, `modified`) and do not
return absolute filesystem paths.
