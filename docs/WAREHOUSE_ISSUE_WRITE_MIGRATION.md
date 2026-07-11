# Stage 0.12.14 Warehouse Issue Write Migration Map

## Scope

Stage 0.12.14 migrates only serialized equipment/component issue flows to
`ApplicationContext -> WarehouseFacade`. Cable issue stays in the cable module.
Deliveries, inventory write, moves, Administration writes, backup/restore,
auth, Monitoring, DB schema migrations and release ZIP are out of scope.

## Current Issue Flows

| Flow | User scenario | Endpoint/action | Current method | Target WarehouseFacade method | Tables | Transaction | Allocations | Audit/event | Unknown S/N | Insufficient stock | Risk |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Manual equipment/component issue | Warehouse -> Issue -> manual form | `POST /api/action`, `action=STOCK_ISSUE`, `source_serial_number` set | `WarehouseService.add_stock_issue(**data)` -> `IssueService` -> `WarehouseCore.add_stock_issue` | `create_issue(data)` | `stock_issues`, `stock_issue_allocations`, `stock_receipts`, `reference_values`, `audit_log` | One SQLite connection; validate, read available lot, insert issue/allocation/audit | Allocates available receipt lot for exact S/N | `ISSUE_CREATE`; event reader emits `ISSUE_CREATED` | Error `позиция с S/N ... не найдена` | Error `недостаточный остаток ... доступно 0` | High: must preserve component target checks and no negative balance |
| Issue scanner validation | Warehouse -> Issue scanner input | `GET /api/scan-serial?kind=issue&serial_number=...` | `WarehouseService.scan_issue_serial(serial)` | `validate_issue_serial(serial_number)` | reads `stock_receipts`, `stock_issue_allocations` | Read-only | none | none | Returns `found=false`, `valid=true`, warning; confirm may create problem row | Returns `valid=false`, error already issued/no stock | Medium: current UI allows unknown S/N in scanner list |
| Scanned S/N batch confirm | Warehouse -> Issue -> scanned temporary list -> confirm | `POST /api/action`, `action=CONFIRM_SCANNED_ISSUES` | `WarehouseService.confirm_scanned_issues(common_fields, serial_numbers)` | `create_issue_by_serials(common_fields, serial_numbers)` | `stock_issues`, `stock_issue_allocations`, `stock_receipts`, `audit_log` | One transaction for all rows | Allocates each valid S/N; problem rows have no allocation | `SCANNED_ISSUE_IMPORT` summary plus `ISSUE_CREATE`/`ISSUE_UNMATCHED` rows; events `ISSUE_CREATED` and `DATA_PROBLEM_FOUND` | Existing contract: creates unmatched problem row and returns `{"imported": n, "unmatched": m}` | Hard error and full rollback if row is known but unavailable/already issued | High: mixed strict/problem behavior must not change |
| Bulk issue CSV preview | Warehouse -> Issue -> bulk S/N file | `POST /api/preview-csv?kind=bulk_issue` | `WarehouseService.preview_bulk_issue_serials(rows)` | `preview_bulk_issue_serials(rows, filename)` or `preview_issue_import(..., kind=bulk_issue)` | reads `stock_receipts`, `stock_issue_allocations`; in-memory preview | Read-only | none | none | Preview error `S/N ... не найден` | Preview error already issued/no stock | Medium: strict batch; no problem rows |
| Bulk issue CSV confirm | Bulk issue preview -> confirm | `POST /api/action`, `action=CONFIRM_BULK_ISSUE` | `WarehouseService.confirm_bulk_issue_preview(preview_id, issue_date, responsible, task_type, task_number, comment, target_serial_number)` | `confirm_bulk_issue_preview(...)` or `create_issue_by_serials(...)` | `stock_issues`, `stock_issue_allocations`, `stock_receipts`, `audit_log` | Re-preview then one transaction | Allocates every S/N; no problem rows | `BULK_ISSUE_IMPORT` summary plus `ISSUE_CREATE`; event `ISSUE_CREATED` | Confirm is blocked by preview error | Confirm is blocked by preview error | Medium: response is `{"ok": true, "imported": count}` |
| Generic issue CSV preview | Warehouse -> Import issue CSV | `POST /api/preview-csv?kind=issue&mode=<soft|strict>` | `WarehouseService.preview_stock_issue_rows(rows, soft=...)` | `preview_issue_import(rows, filename, soft=...)` | temporary transaction over `stock_issues`, `stock_issue_allocations`, `stock_receipts`; in-memory preview | Preview starts transaction/savepoints then rolls back; no DB mutation | simulated only, rolled back | none | Soft mode: preview row valid with warning/problem simulation; strict mode: error | Error unless soft-unmatched rule applies | High: preview must remain mutation-free |
| Generic issue CSV confirm | Generic issue preview -> confirm | `POST /api/action`, `action=CONFIRM_IMPORT_PREVIEW`, `kind=issue` | `WarehouseService.confirm_stock_issue_preview(preview_id)` | `confirm_issue_import(preview_id)` | `stock_issues`, `stock_issue_allocations`, `stock_receipts`, `audit_log` | Re-preview then import transaction | Valid rows allocate; soft unmatched rows create problem issue without allocation | `ISSUE_CREATE` or `ISSUE_UNMATCHED`; events `ISSUE_CREATED`/`DATA_PROBLEM_FOUND` | Soft import creates problem row; strict blocks | Blocks unless classified as soft unmatched | High: author-bound one-time preview required |
| Direct issue CSV import | Public direct import path | `POST /api/import-csv?kind=issue&mode=<soft|strict>` | `WarehouseService.import_stock_issue_rows(rows, soft=...)` | `import_issues(rows, soft=...)` | `stock_issues`, `stock_issue_allocations`, `stock_receipts`, `reference_values`, `audit_log` | One transaction | Allocations for matched rows; no allocation for problem rows | `ISSUE_CREATE`/`ISSUE_UNMATCHED` | Soft creates problem row; strict errors and rolls back | Blocks unless soft unmatched | Medium: API response `{"ok": true, "imported": n}` |
| Find in balance and issue | Warehouse -> Balance/search -> select position -> issue | `GET /api/balance`, `/api/position-card`, then `action=STOCK_ISSUE` | read via `WarehouseFacade`, write via legacy `add_stock_issue` | read unchanged; write `create_issue(data)` | reads balance tables, writes issue tables | write transaction as manual issue | exact S/N allocation | `ISSUE_CREATE`; `ISSUE_CREATED` | Same as manual | Same as manual | Low: read side already facade-backed |
| Problem issues read/export | Problem issues table/export/report | `/api/data` problem fields, `/export/problem-issues.csv`, reports | `WarehouseService.data_quality_problems()` | `get_problem_issues(filters=None)` read contract; problem rows created by issue module | reads `stock_issues`, `stock_issue_allocations` | Read-only for export; write only from soft issue flows | Problem rows have no allocation or partial unmatched quantity | Events `DATA_PROBLEM_FOUND`; audit currently `ISSUE_UNMATCHED` | Shows unknown S/N rows | Shows unmatched quantity if any | Medium: problem rows must not change balance |
| Legacy equipment/operations issue | Old equipment card issue | `POST /api/action`, `action=ISSUE` | `WarehouseService.issue(equipment_id, quantity, basis, responsible)` | Not migrated in this stage | `equipment`, `operations`, sync to stock tables | Legacy | Legacy sync | legacy audit/log | N/A | N/A | Out of scope |

## Current Validation Rules

Serialized issue rows:

- date accepts `YYYY-MM-DD`, `DD.MM.YYYY`, `DD/MM/YYYY`;
- `responsible` and positive `quantity` are required;
- `source_serial_number` is trimmed and uppercased;
- cable rows are rejected from S/N scanner/serialized issue path;
- equipment/components require `task_type` and `task_number`;
- `task_type` is checked against built-in task types plus active references in
  strict mode;
- equipment cannot be issued to itself;
- component issue requires `target_serial_number`;
- component target must exist as a receipt row with `equipment_type <> ''`;
- equipment/components must be issued in whole units;
- repeated S/N with no remaining balance is a controlled insufficient-stock
  error;
- scanner batch rejects duplicate S/N before writing;
- bulk issue preview rejects duplicate S/N;
- CSV soft import may create problem rows for unknown S/N; strict import errors.

## SQL And Allocations

Issue writes currently use:

- `SELECT id FROM stock_receipts WHERE serial_number = ? COLLATE NOCASE`;
- available lots query from `stock_receipts LEFT JOIN stock_issue_allocations`;
- target equipment lookup for component issues;
- `INSERT INTO stock_issues(...)`;
- `INSERT INTO stock_issue_allocations(issue_id, receipt_id, quantity)`;
- `INSERT INTO audit_log(...)`.

Balance is computed from receipt quantity minus allocated issue quantity. No
manual balance rows are written.

## Target Notes

- New implementation belongs in `inventory/warehouse/issues.py`,
  `issue_imports.py`, `issue_repository.py`, `issue_validators.py`,
  `issue_models.py` and `issue_previews.py`.
- Web/API must call `WarehouseFacade` for issue write/import/scanner flows.
- Cable issue remains in `inventory/warehouse/cables.py`.
- Problem issue behavior is preserved:
  scanner confirm and soft issue CSV create unmatched rows for unknown S/N;
  strict bulk confirm and unavailable known S/N block the operation.
- Preview storage is Warehouse-owned, in-memory and author-bound. Confirm is
  one-time and revalidates stock before writing.
