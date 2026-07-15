# DATABASE_OWNERSHIP

## Warehouse stabilization ownership

Warehouse владеет operational `stock_receipts`, `stock_issues`,
`stock_issue_allocations`, deliveries и canonical `reference_domains_v2`,
`reference_values_v2`, `reference_aliases_v2`. Все записи идут через
существующие service/facade boundaries и транзакции.

Migration tables остаются read-only provenance. Reports-owned `work_logs`,
`daily_report_uploads`, `daily_report_rows` не принадлежат Warehouse; они не
создаются, не удаляются и не очищаются стабилизацией. Monitoring-owned таблиц
стабилизация не добавляет.

Reference rename/deactivate/merge не переписывает `stock_receipts` и migration
source columns. Единственная operational correction этого run — exact receipt
1050001/S/N `1`, доказанный как ручной тест; correction script удалил только
его test-created legacy audit/reference trail и добавил отдельный audit.

Boundary introduced in ODE 0.12.6 and verified for source Stage 0.13.3A.5. ODE
keeps one SQLite file; ownership is logical, not physical.

**CURRENT LOCAL FACT (2026-07-14):** `data/warehouse.db` is the sole normal
local working database and is a validated promoted copy of the full historical
candidate. The table ownership below still applies to operational tables.
Migration provenance/reference-v2 tables coexist in the same SQLite file but
remain owned by Offline Migration and are read-only for normal runtime; their
presence does not create a second warehouse runtime.

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

## Stage 0.13.3A Offline Migration Ownership

**IMPLEMENTED:** `inventory/migration/` owns a separate, offline candidate
bounded context. Its reference-domain, alias and staging tables live only in
the disposable DB under `migration_inputs/workspace/`. They are not owned by
Warehouse, Reports or Administration runtime modules because they are not
connected to `ApplicationContext` and are not part of `inventory/db.py`.

| Artifact / logical table group | Owner | Readers | Writers | Production status |
|---|---|---|---|---|
| immutable `migration_inputs/raw/*` | Source owner; Migration reads | Migration extractor/audit | none inside ODE | local-only input; never packaged/committed |
| candidate reference domains/values | Offline Migration | Migration validator/reviewer | candidate generator only | not production master data |
| candidate reference aliases | Offline Migration | Migration validator/reviewer | candidate generator; future approved decision tool | not production aliases |
| migration batches/source files/staging rows | Offline Migration | Migration validator/reviewer | candidate generator only in this Stage | not production operations |
| `warehouse_migration_candidate.db` | Offline Migration | validator/manual SQLite review | generator only | disposable; mode `0600` on POSIX; never working DB or backup |
| migration reports/normalized previews | Offline Migration | reviewer | offline reporting tools | local-only analytical artifacts |

The candidate contains an allowlisted copy of current user/security rows,
including password hashes that are never emitted by reports. It therefore has
backup-level local sensitivity. It may also contain a clean copy of the
current schema for compatibility checks, but operational production-table
counts must remain zero in Stage
0.13.3A. Historical receipts/issues, target entity IDs and production reference
integration are **FUTURE STAGE**.

Production `reference_values` remains Warehouse/shared and current soft import
writers remain unchanged. Candidate unknown values must never call those
writers or become production references automatically.

The local replacement procedure is governed by
[MIGRATION_DATABASE_RESET_PLAN.md](MIGRATION_DATABASE_RESET_PLAN.md) and the
[working DB runbook](LOCAL_WORKING_DATABASE_RUNBOOK.md). It was not executed in
Stage 0.13.3A itself; it was executed later under explicit approval on
2026-07-14. This does not authorize a server production replacement.

## Stage 0.13.3A.5 Pilot Ownership

**PILOT ONLY / NOT PRODUCTION:** the pilot starts from the Stage 0.13.3A
candidate but is published as a different ignored DB. It does not change table
ownership in `data/warehouse.db`.

| Artifact / table group | Owner | Readers | Writers | Boundary |
|---|---|---|---|---|
| `PILOT_RECEIPT_SELECTION.xlsx` / `.md` | Offline Migration | migration reviewer | deterministic selector only | local ignored report; never import authority |
| `migration_pilot_marker` | Offline Migration | startup guard, validator | pilot builder only | exact stage/status/hash/count contract |
| `migration_pilot_selection` | Offline Migration | Warehouse pilot review adapter | pilot builder only | all 200 source decisions |
| `migration_pilot_identities` | Offline Migration + Warehouse receipt link | pilot review | pilot builder transaction | one imported identity per match key |
| `migration_pilot_provenance` | Offline Migration | pilot review/card | pilot builder transaction | source/history links; no production ownership |
| `migration_pilot_quarantine` | Offline Migration | pilot review | pilot builder only | no receipt/balance mutation |
| `migration_pilot_performance` | Offline Migration | validator/reviewer | pilot builder/measurement only | non-secret timings |
| pilot `stock_receipts` | Warehouse | Warehouse card/balance; Reports reader excludes opening-balance rows | `MigrationPilotReceiptWriter` through `ReceiptRepository` | only 130 `IMPORT` primaries in disposable DB |
| pilot `audit_log` | Administration/shared infrastructure | Equipment Card Timeline | existing shared audit adapter | migration actions only in disposable DB |
| `warehouse_pilot_candidate.db` | Offline Migration build; Warehouse read-only review | marker guard, validator, local reviewer | builder only; runtime starts with DB initialization disabled and mutations denied | sensitive disposable artifact, never working DB/backup |

The dedicated orchestration script may inject a Warehouse-owned receipt writer
into the offline builder. This is not permission for `inventory/migration` to
import runtime services or write production. The runtime review adapter lives
under Warehouse, reads only allowlisted pilot columns and exposes plain data
through `WarehouseFacade`.

The compatibility service's `initialize_database` argument remains `True` by
default. Only marker-validated pilot startup passes `False`, so opening the
review cannot run production schema initialization; browser smoke verifies the
pilot-copy SHA before/after.

Exact duplicate/conflict/quarantine rows never call the receipt writer. Shelf
history does not own or fork an identity. Pilot target IDs exist only in the
pilot copy; Stage A source candidate target IDs and all production tables remain
unchanged.

## Full Historical Candidate and Promoted Working Copy Ownership

**BUILD ARTIFACT AND LOCAL WORKING DESCENDANT:**
`warehouse_full_candidate.db` starts from the operationally empty Stage A
candidate. It retains schema, security users and approved/candidate
reference/staging tables; it never copies operational rows from
`data/warehouse.db`.

| Artifact / table group | Owner | Writer | Boundary |
|---|---|---|---|
| `migration_full_*` | Offline Migration | atomic full builder | reconciliation, identity, warning, quarantine, relationship, performance and cleanliness evidence |
| candidate `stock_receipts` | Warehouse | `MigrationFullWarehouseWriter` inside builder transaction | one state per identity; includes explicitly marked opening states |
| candidate `stock_issues` / allocations | Warehouse | same writer | only successfully linked serialized historical issues; one allocation each |
| candidate `audit_log` | shared audit infrastructure | same writer through `write_audit_entry` | allowlisted migration actions only; no second event store |
| full reports | Offline Migration | report generator | derivative evidence; never rebuild input |

Receipt IDs start above 1,000,000, issue IDs above 2,000,000 and allocation IDs
above 3,000,000. Deliveries, legacy equipment/operations, work logs and daily
report tables remain empty at promotion. The source file with the exact
candidate filename remains marker-guarded read-only review and rejects
operational POST requests. Its validated renamed copy at `data/warehouse.db`
is the ordinary local working contour: Warehouse owns writes to operational
tables through the existing facade, while Offline Migration provenance tables
remain diagnostic/read-only. The normal card, balance and dashboard read-path
uses `stock_receipts`, `stock_issues` and allocations, never legacy
`equipment/operations` counts.
