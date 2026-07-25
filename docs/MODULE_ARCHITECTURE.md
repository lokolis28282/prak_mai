# MODULE_ARCHITECTURE

## 0.14 bounded rehearsal contour

`baseline_rehearsal/` — ограниченный orchestration module между
`inventory/warehouse/baseline` и ODE target infrastructure. Он не импортирует
legacy `service`, `webapp`, Reports, Monitoring или offline migration package,
не содержит production DB path и не используется `ode/`. Единственная runtime
точка вызова — `FullInventoryService.build_candidate_rehearsal`; результат
всегда disposable и имеет `publish_available=false`.

Stage 0.12.6 introduced product module boundaries without removing
`WarehouseCore` or legacy UI. This document includes subsequent migrations
through source/runtime `0.14.0`. Last built ZIP remains `0.12.17 RC1`.

## Modules

Core:

- starts and wires modules through `ApplicationContext`;
- owns navigation, current actor context, feature flags and shared runtime configuration;
- does not own business tables.

Warehouse:

- owns stock operations, balance, deliveries, warehouse history and inventory analysis;
- writes equipment/component receipts through `WarehouseFacade`;
- writes cable receipt/issue operations through `WarehouseFacade`;
- writes serialized equipment/component issues through `WarehouseFacade`;
- imports delivery documents through `WarehouseFacade` without creating receipts;
- assigns Inventory Number to existing S/N cards, including bulk CSV
  Preview/Confirm, through the receipt boundary of `WarehouseFacade`;
- does not import Reports or Monitoring;
- publishes/readies warehouse events through the Core event contract.

Reports:

- owns work logs and report generation;
- reads warehouse events through `EventReader`;
- writes work logs and uploaded daily reports through `ReportsFacade`;
- must not write stock receipts, stock issues or delivery tables.

Monitoring:

- owns isolated hostname routing and the manual operator search flow;
- may use an explicitly configured optional DCIM collector and local ignored
  routing rules, but never sends messages automatically;
- does not import Warehouse, Reports, `WarehouseService` or `WarehouseCore`;
- exposes `MonitoringFacade.module_status()` and `resolve_hostname()`.

Knowledge:

- owns `knowledge_*` tables and private attachment files;
- exposes safe Markdown, search and role-checked CRUD through `KnowledgeFacade`;
- does not import Warehouse, Reports or Monitoring.

Administration:

- owns users, backup, restore, audit view and diagnostics;
- must not contain warehouse or report business rules.

Migration staging (offline tooling, not an application runtime module):

- lives in `inventory/migration` with the thin
  `scripts/migration_reference_data.py` CLI;
- reads immutable `migration_inputs/raw` and may inspect the working DB only
  through read-only SQLite;
- owns 16 candidate reference domains, alias decisions, canonical-name
  proposals, S/N provenance and nine candidate-only staging tables;
- writes generated artifacts only below ignored
  `migration_inputs/workspace`;
- must not import `inventory/webapp.py`, call a facade, mutate production
  references, or create warehouse operations.

Migration pilot orchestration (offline, Stage 0.13.3A.5):

- lives in a dedicated `scripts/migration_pilot.py` entry point;
- may combine offline selector/builder with an injected Warehouse-owned exact
  receipt writer only for the disposable pilot DB;
- never makes `inventory/migration` a dependency of Web/API/runtime services;
- creates no production operation and cannot target `data/warehouse.db`;
- publishes ignored selection reports and a separately named marker DB.

Warehouse pilot adapter:

- `migration_pilot.py` owns exact repository writes during offline build;
- `migration_pilot_review.py` owns marker validation and allowlisted runtime
  reads;
- public review goes through `WarehouseFacade`; no direct Web/API SQL or
  `inventory/migration` import is allowed.

## Transitional State

`WarehouseCore` remains the compatibility core. New facades delegate to the existing `WarehouseService` facade, which still delegates to specialized services and `WarehouseCore`. This is intentional for ODE 0.12.6: it creates boundaries without a data migration or behavior change.

Web/API receives `ApplicationContext` via `make_handler()`. The handler still uses a compatibility service adapter internally for write endpoints while module calls are extracted gradually.

Stage 0.12.7 routes read-only Warehouse GET/CSV paths through:

`web/API -> ApplicationContext -> WarehouseFacade -> compatibility service -> WarehouseCore`

Stage 0.12.8 routes read-only Reports GET/CSV paths through:

`web/API -> ApplicationContext -> ReportsFacade -> compatibility service`

Stage 0.12.9 routes read-only Administration GET/CSV paths through:

`web/API -> ApplicationContext -> AdministrationFacade -> compatibility service`

This includes current user/profile read, `/api/admin` aggregation and audit CSV
export. Authentication, session writes and admin actions remain compatibility
flows.

Stage 0.12.10 wires warehouse events through:

`ApplicationContext -> WarehouseEventReader -> ReportsFacade`

Reports owns work logs and report presentation. Warehouse owns event extraction
from warehouse tables. Reports must not import `WarehouseCore` or query
warehouse-owned tables directly.

Stage 0.12.11 routes Reports write/import flows through:

`web/API -> ApplicationContext -> ReportsFacade -> inventory/reports services`

The migrated flows are `WORK_LOG`, `WORK_LOGS`, work-log CSV import, work-log
CSV preview/confirm and uploaded daily report import. Preview storage for these
flows is Reports-owned and in memory.

Stage 0.12.12 routes equipment/component receipt writes through:

`web/API -> ApplicationContext -> WarehouseFacade -> inventory/warehouse receipt services`

Cable receipt, issue, delivery and legacy equipment/operations writes are still
compatibility flows. Delivery endpoints are not migrated in this stage, though
regression coverage ensures delivery acceptance still creates receipts.

Stage 0.12.13 routes cable receipt and cable issue writes through:

`web/API -> ApplicationContext -> WarehouseFacade -> inventory/warehouse cable services`

Cables are quantity-based, do not require S/N and do not use scanner/S/N
receipt validation. Generic equipment/component issue and deliveries remain
compatibility flows.

Stage 0.12.14 routes serialized equipment/component issue writes through:

`web/API -> ApplicationContext -> WarehouseFacade -> inventory/warehouse issue services`

The migrated flows include scanner validation, scanned S/N confirm, manual
issue, generic issue CSV preview/confirm/import and strict bulk S/N issue.
Deliveries, inventory write and legacy equipment/operations remain
compatibility flows.

Stage 0.12.15 routes delivery document import and matching through:

`web/API -> ApplicationContext -> WarehouseFacade -> inventory/warehouse delivery import services`

The migrated flows include delivery CSV preview, explicit mapping, S/N
expansion, duplicate and existing-stock matching, confirm document,
list/card/lines/search/export and template download. Confirm writes only
`deliveries`, `delivery_lines` and compact audit. Physical delivery acceptance,
unplanned acceptance, receipt creation from delivery and close delivery remain
compatibility flows.

Stage 0.12.16 routes physical delivery acceptance through:

`web/API -> ApplicationContext -> WarehouseFacade -> inventory/warehouse delivery acceptance services`

The migrated flows include inspect, planned/unplanned accept, batch accept,
safe line metadata update, conflicts/summary read and status refresh. New S/N
acceptance creates receipts through the receipt repository transaction
contract; existing S/N acceptance fills only empty fields. Close delivery
remains compatibility.

Stage 0.13.1 routes Equipment Card Inventory Number assignment through:

`web/API -> ApplicationContext -> WarehouseFacade -> ReceiptWriteService -> ReceiptRepository`

Stage 0.13.2 reuses that boundary for bulk
`kind=inventory_numbers` Preview/Confirm. S/N-only lookup, revalidation under
`BEGIN IMMEDIATE`, atomic updates/legacy sync/audit and the prohibition on new
cards are Warehouse-owned rules. The older physical inventory comparison
`kind=inventory` and remaining legacy inventory functions are not migrated by
these stages.

**IMPLEMENTED — Stage 0.13.3A:** the offline flow is deliberately parallel to
the runtime dependency graph rather than another Web/API import:

`migration_reference_data.py -> inventory/migration -> disposable candidate DB`

The commands are `inspect-sources`, `build-candidate`, `validate-candidate`
and `report`. Source S/N extraction retains the OOXML token, cell type, number
format and provenance; normalized values exist only for matching. Candidate
reference/model/catalog records and staging decisions do not enter
`data/warehouse.db`.

**FACT:** the production `reference_values(kind, name, is_active)` contract is
unchanged. The nine richer tables (`migration_*`, `reference_*_v2` and
`catalog_items_v2`) exist only in the disposable candidate. Historical
receipt/issue import, a production reference migration and database reset are
not implemented.

**FUTURE STAGE / OPEN DECISION:** Stage 0.13.3B may consume only approved
staging decisions after an explicit migration contract. Whether the richer
reference model ever becomes a production schema is a separate ADR decision.

**IMPLEMENTED / PILOT ONLY — Stage 0.13.3A.5:**

```text
offline:
  raw + Stage A candidate
    -> deterministic selector (200 rows)
    -> pilot builder
    -> injected Warehouse exact writer (130 primary receipts)
    -> marker-guarded disposable pilot DB

review runtime:
  Web GET -> ApplicationContext -> WarehouseFacade
    -> MigrationPilotReviewService -> allowlisted pilot DB reads
```

Ordinary receipt normalization, production schema/API and working DB remain
unchanged. Duplicate/conflict rows share one imported identity/card; shelf is
placement. Pilot review exposes no write/confirm method. A module-boundary audit
keeps `migration_pilot_*` tables out of `inventory/db.py` and keeps runtime
imports one-way. The marker-validated web entry point disables ordinary service
DB initialization only for pilot startup; the compatibility constructor keeps
`initialize_database=True` by default.

**NOT PRODUCTION:** pilot approval does not authorize 0.13.3B, production
references or database replacement. The current NOCASE S/N uniqueness model
requires a separate ADR before case-distinct identities can be migrated.

`WarehouseCore` must not be referenced directly by `inventory/webapp.py`. New read-only Warehouse endpoints must be added to `WarehouseFacade` first.

## Public Facades

- `WarehouseFacade`
- `ReportsFacade`
- `MonitoringFacade`
- `AdministrationFacade`

The web layer must not call `WarehouseCore` directly. Future extraction should move endpoint groups to facade methods first, then move implementation behind each facade.
