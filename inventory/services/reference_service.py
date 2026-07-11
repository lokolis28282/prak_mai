"""Reference dictionary service."""

from __future__ import annotations

from typing import Any

from ._base import ServiceAdapter


class ReferenceService(ServiceAdapter):
    def references(self, *args: Any, **kwargs: Any) -> Any: return self.call("references", *args, **kwargs)
    def reference_groups(self, *args: Any, **kwargs: Any) -> Any: return self.call("reference_groups", *args, **kwargs)
    def add_reference(self, *args: Any, **kwargs: Any) -> Any: return self.call("add_reference", *args, **kwargs)
    def set_reference_active(self, *args: Any, **kwargs: Any) -> Any: return self.call("set_reference_active", *args, **kwargs)
    def reference_data(self, *args: Any, **kwargs: Any) -> Any: return self.call("reference_data", *args, **kwargs)
    def add_category(self, *args: Any, **kwargs: Any) -> Any: return self.call("add_category", *args, **kwargs)
    def add_location(self, *args: Any, **kwargs: Any) -> Any: return self.call("add_location", *args, **kwargs)
