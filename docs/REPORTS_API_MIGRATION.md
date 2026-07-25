# REPORTS_API_MIGRATION

Stage 0.12.8 migrates read-only Reports API calls from the compatibility service to `ReportsFacade`. URLs, JSON/CSV contracts, SQL behavior and write/import flows are unchanged.

## Endpoint Map

| URL | Method | Current legacy method | Target ReportsFacade method | Tables | Warehouse events | UI screen | Response format | Risk |
|---|---|---|---|---|---|---|---|---|
| `/api/work-logs` | GET | `service.work_logs(date_from,date_to)` | `reports.list_work_logs(filters)` | `work_logs` | no | Work logs | `{"logs": list}` | low |
| `/api/daily-report` | GET | `service.daily_report(date)` | `reports.get_daily_report(date)` | `work_logs`, stock read inside compatibility report | yes, via compatibility/EventReader boundary | Daily report | `{"rows": list}` | medium |
| `/api/weekly-report` | GET | `service.weekly_report(start,end)` | `reports.get_weekly_report(start,end)` | `work_logs`, stock/delivery/problem reads inside compatibility report | yes, via compatibility/EventReader boundary | Weekly report | report object | medium |
| `/api/uploaded-daily-report` | GET | `service.uploaded_daily_report(id)` | `reports.get_uploaded_report(id)` | `daily_report_uploads`, `daily_report_rows` | no | Uploaded report | `{"rows": list}` | low |
| `/api/data` | GET | `service.daily_report_uploads()` | `reports.list_uploaded_reports()` | `daily_report_uploads` | no | app bootstrap | same JSON key | low |
| `/export/work-logs.csv` | GET | `service.work_logs(date_from,date_to)` | `reports.export_work_logs_rows(filters)` | `work_logs` | no | Work logs export | CSV localized | low |
| `/export/daily-report.csv` | GET | `service.daily_report(date)` | `reports.export_daily_report_rows(date)` | `work_logs`, stock read inside report | yes | Daily export | CSV localized | medium |
| `/export/weekly-report.csv` | GET | `service.weekly_report_rows(start,end)` | `reports.export_weekly_report_rows(start,end)` | reports + warehouse read inside report | yes | Weekly export | CSV | medium |
| `/export/uploaded-daily-report.csv` | GET | `service.uploaded_daily_report(id)` | `reports.export_uploaded_report_rows(id)` | `daily_report_rows` | no | Uploaded export | CSV localized | low |
| `/import/work-logs-template.csv` | GET | template constant | unchanged | none | no | Work logs import | CSV template | none |
| `/import/daily-report-template.csv` | GET | template constant | unchanged | none | no | Ready report import | CSV template | none |

## Migrated In Stage 0.12.8

- `/api/work-logs`
- `/api/daily-report`
- `/api/weekly-report`
- `/api/uploaded-daily-report`
- `/api/data` reports-owned fields internally
- `/export/work-logs.csv`
- `/export/daily-report.csv`
- `/export/weekly-report.csv`
- `/export/uploaded-daily-report.csv`

## Not Migrated

- `WORK_LOG` and `WORK_LOGS` writes;
- work log CSV import/preview/confirm;
- ready daily report CSV import;
- report UI component migration.

## Contract Rule

`ReportsFacade` returns plain `dict`/`list` values and delegates to the compatibility service in Stage 0.12.8. Semantic contract tests compare legacy service output to facade output programmatically.
