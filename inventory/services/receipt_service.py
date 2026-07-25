"""Compatibility names backed by the extracted receipt write service."""

from __future__ import annotations

from typing import Any

from inventory.shared.validators import WarehouseError
from inventory.warehouse.cable_validators import is_cable_receipt
from inventory.warehouse.cables import CableService
from inventory.warehouse.previews import WarehousePreviewStore
from inventory.warehouse.receipt_imports import ReceiptWriteService


class ReceiptService:
    def __init__(self, actor_provider: Any):
        self.actor_provider = actor_provider
        self.previews = WarehousePreviewStore()
        self.writer = ReceiptWriteService(
            actor_provider.db_path,
            actor_provider=actor_provider,
            strict_reference_validation=actor_provider.strict_reference_validation,
            previews=self.previews,
        )
        self.cables = CableService(
            actor_provider.db_path,
            actor_provider=actor_provider,
            strict_reference_validation=actor_provider.strict_reference_validation,
            previews=self.previews,
        )

    def receipt(self, *args: Any, **kwargs: Any) -> Any:
        """Legacy equipment-card receipt, unrelated to stock_receipts."""
        return self.actor_provider.receipt(*args, **kwargs)

    def preview_stock_receipt_rows(
        self, rows: list[dict[str, Any]], *, soft: bool = False
    ) -> dict[str, Any]:
        cable_rows = [
            is_cable_receipt(row)
            or (soft and not str(row.get("serial_number") or "").strip())
            for row in rows
        ]
        if any(cable_rows):
            if not all(cable_rows):
                raise WarehouseError(
                    "Разделите CSV прихода кабелей и оборудования на разные файлы"
                )
            return self.cables.preview_cable_import(
                rows, filename="receipt.csv", soft=soft
            )
        return self.writer.preview_receipt_import(
            rows, filename="receipt.csv", soft=soft
        )

    def confirm_stock_receipt_preview(self, preview_id: str) -> int:
        try:
            return self.writer.confirm_receipt_import(preview_id)
        except WarehouseError:
            return self.cables.confirm_cable_import(preview_id)

    def scan_receipt_serial(self, serial_number: str) -> dict[str, Any]:
        return self.writer.validate_receipt_serial(serial_number)

    def confirm_scanned_receipts(
        self, common_fields: dict[str, Any], serial_numbers: list[str]
    ) -> int:
        return self.writer.confirm_scanned_receipts(common_fields, serial_numbers)

    def add_stock_receipt(self, **fields: Any) -> int:
        if is_cable_receipt(fields):
            return self.cables.create_cable_receipt(fields)
        return self.writer.create_receipt(fields)

    def import_stock_receipt_rows(
        self, rows: list[dict[str, Any]], *, soft: bool = True
    ) -> int:
        effective_soft = (
            soft and not self.actor_provider.strict_reference_validation
        )
        cable_rows = [
            is_cable_receipt(row)
            or (
                effective_soft
                and not str(row.get("serial_number") or "").strip()
            )
            for row in rows
        ]
        if any(cable_rows):
            if not all(cable_rows):
                raise WarehouseError(
                    "Разделите CSV прихода кабелей и оборудования на разные файлы"
                )
            return int(
                self.cables.create_cable_receipt_batch(
                    rows, soft=effective_soft
                )[
                    "created_count"
                ]
            )
        return self.writer.import_receipts(rows, soft=effective_soft)

    def stock_receipts(self) -> list[dict[str, Any]]:
        return self.writer.repository.receipts(limit=None)

    def import_preview_rows(
        self, kind: str, preview_id: str = ""
    ) -> list[dict[str, Any]]:
        return self.previews.rows(
            kind,
            author=self.writer.audit_author(),
            preview_id=preview_id,
        )
