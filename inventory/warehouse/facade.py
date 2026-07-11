"""Public warehouse facade.

The implementation delegates to the ODE 0.12 compatibility service. Internal
WarehouseCore methods stay behind this boundary during Stage 0.12.6.
"""

from __future__ import annotations

from typing import Any

from inventory.shared.validators import WarehouseError

from .cable_validators import is_cable_issue, is_cable_receipt
from .cables import CableService
from .delivery_acceptance import DeliveryAcceptanceService
from .deliveries import DeliveryReadService
from .delivery_imports import DeliveryImportService
from .issue_imports import IssueWriteService
from .previews import WarehousePreviewStore
from .receipt_imports import ReceiptWriteService


def _plain(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_plain(item) for item in value]
    if hasattr(value, "keys"):
        return {key: _plain(value[key]) for key in value.keys()}
    return value


class WarehouseFacade:
    def __init__(self, service: Any, *, event_publisher: Any = None):
        self.service = service
        self.event_publisher = event_publisher
        self._previews = WarehousePreviewStore()
        self.receipt_writer = ReceiptWriteService(
            service.db_path,
            actor_provider=service,
            strict_reference_validation=service.strict_reference_validation,
            previews=self._previews,
        )
        self.cables = CableService(
            service.db_path,
            actor_provider=service,
            strict_reference_validation=service.strict_reference_validation,
            previews=self._previews,
        )
        self.issue_writer = IssueWriteService(
            service.db_path,
            actor_provider=service,
            strict_reference_validation=service.strict_reference_validation,
            previews=self._previews,
        )
        self.delivery_previews = None
        self.delivery_importer = DeliveryImportService(
            service.db_path,
            actor_provider=service,
            event_publisher=event_publisher,
        )
        self.delivery_reader = DeliveryReadService(service.db_path)
        self.delivery_acceptance = DeliveryAcceptanceService(
            service.db_path,
            actor_provider=service,
            receipt_writer=self.receipt_writer,
        )

    def receipts(self, *args: Any, **kwargs: Any) -> Any:
        return _plain(self.receipt_writer.repository.receipts(*args, **kwargs))

    def add_receipt(self, *args: Any, **kwargs: Any) -> Any:
        if kwargs:
            return self.create_receipt(kwargs)
        if args and isinstance(args[0], dict):
            return self.create_receipt(args[0])
        return self.service.add_stock_receipt(*args, **kwargs)

    def validate_receipt_serial(self, serial_number: str) -> dict[str, Any]:
        return _plain(self.receipt_writer.validate_receipt_serial(serial_number))

    def prepare_receipt(self, data: dict[str, Any]) -> dict[str, Any]:
        return _plain(self.receipt_writer.prepare_receipt(dict(data)))

    def create_receipt(self, data: dict[str, Any]) -> int:
        if self._is_cable_receipt(data):
            return self.create_cable_receipt(data)
        return int(self.receipt_writer.create_receipt(dict(data)))

    def create_receipt_batch(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        return _plain(self.receipt_writer.create_receipt_batch([dict(row) for row in rows]))

    def confirm_scanned_receipts(
        self, common_fields: dict[str, Any], serial_numbers: list[str]
    ) -> int:
        return int(self.receipt_writer.confirm_scanned_receipts(dict(common_fields), list(serial_numbers)))

    def preview_receipt_import(
        self,
        rows: list[dict[str, Any]],
        filename: str = "receipt.csv",
        *,
        unknown_columns: list[str] | None = None,
        soft: bool = False,
    ) -> dict[str, Any]:
        cable_rows = [self._is_cable_receipt(row) for row in rows]
        if any(cable_rows):
            if not all(cable_rows):
                raise WarehouseError("Разделите CSV прихода кабелей и оборудования на разные файлы")
            return _plain(self.preview_cable_import(
                rows,
                filename=filename,
                unknown_columns=unknown_columns,
                soft=soft,
            ))
        return _plain(self.receipt_writer.preview_receipt_import(
            [dict(row) for row in rows],
            filename=filename,
            unknown_columns=unknown_columns,
            soft=soft,
        ))

    def confirm_receipt_import(self, preview_id: str) -> int:
        try:
            return int(self.receipt_writer.confirm_receipt_import(preview_id))
        except WarehouseError:
            return int(self.confirm_cable_import(preview_id))

    def import_receipts(self, rows: list[dict[str, Any]], *, soft: bool = True) -> int:
        cable_rows = [self._is_cable_receipt(row) for row in rows]
        if any(cable_rows):
            if not all(cable_rows):
                raise WarehouseError("Разделите CSV прихода кабелей и оборудования на разные файлы")
            return int(self.create_cable_receipt_batch(rows, soft=soft)["created_count"])
        return int(self.receipt_writer.import_receipts([dict(row) for row in rows], soft=soft))

    def receipt_import_preview_rows(self, preview_id: str = "") -> list[dict[str, Any]]:
        try:
            return _plain(self.receipt_writer.preview_rows(preview_id))
        except WarehouseError:
            return _plain(self.cables.preview_rows(preview_id))

    @staticmethod
    def _is_cable_receipt(row: dict[str, Any]) -> bool:
        return is_cable_receipt(row)

    @staticmethod
    def _is_cable_issue(row: dict[str, Any]) -> bool:
        return is_cable_issue(row)

    def validate_cable_receipt(self, data: dict[str, Any]) -> dict[str, Any]:
        return _plain(self.cables.validate_cable_receipt(dict(data)))

    def validate_cable_issue(self, data: dict[str, Any]) -> dict[str, Any]:
        return _plain(self.cables.validate_cable_issue(dict(data)))

    def create_cable_receipt(self, data: dict[str, Any]) -> int:
        return int(self.cables.create_cable_receipt(dict(data)))

    def create_cable_receipt_batch(
        self, rows: list[dict[str, Any]], *, soft: bool = True
    ) -> dict[str, Any]:
        return _plain(self.cables.create_cable_receipt_batch([dict(row) for row in rows], soft=soft))

    def create_cable_issue(self, data: dict[str, Any]) -> int:
        return int(self.cables.create_cable_issue(dict(data)))

    def validate_issue_serial(
        self, serial_number: str, context: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        return _plain(self.issue_writer.validate_issue_serial(serial_number, context))

    def prepare_issue(self, data: dict[str, Any]) -> dict[str, Any]:
        return _plain(self.issue_writer.prepare_issue(dict(data)))

    def create_issue(self, data: dict[str, Any]) -> int:
        if self._is_cable_issue(data):
            return self.create_cable_issue(data)
        return int(self.issue_writer.create_issue(dict(data)))

    def create_issue_batch(
        self, rows: list[dict[str, Any]], *, soft: bool = False
    ) -> dict[str, Any]:
        return _plain(self.issue_writer.create_issue_batch([dict(row) for row in rows], soft=soft))

    def create_issue_by_serials(
        self, common_fields: dict[str, Any], serial_numbers: list[str]
    ) -> dict[str, int]:
        return _plain(self.issue_writer.create_issue_by_serials(dict(common_fields), list(serial_numbers)))

    def preview_issue_import(
        self,
        rows: list[dict[str, Any]],
        filename: str = "issue.csv",
        *,
        unknown_columns: list[str] | None = None,
        soft: bool = False,
    ) -> dict[str, Any]:
        return _plain(self.issue_writer.preview_issue_import(
            [dict(row) for row in rows],
            filename=filename,
            unknown_columns=unknown_columns,
            soft=soft,
        ))

    def confirm_issue_import(self, preview_id: str) -> int:
        return int(self.issue_writer.confirm_issue_import(preview_id))

    def import_issues(self, rows: list[dict[str, Any]], *, soft: bool = True) -> int:
        return int(self.issue_writer.import_issues([dict(row) for row in rows], soft=soft))

    def preview_bulk_issue_serials(
        self, rows: list[dict[str, Any]], filename: str = "bulk_issue.csv"
    ) -> dict[str, Any]:
        return _plain(self.issue_writer.preview_bulk_issue_serials([dict(row) for row in rows], filename))

    def confirm_bulk_issue_preview(
        self,
        preview_id: str,
        issue_date: str,
        responsible: str,
        task_type: str,
        task_number: str,
        comment: str = "",
        target_serial_number: str = "",
    ) -> int:
        return int(self.issue_writer.confirm_bulk_issue_preview(
            preview_id, issue_date, responsible, task_type, task_number,
            comment, target_serial_number,
        ))

    def get_available_position(self, serial_number: str) -> dict[str, Any] | None:
        return _plain(self.issue_writer.get_available_position(serial_number))

    def find_issue_candidates(
        self, query: str, filters: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        filters = filters or {}
        if query:
            return self.search_warehouse(query)
        return self.get_balance(filters)

    def get_cable_balance(self, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        return _plain(self.cables.get_cable_balance(filters or {}))

    def get_cable_types(self) -> list[str]:
        return _plain(self.cables.get_cable_types())

    def get_cable_items(self, cable_type: str | None = None) -> list[dict[str, Any]]:
        return _plain(self.cables.get_cable_items(cable_type))

    def preview_cable_import(
        self,
        rows: list[dict[str, Any]],
        filename: str = "receipt.csv",
        *,
        unknown_columns: list[str] | None = None,
        soft: bool = False,
    ) -> dict[str, Any]:
        return _plain(self.cables.preview_cable_import(
            [dict(row) for row in rows],
            filename=filename,
            unknown_columns=unknown_columns,
            soft=soft,
        ))

    def confirm_cable_import(self, preview_id: str) -> int:
        return int(self.cables.confirm_cable_import(preview_id))

    def issues(self, *args: Any, **kwargs: Any) -> Any:
        return _plain(self.service.stock_issues(*args, **kwargs))

    def issue_rows(self) -> list[dict[str, Any]]:
        return _plain(self.service.stock_issue_rows())

    def add_issue(self, *args: Any, **kwargs: Any) -> Any:
        if kwargs and self._is_cable_issue(kwargs):
            return self.create_cable_issue(kwargs)
        if args and isinstance(args[0], dict) and self._is_cable_issue(args[0]):
            return self.create_cable_issue(args[0])
        if kwargs:
            return self.create_issue(kwargs)
        if args and isinstance(args[0], dict):
            return self.create_issue(args[0])
        return self.service.add_stock_issue(*args, **kwargs)

    def balance(self, *args: Any, **kwargs: Any) -> Any:
        return _plain(self.service.stock_balance(*args, **kwargs))

    def deliveries(self, *args: Any, **kwargs: Any) -> Any:
        return self.list_deliveries(*args, **kwargs)

    def delivery(self, *args: Any, **kwargs: Any) -> Any:
        return self.get_delivery(*args, **kwargs)

    def warehouse_history(self, *args: Any, **kwargs: Any) -> Any:
        return _plain(self.service.warehouse_history(*args, **kwargs))

    def inventory_analysis(self, *args: Any, **kwargs: Any) -> Any:
        return self.service.inventory_compare(*args, **kwargs)

    def reference_data(self, *args: Any, **kwargs: Any) -> Any:
        return _plain(self.service.reference_data(*args, **kwargs))

    def get_overview(self) -> dict[str, Any]:
        quality = self.service.data_quality_summary(limit=200)
        problems = quality["problems"]
        problem_counts = quality["counts"]
        stats = _plain(self.service.dashboard_stats())
        stats["problems"] = sum(problem_counts.values())
        return {
            "stats": stats,
            "equipment": _plain(self.service.equipment()),
            "operations": _plain(self.service.operation_log(limit=100)),
            "categories": _plain(self.service.reference_data("categories")),
            "locations": _plain(self.service.reference_data("locations")),
            "references": _plain(self.service.references()),
            "reference_kinds": _plain(self.service.REFERENCE_KINDS),
            "balance": self.get_balance(limit=5_000),
            "balance_limit": 5_000,
            "balance_truncated": int(stats["positions"]) > 5_000,
            "recent_receipts": self.receipts(limit=20),
            "problems": _plain({key: rows[:200] for key, rows in problems.items()}),
            "problem_counts": problem_counts,
            "deliveries": self.list_deliveries(limit=100),
            "warehouse_categories": self.get_warehouse_categories(),
            "warehouse_history": self.get_warehouse_history(),
        }

    def get_balance(
        self, filters: dict[str, Any] | None = None, *, limit: int | None = None
    ) -> list[dict[str, Any]]:
        return _plain(self.service.stock_balance(**(filters or {}), limit=limit))

    def get_warehouse_history(
        self, filters: dict[str, Any] | None = None, limit: int = 300
    ) -> list[dict[str, Any]]:
        rows = _plain(self.service.warehouse_history(limit=limit))
        if not filters:
            return rows
        query = str(filters.get("query") or "").casefold()
        if not query:
            return rows
        return [
            row for row in rows
            if any(query in str(value or "").casefold() for value in row.values())
        ]

    def get_warehouse_history_legacy(self) -> list[dict[str, Any]]:
        return _plain(self.service.operation_log(limit=None))

    def preview_delivery_import(
        self,
        rows: list[dict[str, Any]],
        filename: str,
        source_metadata: dict[str, Any] | None = None,
        *,
        unknown_columns: list[str] | None = None,
    ) -> dict[str, Any]:
        return _plain(self.delivery_importer.preview_delivery_import(
            [dict(row) for row in rows],
            filename,
            source_metadata,
            unknown_columns=unknown_columns,
        ))

    def confirm_delivery_import(
        self,
        preview_id: str,
        source_metadata: dict[str, Any] | None = None,
    ) -> int:
        return int(self.delivery_importer.confirm_delivery_import(
            preview_id,
            source_metadata=source_metadata,
        ))

    def get_delivery_import_template(self) -> str:
        return self.delivery_importer.get_template()

    def get_delivery_import_mapping(
        self,
        preview_id: str,
        source_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return _plain(self.delivery_importer.get_mapping(
            preview_id,
            source_metadata=source_metadata,
        ))

    def list_deliveries(
        self,
        query: str = "",
        filters: dict[str, Any] | None = None,
        *,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        return _plain(self.delivery_reader.list_deliveries(query, filters, limit=limit))

    def get_delivery(
        self, delivery_id: int, filters: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        return _plain(self.delivery_reader.get_delivery(delivery_id, filters))

    def get_delivery_lines(
        self,
        delivery_id: int,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        return _plain(self.delivery_reader.get_delivery_lines(delivery_id, filters))

    def search_deliveries(self, query: str) -> list[dict[str, Any]]:
        return _plain(self.delivery_reader.search_deliveries(query))

    def export_delivery_rows(self, delivery_id: int) -> list[dict[str, Any]]:
        return _plain(self.delivery_reader.export_delivery_rows(delivery_id))

    def inspect_delivery_serial(self, delivery_id: int, serial_number: str) -> dict[str, Any]:
        return _plain(self.delivery_acceptance.inspect_delivery_serial(delivery_id, serial_number))

    def accept_delivery_serial(
        self,
        delivery_id: int,
        serial_number: str,
        values: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return _plain(self.delivery_acceptance.accept_delivery_serial(
            delivery_id, serial_number, dict(values or {})
        ))

    def accept_delivery_batch(
        self,
        delivery_id: int,
        line_ids: list[int],
        common_values: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return _plain(self.delivery_acceptance.accept_delivery_batch(
            delivery_id, list(line_ids), dict(common_values or {})
        ))

    def accept_unplanned_delivery_serial(
        self,
        delivery_id: int,
        serial_number: str,
        values: dict[str, Any],
    ) -> dict[str, Any]:
        return _plain(self.delivery_acceptance.accept_unplanned_delivery_serial(
            delivery_id, serial_number, dict(values)
        ))

    def update_delivery_line_metadata(
        self,
        delivery_id: int,
        line_ids: list[int],
        values: dict[str, Any],
        *,
        only_empty: bool = False,
    ) -> int:
        return int(self.delivery_acceptance.update_delivery_line_metadata(
            delivery_id, list(line_ids), dict(values), only_empty=only_empty
        ))

    def get_delivery_acceptance_summary(self, delivery_id: int) -> dict[str, Any]:
        return _plain(self.delivery_acceptance.get_delivery_acceptance_summary(delivery_id))

    def get_delivery_conflicts(self, delivery_id: int) -> list[dict[str, Any]]:
        return _plain(self.delivery_acceptance.get_delivery_conflicts(delivery_id))

    def refresh_delivery_status(self, delivery_id: int) -> str:
        return str(self.delivery_acceptance.refresh_delivery_status(delivery_id))

    def get_inventory_view(self, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        filters = filters or {}
        return _plain(self.service.equipment(
            filters.get("query", ""), filters.get("category", ""),
            filters.get("status", ""), filters.get("location", ""),
        ))

    def get_position_card(self, filters: dict[str, Any]) -> dict[str, Any]:
        return _plain(self.service.position_card(
            serial_number=filters.get("serial_number", ""),
            item_name=filters.get("item_name", ""),
            cable_type=filters.get("cable_type", ""),
            project=filters.get("project", ""),
            datacenter=filters.get("datacenter", ""),
        ))

    def search_warehouse(self, query: str) -> list[dict[str, Any]]:
        return _plain(self.service.search_stock_positions(query))

    def global_search(self, query: str, limit: int = 30) -> list[dict[str, Any]]:
        return _plain(self.service.global_search(query, limit=limit))

    def get_warehouse_references(self) -> dict[str, Any]:
        return {
            "references": _plain(self.service.references()),
            "reference_kinds": _plain(self.service.REFERENCE_KINDS),
            "categories": _plain(self.service.reference_data("categories")),
            "locations": _plain(self.service.reference_data("locations")),
        }

    def get_warehouse_categories(self) -> list[dict[str, Any]]:
        return _plain(self.service.warehouse_categories())

    def export_balance_rows(self, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        return self.get_balance(filters)

    def get_problem_issues(self, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        filters = filters or {}
        return _plain(self.service.data_quality_problems(
            filters.get("date_from", ""), filters.get("date_to", "")
        )["unmatched_issues"])
