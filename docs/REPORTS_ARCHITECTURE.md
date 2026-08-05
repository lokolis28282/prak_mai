# REPORTS_ARCHITECTURE

Reports has two input sources.

## Work Logs

Work logs are Reports-owned operational records entered by engineers:

- `work_logs`;
- `daily_report_uploads`;
- `daily_report_rows`.

They are not warehouse operations.

## Warehouse Events

Warehouse operations remain Warehouse-owned:

- receipts;
- issues;
- deliveries;
- cable receipts/issues;
- inventory checks.

Reports reads these events through `WarehouseEventReader`. Reports must not
insert, update or query `stock_receipts`, `stock_issues`, `deliveries`, or
`delivery_lines` directly. Reports may publish audit events through the shared
audit adapter.

Stage 0.12.8 keeps report calculations in the compatibility implementation, but web/API read routes now enter through `ReportsFacade`. Warehouse data remains read-only from the Reports point of view and must later move behind `EventReader` or another public Warehouse contract before `WarehouseCore` is removed.

Stage 0.12.10 moves daily/weekly report read calculations in `ReportsFacade`
to `WarehouseEventReader`. The reader is still compatibility-backed inside the
Warehouse module and may read the current SQLite schema, but Reports sees only
the event contract.

Stage 0.12.11 moves Reports write/import flows to `ReportsFacade` and
Reports-owned services. Work-log writes, work-log CSV preview/confirm/import,
and uploaded daily report import no longer call legacy Reports write methods
from the web/API layer.

## ReportsFacade Read Contract

- `list_work_logs(filters=None)`
- `work_logs_page(filters=None)` — bounded page (`WORK_LOG_PAGE_LIMIT`) plus `total`/`truncated`; supports `search`, `needs_review`, date range
- `shift_stats(report_date)` — KPI summary for the shift dashboard
- `assign_section(ids, section)` — bulk-assign a section and clear the review flag
- `handover_logs(filters=None)` — unfinished tasks (status != «Выполнено») for shift handover
- `shift_report_xlsx(report_date)` — two-sheet XLSX («Выполненные работы» + «Передача по смене»)
- `get_daily_report(report_date)`
- `get_weekly_report(start_date, end_date)`
- `get_weekly_report_rows(start_date, end_date)`
- `list_uploaded_reports()`
- `get_uploaded_report(upload_id)`
- `export_work_logs_rows(filters=None)` / `export_daily_report_rows(report_date)` / `export_weekly_report_rows(start_date, end_date)` / `export_uploaded_report_rows(upload_id)` — raw row builders reused by the XLSX exporters
- `work_logs_xlsx(filters=None)` / `daily_report_xlsx(report_date)` / `weekly_report_xlsx(start_date, end_date)` / `uploaded_report_xlsx(upload_id)` — single styled sheet per download; Reports downloads are XLSX, CSV stays only on the import side
- `get_reports_summary()`

All methods return plain `dict`/`list` data and preserve existing row order and key names.

## ReportsFacade Write Contract

- `create_work_log(data)`
- `create_work_logs(rows)`
- `update_work_log(log_id, data)`
- `delete_work_log(log_id)`
- `preview_work_log_import(rows, filename, soft=True)`
- `preview_work_log_xlsx(data, sheet_name, filename)`
- `confirm_work_log_import(preview_id)`
- `import_work_logs(rows, soft=False)`
- `preview_daily_report_import(rows, filename)`
- `confirm_daily_report_import(preview_id)`
- `import_daily_report(filename, rows)`

The facade accepts plain dictionaries/lists and returns plain dictionaries,
lists or integers. Validation lives inside `inventory/reports`. The УВР
(work-log) records carry an optional `section` field and a `needs_review` flag;
the flag is set for rows migrated from legacy Excel whose section could not be
matched to the reference set. XLSX import reuses the standard preview → confirm
pipeline; the reader (`inventory/shared/xlsx.py`) is standard-library only.
The shift and week report tabs reuse `list_work_logs` with a date filter, so all
report views share the same underlying `work_logs` model.

Records also carry `due_date` and `pnr_checklist`. `due_date` is required for a
single interactive entry (`prepare_work_log` with no `line_number`) and optional
for bulk CSV/XLSX imports; `section` is optional. When the task source is `PNR`,
`prepare_work_log` derives the description and status from the checked steps (see
`validators.PNR_CHECKLIST`): all steps → «Выполнено», at least one but not all →
«В работе». The checklist enforces a work order via `PNR_PREREQUISITES`
(«Прокладка кабеля» requires «Маркировка кабеля»; «Коммутация…» requires
«Прокладка кабеля»); `normalize_pnr_checklist` drops any step whose prerequisite
is unchecked, so a crafted request cannot bypass the UI blocking.
`handover_logs` returns every record whose status is not «Выполнено», so a fully
completed task (including a fully checked PNR) is never handed over while
unfinished tasks are never lost between shifts. For an unfinished PNR task the
handover description is replaced with the specific remaining actions
(`pnr_handover_text`/`pnr_remaining_steps`): one remaining step →
«Необходимо выполнить: <шаг>.», several → a bullet list. The same enrichment
feeds both the handover table and the «Передача по смене» sheet.

The two-sheet shift XLSX and the single-sheet report exports are written by
`inventory/shared/xlsx_writer.py`. `build_styled_workbook`/`SheetSpec` render a
merged, centred, light-green title band (row 7), a bold light-yellow header band
(row 8, starting column C), thin table borders and per-column auto-width; the
plain `build_workbook` is kept for raw grids. The «Выполненные работы» sheet has
no «Срок» column, the «Передача по смене» sheet keeps it.

The removed «Тип задачи» field: the work-log UI form and the «Все работы»
registry no longer show `task_type` (it duplicated «Источник задачи»).
`full_task_name` is now derived as `task_source-task_number` (source only when
the number is empty). The `task_type` column stays in `work_logs` for CSV import
compatibility and is optional in `prepare_work_log`; nothing in the UI writes it.

Per-source «Описание работ» hints (ЗНР/ИНЦ searchable lists, Outlook/ИЗМ
placeholders) live in the frontend config `static/js/reports/index.js`
(`descriptionModes`) and always allow free text; the backend stores the final
text unchanged.

HTTP endpoints: `GET /api/handover`, `GET /api/work-logs-page`,
`GET /api/shift-stats`, action `ASSIGN_SECTION`, and the XLSX exports
`GET /export/shift-report.xlsx`, `GET /export/work-logs.xlsx`,
`GET /export/daily-report.xlsx`, `GET /export/weekly-report.xlsx`,
`GET /export/uploaded-daily-report.xlsx`. The former `/export/*.csv` report
routes are gone; CSV survives only as import templates and Warehouse exports.
The УВР registry now lives inside the «Отчёт за смену» tab as an inner
«Все работы» switch; it reads through `work_logs_page` so the table stays bounded
as the log grows and paginates client-side in pages of 25. Audit action
`WORK_LOG_BULK_SECTION` records bulk assignments. The shift dashboard shows three
cards — «Работ за смену», «Выполнено», «Незавершённых» (the «PNR прогресс» card
was removed); `shift_stats` still returns the PNR fields for other callers.

The «За смену» table renders per-row actions («Изменить» / «Удалить»; a viewer
gets a read-only «Просмотр»), so shift entries — including completed ones — can be
changed or removed in place, not only from the «Все работы» registry. The action
cell is produced by the registry controller (`reports.workLogs.actionsFor(row,
onChange)`); the shift view passes its own `buildShift` refresh callback and its
rows by value, while the registry keeps refreshing through `load`. Edit and
delete reuse the existing `UPDATE_WORK_LOG` / `DELETE_WORK_LOG` actions, so no new
endpoint or audit action was added. Delete asks for confirmation through the
shared styled dialog `confirmDialog` (`static/js/components.js`) rather than the
browser `confirm()`; it returns a `Promise<boolean>` and is reused for the
Excel-import confirmation too.

## Atomicity And Preview

Bulk work-log creation, work-log CSV import and uploaded daily report import
validate all rows before writing. If any row fails validation, no report rows
and no audit row are committed.

Preview storage is Reports-owned and in memory. Preview entries include kind,
author, filename, created timestamp, source rows and validation result. Preview
does not write the database or audit log. Confirm consumes the preview id; a
second confirm receives the existing "preview not found or expired" error.

## Audit

Reports publishes these actions through the shared audit adapter:

- `WORK_LOG_CREATE`
- `WORK_LOG_BATCH_CREATE`
- `WORK_LOG_UPDATE`
- `WORK_LOG_DELETE`
- `WORK_LOG_IMPORT`
- `DAILY_REPORT_UPLOAD`

Audit details include row counts, filenames or created ids where applicable and
must not include passwords or secrets.

## Output

Daily and weekly reports combine Reports-owned work logs with read-only Warehouse event data at report generation time. They must not merge work logs and stock movements into one storage table.
# Stage 0.12.16 Delivery Acceptance

Reports continue to consume warehouse facts through `WarehouseEventReader`.
Delivery document upload is a `DELIVERY_IMPORTED` fact. Physical acceptance of
a delivery line is a `DELIVERY_ACCEPTED` fact derived from
`delivery_lines.receipt_id`. Existing-S/N reconciliation does not create a new
receipt row, so it must not appear as a new warehouse receipt.
