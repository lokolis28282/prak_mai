# Stage 0.12.13 Cable Warehouse Migration Map

## Scope

Stage 0.12.13 separates cable receipt/issue business logic from serialized
equipment/component flows behind `ApplicationContext -> WarehouseFacade`.

Out of scope: equipment/component issue migration, deliveries, inventory write,
Administration write, backup/restore, Monitoring, auth, frontend component
migration, database schema migration and release ZIP rebuild.

## Current Cable Flows

| Flow | User scenario | Endpoint/action | Legacy method | Target WarehouseFacade method | Tables | Transaction | Audit/event | Response | Risk |
|---|---|---|---|---|---|---|---|---|---|
| Manual cable receipt | Warehouse -> Receipt -> `Принять кабели` simple form | `POST /api/action`, `action=STOCK_RECEIPT`, `category=Кабели` or `cable_type` set | `WarehouseService.add_stock_receipt(**data)` -> `ReceiptService` -> `WarehouseCore.add_stock_receipt` | `create_cable_receipt(data)` | `stock_receipts`, `reference_values`, `audit_log` | One SQLite connection; validate, collect references, insert receipt, audit | Current audit `RECEIPT_CREATE`; event reader emits `CABLE_RECEIVED` from `stock_receipts.cable_type` | `{"ok": true}` | Medium: same endpoint/action as equipment receipt, must branch without changing response |
| Cable receipt through generic receipt CSV | Warehouse -> Receipt -> import file with `cable_type` rows | `POST /api/preview-csv?kind=receipt`, `POST /api/action action=CONFIRM_IMPORT_PREVIEW kind=receipt`, direct `POST /api/import-csv?kind=receipt` | Stage 0.12.12 facade delegates cable rows to legacy `preview_stock_receipt_rows`, `confirm_stock_receipt_preview`, `import_stock_receipt_rows` | Keep generic receipt CSV compatible; route cable rows to cable module only if needed by current API | `stock_receipts`, `reference_values`, `audit_log` | Preview read-only; confirm/import validates all rows then one transaction | Current audit `RECEIPT_IMPORT`; event reader emits `CABLE_RECEIVED` per receipt row | Existing preview/import response keys | High: mixed equipment/cable files may exist; no new cable-specific CSV flow is introduced in this stage |
| Manual cable issue | Warehouse -> Issue -> `Списать кабели` form | `POST /api/action`, `action=STOCK_ISSUE`, empty `source_serial_number`, `source_item_name`, `source_cable_type` set | `WarehouseService.add_stock_issue(**data)` -> `IssueService` -> `WarehouseCore.add_stock_issue` -> `_create_stock_issue` | `create_cable_issue(data)` | `stock_issues`, `stock_issue_allocations`, `stock_receipts`, `reference_values`, `audit_log` | One SQLite connection; validate issue, find available cable lots, check balance, insert issue and allocations, audit | Current audit `ISSUE_CREATE`; event reader emits `CABLE_ISSUED` when allocation receipt has `cable_type` | `{"ok": true}` | High: balance check and allocations must remain atomic and cannot allow negative cable stock |
| Cable balance | Warehouse -> Balance, KPI `Кабели`, position card | `GET /api/data`, `/api/position-card`, `/export/balance.csv` | `WarehouseService.stock_balance(...)`, `position_card(...)` | `get_cable_balance(filters=None)` for cable-only contract; existing balance endpoints continue through `WarehouseFacade.get_balance` | reads `stock_receipts`, `stock_issue_allocations` | Read-only | No audit; events are source rows | Existing balance JSON keys | Medium: current aggregate key ignores shelf as a grouping column and concatenates shelves; keep current result unless explicitly changed |
| Cable history | Warehouse -> History | `GET /api/data` warehouse history block | `WarehouseService.warehouse_history()` | existing `WarehouseFacade.get_warehouse_history`; cable writes produce history rows through same tables | reads `stock_receipts`, `stock_issues`, `audit_log` | Read-only | Shows receipt/issue plus audit rows | Existing history JSON keys | Low: write audit action names may change, history must still show cable movement |
| Cable events for reports | Reports daily/weekly via `WarehouseEventReader` | internal report call | `WarehouseEventReader._receipt_events/_issue_events` | unchanged event contract; cable module writes source rows | reads `stock_receipts`, `stock_issues`, `stock_issue_allocations` | Read-only | `CABLE_RECEIVED`, `CABLE_ISSUED` | Reports rows unchanged | Medium: avoid double reflection of the same operation |
| Frontend cable receipt scenario | Receipt scenario card `Принять кабели` | same `STOCK_RECEIPT` action from `receiptPayload()` | generic receipt form posts cable fields into legacy receipt method | same URL/action; web handler branches to `create_cable_receipt` | same as manual receipt | same as manual receipt | same as manual receipt | same as manual receipt | Low: UI already separate from scanner; should not trigger S/N wizard |
| Frontend cable issue scenario | Issue scenario card `Списать кабели` | same `STOCK_ISSUE` action from `cableIssuePayload()` | generic issue handler posts to legacy issue method | same URL/action; web handler branches to `create_cable_issue` | same as manual issue | same as manual issue | same as manual issue | same as manual issue | Medium: UI should show current balance and not use scanner table |

## Current Validation To Preserve

Cable receipt:

- accepts dates supported by shared warehouse date parser: `YYYY-MM-DD`,
  `DD.MM.YYYY`, `DD/MM/YYYY`;
- requires receipt date, responsible, item name, supplier, object/datacenter,
  cable type, unit and positive quantity;
- does not require S/N or inventory number;
- stores `serial_number=''`, `inventory_number=''`, equipment/component type
  empty, and `cable_type` set;
- strict reference mode rejects unknown active-reference fields; soft mode may
  collect references;
- quantity is positive; current schema supports REAL, but UI process uses `шт`.

Cable issue:

- issue date, responsible, source item name, source cable type and positive
  quantity are required;
- S/N is not used; scanner issue rejects cable lots by S/N;
- task type and task number are optional, but if one is present the other must
  be present;
- available cable lots are found by current legacy key:
  `item_name + cable_type` for allocation, while balance display groups by
  `project + item_name + supplier + vendor + model + unit + object_name +
  cable_type + datacenter`;
- issue cannot exceed available stock; allocations are FIFO by receipt date/id.

## Current SQL

Cable receipt writes:

- `INSERT INTO stock_receipts(...)` with `cable_type <> ''` and empty S/N fields;
- `INSERT OR IGNORE INTO reference_values(kind, name)` for soft references;
- `INSERT INTO audit_log(...)`.

Cable issue writes:

- `SELECT r.*, r.quantity - COALESCE(SUM(a.quantity), 0) AS available FROM stock_receipts ... WHERE r.item_name = ? COLLATE NOCASE AND r.cable_type = ? COLLATE NOCASE GROUP BY r.id HAVING available > 0`;
- `INSERT INTO stock_issues(...)`;
- `INSERT INTO stock_issue_allocations(issue_id, receipt_id, quantity)`;
- `INSERT INTO audit_log(...)`.

## Target Notes

- New code lives in `inventory/warehouse/cables.py`,
  `cable_repository.py`, `cable_validators.py` and `cable_models.py`.
- Public web/API entrypoint is `WarehouseFacade`.
- Cable receipt/issue must not call equipment/component receipt validators or
  S/N scanner validation.
- Generic equipment issue remains legacy; the web handler only diverts cable
  issue rows to the cable module.
- No cable-specific CSV flow is invented in this stage. Existing generic receipt
  CSV compatibility must keep working.
- Balance aggregation remains compatible with current UI/API. The documented
  cable balance identity for this stage is:
  `item_name + cable_type + project + datacenter + object_name + supplier +
  vendor + model + unit`; shelves are combined for display.
