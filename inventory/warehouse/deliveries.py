"""Read/export operations for Warehouse delivery documents."""

from __future__ import annotations

from typing import Any

from inventory.shared.validators import WarehouseError

from .delivery_repository import DeliveryRepository


class DeliveryReadService:
    def __init__(self, db_path: Any):
        self.repository = DeliveryRepository(db_path)

    def list_deliveries(
        self, query: str = "", filters: dict[str, Any] | None = None,
        *, limit: int | None = None,
    ) -> list[dict[str, Any]]:
        return self.repository.list_deliveries(
            query or str((filters or {}).get("query") or ""), limit=limit
        )

    def get_delivery(
        self, delivery_id: int, filters: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        delivery = self.repository.get_delivery(int(delivery_id))
        if delivery is None:
            raise WarehouseError("Поставка не найдена")
        lines = self.get_delivery_lines(int(delivery_id), filters)
        summary = self.repository.delivery_line_summary(int(delivery_id))
        return {
            "delivery": delivery, "lines": lines, "summary": summary,
            "truncated": len(lines) < summary["total"],
        }

    def get_delivery_lines(self, delivery_id: int, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        return self.repository.get_delivery_lines(int(delivery_id), filters)

    def search_deliveries(self, query: str) -> list[dict[str, Any]]:
        return self.repository.list_deliveries(query)

    def export_delivery_rows(self, delivery_id: int) -> list[dict[str, Any]]:
        return self.get_delivery_lines(delivery_id)
