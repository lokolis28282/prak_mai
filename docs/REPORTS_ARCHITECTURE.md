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
- `get_daily_report(report_date)`
- `get_weekly_report(start_date, end_date)`
- `get_weekly_report_rows(start_date, end_date)`
- `list_uploaded_reports()`
- `get_uploaded_report(upload_id)`
- `export_work_logs_rows(filters=None)`
- `export_daily_report_rows(report_date)`
- `export_weekly_report_rows(start_date, end_date)`
- `export_uploaded_report_rows(upload_id)`
- `get_reports_summary()`

All methods return plain `dict`/`list` data and preserve existing row order and key names.

## ReportsFacade Write Contract

- `create_work_log(data)`
- `create_work_logs(rows)`
- `preview_work_log_import(rows, filename, soft=True)`
- `confirm_work_log_import(preview_id)`
- `import_work_logs(rows, soft=False)`
- `preview_daily_report_import(rows, filename)`
- `confirm_daily_report_import(preview_id)`
- `import_daily_report(filename, rows)`

The facade accepts plain dictionaries/lists and returns plain dictionaries,
lists or integers. Validation lives inside `inventory/reports`. Update/delete
work-log methods are not exposed because no legacy implementation exists.

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
