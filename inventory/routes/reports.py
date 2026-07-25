"""Reports HTTP routes."""

from __future__ import annotations

from typing import Any
from urllib.parse import unquote

from ..service import WarehouseError
from .csv import REPORT_HEADERS, USER_CSV_TEMPLATES, WORK_LOG_HEADERS, localized
from .runtime import RouteRuntime


def handle_get(
    handler: Any,
    runtime: RouteRuntime,
    path: str,
    query: dict[str, list[str]],
) -> bool:
    """Handle Reports reads, exports, and import templates."""
    reports = runtime.app_context.reports
    if path == "/api/work-logs":
        handler._send_json(200, {"logs": reports.list_work_logs({
            "date_from": handler._query(query, "date_from"),
            "date_to": handler._query(query, "date_to"),
        })})
    elif path == "/api/daily-report":
        handler._send_json(
            200,
            {"rows": reports.get_daily_report(handler._query(query, "date"))},
        )
    elif path == "/api/weekly-report":
        handler._send_json(
            200,
            reports.get_weekly_report(
                handler._query(query, "start_date"),
                handler._query(query, "end_date"),
            ),
        )
    elif path == "/api/uploaded-daily-report":
        handler._send_json(
            200,
            {
                "rows": reports.get_uploaded_report(
                    handler._query_int(query, "id", minimum=1)
                )
            },
        )
    elif path == "/export/work-logs.csv":
        rows = reports.export_work_logs_rows({
            "date_from": handler._query(query, "date_from"),
            "date_to": handler._query(query, "date_to"),
        })
        handler._send_csv("work_logs.csv", localized(rows, WORK_LOG_HEADERS))
    elif path == "/export/daily-report.csv":
        rows = reports.export_daily_report_rows(handler._query(query, "date"))
        handler._send_csv("daily_report.csv", localized(rows, REPORT_HEADERS))
    elif path == "/export/uploaded-daily-report.csv":
        rows = reports.export_uploaded_report_rows(
            handler._query_int(query, "id", minimum=1)
        )
        handler._send_csv(
            "uploaded_daily_report.csv", localized(rows, REPORT_HEADERS)
        )
    elif path == "/export/weekly-report.csv":
        handler._send_csv(
            "period_report.csv",
            reports.export_weekly_report_rows(
                handler._query(query, "start_date"),
                handler._query(query, "end_date"),
            ),
        )
    elif path == "/import/work-logs-template.csv":
        handler._send_template(
            "work_logs_import_template.csv", USER_CSV_TEMPLATES["work_logs"]
        )
    elif path == "/import/daily-report-template.csv":
        handler._send_template(
            "daily_report_template.csv", USER_CSV_TEMPLATES["daily_report"]
        )
    else:
        return False
    return True


def handle_action(
    handler: Any,
    runtime: RouteRuntime,
    action: str,
    data: dict[str, Any],
    response: dict[str, Any],
) -> bool:
    """Handle Reports writes routed through the Reports facade."""
    reports = runtime.app_context.reports
    if action == "WORK_LOG":
        reports.create_work_log(handler._work_log_payload(data))
    elif action == "UPDATE_WORK_LOG":
        reports.update_work_log(
            handler._query_int_value(data.get("id"), "id"),
            handler._work_log_payload(data),
        )
    elif action == "DELETE_WORK_LOG":
        reports.delete_work_log(handler._query_int_value(data.get("id"), "id"))
    elif action == "WORK_LOGS":
        response["saved"] = reports.create_work_logs(data.get("rows", []))
    elif action == "CONFIRM_IMPORT_PREVIEW":
        kind = data.get("kind", "")
        if kind == "work_logs":
            response["imported"] = reports.confirm_work_log_import(
                data.get("preview_id", "")
            )
        elif kind == "daily_report":
            result = reports.confirm_daily_report_import(
                data.get("preview_id", "")
            )
            response["imported"] = result["row_count"]
            response["upload_id"] = result["id"]
        else:
            return False
    else:
        return False
    return True


def handle_csv_import(
    handler: Any,
    runtime: RouteRuntime,
    *,
    kind: str,
    rows: list[dict[str, str]],
    preview: bool,
    soft: bool,
) -> bool:
    """Handle CSV imports owned by Reports."""
    reports = runtime.app_context.reports
    if kind == "work_logs":
        if preview:
            result = reports.preview_work_log_import(
                rows,
                unquote(handler.headers.get("X-Filename", "work_logs.csv")),
                soft=soft,
            )
            handler._send_json(200, {"ok": True, **result})
        else:
            imported = reports.import_work_logs(rows, soft=soft)
            handler._send_json(200, {"ok": True, "imported": imported})
        return True
    if kind == "daily_report":
        for row in rows:
            row["date"] = row.pop("work_date", "")
        filename = unquote(
            handler.headers.get("X-Filename", "daily_report.csv")
        )
        if preview:
            result = reports.preview_daily_report_import(rows, filename)
            handler._send_json(200, {"ok": True, **result})
        else:
            result = reports.import_daily_report(filename, rows)
            handler._send_json(
                200,
                {
                    "ok": True,
                    "imported": result["row_count"],
                    "upload_id": result["id"],
                },
            )
        return True
    return False


def preview_work_log_xlsx(
    handler: Any,
    runtime: RouteRuntime,
    sheet: str,
) -> None:
    """Preview an XLSX work-log sheet without mutating Reports data."""
    try:
        length = int(handler.headers.get("Content-Length", "0"))
        if length <= 0:
            raise WarehouseError("Выберите непустой XLSX-файл")
        if length > 50_000_000:
            raise WarehouseError("XLSX-файл превышает допустимый размер 50 МБ")
        body = handler.rfile.read(length)
        result = runtime.app_context.reports.preview_work_log_xlsx(
            body,
            sheet_name=sheet,
            filename=unquote(
                handler.headers.get("X-Filename", "work_logs.xlsx")
            ),
        )
        handler._send_json(200, {"ok": True, **result})
    except (WarehouseError, ValueError, UnicodeError) as error:
        handler._send_json(400, {"error": str(error)})
    except Exception:
        handler._send_json(500, {"error": "Внутренняя ошибка сервера"})
