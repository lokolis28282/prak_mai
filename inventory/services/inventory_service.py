"""Legacy inventory-card, import, export, and backup service."""

from __future__ import annotations

from typing import Any

from ._base import ServiceAdapter


class InventoryService(ServiceAdapter):
    def list_backups(self, *args: Any, **kwargs: Any) -> Any: return self.call("list_backups", *args, **kwargs)
    def create_backup(self, *args: Any, **kwargs: Any) -> Any: return self.call("create_backup", *args, **kwargs)
    def restore_backup(self, *args: Any, **kwargs: Any) -> Any: return self.call("restore_backup", *args, **kwargs)
    def replace_production_database(self, *args: Any, **kwargs: Any) -> Any: return self.call("replace_production_database", *args, **kwargs)
    def add_equipment(self, *args: Any, **kwargs: Any) -> Any: return self.call("add_equipment", *args, **kwargs)
    def move(self, *args: Any, **kwargs: Any) -> Any: return self.call("move", *args, **kwargs)
    def equipment(self, *args: Any, **kwargs: Any) -> Any: return self.call("equipment", *args, **kwargs)
    def inventory_compare(self, *args: Any, **kwargs: Any) -> Any: return self.call("inventory_compare", *args, **kwargs)
    def import_operation_rows(self, *args: Any, **kwargs: Any) -> Any: return self.call("import_operation_rows", *args, **kwargs)
    def import_equipment_rows(self, *args: Any, **kwargs: Any) -> Any: return self.call("import_equipment_rows", *args, **kwargs)
    def export_csv(self, *args: Any, **kwargs: Any) -> Any: return self.call("export_csv", *args, **kwargs)
    def import_preview_rows(self, *args: Any, **kwargs: Any) -> Any: return self.call("import_preview_rows", *args, **kwargs)
