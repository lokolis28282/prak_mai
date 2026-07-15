"""Warehouse receipt write/import service."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Iterable

from inventory.importing import PREVIEW_ERROR_LIMIT, PREVIEW_ROW_LIMIT
from inventory.shared.db import connect
from inventory.shared.validators import WarehouseError

from .naming import build_item_name
from .previews import WarehousePreviewStore
from .receipt_repository import ReceiptRepository
from .validators import is_cable_receipt, prepare_receipt, soft_receipt_source


INVENTORY_NUMBER_IMPORT_KIND = "inventory_numbers"
INVENTORY_NUMBER_STATUSES = (
    "SUCCESS",
    "UNCHANGED",
    "NOT_FOUND",
    "ALREADY_ASSIGNED",
    "DUPLICATE_INVENTORY_NUMBER",
    "VALIDATION_ERROR",
)
SQL_VALUE_CHUNK_SIZE = 400


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
                "SELECT 1 FROM stock_receipts WHERE trim(serial_number) <> '' AND trim(serial_number) = trim(?) COLLATE NOCASE",
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

    def assign_inventory_number(
        self, serial_number: str, inventory_number: str
    ) -> dict[str, Any]:
        self._require_write()
        serial = self._identifier(serial_number, "S/N")
        inventory = self._identifier(inventory_number, "инвентарный номер")
        return self.repository.assign_inventory_number(
            serial,
            inventory,
            author=self.audit_author(),
        )

    def preview_inventory_number_import(
        self,
        rows: Iterable[dict[str, Any]],
        filename: str = "inventory_numbers.csv",
    ) -> dict[str, Any]:
        """Analyze inventory-number assignments without changing the database."""
        self._require_write()
        source_rows = [dict(row) for row in rows]
        with connect(self.repository.db_path) as db:
            analysis = self._analyze_inventory_number_rows(db, source_rows)
        all_rows = analysis.pop("_all_rows")
        stored_rows = [
            {
                "serial_number": row["serial_number"],
                "inventory_number": row["inventory_number"],
                "_preview_status": row["status"],
                "_preview_current_inventory_number": row["current_inventory_number"],
                "_preview_receipt_id": str(row.get("_receipt_id") or ""),
            }
            for row in all_rows
        ]
        return self.previews.store(
            kind=INVENTORY_NUMBER_IMPORT_KIND,
            author=self.audit_author(),
            filename=filename,
            rows=stored_rows,
            validation=analysis,
        )

    def confirm_inventory_number_import(self, preview_id: str) -> dict[str, Any]:
        """Apply every SUCCESS row in one caller-visible atomic transaction."""
        self._require_write()
        preview = self.previews.consume(
            preview_id,
            kind=INVENTORY_NUMBER_IMPORT_KIND,
            author=self.audit_author(),
        )
        stored_rows = [dict(row) for row in preview["rows"]]
        source_rows = [
            {
                "serial_number": row.get("serial_number", ""),
                "inventory_number": row.get("inventory_number", ""),
            }
            for row in stored_rows
        ]
        try:
            with connect(self.repository.db_path) as db:
                # Lock before revalidation so classification and all writes see
                # one stable warehouse state.
                db.execute("BEGIN IMMEDIATE")
                analysis = self._analyze_inventory_number_rows(db, source_rows)
                all_rows = analysis.pop("_all_rows")
                if analysis["errors"]:
                    raise WarehouseError(analysis["errors"][0]["reason"])
                if not self._inventory_preview_matches(stored_rows, all_rows):
                    raise WarehouseError(
                        "Данные склада изменились после предпросмотра. "
                        "Выполните предпросмотр повторно."
                    )

                changed_count = 0
                author = self.audit_author()
                for row in all_rows:
                    if row["status"] != "SUCCESS":
                        continue
                    result = self.repository.assign_inventory_number_in_transaction(
                        db,
                        row["serial_number"],
                        row["inventory_number"],
                        author=author,
                    )
                    if not result["updated"]:
                        raise WarehouseError(
                            "Данные склада изменились во время импорта. "
                            "Все изменения отменены."
                        )
                    row["message"] = "Инвентарный номер назначен"
                    changed_count += 1
        except sqlite3.Error as error:
            raise WarehouseError(
                "Не удалось применить импорт. Все изменения отменены."
            ) from error

        analysis["rows"] = [
            self._public_inventory_number_row(row)
            for row in all_rows[:PREVIEW_ROW_LIMIT]
        ]
        return {
            **analysis,
            "imported": changed_count,
            "changed_count": changed_count,
        }

    def _analyze_inventory_number_rows(
        self,
        db: sqlite3.Connection,
        source_rows: list[dict[str, Any]],
    ) -> dict[str, Any]:
        normalized: list[dict[str, Any]] = []
        serial_occurrences: dict[str, int] = {}
        for line, source in enumerate(source_rows, start=2):
            reasons: list[str] = []
            serial_value = source.get("serial_number", "")
            inventory_value = source.get("inventory_number", "")
            if not isinstance(serial_value, str):
                reasons.append("Serial Number должен быть строкой")
                serial = ""
            else:
                serial = serial_value.strip().upper()
            if not isinstance(inventory_value, str):
                reasons.append("Inventory Number должен быть строкой")
                inventory = ""
            else:
                inventory = inventory_value.strip().upper()
            if not serial:
                reasons.append("Serial Number не может быть пустым")
            elif len(serial) > 255:
                reasons.append("Serial Number не должен быть длиннее 255 символов")
            if not inventory:
                reasons.append("Inventory Number не может быть пустым")
            elif len(inventory) > 255:
                reasons.append("Inventory Number не должен быть длиннее 255 символов")
            if serial:
                serial_key = serial.casefold()
                serial_occurrences[serial_key] = serial_occurrences.get(serial_key, 0) + 1
            normalized.append({
                "line": line,
                "serial_number": serial,
                "inventory_number": inventory,
                "current_inventory_number": "",
                "status": "VALIDATION_ERROR" if reasons else "",
                "message": "; ".join(dict.fromkeys(reasons)),
                "_receipt_id": None,
                "_legacy_equipment_id": None,
            })

        for row in normalized:
            serial_key = row["serial_number"].casefold()
            if serial_key and serial_occurrences.get(serial_key, 0) > 1:
                reason = f"Serial Number «{row['serial_number']}» повторяется внутри CSV"
                existing = [part for part in row["message"].split("; ") if part]
                if reason not in existing:
                    existing.append(reason)
                row["status"] = "VALIDATION_ERROR"
                row["message"] = "; ".join(existing)

        valid_rows = [row for row in normalized if row["status"] != "VALIDATION_ERROR"]
        serials = {row["serial_number"].casefold(): row["serial_number"] for row in valid_rows}
        inventories = {
            row["inventory_number"].casefold(): row["inventory_number"]
            for row in valid_rows
        }
        receipts = self._receipt_rows_by_serial(db, list(serials.values()))
        receipt_by_serial = {
            str(row["serial_number"]).strip().casefold(): row for row in receipts
        }
        legacy_ids = {
            int(row["legacy_equipment_id"])
            for row in receipts if row["legacy_equipment_id"] is not None
        }
        legacy_by_id = self._legacy_rows_by_id(db, legacy_ids)
        stock_owners = self._stock_inventory_owners(db, list(inventories.values()))
        legacy_owners = self._legacy_inventory_owners(db, list(inventories.values()))

        for row in valid_rows:
            receipt = receipt_by_serial.get(row["serial_number"].casefold())
            if receipt is None:
                row["status"] = "NOT_FOUND"
                row["message"] = "Оборудование с таким Serial Number не найдено"
                continue
            receipt_id = int(receipt["id"])
            legacy_id = (
                int(receipt["legacy_equipment_id"])
                if receipt["legacy_equipment_id"] is not None else None
            )
            row["_receipt_id"] = receipt_id
            row["_legacy_equipment_id"] = legacy_id
            current = str(receipt["inventory_number"] or "").strip()
            legacy_inventory = ""
            if legacy_id is not None and legacy_id in legacy_by_id:
                legacy_inventory = str(
                    legacy_by_id[legacy_id]["inventory_number"] or ""
                ).strip()
            incoming_key = row["inventory_number"].casefold()
            if current:
                row["current_inventory_number"] = current
                if current.casefold() == incoming_key:
                    row["status"] = "UNCHANGED"
                    row["message"] = "Инвентарный номер уже совпадает"
                else:
                    row["status"] = "ALREADY_ASSIGNED"
                    row["message"] = f"Уже назначен другой номер «{current}»"
                continue
            if legacy_inventory and legacy_inventory.casefold() != incoming_key:
                row["current_inventory_number"] = legacy_inventory
                row["status"] = "ALREADY_ASSIGNED"
                row["message"] = (
                    f"В связанной карточке уже назначен номер «{legacy_inventory}»"
                )
                continue
            foreign_stock_owner = any(
                owner_id != receipt_id
                for owner_id in stock_owners.get(incoming_key, set())
            )
            foreign_legacy_owner = any(
                legacy_id is None or owner_id != legacy_id
                for owner_id in legacy_owners.get(incoming_key, set())
            )
            if foreign_stock_owner or foreign_legacy_owner:
                row["status"] = "DUPLICATE_INVENTORY_NUMBER"
                row["message"] = "Inventory Number уже принадлежит другому оборудованию"
                continue
            row["status"] = "SUCCESS"
            row["message"] = "Инвентарный номер будет назначен"

        planned: dict[str, list[dict[str, Any]]] = {}
        for row in valid_rows:
            if row["status"] == "SUCCESS":
                planned.setdefault(row["inventory_number"].casefold(), []).append(row)
        for duplicates in planned.values():
            if len(duplicates) < 2:
                continue
            for row in duplicates:
                row["status"] = "DUPLICATE_INVENTORY_NUMBER"
                row["message"] = (
                    "Inventory Number назначается нескольким строкам внутри CSV"
                )

        counts = {status: 0 for status in INVENTORY_NUMBER_STATUSES}
        for row in normalized:
            counts[row["status"]] += 1
        errors = [
            {"line": row["line"], "reason": row["message"]}
            for row in normalized if row["status"] == "VALIDATION_ERROR"
        ]
        if not normalized:
            errors.append({"line": 1, "reason": "В CSV-файле нет строк"})
            counts["VALIDATION_ERROR"] = 1
        summary = {"total": len(normalized), **counts}
        return {
            "total": len(normalized),
            "success": counts["SUCCESS"],
            "unchanged": counts["UNCHANGED"],
            "not_found": counts["NOT_FOUND"],
            "already_assigned": counts["ALREADY_ASSIGNED"],
            "duplicate_inventory_number": counts["DUPLICATE_INVENTORY_NUMBER"],
            "validation_error": counts["VALIDATION_ERROR"],
            "valid": len(normalized) - counts["VALIDATION_ERROR"],
            "new": counts["SUCCESS"],
            "error_count": counts["VALIDATION_ERROR"],
            "summary": summary,
            "errors": errors[:PREVIEW_ERROR_LIMIT],
            "rows": [
                self._public_inventory_number_row(row)
                for row in normalized[:PREVIEW_ROW_LIMIT]
            ],
            "_all_rows": normalized,
        }

    @staticmethod
    def _public_inventory_number_row(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "line": row["line"],
            "serial_number": row["serial_number"],
            "inventory_number": row["inventory_number"],
            "current_inventory_number": row["current_inventory_number"],
            "status": row["status"],
            "message": row["message"],
        }

    @staticmethod
    def _inventory_preview_matches(
        stored_rows: list[dict[str, Any]],
        current_rows: list[dict[str, Any]],
    ) -> bool:
        if len(stored_rows) != len(current_rows):
            return False
        for stored, current in zip(stored_rows, current_rows):
            if (
                str(stored.get("_preview_status") or "") != current["status"]
                or str(stored.get("_preview_current_inventory_number") or "")
                != current["current_inventory_number"]
                or str(stored.get("_preview_receipt_id") or "")
                != str(current.get("_receipt_id") or "")
            ):
                return False
        return True

    @staticmethod
    def _receipt_rows_by_serial(
        db: sqlite3.Connection, values: list[str]
    ) -> list[sqlite3.Row]:
        rows: list[sqlite3.Row] = []
        for offset in range(0, len(values), SQL_VALUE_CHUNK_SIZE):
            chunk = values[offset:offset + SQL_VALUE_CHUNK_SIZE]
            placeholders = ",".join("?" for _ in chunk)
            rows.extend(db.execute(
                f"""SELECT id, serial_number, inventory_number, legacy_equipment_id
                    FROM stock_receipts
                    WHERE trim(serial_number) <> ''
                      AND serial_number COLLATE NOCASE IN ({placeholders})""",
                chunk,
            ).fetchall())
        return rows

    @staticmethod
    def _legacy_rows_by_id(
        db: sqlite3.Connection, values: set[int]
    ) -> dict[int, sqlite3.Row]:
        result: dict[int, sqlite3.Row] = {}
        ordered = sorted(values)
        for offset in range(0, len(ordered), SQL_VALUE_CHUNK_SIZE):
            chunk = ordered[offset:offset + SQL_VALUE_CHUNK_SIZE]
            placeholders = ",".join("?" for _ in chunk)
            for row in db.execute(
                f"SELECT id, inventory_number FROM equipment WHERE id IN ({placeholders})",
                chunk,
            ):
                result[int(row["id"])] = row
        return result

    @staticmethod
    def _stock_inventory_owners(
        db: sqlite3.Connection, values: list[str]
    ) -> dict[str, set[int]]:
        result: dict[str, set[int]] = {}
        for offset in range(0, len(values), SQL_VALUE_CHUNK_SIZE):
            chunk = values[offset:offset + SQL_VALUE_CHUNK_SIZE]
            placeholders = ",".join("?" for _ in chunk)
            for row in db.execute(
                f"""SELECT id, inventory_number FROM stock_receipts
                    WHERE trim(inventory_number) <> ''
                      AND inventory_number COLLATE NOCASE IN ({placeholders})""",
                chunk,
            ):
                key = str(row["inventory_number"]).strip().casefold()
                result.setdefault(key, set()).add(int(row["id"]))
        return result

    @staticmethod
    def _legacy_inventory_owners(
        db: sqlite3.Connection, values: list[str]
    ) -> dict[str, set[int]]:
        result: dict[str, set[int]] = {}
        for offset in range(0, len(values), SQL_VALUE_CHUNK_SIZE):
            chunk = values[offset:offset + SQL_VALUE_CHUNK_SIZE]
            placeholders = ",".join("?" for _ in chunk)
            for row in db.execute(
                f"""SELECT id, inventory_number FROM equipment
                    WHERE trim(inventory_number) <> ''
                      AND inventory_number COLLATE NOCASE IN ({placeholders})""",
                chunk,
            ):
                key = str(row["inventory_number"]).strip().casefold()
                result.setdefault(key, set()).add(int(row["id"]))
        return result

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

    @classmethod
    def _identifier(cls, value: str, field: str) -> str:
        normalized = cls._required(str(value or ""), field).upper()
        if len(normalized) > 255:
            raise WarehouseError(f"Поле «{field}» не должно быть длиннее 255 символов")
        return normalized
