# Stage 0.12.11 Reports Write Migration Map

## Scope

Reports write/import flows currently owned by the legacy compatibility service are moved to `ApplicationContext -> ReportsFacade`. Warehouse receipts, issues, deliveries, users/passwords, backup/restore, and Monitoring are out of scope.

## Flows

| Flow | UI scenario | URL / method | action / kind | Current legacy method | Target ReportsFacade method | Reports tables | Audit action | Transaction | Response format | Migration risk |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Single work log | Legacy work-log form posts one task row | `POST /api/action` | `action=WORK_LOG` | `WarehouseService.add_work_log(...) -> ReportService -> WarehouseCore.add_work_log` | `create_work_log(data)` | `work_logs`, `audit_log` | `WORK_LOG_CREATE` | Insert and audit in one transaction after validation | `{"ok": true}` | Low: route exists, facade can preserve shape |
| Daily report task batch | Reports -> Daily report -> add rows -> save report | `POST /api/action` | `action=WORK_LOGS` | `WarehouseService.add_work_logs(rows)` | `create_work_logs(rows)` | `work_logs`, `audit_log` | `WORK_LOG_BATCH_CREATE` | Validate all rows first; if any row fails, no rows or audit are written | `{"ok": true, "saved": <count>}` | Medium: must preserve row numbering and atomicity |
| Work logs CSV direct import | Reports -> Work logs -> upload CSV without preview | `POST /api/import-csv?kind=work_logs&mode=<soft|strict>` | `kind=work_logs` | `WarehouseService.import_work_log_rows(rows, soft=...)` | `import_work_logs(rows, soft=...)` | `work_logs`, `reference_values`, `audit_log` | `WORK_LOG_IMPORT` | Validate all non-empty rows first; collect soft references and insert in one transaction | `{"ok": true, "imported": <count>}` | Medium: soft mode currently adds unknown references |
| Work logs CSV preview | Reports -> Work logs -> choose CSV | `POST /api/preview-csv?kind=work_logs&mode=<soft|strict>` | `kind=work_logs` | `WarehouseService.preview_work_log_rows(rows, soft=...)` | `preview_work_log_import(rows, filename, soft=...)` | None on preview | None | Preview must not write DB or audit; stores in memory only | `{"ok": true, "total": ..., "valid": ..., "new": ..., "duplicates": ..., "error_count": ..., "errors": [...], "rows": [...], "mode": "...", "preview_id": "...", "can_confirm": ...}` | Medium: preview storage must become Reports-owned |
| Work logs CSV confirm | CSV preview confirmation | `POST /api/action` | `action=CONFIRM_IMPORT_PREVIEW`, `kind=work_logs` | `WarehouseService.confirm_work_log_preview(preview_id)` | `confirm_work_log_import(preview_id)` | `work_logs`, `reference_values`, `audit_log` | `WORK_LOG_IMPORT` | Revalidate stored rows, then import atomically; current contract consumes preview and rejects repeated confirm | `{"ok": true, "imported": <count>}` | Medium: repeated confirm behavior must stay rejected |
| Uploaded daily report | Reports -> Daily report -> upload ready CSV | `POST /api/import-csv?kind=daily_report` | `kind=daily_report` | `WarehouseService.import_daily_report_rows(filename, rows)` | `import_daily_report(filename, rows)` | `daily_report_uploads`, `daily_report_rows`, `audit_log` | `DAILY_REPORT_UPLOAD` | Validate all rows first; upload header, rows, and audit in one transaction | `{"ok": true, "imported": <row_count>, "upload_id": <id>}` | Low: isolated Reports tables |
| Daily report preview | Not currently wired in UI/API | N/A | N/A | N/A | `preview_daily_report_import(rows, filename)` | None on preview | None | Should validate and store Reports-owned preview if introduced | Same preview envelope as work logs | Low: additive facade contract |
| Daily report confirm | Not currently wired in UI/API | N/A | N/A | N/A | `confirm_daily_report_import(preview_id)` | `daily_report_uploads`, `daily_report_rows`, `audit_log` | `DAILY_REPORT_UPLOAD` | One-shot confirm, atomically writes upload | `{"id": <id>, "filename": "...", "row_count": <count>}` | Low: additive facade contract |
| Update work log | Not implemented | N/A | N/A | No legacy method found | Not added | N/A | N/A | N/A | N/A | None |
| Delete work log | Not implemented | N/A | N/A | No legacy method found | Not added | N/A | N/A | N/A | N/A | None |

## Current Frontend Callers

- `saveDailyLogs()` in the legacy inline UI and current `static/js/ui.js` sends `action=WORK_LOGS` to `/api/action`.
- CSV inputs with `data-kind="work_logs"` use `/api/preview-csv?kind=work_logs` for preview and `/api/import-csv?kind=work_logs` for direct import.
- Preview confirmation uses `action=CONFIRM_IMPORT_PREVIEW`, `kind=work_logs`.
- Ready daily report upload uses `/api/import-csv?kind=daily_report`.
- `static/js/reports/*.js` currently contains legacy placeholders and does not own these flows.

## Validation Rules To Preserve

- Dates accept `YYYY-MM-DD`, `DD.MM.YYYY`, and `DD/MM/YYYY`, normalized to ISO.
- Work log required fields: date, task source, task number, description, status.
- Work log task type is optional but, if present, must resolve to a task type reference in strict mode.
- Work log task number is currently required; empty task numbers are not allowed.
- Comments are trimmed and otherwise not length-limited by application validation.
- Cyrillic and whitespace-trimmed text are accepted.
- Empty CSV rows are skipped.
- Duplicate work log rows in preview are counted but do not block confirmation.
- Soft work-log import may collect unknown task source, task type, and status reference values.

## Preview Storage

Current preview storage is `WarehouseCore._import_previews`, shared with warehouse previews and in memory only. Reports migration must move work-log and daily-report previews to Reports-owned storage, with `kind`, `author`, `filename`, `created_at`, `rows`, and validation result. Preview does not write DB or audit.

## Audit

Reports writes currently call the shared audit table through the legacy core. The migration should keep audit rows in `audit_log` through an allowed shared/public audit adapter, without importing Administration internals. Audit details must include row count, filename, and created entity id where applicable, and must not contain secrets.
