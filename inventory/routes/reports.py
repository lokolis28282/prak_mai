"""Reports HTTP routes."""

from __future__ import annotations

from typing import Any
from urllib.parse import unquote

from ..service import WarehouseError
from .csv import USER_CSV_TEMPLATES
from .runtime import RouteRuntime


_XLSX_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)


def _send_xlsx(handler: Any, filename: str, body: bytes) -> None:
    handler._send_binary_download(filename, body, _XLSX_CONTENT_TYPE)


def _work_log_payload(data: dict[str, Any]) -> dict[str, Any]:
    """Extract a work-log write payload from a JSON action body."""
    fields = (
        "work_date", "task_source", "task_type", "task_number",
        "description", "status", "section", "due_date", "comment",
    )
    payload: dict[str, Any] = {field: str(data.get(field, "") or "") for field in fields}
    # The PNR checklist may arrive as a JSON array; keep it unflattened so the
    # validator can normalize the checked steps.
    payload["pnr_checklist"] = data.get("pnr_checklist", "")
    return payload


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
    elif path == "/api/work-logs-page":
        handler._send_json(200, reports.work_logs_page({
            "date_from": handler._query(query, "date_from"),
            "date_to": handler._query(query, "date_to"),
            "search": handler._query(query, "search"),
            "needs_review": handler._query(query, "needs_review"),
        }))
    elif path == "/api/shift-stats":
        handler._send_json(200, reports.shift_stats(handler._query(query, "date")))
    elif path == "/api/handover":
        handler._send_json(200, {"logs": reports.handover_logs({
            "date_from": handler._query(query, "date_from"),
            "date_to": handler._query(query, "date_to"),
        })})
    elif path == "/export/shift-report.xlsx":
        body = reports.shift_report_xlsx(handler._query(query, "date"))
        _send_xlsx(handler, "shift_report.xlsx", body)
    elif path == "/export/work-logs.xlsx":
        body = reports.work_logs_xlsx({
            "date_from": handler._query(query, "date_from"),
            "date_to": handler._query(query, "date_to"),
            "search": handler._query(query, "search"),
            "needs_review": handler._query(query, "needs_review"),
        })
        _send_xlsx(handler, "work_logs.xlsx", body)
    elif path == "/export/daily-report.xlsx":
        body = reports.daily_report_xlsx(handler._query(query, "date"))
        _send_xlsx(handler, "daily_report.xlsx", body)
    elif path == "/export/uploaded-daily-report.xlsx":
        body = reports.uploaded_report_xlsx(
            handler._query_int(query, "id", minimum=1)
        )
        _send_xlsx(handler, "uploaded_daily_report.xlsx", body)
    elif path == "/export/weekly-report.xlsx":
        body = reports.weekly_report_xlsx(
            handler._query(query, "start_date"),
            handler._query(query, "end_date"),
        )
        _send_xlsx(handler, "period_report.xlsx", body)
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
        reports.create_work_log(_work_log_payload(data), require_due_date=True)
    elif action == "UPDATE_WORK_LOG":
        reports.update_work_log(
            handler._query_int_value(data.get("id"), "id"),
            _work_log_payload(data),
            require_due_date=True,
        )
    elif action == "DELETE_WORK_LOG":
        reports.delete_work_log(handler._query_int_value(data.get("id"), "id"))
    elif action == "ASSIGN_SECTION":
        response["updated"] = reports.assign_section(
            data.get("ids", []), data.get("section", "")
        )
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
