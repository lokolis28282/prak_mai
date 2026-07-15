"""Warehouse receipt persistence."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Iterable

from inventory.shared.audit import write_audit_entry
from inventory.shared.db import connect
from inventory.shared.validators import WarehouseError

from .validators import RECEIPT_REFERENCE_FIELDS


RECEIPT_FIELDS = (
    "receipt_date", "responsible", "order_date", "request_number", "order_number",
    "plu", "item_name", "project", "serial_number", "inventory_number", "supplier",
    "vendor", "model", "shelf", "object_name", "datacenter",
    "equipment_type", "component_type", "cable_type", "unit", "quantity",
)


class ReceiptRepository:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)

    def reference_sets(self, db: sqlite3.Connection) -> dict[str, set[str]]:
        result: dict[str, set[str]] = {}
        for row in db.execute("SELECT kind, name FROM reference_values WHERE is_active = 1"):
            result.setdefault(str(row["kind"]), set()).add(str(row["name"]).casefold())
        return result

    def existing_serials(self, db: sqlite3.Connection) -> set[str]:
        return {str(row[0]).casefold() for row in db.execute("SELECT serial_number FROM stock_receipts WHERE serial_number <> ''")}

    def existing_inventories(self, db: sqlite3.Connection) -> set[str]:
        return {str(row[0]).casefold() for row in db.execute("SELECT inventory_number FROM stock_receipts WHERE inventory_number <> ''")}

    def collect_references(self, db: sqlite3.Connection, rows: Iterable[dict[str, Any]], *, enabled: bool, author: str) -> None:
        if not enabled:
            return
        for field, kind in RECEIPT_REFERENCE_FIELDS.items():
            for value in {str(row[field]).strip() for row in rows if str(row.get(field, "")).strip()}:
                cursor = db.execute(
                    "INSERT OR IGNORE INTO reference_values(kind, name) VALUES (?, ?)",
                    (kind, value),
                )
                if cursor.rowcount:
                    write_audit_entry(
                        db,
                        action="REFERENCE_AUTO_CREATE",
                        entity_type="reference_value",
                        entity_id=cursor.lastrowid,
                        author=author,
                        details={"kind": kind, "name": value},
                    )

    def insert_one(self, row: dict[str, Any], *, author: str, collect_refs: bool) -> int:
        with connect(self.db_path) as db:
            if row["serial_number"] and db.execute(
                """SELECT 1 FROM stock_receipts
                   WHERE trim(serial_number) <> '' AND trim(serial_number) = trim(?) COLLATE NOCASE""",
                (row["serial_number"],),
            ).fetchone():
                raise WarehouseError(f"S/N «{row['serial_number']}» уже используется")
            if row["inventory_number"] and db.execute(
                """SELECT 1 FROM stock_receipts
                   WHERE trim(inventory_number) <> '' AND inventory_number = ? COLLATE NOCASE""",
                (row["inventory_number"],),
            ).fetchone():
                raise WarehouseError(f"инвентарный номер «{row['inventory_number']}» уже используется")
            self.collect_references(db, [row], enabled=collect_refs, author=author)
            try:
                cursor = db.execute(self.insert_sql(), self.values(row))
            except sqlite3.IntegrityError as error:
                raise WarehouseError("S/N или инвентарный номер уже используется") from error
            receipt_id = int(cursor.lastrowid)
            write_audit_entry(
                db,
                action="RECEIPT_CREATE",
                entity_type="stock_receipt",
                entity_id=receipt_id,
                author=author,
                details={"item_name": row["item_name"], "quantity": row["quantity"], "serial_number": row["serial_number"]},
            )
            return receipt_id

    def insert_one_in_transaction(
        self,
        db: sqlite3.Connection,
        row: dict[str, Any],
        *,
        author: str,
        collect_refs: bool,
        audit_action: str = "RECEIPT_CREATE",
    ) -> int:
        if row["serial_number"] and db.execute(
            """SELECT 1 FROM stock_receipts
               WHERE trim(serial_number) <> '' AND trim(serial_number) = trim(?) COLLATE NOCASE""",
            (row["serial_number"],),
        ).fetchone():
            raise WarehouseError(f"S/N «{row['serial_number']}» уже используется")
        if row["inventory_number"] and db.execute(
            """SELECT 1 FROM stock_receipts
               WHERE trim(inventory_number) <> '' AND inventory_number = ? COLLATE NOCASE""",
            (row["inventory_number"],),
        ).fetchone():
            raise WarehouseError(f"инвентарный номер «{row['inventory_number']}» уже используется")
        self.collect_references(db, [row], enabled=collect_refs, author=author)
        try:
            cursor = db.execute(self.insert_sql(), self.values(row))
        except sqlite3.IntegrityError as error:
            raise WarehouseError("S/N или инвентарный номер уже используется") from error
        receipt_id = int(cursor.lastrowid)
        write_audit_entry(
            db,
            action=audit_action,
            entity_type="stock_receipt",
            entity_id=receipt_id,
            author=author,
            details={"item_name": row["item_name"], "quantity": row["quantity"], "serial_number": row["serial_number"]},
        )
        return receipt_id

    def fill_empty_fields_in_transaction(
        self,
        db: sqlite3.Connection,
        receipt_id: int,
        values: dict[str, Any],
        *,
        allowed_fields: set[str],
    ) -> dict[str, Any]:
        row = db.execute("SELECT * FROM stock_receipts WHERE id=?", (receipt_id,)).fetchone()
        if row is None:
            raise WarehouseError("Складская позиция не найдена")
        updates: dict[str, Any] = {}
        skipped: dict[str, dict[str, Any]] = {}
        for field, value in values.items():
            if field not in allowed_fields:
                continue
            text = str(value or "").strip()
            if not text:
                continue
            current = str(row[field] or "").strip()
            if current:
                if current.casefold() != text.casefold():
                    skipped[field] = {"current": current, "incoming": text}
                continue
            updates[field] = text
        if updates:
            assignments = ", ".join(f"{field}=?" for field in updates)
            db.execute(
                f"UPDATE stock_receipts SET {assignments} WHERE id=?",
                (*updates.values(), receipt_id),
            )
        return {"updated_fields": updates, "conflicts": skipped}

    def assign_inventory_number(
        self,
        serial_number: str,
        inventory_number: str,
        *,
        author: str,
    ) -> dict[str, Any]:
        """Assign a secondary identifier to an existing serialized receipt.

        S/N remains the identity of the card.  This method only fills an empty
        inventory number and never creates or replaces a receipt.
        """
        with connect(self.db_path) as db:
            return self.assign_inventory_number_in_transaction(
                db, serial_number, inventory_number, author=author
            )

    def assign_inventory_number_in_transaction(
        self,
        db: sqlite3.Connection,
        serial_number: str,
        inventory_number: str,
        *,
        author: str,
    ) -> dict[str, Any]:
        """Assign an inventory number using the caller-owned transaction."""
        receipt = db.execute(
            """SELECT id, serial_number, inventory_number, legacy_equipment_id
               FROM stock_receipts
               WHERE trim(serial_number) <> ''
                 AND trim(serial_number) = trim(?) COLLATE NOCASE""",
            (serial_number,),
        ).fetchone()
        if receipt is None:
            raise WarehouseError(
                f"Карточка оборудования с S/N «{serial_number}» не найдена"
            )

        receipt_id = int(receipt["id"])
        current = str(receipt["inventory_number"] or "").strip()
        if current:
            if current.casefold() == inventory_number.casefold():
                return {
                    "receipt_id": receipt_id,
                    "serial_number": str(receipt["serial_number"]),
                    "inventory_number": current,
                    "updated": False,
                }
            raise WarehouseError(
                f"Для S/N «{serial_number}» уже указан инвентарный номер «{current}»"
            )

        legacy_equipment_id = receipt["legacy_equipment_id"]
        legacy_inventory = ""
        if legacy_equipment_id is not None:
            legacy = db.execute(
                "SELECT inventory_number FROM equipment WHERE id = ?",
                (int(legacy_equipment_id),),
            ).fetchone()
            if legacy is not None:
                legacy_inventory = str(legacy["inventory_number"] or "").strip()
                if (
                    legacy_inventory
                    and legacy_inventory.casefold() != inventory_number.casefold()
                ):
                    raise WarehouseError(
                        f"Для legacy-карточки S/N «{serial_number}» уже указан "
                        f"инвентарный номер «{legacy_inventory}»"
                    )

        legacy_owner = db.execute(
            """SELECT id FROM equipment
               WHERE trim(inventory_number) <> ''
                 AND inventory_number = ? COLLATE NOCASE
               LIMIT 1""",
            (inventory_number,),
        ).fetchone()
        if legacy_owner is not None and (
            legacy_equipment_id is None
            or int(legacy_owner["id"]) != int(legacy_equipment_id)
        ):
            raise WarehouseError(
                f"Инвентарный номер «{inventory_number}» уже используется"
            )

        try:
            fill = self.fill_empty_fields_in_transaction(
                db,
                receipt_id,
                {"inventory_number": inventory_number},
                allowed_fields={"inventory_number"},
            )
            if "inventory_number" not in fill["updated_fields"]:
                latest = db.execute(
                    "SELECT inventory_number FROM stock_receipts WHERE id = ?",
                    (receipt_id,),
                ).fetchone()
                latest_value = str(latest["inventory_number"] or "").strip()
                if latest_value.casefold() == inventory_number.casefold():
                    return {
                        "receipt_id": receipt_id,
                        "serial_number": str(receipt["serial_number"]),
                        "inventory_number": latest_value,
                        "updated": False,
                    }
                raise WarehouseError(
                    f"Для S/N «{serial_number}» уже указан другой инвентарный номер"
                )
            if legacy_equipment_id is not None and not legacy_inventory:
                db.execute(
                    "UPDATE equipment SET inventory_number = ? WHERE id = ?",
                    (inventory_number, int(legacy_equipment_id)),
                )
            write_audit_entry(
                db,
                action="EQUIPMENT_INVENTORY_NUMBER_ASSIGNED",
                entity_type="stock_receipt",
                entity_id=receipt_id,
                author=author,
                details={
                    "serial_number": str(receipt["serial_number"]),
                    "inventory_number": inventory_number,
                },
            )
        except sqlite3.IntegrityError as error:
            raise WarehouseError(
                f"Инвентарный номер «{inventory_number}» уже используется"
            ) from error

        return {
            "receipt_id": receipt_id,
            "serial_number": str(receipt["serial_number"]),
            "inventory_number": inventory_number,
            "updated": True,
        }

    def insert_many(
        self,
        rows: list[dict[str, Any]],
        *,
        author: str,
        collect_refs: bool,
        audit_action: str = "RECEIPT_IMPORT",
    ) -> list[int]:
        with connect(self.db_path) as db:
            self.validate_unique(db, rows)
            self.collect_references(db, rows, enabled=collect_refs, author=author)
            try:
                ids: list[int] = []
                for row in rows:
                    cursor = db.execute(self.insert_sql(), self.values(row))
                    ids.append(int(cursor.lastrowid))
            except sqlite3.IntegrityError as error:
                raise WarehouseError("S/N или инвентарный номер уже используется") from error
            write_audit_entry(
                db,
                action=audit_action,
                entity_type="stock_receipt",
                author=author,
                details={"count": len(rows), "receipt_ids": ids[:100]},
            )
            return ids

    def validate_unique(self, db: sqlite3.Connection, rows: list[dict[str, Any]]) -> None:
        requested_serials = {
            str(row["serial_number"]).strip().casefold()
            for row in rows if str(row["serial_number"]).strip()
        }
        requested_inventories = {
            str(row["inventory_number"]).strip().casefold()
            for row in rows if str(row["inventory_number"]).strip()
        }
        existing_serials = self._existing_identifiers(db, "serial_number", requested_serials)
        existing_inventories = self._existing_identifiers(
            db, "inventory_number", requested_inventories
        )
        seen_serials: set[str] = set()
        seen_inventories: set[str] = set()
        for row in rows:
            line = row.get("_line")
            prefix = f"Строка {line}: " if line else ""
            serial = str(row["serial_number"]).casefold()
            inventory = str(row["inventory_number"]).casefold()
            if serial and (serial in existing_serials or serial in seen_serials):
                raise WarehouseError(f"{prefix}S/N «{row['serial_number']}» уже используется")
            if inventory and (inventory in existing_inventories or inventory in seen_inventories):
                raise WarehouseError(f"{prefix}инвентарный номер «{row['inventory_number']}» уже используется")
            seen_serials.add(serial)
            if inventory:
                seen_inventories.add(inventory)

    @staticmethod
    def _existing_identifiers(
        db: sqlite3.Connection, column: str, values: set[str]
    ) -> set[str]:
        if column not in {"serial_number", "inventory_number"}:
            raise ValueError("unsupported identifier column")
        result: set[str] = set()
        ordered = list(values)
        for offset in range(0, len(ordered), 400):
            chunk = ordered[offset:offset + 400]
            if not chunk:
                continue
            placeholders = ",".join("?" for _ in chunk)
            rows = db.execute(
                f"""SELECT {column} FROM stock_receipts
                    WHERE trim({column}) <> ''
                      AND {column} COLLATE NOCASE IN ({placeholders})""",
                chunk,
            )
            result.update(str(row[0]).casefold() for row in rows)
        return result

    def receipts(self, limit: int | None = None) -> list[dict[str, Any]]:
        sql = """SELECT r.*,
                        r.quantity - COALESCE(SUM(a.quantity), 0) AS available
                 FROM stock_receipts r
                 LEFT JOIN stock_issue_allocations a ON a.receipt_id = r.id
                 GROUP BY r.id ORDER BY r.receipt_date DESC, r.id DESC"""
        params: tuple[int, ...] = ()
        if limit is not None:
            sql += " LIMIT ?"
            params = (max(1, min(int(limit), 10_000)),)
        with connect(self.db_path) as db:
            return [dict(row) for row in db.execute(
                sql, params
            )]

    @staticmethod
    def values(row: dict[str, Any]) -> tuple[Any, ...]:
        return tuple(row[field] for field in RECEIPT_FIELDS)

    @staticmethod
    def insert_sql() -> str:
        return """INSERT INTO stock_receipts(
                   receipt_date, responsible, order_date, request_number, order_number,
                   plu, item_name, project, serial_number, inventory_number, supplier,
                   vendor, model, shelf, object_name, datacenter, equipment_type,
                   component_type, cable_type, unit, quantity
               ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""
