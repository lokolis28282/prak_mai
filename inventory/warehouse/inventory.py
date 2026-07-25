"""Extracted Warehouse domain service."""

from __future__ import annotations

import csv
import json
import re
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

from inventory.db import connect
from inventory.shared.validators import WarehouseError

from .classification import (
    canonical_vendor,
    classify_card,
    infer_vendor,
    operational_category,
)
from .component import WarehouseComponent
from .issue_repository import IssueRepository


class LegacyInventoryService(WarehouseComponent):
    @staticmethod
    def _required(value: str, field: str) -> str:
        value = value.strip()
        if not value:
            raise WarehouseError(f"Поле «{field}» не может быть пустым")
        return value

    @staticmethod
    def _date(value: str, field: str = "дата") -> str:
        value = value.strip()
        for date_format in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
            try:
                return datetime.strptime(value, date_format).date().isoformat()
            except ValueError:
                pass
        raise WarehouseError(
            f"Поле «{field}» должно содержать дату в формате "
            "ГГГГ-ММ-ДД, ДД.ММ.ГГГГ или ДД/ММ/ГГГГ"
        )

    @staticmethod
    def _choice(value: str, field: str, choices: tuple[str, ...]) -> str:
        value = value.strip()
        if value not in choices:
            raise WarehouseError(
                f"Поле «{field}»: значение «{value}» отсутствует в справочнике"
            )
        return value

    def add_category(self, name: str, description: str = "") -> int:
        self._require_write()
        name = self._required(name, "категория")
        try:
            with connect(self.db_path) as db:
                cursor = db.execute(
                    "INSERT INTO categories(name, description) VALUES (?, ?)",
                    (name, description.strip()),
                )
                return int(cursor.lastrowid)
        except sqlite3.IntegrityError as error:
            raise WarehouseError(f"Категория «{name}» уже существует") from error

    def add_location(self, code: str, name: str, description: str = "") -> int:
        self._require_write()
        code = self._required(code, "код места").upper()
        name = self._required(name, "название места")
        try:
            with connect(self.db_path) as db:
                cursor = db.execute(
                    "INSERT INTO locations(code, name, description) VALUES (?, ?, ?)",
                    (code, name, description.strip()),
                )
                return int(cursor.lastrowid)
        except sqlite3.IntegrityError as error:
            raise WarehouseError(f"Место хранения «{code}» уже существует") from error

    def _lookup_id(self, db: sqlite3.Connection, table: str, field: str, value: str) -> int:
        row = db.execute(
            f"SELECT id FROM {table} WHERE {field} = ? COLLATE NOCASE", (value.strip(),)
        ).fetchone()
        if row is None:
            raise WarehouseError(f"Не найдено значение «{value}» в справочнике {table}")
        return int(row["id"])

    @staticmethod
    def _sync_legacy_stock_receipt(db: sqlite3.Connection, equipment_id: int) -> None:
        """Синхронизировать старые CLI-операции с начальной позицией новой модели."""
        db.execute(
            """INSERT OR IGNORE INTO stock_receipts(
                   receipt_date, responsible, item_name, serial_number, inventory_number,
                   supplier, vendor, model, shelf, object_name, datacenter,
                   equipment_type, component_type, cable_type, unit, quantity, legacy_equipment_id,
                   is_opening_balance
               )
               SELECT substr(e.created_at, 1, 10), 'Совместимый режим', e.model,
                      e.serial_number, e.inventory_number, 'Не указан', 'Не указан',
                      e.model, COALESCE(l.code, ''), 'Не указано', e.datacenter,
                      CASE WHEN c.name <> 'Комплектующие' AND c.name NOT LIKE 'Провода — %'
                           THEN c.name ELSE '' END,
                      CASE WHEN c.name = 'Комплектующие' THEN c.name ELSE '' END,
                      CASE WHEN c.name = 'Провода — оптика' THEN 'Оптика'
                           WHEN c.name = 'Провода — медь' THEN 'Медь' ELSE '' END,
                      CASE WHEN c.name LIKE 'Провода — %' THEN 'м' ELSE 'шт' END,
                      e.quantity, e.id, 1
               FROM equipment e JOIN categories c ON c.id = e.category_id
               LEFT JOIN locations l ON l.id = e.location_id
               WHERE e.id = ? AND e.quantity > 0""",
            (equipment_id,),
        )
        db.execute(
            """DELETE FROM stock_receipts
               WHERE legacy_equipment_id = ?
                 AND (SELECT quantity FROM equipment WHERE id = ?) = 0
                 AND NOT EXISTS (
                     SELECT 1 FROM stock_issue_allocations a
                     WHERE a.receipt_id = stock_receipts.id
                 )""",
            (equipment_id, equipment_id),
        )
        db.execute(
            """UPDATE stock_receipts
               SET quantity = (SELECT quantity FROM equipment WHERE id = ?),
                   datacenter = COALESCE((
                       SELECT datacenter FROM equipment WHERE id = ?
                   ), datacenter),
                   shelf = COALESCE((
                       SELECT l.code FROM equipment e
                       LEFT JOIN locations l ON l.id = e.location_id WHERE e.id = ?
                   ), shelf)
               WHERE legacy_equipment_id = ?""",
            (equipment_id, equipment_id, equipment_id, equipment_id),
        )

    def add_equipment(
        self,
        category: str,
        model: str,
        serial_number: str,
        inventory_number: str,
        location_code: str,
        quantity: int = 0,
        basis: str = "Карточка оборудования",
        responsible: str = "Кладовщик № 1",
        notes: str = "",
        datacenter: str = "Ixcellerate",
    ) -> int:
        self._require_write()
        if quantity < 0:
            raise WarehouseError("Количество не может быть отрицательным")
        model = self._required(model, "модель")
        serial_number = self._required(serial_number, "серийный номер").upper()
        inventory_number = self._required(inventory_number, "инвентарный номер").upper()
        basis = self._required(basis, "основание")
        responsible = self._required(responsible, "ответственный")
        datacenter = self._required(datacenter, "ЦОД")
        try:
            with connect(self.db_path) as db:
                category_id = self._lookup_id(db, "categories", "name", category)
                location_id = self._lookup_id(db, "locations", "code", location_code)
                cursor = db.execute(
                    """INSERT INTO equipment(
                           category_id, model, serial_number, inventory_number,
                           status, location_id, quantity, notes, datacenter
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        category_id, model, serial_number, inventory_number,
                        "IN_STOCK" if quantity > 0 else "ISSUED",
                        location_id, quantity, notes.strip(), datacenter,
                    ),
                )
                equipment_id = int(cursor.lastrowid)
                db.execute(
                    """INSERT INTO operations(
                           operation_type, equipment_id, quantity, basis, responsible,
                           to_location_id, comment
                       ) VALUES ('ADD', ?, 1, ?, ?, ?, ?)""",
                    (equipment_id, basis, responsible, location_id, "Создание карточки"),
                )
                if quantity:
                    db.execute(
                        """INSERT INTO operations(
                               operation_type, equipment_id, quantity, basis, responsible,
                               to_location_id, comment
                           ) VALUES ('RECEIPT', ?, ?, ?, ?, ?, ?)""",
                        (equipment_id, quantity, basis, responsible, location_id, "Начальный приход"),
                    )
                self._sync_legacy_stock_receipt(db, equipment_id)
                self._audit(
                    db, "CREATE", "legacy_equipment", equipment_id,
                    {"serial_number": serial_number, "quantity": quantity},
                )
                return equipment_id
        except sqlite3.IntegrityError as error:
            raise WarehouseError("Серийный или инвентарный номер уже используется") from error

    def receipt(self, equipment_id: int, quantity: int, basis: str, responsible: str) -> None:
        self._require_write()
        self._change_quantity(equipment_id, quantity, basis, responsible, "RECEIPT")

    def issue(self, equipment_id: int, quantity: int, basis: str, responsible: str) -> None:
        self._require_write()
        self._change_quantity(equipment_id, quantity, basis, responsible, "ISSUE")

    def _change_quantity(
        self, equipment_id: int, quantity: int, basis: str, responsible: str, operation: str
    ) -> None:
        if quantity <= 0:
            raise WarehouseError("Количество должно быть больше нуля")
        basis = self._required(basis, "основание")
        responsible = self._required(responsible, "ответственный")
        with connect(self.db_path) as db:
            item = db.execute(
                "SELECT quantity, location_id, status FROM equipment WHERE id = ?", (equipment_id,)
            ).fetchone()
            if item is None:
                raise WarehouseError(f"Оборудование с ID {equipment_id} не найдено")
            current = int(item["quantity"])
            available_current = current
            if operation == "ISSUE":
                legacy = db.execute(
                    """SELECT r.quantity - COALESCE(SUM(a.quantity), 0) AS available
                       FROM stock_receipts r
                       LEFT JOIN stock_issue_allocations a ON a.receipt_id = r.id
                       WHERE r.legacy_equipment_id = ? GROUP BY r.id""",
                    (equipment_id,),
                ).fetchone()
                if legacy is not None:
                    available_current = min(current, int(float(legacy["available"])))
            if operation == "ISSUE" and quantity > available_current:
                raise WarehouseError(
                    f"Недостаточный остаток: доступно {available_current}, запрошено {quantity}"
                )
            new_quantity = current + quantity if operation == "RECEIPT" else current - quantity
            new_status = "IN_STOCK" if new_quantity > 0 else "ISSUED"
            db.execute(
                "UPDATE equipment SET quantity = ?, status = ? WHERE id = ?",
                (new_quantity, new_status, equipment_id),
            )
            from_location = item["location_id"] if operation == "ISSUE" else None
            to_location = item["location_id"] if operation == "RECEIPT" else None
            db.execute(
                """INSERT INTO operations(
                       operation_type, equipment_id, quantity, basis, responsible,
                       from_location_id, to_location_id
                   ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (operation, equipment_id, quantity, basis, responsible, from_location, to_location),
            )
            self._sync_legacy_stock_receipt(db, equipment_id)
            self._audit(
                db, operation, "legacy_equipment", equipment_id,
                {"quantity": quantity, "basis": basis, "responsible": responsible},
            )

    def move(
        self, equipment_id: int, destination_code: str, basis: str, responsible: str
    ) -> None:
        self._require_write()
        basis = self._required(basis, "основание")
        responsible = self._required(responsible, "ответственный")
        with connect(self.db_path) as db:
            item = db.execute(
                "SELECT quantity, location_id FROM equipment WHERE id = ?", (equipment_id,)
            ).fetchone()
            if item is None:
                raise WarehouseError(f"Оборудование с ID {equipment_id} не найдено")
            destination_id = self._lookup_id(db, "locations", "code", destination_code)
            if item["location_id"] == destination_id:
                raise WarehouseError("Оборудование уже находится в указанном месте")
            db.execute(
                "UPDATE equipment SET location_id = ? WHERE id = ?",
                (destination_id, equipment_id),
            )
            db.execute(
                """INSERT INTO operations(
                       operation_type, equipment_id, quantity, basis, responsible,
                       from_location_id, to_location_id
                   ) VALUES ('MOVE', ?, ?, ?, ?, ?, ?)""",
                (
                    equipment_id, max(1, int(item["quantity"])), basis, responsible,
                    item["location_id"], destination_id,
                ),
            )
            self._sync_legacy_stock_receipt(db, equipment_id)
            self._audit(
                db, "MOVE", "legacy_equipment", equipment_id,
                {"destination": destination_code, "basis": basis},
            )

    def equipment(self, query: str = "", category: str = "", status: str = "", location: str = "") -> list[dict[str, Any]]:
        sql = """SELECT e.id, c.name AS category, e.model, e.serial_number,
                        e.inventory_number, e.datacenter, e.status,
                        l.code AS location, e.quantity
                 FROM equipment e
                 JOIN categories c ON c.id = e.category_id
                 LEFT JOIN locations l ON l.id = e.location_id
                 WHERE 1 = 1"""
        params: list[Any] = []
        if query:
            sql += " AND (e.model LIKE ? OR e.serial_number LIKE ? OR e.inventory_number LIKE ?)"
            term = f"%{query}%"
            params.extend((term, term, term))
        if category:
            sql += " AND c.name = ? COLLATE NOCASE"
            params.append(category)
        if status:
            sql += " AND e.status = ? COLLATE NOCASE"
            params.append(status)
        if location:
            sql += " AND l.code = ? COLLATE NOCASE"
            params.append(location)
        sql += " ORDER BY c.name, e.model, e.id"
        with connect(self.db_path) as db:
            return [dict(row) for row in db.execute(sql, params).fetchall()]

    def import_operation_rows(
        self, rows: Iterable[dict[str, Any]], operation_type: str
    ) -> int:
        """Атомарно импортировать большой CSV прихода или расхода."""
        self._require_write()
        if operation_type not in {"RECEIPT", "ISSUE"}:
            raise WarehouseError("Поддерживается импорт только прихода или расхода")

        prepared: list[dict[str, Any]] = []
        for line_number, source in enumerate(rows, start=2):
            if not any(str(value or "").strip() for value in source.values()):
                continue
            try:
                quantity = int(str(source.get("quantity", "")).strip())
            except ValueError as error:
                raise WarehouseError(
                    f"Строка {line_number}: количество должно быть целым числом"
                ) from error
            if quantity <= 0:
                raise WarehouseError(f"Строка {line_number}: количество должно быть больше нуля")
            prepared.append({
                "line": line_number,
                "inventory_number": self._required(
                    str(source.get("inventory_number", "")), "инвентарный номер"
                ).upper(),
                "quantity": quantity,
                "basis": self._required(str(source.get("basis", "")), "основание"),
                "responsible": self._required(
                    str(source.get("responsible", "")), "ответственный"
                ),
            })
        if not prepared:
            raise WarehouseError("В CSV-файле нет строк операций")

        with connect(self.db_path) as db:
            items = {
                str(row["inventory_number"]).upper(): {
                    "id": int(row["id"]),
                    "quantity": int(row["quantity"]),
                    "location_id": row["location_id"],
                }
                for row in db.execute(
                    "SELECT id, inventory_number, quantity, location_id FROM equipment"
                )
            }
            operation_values: list[tuple[Any, ...]] = []
            changed: dict[int, int] = {}
            for row in prepared:
                item = items.get(row["inventory_number"])
                if item is None:
                    raise WarehouseError(
                        f"Строка {row['line']}: позиция «{row['inventory_number']}» не найдена"
                    )
                current = int(item["quantity"])
                if operation_type == "ISSUE" and row["quantity"] > current:
                    raise WarehouseError(
                        f"Строка {row['line']}: недостаточный остаток для "
                        f"«{row['inventory_number']}»: доступно {current}"
                    )
                new_quantity = (
                    current + row["quantity"]
                    if operation_type == "RECEIPT"
                    else current - row["quantity"]
                )
                item["quantity"] = new_quantity
                changed[int(item["id"])] = new_quantity
                from_location = item["location_id"] if operation_type == "ISSUE" else None
                to_location = item["location_id"] if operation_type == "RECEIPT" else None
                operation_values.append((
                    operation_type, item["id"], row["quantity"], row["basis"],
                    row["responsible"], from_location, to_location, "Импорт из CSV",
                ))

            db.executemany(
                "UPDATE equipment SET quantity = ?, status = ? WHERE id = ?",
                [
                    (quantity, "IN_STOCK" if quantity > 0 else "ISSUED", equipment_id)
                    for equipment_id, quantity in changed.items()
                ],
            )
            db.executemany(
                """INSERT INTO operations(
                       operation_type, equipment_id, quantity, basis, responsible,
                       from_location_id, to_location_id, comment
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                operation_values,
            )
        return len(prepared)

    def import_equipment_rows(self, rows: Iterable[dict[str, Any]]) -> int:
        """Атомарно импортировать карточки оборудования из подготовленных строк CSV."""
        self._require_write()
        prepared: list[dict[str, Any]] = []
        for line_number, source in enumerate(rows, start=2):
            if not any(str(value or "").strip() for value in source.values()):
                continue
            try:
                quantity = int(str(source.get("quantity", "")).strip() or "0")
            except ValueError as error:
                raise WarehouseError(
                    f"Строка {line_number}: количество должно быть целым числом"
                ) from error
            if quantity < 0:
                raise WarehouseError(f"Строка {line_number}: количество не может быть отрицательным")
            prepared.append({
                "line": line_number,
                "category": self._required(str(source.get("category", "")), "категория"),
                "model": self._required(str(source.get("model", "")), "модель"),
                "serial_number": self._required(
                    str(source.get("serial_number", "")), "серийный номер"
                ).upper(),
                "inventory_number": self._required(
                    str(source.get("inventory_number", "")), "инвентарный номер"
                ).upper(),
                "location": self._required(str(source.get("location", "")), "место").upper(),
                "quantity": quantity,
                "notes": str(source.get("notes", "")).strip(),
                "datacenter": str(source.get("datacenter", "")).strip() or "Ixcellerate",
            })
        if not prepared:
            raise WarehouseError("В CSV-файле нет строк с оборудованием")

        serials = [row["serial_number"] for row in prepared]
        inventories = [row["inventory_number"] for row in prepared]
        if len(serials) != len(set(serials)):
            raise WarehouseError("В CSV-файле повторяется серийный номер")
        if len(inventories) != len(set(inventories)):
            raise WarehouseError("В CSV-файле повторяется инвентарный номер")

        with connect(self.db_path) as db:
            categories = {
                str(row["name"]).casefold(): int(row["id"])
                for row in db.execute("SELECT id, name FROM categories")
            }
            locations = {
                str(row["code"]).upper(): int(row["id"])
                for row in db.execute("SELECT id, code FROM locations")
            }
            existing_serials = {
                str(row[0]).upper() for row in db.execute("SELECT serial_number FROM equipment")
            }
            existing_inventories = {
                str(row[0]).upper() for row in db.execute("SELECT inventory_number FROM equipment")
            }
            for row in prepared:
                line = row["line"]
                if row["category"].casefold() not in categories:
                    raise WarehouseError(
                        f"Строка {line}: категория «{row['category']}» не найдена"
                    )
                if row["location"] not in locations:
                    raise WarehouseError(f"Строка {line}: место «{row['location']}» не найдено")
                if row["serial_number"] in existing_serials:
                    raise WarehouseError(
                        f"Строка {line}: серийный номер «{row['serial_number']}» уже существует"
                    )
                if row["inventory_number"] in existing_inventories:
                    raise WarehouseError(
                        f"Строка {line}: инвентарный номер «{row['inventory_number']}» уже существует"
                    )

            for row in prepared:
                category_id = categories[row["category"].casefold()]
                location_id = locations[row["location"]]
                cursor = db.execute(
                    """INSERT INTO equipment(
                           category_id, model, serial_number, inventory_number,
                           status, location_id, quantity, notes, datacenter
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        category_id, row["model"], row["serial_number"],
                        row["inventory_number"],
                        "IN_STOCK" if row["quantity"] > 0 else "ISSUED",
                        location_id, row["quantity"], row["notes"], row["datacenter"],
                    ),
                )
                equipment_id = int(cursor.lastrowid)
                db.execute(
                    """INSERT INTO operations(
                           operation_type, equipment_id, quantity, basis, responsible,
                           to_location_id, comment
                       ) VALUES ('ADD', ?, 1, 'Импорт CSV', 'Импорт из файла', ?,
                                 'Создание карточки из CSV')""",
                    (equipment_id, location_id),
                )
                if row["quantity"]:
                    db.execute(
                        """INSERT INTO operations(
                               operation_type, equipment_id, quantity, basis, responsible,
                               to_location_id, comment
                           ) VALUES ('RECEIPT', ?, ?, 'Импорт CSV', 'Импорт из файла', ?,
                                     'Начальный приход из CSV')""",
                        (equipment_id, row["quantity"], location_id),
                    )
        return len(prepared)

    def reference_data(self, table: str) -> list[dict[str, Any]]:
        if table not in {"categories", "locations"}:
            raise WarehouseError("Неизвестный справочник")
        order = "name" if table == "categories" else "code"
        with connect(self.db_path) as db:
            return [dict(row) for row in db.execute(f"SELECT * FROM {table} ORDER BY {order}")]

    def export_csv(self, output_dir: str | Path) -> tuple[Path, Path]:
        directory = Path(output_dir)
        directory.mkdir(parents=True, exist_ok=True)
        stock_path = directory / "equipment_stock.csv"
        operations_path = directory / "operation_log.csv"
        self._write_csv(stock_path, self.equipment())
        self._write_csv(operations_path, self.operation_log(limit=None))
        return stock_path, operations_path

    @staticmethod
    def _write_csv(path: Path, rows: Iterable[dict[str, Any]]) -> None:
        rows = list(rows)
        with path.open("w", encoding="utf-8-sig", newline="") as file:
            if not rows:
                file.write("")
                return
            writer = csv.DictWriter(file, fieldnames=list(rows[0].keys()), delimiter=",")
            writer.writeheader()
            writer.writerows(rows)
