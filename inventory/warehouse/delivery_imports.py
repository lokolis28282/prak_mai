"""Delivery document import preview and confirm service."""

from __future__ import annotations

from typing import Any

from inventory.core.events import WarehouseEvent
from inventory.shared.validators import WarehouseError

from .delivery_mapping import map_headers, normalize_row
from .delivery_models import (
    DELIVERY_TEMPLATE_HEADERS,
    NO_SERIAL_LABEL,
    PREVIEW_ROW_LIMIT,
    QUANTITY_ERROR_LABEL,
    READY_LABEL,
    REVIEW_LABEL,
    STATE_DUPLICATE,
    STATE_ERROR,
    STATE_EXISTING,
    STATE_WAITING,
    UNKNOWN_REQUIRED_LABEL,
)
from .delivery_previews import DeliveryPreviewStore
from .delivery_repository import DeliveryRepository
from .delivery_validators import parse_quantity, quantity_warning, split_serials, state_for_validation


class DeliveryImportService:
    def __init__(
        self,
        db_path: Any,
        *,
        actor_provider: Any,
        previews: DeliveryPreviewStore | None = None,
        event_publisher: Any = None,
    ):
        self.repository = DeliveryRepository(db_path)
        self.actor_provider = actor_provider
        self.previews = previews or DeliveryPreviewStore()
        self.event_publisher = event_publisher

    def get_template(self) -> str:
        return ";".join(DELIVERY_TEMPLATE_HEADERS) + "\r\n"

    def preview_delivery_import(
        self,
        rows: list[dict[str, Any]],
        filename: str,
        source_metadata: dict[str, Any] | None = None,
        *,
        unknown_columns: list[str] | None = None,
    ) -> dict[str, Any]:
        self.actor_provider._require_write()
        if not rows:
            raise WarehouseError("В файле поставки нет строк")
        source_metadata = source_metadata or {}
        headers = list(rows[0].keys())
        mapping_info = map_headers(headers)
        if unknown_columns:
            merged_unknown = list(dict.fromkeys([*mapping_info["unknown_columns"], *unknown_columns]))
            mapping_info["unknown_columns"] = merged_unknown
        expanded = self._expand_rows(rows)
        serials = [str(row.get("serial_number") or "") for row in expanded if row.get("serial_number")]
        stock_matches = self.repository.existing_stock_serials(serials)
        delivery_matches = self.repository.existing_delivery_serials(serials)
        self._apply_matches(expanded, stock_matches, delivery_matches)
        summary = self._summary(expanded, len(rows), mapping_info)
        author = str(self.actor_provider.current_user()["email"])
        preview = self.previews.store({
            "author": author,
            "session": str(source_metadata.get("session") or ""),
            "filename": filename,
            "source_headers": headers,
            "normalized_mapping": mapping_info["mapping"],
            "unknown_columns": mapping_info["unknown_columns"],
            "ambiguous_columns": mapping_info["ambiguous_columns"],
            "source_rows": [dict(row) for row in rows],
            "expanded_rows": expanded,
            "validation_results": [{"row_number": row["row_number"], "state": row["state"], "error_text": row["error_text"]} for row in expanded],
            "summary": summary,
        })
        return {
            "preview_id": preview["preview_id"],
            "kind": preview["kind"],
            "filename": filename,
            "created_at": preview["created_at"],
            "source_headers": headers,
            "normalized_mapping": mapping_info["mapping"],
            "unknown_columns": mapping_info["unknown_columns"],
            "ambiguous_columns": mapping_info["ambiguous_columns"],
            "summary": summary,
            "counts": {
                STATE_WAITING: summary["ready_rows"],
                STATE_EXISTING: summary["existing_stock"],
                STATE_DUPLICATE: summary["duplicates"],
                STATE_ERROR: summary["errors"],
            },
            "total": summary["expanded_rows"],
            "new": summary["new_serials"],
            "updated": summary["existing_stock"],
            "duplicates": summary["duplicates"],
            "errors": summary["errors"],
            "rows": expanded[:PREVIEW_ROW_LIMIT],
            "can_confirm": summary["expanded_rows"] > 0,
        }

    def confirm_delivery_import(self, preview_id: str, *, source_metadata: dict[str, Any] | None = None) -> int:
        self.actor_provider._require_write()
        user = self.actor_provider.current_user()
        source_metadata = source_metadata or {}
        preview = self.previews.consume(
            preview_id,
            author=str(user["email"]),
            session=str(source_metadata.get("session") or ""),
        )
        rows = [dict(row) for row in preview["expanded_rows"]]
        if not rows:
            raise WarehouseError("В предпросмотре нет строк поставки")
        first = rows[0]
        details = {
            "filename": preview["filename"],
            "rows": len(rows),
            "summary": preview["summary"],
            "mapping": preview["normalized_mapping"],
        }
        delivery_id = self.repository.create_delivery_document(
            filename=str(preview["filename"]),
            delivery_number=str(first.get("delivery_number") or ""),
            supplier=str(first.get("supplier") or ""),
            uploaded_by=str(user["email"]),
            rows=rows,
            audit_details=details,
            audit_callback=self.actor_provider._audit,
        )
        if self.event_publisher:
            self.event_publisher.publish(WarehouseEvent(
                event_type="DELIVERY_IMPORTED",
                occurred_at=str(preview["created_at"]),
                actor=str(user["email"]),
                entity_id=str(delivery_id),
                payload={"filename": preview["filename"], "summary": preview["summary"]},
            ))
        return delivery_id

    def get_mapping(self, preview_id: str, *, source_metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        user = self.actor_provider.current_user()
        preview = self.previews.get(
            preview_id,
            author=str(user["email"]),
            session=str((source_metadata or {}).get("session") or ""),
        )
        return {
            "normalized_mapping": preview["normalized_mapping"],
            "unknown_columns": preview["unknown_columns"],
            "ambiguous_columns": preview["ambiguous_columns"],
        }

    def _expand_rows(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        expanded: list[dict[str, Any]] = []
        seen: set[str] = set()
        for source_index, source in enumerate(rows, start=2):
            normalized = normalize_row(source)
            serials = split_serials(normalized.get("serial_number"))
            quantity, quantity_error = parse_quantity(normalized.get("quantity"))
            warning = quantity_warning(quantity, len(serials))
            if not serials:
                serials = [""]
            row_seen: set[str] = set()
            for serial in serials:
                key = serial.casefold()
                state, error = state_for_validation(serial, warning)
                warnings = [warning] if warning and warning != NO_SERIAL_LABEL else []
                if not normalized.get("quantity"):
                    normalized["quantity"] = "1"
                if serial and key in row_seen:
                    state, error = STATE_DUPLICATE, "S/N повторяется в одной строке"
                elif serial and key in seen:
                    state, error = STATE_DUPLICATE, "S/N повторяется в файле"
                elif warning == REVIEW_LABEL and state != STATE_ERROR:
                    error = REVIEW_LABEL
                if serial:
                    row_seen.add(key)
                    seen.add(key)
                item = {
                    **normalized,
                    "source_line": source_index,
                    "row_number": len(expanded) + 1,
                    "serial_number": serial,
                    "quantity": quantity or 1,
                    "state": state,
                    "status_label": self._status_label(state, error),
                    "error_text": error,
                    "warnings": warnings,
                    "source_serial_value": source.get("serial_number") or source.get("Серийный номер") or "",
                }
                if not serial:
                    item["status_label"] = NO_SERIAL_LABEL
                if state == STATE_ERROR and error == "Количество и S/N не согласованы":
                    item["status_label"] = QUANTITY_ERROR_LABEL
                if not item.get("serial_number") and not item.get("delivery_number"):
                    item["status_label"] = UNKNOWN_REQUIRED_LABEL
                expanded.append(item)
        return expanded

    def _apply_matches(
        self,
        rows: list[dict[str, Any]],
        stock_matches: dict[str, dict[str, Any]],
        delivery_matches: dict[str, list[dict[str, Any]]],
    ) -> None:
        for row in rows:
            key = str(row.get("serial_number") or "").casefold()
            if not key or row["state"] in {STATE_DUPLICATE, STATE_ERROR}:
                continue
            if key in stock_matches:
                match = stock_matches[key]
                row["state"] = STATE_EXISTING
                row["status_label"] = "Уже есть на складе"
                row["error_text"] = "S/N уже есть на складе"
                row["existing_receipt_id"] = match.get("id")
                row["existing_serial"] = match.get("serial_number")
                row["existing_stock"] = match
            elif key in delivery_matches:
                match = delivery_matches[key][0]
                row["status_label"] = "Повтор в другой загруженной поставке"
                row["error_text"] = "S/N уже есть в другой поставке"
                row["other_delivery"] = match
            else:
                row["status_label"] = "Новый S/N"

    def _summary(self, rows: list[dict[str, Any]], source_count: int, mapping_info: dict[str, Any]) -> dict[str, Any]:
        return {
            "source_rows": source_count,
            "expanded_rows": len(rows),
            "serials": sum(1 for row in rows if row.get("serial_number")),
            "new_serials": sum(1 for row in rows if row.get("status_label") == "Новый S/N"),
            "existing_stock": sum(1 for row in rows if row.get("state") == STATE_EXISTING),
            "duplicates": sum(1 for row in rows if row.get("state") == STATE_DUPLICATE),
            "errors": sum(1 for row in rows if row.get("state") == STATE_ERROR),
            "unknown_columns": len(mapping_info["unknown_columns"]),
            "warnings": sum(len(row.get("warnings") or []) + (1 if row.get("error_text") and row.get("state") != STATE_ERROR else 0) for row in rows),
            "rows_without_serial": sum(1 for row in rows if not row.get("serial_number")),
            "ready_rows": sum(1 for row in rows if row.get("state") in {STATE_WAITING, STATE_EXISTING}),
        }

    @staticmethod
    def _status_label(state: str, error: str) -> str:
        if state == STATE_WAITING and not error:
            return READY_LABEL
        if state == STATE_DUPLICATE:
            return "Дубль в файле"
        if state == STATE_EXISTING:
            return "Уже есть на складе"
        if state == STATE_ERROR:
            return error or "Ошибка"
        return REVIEW_LABEL
