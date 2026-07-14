"""Public reports facade."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from .daily import DailyReportImportService
from .imports import ReportsPreviewStore
from .repository import ReportsRepository
from .validators import parse_date
from .work_logs import WorkLogService


def _plain(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_plain(item) for item in value]
    if hasattr(value, "keys"):
        return {key: _plain(value[key]) for key in value.keys()}
    return value


class ReportsFacade:
    def __init__(self, service: Any, *, warehouse_events: Any = None):
        self.service = service
        self.warehouse_events = warehouse_events
        self._previews = ReportsPreviewStore()
        self.repository = ReportsRepository(service.db_path)
        self.work_log_service = WorkLogService(
            service.db_path,
            actor_provider=service,
            strict_reference_validation=service.strict_reference_validation,
            previews=self._previews,
        )
        self.daily_import_service = DailyReportImportService(
            service.db_path,
            work_logs=self.work_log_service,
            previews=self._previews,
        )

    def work_logs(self, *args: Any, **kwargs: Any) -> Any:
        return _plain(self.repository.work_logs(*args, **kwargs))

    def add_work_log(self, *args: Any, **kwargs: Any) -> Any:
        if kwargs:
            return self.create_work_log(kwargs)
        if args and isinstance(args[0], dict):
            return self.create_work_log(args[0])
        fields = (
            "work_date", "task_source", "task_type", "task_number",
            "description", "status", "comment",
        )
        return self.create_work_log({field: args[index] if index < len(args) else "" for index, field in enumerate(fields)})

    def add_work_logs(self, rows: list[dict[str, Any]]) -> int:
        return self.create_work_logs(rows)

    def create_work_log(self, data: dict[str, Any]) -> int:
        return int(self.work_log_service.create_work_log(dict(data)))

    def create_work_logs(self, rows: list[dict[str, Any]]) -> int:
        return int(self.work_log_service.create_work_logs([dict(row) for row in rows]))

    def update_work_log(self, log_id: int, data: dict[str, Any]) -> None:
        self.work_log_service.update_work_log(int(log_id), dict(data))

    def delete_work_log(self, log_id: int) -> None:
        self.work_log_service.delete_work_log(int(log_id))

    def preview_work_log_xlsx(
        self, data: bytes, *, sheet_name: str = "Логи", filename: str = "work_logs.xlsx"
    ) -> dict[str, Any]:
        return _plain(self.work_log_service.preview_xlsx_import(
            data, sheet_name=sheet_name, filename=filename
        ))

    def work_log_xlsx_sheets(self, data: bytes) -> list[str]:
        from inventory.shared.xlsx import XlsxError, sheet_names

        try:
            return list(sheet_names(data))
        except XlsxError as error:
            from inventory.shared.validators import WarehouseError

            raise WarehouseError(str(error)) from error

    def preview_work_log_import(
        self, rows: list[dict[str, Any]], filename: str = "work_logs.csv", *, soft: bool = True
    ) -> dict[str, Any]:
        return _plain(self.work_log_service.preview_work_log_import(
            [dict(row) for row in rows], filename=filename, soft=soft
        ))

    def confirm_work_log_import(self, preview_id: str) -> int:
        return int(self.work_log_service.confirm_work_log_import(preview_id))

    def import_work_logs(self, rows: list[dict[str, Any]], *, soft: bool = False) -> int:
        return int(self.work_log_service.import_work_logs([dict(row) for row in rows], soft=soft))

    def preview_daily_report_import(
        self, rows: list[dict[str, Any]], filename: str = "daily_report.csv"
    ) -> dict[str, Any]:
        return _plain(self.daily_import_service.preview_daily_report_import(
            [dict(row) for row in rows], filename=filename
        ))

    def confirm_daily_report_import(self, preview_id: str) -> dict[str, Any]:
        return _plain(self.daily_import_service.confirm_daily_report_import(preview_id))

    def import_daily_report(self, filename: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
        return _plain(self.daily_import_service.import_daily_report(
            filename, [dict(row) for row in rows]
        ))

    def preview_work_log_rows(self, rows: list[dict[str, Any]], *, soft: bool = True) -> dict[str, Any]:
        return self.preview_work_log_import(rows, soft=soft)

    def confirm_work_log_preview(self, preview_id: str) -> int:
        return self.confirm_work_log_import(preview_id)

    def import_work_log_rows(self, rows: list[dict[str, Any]], *, soft: bool = False) -> int:
        return self.import_work_logs(rows, soft=soft)

    def import_daily_report_rows(self, filename: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
        return self.import_daily_report(filename, rows)

    def daily_report(self, *args: Any, **kwargs: Any) -> Any:
        return self.get_daily_report(*args, **kwargs)

    def weekly_report(self, *args: Any, **kwargs: Any) -> Any:
        return self.get_weekly_report(*args, **kwargs)

    def daily_report_uploads(self, *args: Any, **kwargs: Any) -> Any:
        return _plain(self.repository.daily_report_uploads(*args, **kwargs))

    def uploaded_daily_report(self, *args: Any, **kwargs: Any) -> Any:
        return _plain(self.repository.uploaded_daily_report(*args, **kwargs))

    def weekly_report_rows(self, *args: Any, **kwargs: Any) -> Any:
        return self.get_weekly_report_rows(*args, **kwargs)

    def export_report(self, *args: Any, **kwargs: Any) -> Any:
        return self.service.export_csv(*args, **kwargs)

    def read_warehouse_events(self, limit: int = 300) -> list[Any]:
        if not self.warehouse_events:
            return []
        return self.warehouse_events.list_events("1900-01-01", "2999-12-31", limit=limit)

    def list_work_logs(self, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        filters = filters or {}
        start, end = self.work_log_service.validate_period(
            str(filters.get("date_from", "") or ""),
            str(filters.get("date_to", "") or ""),
            optional=True,
        )
        return self.work_logs(start, end)

    def get_daily_report(self, report_date: str) -> list[dict[str, Any]]:
        report_date = parse_date(report_date, "дата отчета")
        work_rows = sorted(
            self.work_logs(report_date, report_date),
            key=lambda row: (str(row.get("work_date") or ""), int(row.get("id") or 0)),
        )
        result: list[dict[str, Any]] = []
        for row in work_rows:
            result.append({
                "date": row["work_date"],
                "report_block": "Логи работ",
                "task_number": row["full_task_name"],
                "description": row["description"],
                "quantity": "",
                "serial_number": "",
                "responsible": "",
                "comment": row["comment"],
            })
        events = self._report_events(report_date, report_date)
        receipts = [event for event in events if event["event_type"] in {"RECEIPT_CREATED", "CABLE_RECEIVED"}]
        issues = [
            event for event in events
            if event["event_type"] in {"ISSUE_CREATED", "CABLE_ISSUED"}
            and float(event.get("metadata", {}).get("matched_quantity") or 0) > 0
        ]
        problem_rows = [
            event for event in events
            if event["event_type"] == "DATA_PROBLEM_FOUND"
            and event.get("metadata", {}).get("kind") == "unmatched_issues"
        ]
        deliveries = [event for event in events if event["event_type"] == "DELIVERY_IMPORTED"]
        delivery_accepts = [event for event in events if event["event_type"] == "DELIVERY_ACCEPTED"]
        delivery_problems = [
            event for event in events
            if event["event_type"] == "DATA_PROBLEM_FOUND"
            and event.get("metadata", {}).get("kind") == "delivery_problem_rows"
        ]
        for event in sorted(receipts, key=self._event_order):
            meta = event["metadata"]
            model = str(meta.get("model") or "")
            result.append({
                "date": event["event_date"], "report_block": "Приход", "task_number": "",
                "description": event["item_name"] + (f" / {model}" if model else ""),
                "quantity": self._quantity_text(event["quantity"], event["unit"]),
                "serial_number": event["serial_number"], "responsible": event["actor"],
                "comment": event["comment"],
            })
        for event in sorted(issues, key=self._event_order):
            result.append({
                "date": event["event_date"], "report_block": "Расход",
                "task_number": event["task_number"],
                "description": event["item_name"],
                "quantity": self._quantity_text(event["quantity"], event["unit"]),
                "serial_number": event["serial_number"], "responsible": event["actor"],
                "comment": event["comment"],
            })
        for event in sorted(problem_rows, key=self._event_order):
            result.append({
                "date": event["event_date"], "report_block": "Проблемные строки",
                "task_number": "", "description": event["item_name"] or "Не сопоставленный расход",
                "quantity": f"{float(event['quantity']):g}",
                "serial_number": event["serial_number"], "responsible": event["actor"],
                "comment": event["comment"],
            })
        for event in [*sorted(deliveries, key=self._event_order), *sorted(delivery_accepts, key=self._event_order), *sorted(delivery_problems, key=self._event_order)]:
            kind = {
                "DELIVERY_IMPORTED": "Загруженная поставка",
                "DELIVERY_ACCEPTED": "Принятая позиция",
                "DATA_PROBLEM_FOUND": "Проблемная строка",
            }[event["event_type"]]
            source_text = event["comment"] if event["event_type"] != "DELIVERY_ACCEPTED" else event["item_name"]
            result.append({
                "date": event["event_date"], "report_block": "Поставки",
                "task_number": event["task_number"], "description": kind + ": " + (source_text or ""),
                "quantity": "", "serial_number": event["serial_number"], "responsible": "",
                "comment": event["supplier"],
            })
        return result

    def get_weekly_report(self, start_date: str, end_date: str) -> dict[str, Any]:
        start, end = self.work_log_service.validate_period(start_date, end_date)
        events = self._report_events(start, end)
        work_logs = self.work_logs(start, end)
        receipts = [event for event in events if event["event_type"] in {"RECEIPT_CREATED", "CABLE_RECEIVED"}]
        issues = [event for event in events if event["event_type"] in {"ISSUE_CREATED", "CABLE_ISSUED"}]
        problems = self._problem_groups(events)
        summary = {
            "work_logs": len(work_logs),
            "receipts": len(receipts),
            "received_quantity": sum(float(event["quantity"] or 0) for event in receipts),
            "issues": len(issues),
            "issued_quantity": sum(float(event["quantity"] or 0) for event in issues),
            "cable_received": sum(float(event["quantity"] or 0) for event in receipts if event["event_type"] == "CABLE_RECEIVED"),
            "cable_issued": sum(
                float(allocation.get("quantity") or 0)
                for event in issues
                for allocation in event.get("metadata", {}).get("allocations", [])
                if allocation.get("cable_type")
            ),
        }
        summary["problem_rows"] = sum(len(rows) for rows in problems.values())
        summary.update({
            "loaded_deliveries": sum(1 for event in events if event["event_type"] == "DELIVERY_IMPORTED"),
            "accepted_delivery_items": sum(1 for event in events if event["event_type"] == "DELIVERY_ACCEPTED"),
            "delivery_problem_rows": len(problems.get("delivery_problem_rows", [])),
        })
        project_totals: dict[str, dict[str, float]] = defaultdict(lambda: {"received": 0.0, "issued": 0.0})
        type_totals: dict[str, dict[str, float]] = defaultdict(lambda: {"received": 0.0, "issued": 0.0})
        for event in receipts:
            project = event["project"] or "Без проекта"
            project_totals[project]["received"] += float(event["quantity"] or 0)
            type_totals[self._type_label(event["metadata"])]["received"] += float(event["quantity"] or 0)
        for event in issues:
            for allocation in event.get("metadata", {}).get("allocations", []):
                project = allocation.get("project") or "Без проекта"
                project_totals[project]["issued"] += float(allocation.get("quantity") or 0)
                type_totals[self._type_label(allocation)]["issued"] += float(allocation.get("quantity") or 0)
        return {
            "date_from": start, "date_to": end, "summary": summary,
            "projects": self._totals_rows(project_totals),
            "types": self._totals_rows(type_totals),
            "problems": problems,
        }

    def get_weekly_report_rows(self, start_date: str, end_date: str) -> list[dict[str, Any]]:
        report = self.get_weekly_report(start_date, end_date)
        labels = {
            "work_logs": "Логи работ", "receipts": "Операции прихода",
            "received_quantity": "Принято позиций", "issues": "Операции расхода",
            "issued_quantity": "Списано позиций", "cable_received": "Кабеля принято",
            "cable_issued": "Кабеля списано", "problem_rows": "Проблемные строки",
            "loaded_deliveries": "Загруженные поставки",
            "accepted_delivery_items": "Принятые позиции поставок",
            "delivery_problem_rows": "Проблемные строки поставок",
        }
        rows = [
            {"Блок": "Итоги", "Показатель": labels[key], "Принято": value, "Списано": ""}
            for key, value in report["summary"].items()
        ]
        rows.extend(
            {"Блок": "Проекты", "Показатель": row["name"],
             "Принято": row["received"], "Списано": row["issued"]}
            for row in report["projects"]
        )
        rows.extend(
            {"Блок": "Типы", "Показатель": row["name"],
             "Принято": row["received"], "Списано": row["issued"]}
            for row in report["types"]
        )
        for kind, problem_rows in report["problems"].items():
            rows.extend({
                "Блок": "Проблемные строки", "Показатель": kind,
                "Принято": row.get("serial_number", row.get("item_name", "")),
                "Списано": row.get("unmatched_quantity", row.get("count", "")),
            } for row in problem_rows)
        return rows

    def list_uploaded_reports(self) -> list[dict[str, Any]]:
        return self.daily_report_uploads()

    def get_uploaded_report(self, upload_id: int) -> list[dict[str, Any]]:
        return self.uploaded_daily_report(upload_id)

    def export_work_logs_rows(self, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        return self.list_work_logs(filters)

    def export_daily_report_rows(self, report_date: str) -> list[dict[str, Any]]:
        return self.get_daily_report(report_date)

    def export_weekly_report_rows(self, start_date: str, end_date: str) -> list[dict[str, Any]]:
        return self.get_weekly_report_rows(start_date, end_date)

    def export_uploaded_report_rows(self, upload_id: int) -> list[dict[str, Any]]:
        return self.get_uploaded_report(upload_id)

    def get_reports_summary(self) -> dict[str, Any]:
        return {"daily_report_uploads": self.list_uploaded_reports()}

    def _report_events(self, date_from: str, date_to: str) -> list[dict[str, Any]]:
        if not self.warehouse_events:
            return []
        return _plain([
            event.to_dict() if hasattr(event, "to_dict") else event
            for event in self.warehouse_events.list_report_events(date_from, date_to)
        ])

    @staticmethod
    def _event_order(event: dict[str, Any]) -> tuple[str, int | str]:
        entity = str(event.get("entity_id") or "")
        return (str(event.get("event_date") or ""), int(entity) if entity.isdigit() else entity)

    @staticmethod
    def _quantity_text(quantity: Any, unit: Any) -> str:
        return f"{float(quantity):g} {unit}"

    @staticmethod
    def _type_label(row: dict[str, Any]) -> str:
        if row.get("equipment_type"):
            return "Оборудование: " + str(row["equipment_type"])
        if row.get("component_type"):
            return "Компонент: " + str(row["component_type"])
        return "Кабель: " + str(row.get("cable_type") or "")

    @staticmethod
    def _totals_rows(totals: dict[str, dict[str, float]]) -> list[dict[str, Any]]:
        def legacy_number(value: float) -> float | int:
            return 0 if abs(value) < 1e-12 else value
        return [
            {
                "name": name,
                "received": legacy_number(values["received"]),
                "issued": legacy_number(values["issued"]),
            }
            for name, values in sorted(totals.items(), key=lambda item: item[0].casefold())
        ]

    @staticmethod
    def _problem_groups(events: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        grouped: dict[str, list[dict[str, Any]]] = {
            "unmatched_issues": [],
            "duplicate_serials": [],
            "negative_balances": [],
            "incomplete_rows": [],
        }
        for event in events:
            if event["event_type"] != "DATA_PROBLEM_FOUND":
                continue
            metadata = event.get("metadata", {})
            kind = metadata.get("kind", "problems")
            row = metadata.get("row") or metadata
            if kind == "delivery_problem_rows":
                row = {
                    "id": event.get("entity_id", ""),
                    "date": event.get("event_date", ""),
                    "serial_number": event.get("serial_number", ""),
                    "item_name": event.get("item_name", ""),
                    "count": event.get("quantity", ""),
                    "comment": event.get("comment", ""),
                }
            grouped.setdefault(kind, []).append(_plain(row))
        return grouped
