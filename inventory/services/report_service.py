"""Work-log and report service."""

from __future__ import annotations

from typing import Any

from ._base import ServiceAdapter


class ReportService(ServiceAdapter):
    def add_work_log(self, *args: Any, **kwargs: Any) -> Any: return self.call("add_work_log", *args, **kwargs)
    def add_work_logs(self, *args: Any, **kwargs: Any) -> Any: return self.call("add_work_logs", *args, **kwargs)
    def work_logs(self, *args: Any, **kwargs: Any) -> Any: return self.call("work_logs", *args, **kwargs)
    def import_work_log_rows(self, *args: Any, **kwargs: Any) -> Any: return self.call("import_work_log_rows", *args, **kwargs)
    def preview_work_log_rows(self, *args: Any, **kwargs: Any) -> Any: return self.call("preview_work_log_rows", *args, **kwargs)
    def confirm_work_log_preview(self, *args: Any, **kwargs: Any) -> Any: return self.call("confirm_work_log_preview", *args, **kwargs)
    def daily_report(self, *args: Any, **kwargs: Any) -> Any: return self.call("daily_report", *args, **kwargs)
    def weekly_report(self, *args: Any, **kwargs: Any) -> Any: return self.call("weekly_report", *args, **kwargs)
    def weekly_report_rows(self, *args: Any, **kwargs: Any) -> Any: return self.call("weekly_report_rows", *args, **kwargs)
    def import_daily_report_rows(self, *args: Any, **kwargs: Any) -> Any: return self.call("import_daily_report_rows", *args, **kwargs)
    def daily_report_uploads(self, *args: Any, **kwargs: Any) -> Any: return self.call("daily_report_uploads", *args, **kwargs)
    def uploaded_daily_report(self, *args: Any, **kwargs: Any) -> Any: return self.call("uploaded_daily_report", *args, **kwargs)
    def export_work_logs_csv(self, *args: Any, **kwargs: Any) -> Any: return self.call("export_work_logs_csv", *args, **kwargs)
