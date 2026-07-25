"""Issue workflow service."""

from __future__ import annotations

from typing import Any

from ._base import ServiceAdapter


class IssueService(ServiceAdapter):
    def add_stock_issue(self, *args: Any, **kwargs: Any) -> Any: return self.call("add_stock_issue", *args, **kwargs)
    def scan_issue_serial(self, *args: Any, **kwargs: Any) -> Any: return self.call("scan_issue_serial", *args, **kwargs)
    def confirm_scanned_issues(self, *args: Any, **kwargs: Any) -> Any: return self.call("confirm_scanned_issues", *args, **kwargs)
    def import_stock_issue_rows(self, *args: Any, **kwargs: Any) -> Any: return self.call("import_stock_issue_rows", *args, **kwargs)
    def preview_stock_issue_rows(self, *args: Any, **kwargs: Any) -> Any: return self.call("preview_stock_issue_rows", *args, **kwargs)
    def confirm_stock_issue_preview(self, *args: Any, **kwargs: Any) -> Any: return self.call("confirm_stock_issue_preview", *args, **kwargs)
    def preview_bulk_issue_serials(self, *args: Any, **kwargs: Any) -> Any: return self.call("preview_bulk_issue_serials", *args, **kwargs)
    def confirm_bulk_issue_preview(self, *args: Any, **kwargs: Any) -> Any: return self.call("confirm_bulk_issue_preview", *args, **kwargs)
    def stock_issue_rows(self, *args: Any, **kwargs: Any) -> Any: return self.call("stock_issue_rows", *args, **kwargs)
    def issue(self, *args: Any, **kwargs: Any) -> Any: return self.call("issue", *args, **kwargs)
