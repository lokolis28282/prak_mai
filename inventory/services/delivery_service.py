"""Compatibility names backed by extracted delivery services."""

from __future__ import annotations

from typing import Any

from inventory.shared.audit import write_audit_entry
from inventory.shared.db import connect
from inventory.shared.validators import WarehouseError
from inventory.warehouse.deliveries import DeliveryReadService
from inventory.warehouse.delivery_acceptance import DeliveryAcceptanceService
from inventory.warehouse.receipt_imports import ReceiptWriteService


class DeliveryService:
    def __init__(
        self,
        actor_provider: Any,
        *,
        receipt_writer: ReceiptWriteService,
    ):
        # Local import avoids inventory.core -> application -> service bootstrap
        # while this compatibility module itself is being imported.
        from inventory.warehouse.delivery_imports import DeliveryImportService

        self.actor_provider = actor_provider
        self.importer = DeliveryImportService(
            actor_provider.db_path,
            actor_provider=actor_provider,
        )
        self.reader = DeliveryReadService(actor_provider.db_path)
        self.acceptance = DeliveryAcceptanceService(
            actor_provider.db_path,
            actor_provider=actor_provider,
            receipt_writer=receipt_writer,
        )
        self._auto_apply_previews: set[str] = set()

    def preview_delivery_rows(
        self,
        rows: list[dict[str, Any]],
        filename: str,
        unknown_columns: list[str] | tuple[str, ...] = (),
        *,
        auto_apply: bool = False,
    ) -> dict[str, Any]:
        result = self.importer.preview_delivery_import(
            [dict(row) for row in rows],
            filename,
            unknown_columns=list(unknown_columns),
        )
        if auto_apply:
            self._auto_apply_previews.add(str(result["preview_id"]))
        return result

    def confirm_delivery_preview(self, preview_id: str) -> int:
        delivery_id = self.importer.confirm_delivery_import(preview_id)
        if preview_id in self._auto_apply_previews:
            self._auto_apply_previews.discard(preview_id)
            for line in self.reader.get_delivery_lines(delivery_id):
                if line.get("state") not in {"Ожидается", "Уже на складе"}:
                    continue
                serial = str(line.get("serial_number") or "").strip()
                if serial:
                    self.acceptance.accept_delivery_serial(
                        delivery_id, serial, dict(line)
                    )
        return delivery_id

    def deliveries(self, query: str = "") -> list[dict[str, Any]]:
        return self.reader.list_deliveries(query)

    def delivery(self, delivery_id: int) -> dict[str, Any]:
        return self.reader.get_delivery(delivery_id)

    def update_delivery_lines(
        self,
        delivery_id: int,
        line_ids: list[int],
        values: dict[str, Any],
        *,
        only_empty: bool = False,
    ) -> int:
        return self.acceptance.update_delivery_line_metadata(
            delivery_id, line_ids, values, only_empty=only_empty
        )

    def accept_delivery_serial(
        self,
        delivery_id: int,
        serial_number: str,
        values: dict[str, Any] | None = None,
        *,
        unplanned: bool = False,
    ) -> dict[str, Any]:
        if not unplanned:
            return self.acceptance.accept_delivery_serial(
                delivery_id, serial_number, values
            )
        delivery = self.reader.get_delivery(delivery_id)["delivery"]
        supplied = {
            "supplier": delivery.get("supplier") or "Не указан",
            "vendor": "Не указан",
            "datacenter": "Ixcellerate",
            "shelf": "Не указано",
            "project": "Не указан",
            "equipment_type": "Прочее",
            **dict(values or {}),
        }
        return self.acceptance.accept_unplanned_delivery_serial(
            delivery_id, serial_number, supplied
        )

    def close_delivery(self, delivery_id: int) -> None:
        self.actor_provider._require_write()
        actor = str(self.actor_provider.current_user()["email"])
        with connect(self.actor_provider.db_path) as db:
            if (
                db.execute(
                    "SELECT id FROM deliveries WHERE id=?", (delivery_id,)
                ).fetchone()
                is None
            ):
                raise WarehouseError("Поставка не найдена")
            db.execute(
                """UPDATE deliveries
                      SET status='Закрыта',closed_by=?,
                          closed_at=datetime('now','localtime')
                    WHERE id=?""",
                (actor, delivery_id),
            )
            write_audit_entry(
                db,
                action="DELIVERY_CLOSE",
                entity_type="delivery",
                entity_id=delivery_id,
                author=actor,
            )
