"""Warehouse history and audit service."""

from __future__ import annotations

from typing import Any

from ._base import ServiceAdapter


class HistoryService(ServiceAdapter):
    def audit_entries(self, *args: Any, **kwargs: Any) -> Any: return self.call("audit_entries", *args, **kwargs)
    def warehouse_history(self, *args: Any, **kwargs: Any) -> Any: return self.call("warehouse_history", *args, **kwargs)
    def operation_log(self, *args: Any, **kwargs: Any) -> Any: return self.call("operation_log", *args, **kwargs)
