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
    def editor_catalog(self, *args: Any, **kwargs: Any) -> Any: return self.call("reference_editor_catalog", *args, **kwargs)
    def models(self, *args: Any, **kwargs: Any) -> Any: return self.call("reference_models", *args, **kwargs)
    def propose(self, *args: Any, **kwargs: Any) -> Any: return self.call("propose_reference", *args, **kwargs)
    def rename(self, *args: Any, **kwargs: Any) -> Any: return self.call("rename_reference", *args, **kwargs)
    def merge_preview(self, *args: Any, **kwargs: Any) -> Any: return self.call("preview_reference_merge", *args, **kwargs)
    def merge(self, *args: Any, **kwargs: Any) -> Any: return self.call("merge_reference", *args, **kwargs)
