"""Compatibility names backed by the extracted issue write service."""

from __future__ import annotations

from typing import Any

from inventory.shared.validators import WarehouseError
from inventory.warehouse.cable_validators import is_cable_issue
from inventory.warehouse.cables import CableService
from inventory.warehouse.issue_imports import IssueWriteService
from inventory.warehouse.previews import WarehousePreviewStore


class IssueService:
    def __init__(
        self,
        actor_provider: Any,
        *,
        previews: WarehousePreviewStore,
        cables: CableService,
    ):
        self.actor_provider = actor_provider
        self.writer = IssueWriteService(
            actor_provider.db_path,
            actor_provider=actor_provider,
            strict_reference_validation=actor_provider.strict_reference_validation,
            previews=previews,
        )
        self.cables = cables

    def issue(self, *args: Any, **kwargs: Any) -> Any:
        """Legacy equipment-card issue, unrelated to stock_issues."""
        return self.actor_provider.issue(*args, **kwargs)

    def add_stock_issue(self, **fields: Any) -> int:
        if is_cable_issue(fields):
            return self.cables.create_cable_issue(fields)
        return self.writer.create_issue(fields)

    def scan_issue_serial(self, serial_number: str) -> dict[str, Any]:
        return self.writer.validate_issue_serial(serial_number)

    def confirm_scanned_issues(
        self, common_fields: dict[str, Any], serial_numbers: list[str]
    ) -> int:
        return int(
            self.writer.create_issue_by_serials(
                common_fields, serial_numbers
            )["imported"]
        )

    def import_stock_issue_rows(
        self, rows: list[dict[str, Any]], *, soft: bool = True
    ) -> int:
        cable_rows = [is_cable_issue(row) for row in rows]
        if any(cable_rows):
            if not all(cable_rows):
                raise WarehouseError(
                    "Разделите CSV расхода кабелей и оборудования на разные файлы"
                )
            prepared = [
                self.cables._prepare_issue(row)
                for row in rows
            ]
            return sum(
                bool(
                    self.cables.repository.insert_issue(
                        row,
                        author=self.cables.audit_author(),
                        collect_refs=(
                            soft
                            or not self.actor_provider.strict_reference_validation
                        ),
                    )
                )
                for row in prepared
            )
        effective_soft = (
            soft and not self.actor_provider.strict_reference_validation
        )
        return self.writer.import_issues(rows, soft=effective_soft)

    def preview_stock_issue_rows(
        self, rows: list[dict[str, Any]], *, soft: bool = False
    ) -> dict[str, Any]:
        return self.writer.preview_issue_import(rows, soft=soft)

    def confirm_stock_issue_preview(self, preview_id: str) -> int:
        return self.writer.confirm_issue_import(preview_id)

    def preview_bulk_issue_serials(
        self, rows: list[dict[str, Any]]
    ) -> dict[str, Any]:
        return self.writer.preview_bulk_issue_serials(rows)

    def confirm_bulk_issue_preview(self, *args: Any, **kwargs: Any) -> int:
        return self.writer.confirm_bulk_issue_preview(*args, **kwargs)

    def stock_issue_rows(
        self, limit: int | None = None
    ) -> list[dict[str, Any]]:
        return self.writer.repository.list_rows(limit=limit)
