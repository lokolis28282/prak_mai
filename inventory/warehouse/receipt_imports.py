"""Warehouse receipt write/import service."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from inventory.importing import PREVIEW_ERROR_LIMIT, PREVIEW_ROW_LIMIT
from inventory.shared.db import connect
from inventory.shared.validators import WarehouseError

from .naming import build_item_name
from .previews import WarehousePreviewStore
from .receipt_repository import ReceiptRepository
from .validators import is_cable_receipt, prepare_receipt, soft_receipt_source


class ReceiptWriteService:
    def __init__(
        self,
        db_path: str | Path,
        *,
        actor_provider: Any,
        strict_reference_validation: bool = True,
        previews: WarehousePreviewStore | None = None,
    ):
        self.repository = ReceiptRepository(db_path)
        self.actor_provider = actor_provider
        self.strict_reference_validation = strict_reference_validation
        self.previews = previews or WarehousePreviewStore()

    def validate_receipt_serial(self, serial_number: str) -> dict[str, Any]:
        self._require_write()
        serial = self._required(str(serial_number).strip().upper(), "S/N")
        with connect(self.repository.db_path) as db:
            exists = db.execute(
                "SELECT 1 FROM stock_receipts WHERE serial_number = ? COLLATE NOCASE",
                (serial,),
            ).fetchone()
        return {
            "serial_number": serial,
            "valid": exists is None,
            "error": f"S/N «{serial}» уже есть на складе" if exists else "",
        }

    def prepare_receipt(self, data: dict[str, Any], *, line_number: int | None = None, soft: bool = False) -> dict[str, Any]:
        source = self._with_system_name(data)
        if soft:
            source = soft_receipt_source(source)
        with connect(self.repository.db_path) as db:
            return prepare_receipt(
                source,
                self.repository.reference_sets(db),
                line_number=line_number,
                strict_references=not soft if soft else self.strict_reference_validation,
            )

    def create_receipt(self, data: dict[str, Any]) -> int:
        self._require_write()
        if is_cable_receipt(data):
            raise WarehouseError("приход кабелей переносится отдельным этапом")
        row = self.prepare_receipt(data)
        return self.repository.insert_one(
            row,
            author=self.audit_author(),
            collect_refs=not self.strict_reference_validation,
        )

    def create_receipt_batch(self, rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
        self._require_write()
        prepared = self._prepare_rows(rows, soft=False)
        ids = self.repository.insert_many(
            prepared,
            author=self.audit_author(),
            collect_refs=not self.strict_reference_validation,
            audit_action="RECEIPT_BATCH_CREATE",
        )
        return {"created_count": len(ids), "skipped_count": 0, "errors": [], "receipt_ids": ids}

    def confirm_scanned_receipts(
        self, common_fields: dict[str, Any], serial_numbers: Iterable[str]
    ) -> int:
        serials = [str(value).strip().upper() for value in serial_numbers]
        if not serials or any(not value for value in serials):
            raise WarehouseError("Список S/N пуст или содержит пустое значение")
        folded = [value.casefold() for value in serials]
        if len(set(folded)) != len(folded):
            raise WarehouseError("Список содержит повторяющиеся S/N")
        rows = [
            {**common_fields, "serial_number": serial, "inventory_number": "", "quantity": 1}
            for serial in serials
        ]
        result = self.create_receipt_batch(rows)
        return int(result["created_count"])

    def import_receipts(self, rows: Iterable[dict[str, Any]], *, soft: bool = True) -> int:
        self._require_write()
        prepared = self._prepare_rows(rows, soft=soft)
        ids = self.repository.insert_many(
            prepared,
            author=self.audit_author(),
            collect_refs=soft or not self.strict_reference_validation,
            audit_action="RECEIPT_IMPORT",
        )
        return len(ids)

    def preview_receipt_import(
        self,
        rows: Iterable[dict[str, Any]],
        *,
        filename: str = "receipt.csv",
        unknown_columns: list[str] | None = None,
        soft: bool = False,
    ) -> dict[str, Any]:
        self._require_write()
        source_rows = [dict(row) for row in rows]
        errors: list[dict[str, Any]] = []
        preview_rows: list[dict[str, Any]] = []
        valid = duplicates = error_count = total = 0
        with connect(self.repository.db_path) as db:
            references = self.repository.reference_sets(db)
            existing_serials = self.repository.existing_serials(db)
            existing_inventories = self.repository.existing_inventories(db)
            seen_serials: set[str] = set()
            seen_inventories: set[str] = set()
            for line, source in enumerate(source_rows, start=2):
                if not any(str(value or "").strip() for value in source.values()):
                    continue
                total += 1
                reason = ""
                prepared: dict[str, Any] | None = None
                try:
                    if is_cable_receipt(source):
                        raise WarehouseError(f"Строка {line}: приход кабелей переносится отдельным этапом")
                    candidate = self._with_system_name(source)
                    if soft:
                        candidate = soft_receipt_source(candidate)
                    prepared = prepare_receipt(
                        candidate,
                        references,
                        line_number=line,
                        strict_references=not soft,
                    )
                    serial = prepared["serial_number"].casefold()
                    inventory = prepared["inventory_number"].casefold()
                    duplicate_reasons: list[str] = []
                    if serial and (serial in existing_serials or serial in seen_serials):
                        duplicate_reasons.append(f"S/N «{prepared['serial_number']}» уже используется")
                    if inventory and (inventory in existing_inventories or inventory in seen_inventories):
                        duplicate_reasons.append(f"инвентарный номер «{prepared['inventory_number']}» уже используется")
                    if duplicate_reasons:
                        duplicates += 1
                        raise WarehouseError(f"Строка {line}: " + "; ".join(duplicate_reasons))
                    seen_serials.add(serial)
                    if inventory:
                        seen_inventories.add(inventory)
                    valid += 1
                except WarehouseError as error:
                    reason = str(error)
                    error_count += 1
                    if len(errors) < PREVIEW_ERROR_LIMIT:
                        errors.append({"line": line, "reason": reason})
                if len(preview_rows) < PREVIEW_ROW_LIMIT:
                    shown = dict(prepared or source)
                    shown.update({"line": line, "valid": not reason, "error": reason})
                    preview_rows.append(shown)
        if total == 0:
            error_count += 1
            errors.append({"line": 1, "reason": "В CSV-файле нет строк прихода"})
        return self.previews.store(
            kind="receipt",
            author=self.audit_author(),
            filename=filename,
            rows=source_rows,
            validation={
                "total": total,
                "valid": valid,
                "new": valid,
                "duplicates": duplicates,
                "error_count": error_count,
                "errors": errors,
                "rows": preview_rows,
                "mode": "soft" if soft else "strict",
                "unknown_columns": list(unknown_columns or []),
            },
        )

    def confirm_receipt_import(self, preview_id: str) -> int:
        self._require_write()
        preview = self.previews.consume(preview_id, kind="receipt", author=self.audit_author())
        soft = preview.get("validation", {}).get("mode") == "soft"
        check = self.preview_receipt_import(
            preview["rows"],
            filename=preview.get("filename", "receipt.csv"),
            soft=soft,
        )
        self.previews.consume(check["preview_id"], kind="receipt", author=self.audit_author())
        if check["errors"]:
            raise WarehouseError(check["errors"][0]["reason"])
        return self.import_receipts(preview["rows"], soft=soft)

    def preview_rows(self, preview_id: str = "") -> list[dict[str, Any]]:
        return self.previews.rows("receipt", author=self.audit_author(), preview_id=preview_id)

    def _prepare_rows(self, rows: Iterable[dict[str, Any]], *, soft: bool) -> list[dict[str, Any]]:
        source_rows = [dict(row) for row in rows]
        prepared: list[dict[str, Any]] = []
        with connect(self.repository.db_path) as db:
            references = self.repository.reference_sets(db)
            for line, source in enumerate(source_rows, start=2):
                if not any(str(value or "").strip() for value in source.values()):
                    continue
                if is_cable_receipt(source):
                    raise WarehouseError(f"Строка {line}: приход кабелей переносится отдельным этапом")
                candidate = self._with_system_name(source)
                if soft:
                    candidate = soft_receipt_source(candidate)
                row = prepare_receipt(
                    candidate,
                    references,
                    line_number=line,
                    strict_references=not soft if soft else self.strict_reference_validation,
                )
                row["_line"] = line
                prepared.append(row)
        if not prepared:
            raise WarehouseError("В CSV-файле нет строк прихода")
        return prepared

    def _with_system_name(self, data: dict[str, Any]) -> dict[str, Any]:
        row = dict(data)
        category = str(row.get("category", "")).strip()
        item_type = str(row.get("item_type", "")).strip()
        if category.casefold() in {"оборудование", "компоненты"} and item_type:
            row["item_name"] = build_item_name(
                category,
                item_type,
                str(row.get("vendor") or row.get("custom_vendor") or ""),
                str(row.get("model") or ""),
            )
        return row

    def current_user(self) -> dict[str, Any]:
        return self.actor_provider.current_user()

    def audit_author(self) -> str:
        core = getattr(self.actor_provider, "_core", self.actor_provider)
        name = core._actor_name.get()
        user = self.current_user()
        return name or str(user.get("email") or "lokolis")

    def _require_write(self) -> dict[str, Any]:
        user = self.current_user()
        if user.get("role") not in {"admin", "engineer"}:
            raise WarehouseError("Недостаточно прав для выполнения операции")
        return user

    @staticmethod
    def _required(value: str, field: str) -> str:
        value = value.strip()
        if not value:
            raise WarehouseError(f"Поле «{field}» не может быть пустым")
        return value
