"""Data-quality and monitoring service."""

from __future__ import annotations

from typing import Any

from ._base import ServiceAdapter


class MonitoringService(ServiceAdapter):
    def data_quality_problems(self, *args: Any, **kwargs: Any) -> Any: return self.call("data_quality_problems", *args, **kwargs)
    def check_integrity(self, *args: Any, **kwargs: Any) -> Any: return self.call("check_integrity", *args, **kwargs)
