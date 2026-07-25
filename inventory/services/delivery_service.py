"""Delivery workflow service."""

from __future__ import annotations

from typing import Any

from ._base import ServiceAdapter


class DeliveryService(ServiceAdapter):
    def preview_delivery_rows(self, *args: Any, **kwargs: Any) -> Any: return self.call("preview_delivery_rows", *args, **kwargs)
    def confirm_delivery_preview(self, *args: Any, **kwargs: Any) -> Any: return self.call("confirm_delivery_preview", *args, **kwargs)
    def deliveries(self, *args: Any, **kwargs: Any) -> Any: return self.call("deliveries", *args, **kwargs)
    def delivery(self, *args: Any, **kwargs: Any) -> Any: return self.call("delivery", *args, **kwargs)
    def update_delivery_lines(self, *args: Any, **kwargs: Any) -> Any: return self.call("update_delivery_lines", *args, **kwargs)
    def accept_delivery_serial(self, *args: Any, **kwargs: Any) -> Any: return self.call("accept_delivery_serial", *args, **kwargs)
    def close_delivery(self, *args: Any, **kwargs: Any) -> Any: return self.call("close_delivery", *args, **kwargs)
