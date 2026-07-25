"""Core implementation used by backend service modules during refactoring."""

from __future__ import annotations

import csv
import json
import re
import secrets
import sqlite3
import threading
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

from ..administration.service import AdministrationService
from ..administration.diagnostics import AdministrationDiagnosticsService
from ..db import DEFAULT_DB_PATH, connect, initialize
from ..importing import PREVIEW_ERROR_LIMIT, PREVIEW_ROW_LIMIT
from ..shared.helpers import STRICT_REFERENCES, WarehouseError
from ..warehouse.references import ReferenceDataService
from ..warehouse.classification import (
    canonical_vendor,
    classify_card,
    infer_vendor,
    operational_category,
)
from ..warehouse.issue_repository import IssueRepository


class WarehouseCore:
    DELIVERY_STATUSES = ("Загружена", "Ожидается", "Частично принята", "Принята", "Закрыта")
    DELIVERY_EDITABLE_FIELDS = {
        "item_name", "model", "vendor", "supplier", "project", "datacenter", "shelf",
        "object_name", "equipment_type", "component_type", "cable_type", "unit", "quantity",
    }
    STRICT_REFERENCE_VALIDATION = STRICT_REFERENCES
    STRICT_REFERENCES = STRICT_REFERENCES
    ROLES = ("admin", "engineer", "viewer")
    STATUSES = ("IN_STOCK", "ISSUED", "RESERVED", "MAINTENANCE", "WRITTEN_OFF")
    TASK_SOURCES = ("Rooms", "Outlook", "ITSM", "Zabbix", "DCIM", "Склад", "Другое")
    TASK_TYPES = ("ЗНР", "ПНР", "ИЗМ", "ЗНО", "ИНЦ", "Другое")
    WORK_LOG_STATUSES = ("Выполнено", "В работе", "Ожидание", "Отложено")
    REFERENCE_KINDS = {
        "item_name": "Наименования позиций",
        "model": "Модели",
        "supplier": "Поставщики",
        "vendor": "Вендоры",
        "shelf": "Стеллажи/полки",
        "object": "Объекты",
        "datacenter": "ЦОД",
        "project": "Проекты",
        "equipment_type": "Типы оборудования",
        "component_type": "Типы компонентов",
        "cable_type": "Типы кабеля",
        "unit": "Единицы учета",
        "task_source": "Источники задач",
        "task_type": "Типы задач",
        "work_log_status": "Статусы логов",
        "work_log_section": "Разделы работ (УВР)",
    }
    RECEIPT_REFERENCE_FIELDS = {
        "item_name": "item_name", "model": "model", "shelf": "shelf",
        "project": "project", "supplier": "supplier", "vendor": "vendor",
        "object_name": "object", "datacenter": "datacenter",
        "equipment_type": "equipment_type", "component_type": "component_type",
        "cable_type": "cable_type", "unit": "unit",
    }
    ISSUE_REFERENCE_FIELDS = {
        "source_item_name": "item_name", "source_cable_type": "cable_type",
    }
    KEY_TABLES = {
        "categories", "locations", "equipment", "operations", "work_logs",
        "reference_values", "stock_receipts", "stock_issues",
        "stock_issue_allocations", "audit_log", "users",
        "daily_report_uploads", "daily_report_rows",
        "deliveries", "delivery_lines",
    }
    RESTORE_BASE_TABLES = {"categories", "locations", "equipment", "operations"}

    def __init__(
        self,
        db_path: str | Path = DEFAULT_DB_PATH,
        *,
        strict_reference_validation: bool = STRICT_REFERENCE_VALIDATION,
        initialize_database: bool = True,
    ):
        self.db_path = Path(db_path)
        self.strict_reference_validation = strict_reference_validation
        self.lock = threading.RLock()
        # Preview хранится только в памяти процесса: просмотр не создает строк в БД
        # и автоматически исчезает после перезапуска сервиса.
        self._import_previews: dict[str, dict[str, Any]] = {}
        self._last_import_rows: dict[tuple[str, str], list[dict[str, Any]]] = {}
        if initialize_database:
            self.default_admin_created = initialize(self.db_path)
        else:
            if not self.db_path.is_file():
                raise FileNotFoundError(self.db_path)
            self.default_admin_created = False
        self.administration = AdministrationService(
            self.db_path,
            lock=self.lock,
            key_tables=self.KEY_TABLES,
            restore_base_tables=self.RESTORE_BASE_TABLES,
        )
        # DEPRECATED: actor fields remain aliases until all warehouse/report
        # collaborators consume the Administration boundary directly.
        self._actor_email = self.administration._actor_email
        self._actor_name = self.administration._actor_name
        self._actor_role_override = self.administration._actor_role_override
        # Attached by WarehouseService after the independent Reports boundary
        # and WarehouseEventReader have been composed.
        self.reports: Any | None = None
        # Bootstrap credentials are documented for the local compatibility
        # runtime, but must never be echoed into application or CI logs.
        self.reference_catalog = ReferenceDataService(self)

    @staticmethod
    def _public_user(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        # DEPRECATED: use AdministrationService._public_user.
        return AdministrationService._public_user(row)

    @staticmethod
    def _operational_category(
        equipment_type: Any, component_type: Any, cable_type: Any
    ) -> str:
        return operational_category(equipment_type, component_type, cable_type)

    def authenticate(
        self, email: str, password: str, *, record_login: bool = True
    ) -> dict[str, Any]:
        # DEPRECATED: use ApplicationContext.administration.authenticate.
        return self.administration.authenticate(
            email, password, record_login=record_login
        )

    def user_by_email(self, email: str) -> dict[str, Any]:
        # DEPRECATED: use ApplicationContext.administration.get_user.
        return self.administration.user_by_email(email)

    def current_user(self) -> dict[str, Any]:
        # DEPRECATED: use ApplicationContext.administration.current_user.
        return self.administration.current_user()

    @contextmanager
    def user_context(
        self,
        email: str,
        *,
        author_name: str | None = None,
        role_override: str | None = None,
    ) -> Iterable[dict[str, Any]]:
        # DEPRECATED: use ApplicationContext.administration.user_context.
        with self.administration.user_context(
            email,
            author_name=author_name,
            role_override=role_override,
        ) as user:
            yield user

    def _require_role(self, *roles: str) -> dict[str, Any]:
        # DEPRECATED: warehouse collaborators still use the shared actor policy.
        return self.administration._require_role(*roles)

    def _require_write(self) -> dict[str, Any]:
        # DEPRECATED: warehouse collaborators still use the shared actor policy.
        return self.administration._require_write()

    def users(self) -> list[dict[str, Any]]:
        # DEPRECATED: use ApplicationContext.administration.list_users.
        return self.administration.users()

    def create_user(
        self, first_name: str, last_name: str, position: str,
        email: str, password: str, role: str,
    ) -> int:
        # DEPRECATED: use ApplicationContext.administration.create_user.
        return self.administration.create_user(
            first_name, last_name, position, email, password, role
        )

    def change_password(self, old_password: str, new_password: str) -> None:
        # DEPRECATED: use ApplicationContext.administration.change_password.
        self.administration.change_password(old_password, new_password)

    def update_profile(self, first_name: str, last_name: str, position: str) -> dict[str, Any]:
        # DEPRECATED: use ApplicationContext.administration.update_profile.
        return self.administration.update_profile(first_name, last_name, position)

    def _audit(
        self,
        db: sqlite3.Connection,
        action: str,
        entity_type: str,
        entity_id: int | str | None = None,
        details: dict[str, Any] | str | None = None,
    ) -> None:
        # DEPRECATED: shared write adapter delegates to Administration ownership.
        self.administration._audit(db, action, entity_type, entity_id, details)

    def audit_entries(self, limit: int = 200) -> list[dict[str, Any]]:
        # DEPRECATED: use ApplicationContext.administration.list_audit_entries.
        return self.administration.audit_entries(limit)

    def warehouse_history(self, limit: int = 300) -> list[dict[str, Any]]:
        """Человекочитаемая история склада без раскрытия внутренних имён таблиц."""
        labels = {
            "RECEIPT_CREATE": "Ручной приход", "RECEIPT_IMPORT": "Приход из файла",
            "ISSUE_CREATE": "Ручной расход", "ISSUE_IMPORT": "Расход из файла",
            "DELIVERY_UPLOAD": "Загружена поставка", "DELIVERY_ACCEPT": "Принято из поставки",
            "DELIVERY_LINE_UPDATE": "Изменены данные поставки", "DELIVERY_CLOSE": "Закрыта поставка",
        }
        rows: list[dict[str, Any]] = []
        with connect(self.db_path) as db:
            for row in db.execute("""SELECT id history_id,NULLIF(trim(receipt_date),'') event_date,responsible engineer,
                    CASE WHEN is_opening_balance=1 OR trim(COALESCE(responsible,''))='Историческая миграция'
                         THEN 'Начальный остаток' ELSE 'Приход' END action,
                    serial_number,inventory_number,item_name,quantity,'' comment,
                    CASE WHEN is_opening_balance=1 OR trim(COALESCE(responsible,''))='Историческая миграция' THEN 1 ELSE 0 END is_opening_balance
                    FROM stock_receipts
                    ORDER BY CASE WHEN is_opening_balance=1 OR trim(COALESCE(responsible,''))='Историческая миграция' THEN 1 ELSE 0 END ASC,
                             NULLIF(trim(receipt_date),'') DESC,id DESC LIMIT ?""", (limit,)):
                item = dict(row)
                item["_history_source"] = "receipt"
                rows.append(item)
            for row in db.execute("SELECT id history_id,NULLIF(trim(issue_date),'') event_date,responsible engineer,'Расход' action,source_serial_number serial_number,'' inventory_number,source_item_name item_name,quantity,comment,0 is_opening_balance FROM stock_issues ORDER BY NULLIF(trim(issue_date),'') DESC,id DESC LIMIT ?", (limit,)):
                item = dict(row)
                item["_history_source"] = "issue"
                rows.append(item)
            for row in db.execute("""SELECT o.id history_id,o.operation_date event_date,
                    o.responsible engineer,'Перемещение' action,
                    e.serial_number,e.inventory_number,e.model item_name,o.quantity,
                    trim(o.basis || CASE WHEN src.code IS NOT NULL OR dst.code IS NOT NULL
                        THEN '; ' || COALESCE(src.code,'') || ' -> ' || COALESCE(dst.code,'')
                        ELSE '' END) comment,0 is_opening_balance
                    FROM operations o JOIN equipment e ON e.id=o.equipment_id
                    LEFT JOIN locations src ON src.id=o.from_location_id
                    LEFT JOIN locations dst ON dst.id=o.to_location_id
                    WHERE o.operation_type='MOVE'
                    ORDER BY o.operation_date DESC,o.id DESC LIMIT ?""", (limit,)):
                item = dict(row)
                item["_history_source"] = "movement"
                rows.append(item)
            for row in db.execute("SELECT id history_id,event_date,author engineer,action,details,entity_id FROM audit_log WHERE action LIKE 'DELIVERY_%' OR action IN ('RECEIPT_IMPORT','ISSUE_IMPORT') ORDER BY event_date DESC,id DESC LIMIT ?", (limit,)):
                details = json.loads(row["details"] or "{}") if str(row["details"] or "").startswith("{") else {}
                rows.append({"event_date": row["event_date"], "engineer": row["engineer"],
                    "action": labels.get(row["action"], "Изменение склада"),
                    "serial_number": details.get("serial_number", ""),
                    "inventory_number": details.get("inventory_number", ""),
                    "entity_id": row["entity_id"],
                    "item_name": details.get("item_name", ""), "quantity": details.get("quantity", ""),
                    "comment": details.get("filename", "") or details.get("reason", ""),
                    "is_opening_balance": 0, "history_id": row["history_id"],
                    "_history_source": "audit"})

        def sort_key(item: dict[str, Any]) -> tuple[datetime, int, str]:
            raw_date = str(item.get("event_date") or "").strip()
            try:
                event_time = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
                if event_time.tzinfo is not None:
                    event_time = event_time.replace(tzinfo=None)
            except ValueError:
                event_time = datetime.min
            return (
                event_time,
                int(item.get("history_id") or 0),
                str(item.get("_history_source") or ""),
            )

        rows.sort(key=sort_key, reverse=True)
        result = rows[:limit]
        for item in result:
            item.pop("history_id", None)
            item.pop("_history_source", None)
        return result

    @property
    def backup_dir(self) -> Path:
        # DEPRECATED: use ApplicationContext.administration.backup_dir.
        return self.administration.backup_dir

    def list_backups(self) -> list[dict[str, Any]]:
        # DEPRECATED: use ApplicationContext.administration.list_backups.
        return self.administration.list_backups()

    def _next_backup_path(self, prefix: str) -> Path:
        # DEPRECATED: Administration owns backup naming.
        return self.administration._next_backup_path(prefix)

    @staticmethod
    def _database_check(path: Path, required_tables: set[str]) -> dict[str, Any]:
        # DEPRECATED: Administration owns database diagnostics.
        return AdministrationDiagnosticsService.database_check(path, required_tables)

    def check_integrity(self) -> dict[str, Any]:
        # DEPRECATED: use ApplicationContext.administration.integrity_check.
        return self.administration.check_integrity()

    def create_backup(self, prefix: str = "warehouse") -> dict[str, Any]:
        # DEPRECATED: use ApplicationContext.administration.create_backup.
        return self.administration.create_backup(prefix)

    def _backup_by_name(self, filename: str) -> Path:
        # DEPRECATED: Administration owns backup resolution.
        return self.administration._backup_by_name(filename)

    def restore_backup(self, filename: str, confirmed: bool = False) -> dict[str, Any]:
        # DEPRECATED: use ApplicationContext.administration.restore_backup.
        return self.administration.restore_backup(filename, confirmed)

    def replace_production_database(
        self, uploaded_path: str | Path, confirmed: bool = False,
    ) -> dict[str, Any]:
        # DEPRECATED: use ApplicationContext.administration.replace_production_database.
        return self.administration.replace_production_database(
            uploaded_path, confirmed
        )

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

    def dashboard_stats(self) -> dict[str, int | float]:
        """Вернуть показатели, рассчитанные только по новой складской модели."""
        with connect(self.db_path) as db:
            row = db.execute(
                """WITH lots AS (
                       SELECT r.project, r.item_name, r.vendor, r.model,
                              r.serial_number, r.inventory_number, r.unit,
                              r.object_name, r.equipment_type, r.component_type,
                              r.cable_type, r.datacenter,
                              r.quantity - COALESCE(SUM(a.quantity), 0) AS balance
                       FROM stock_receipts r
                       LEFT JOIN stock_issue_allocations a ON a.receipt_id = r.id
                       GROUP BY r.id
                   ), positions AS (
                       SELECT cable_type, SUM(balance) AS balance
                       FROM lots
                       GROUP BY project, item_name, vendor, model, serial_number,
                                inventory_number, unit, object_name, equipment_type,
                                component_type, cable_type, datacenter
                   )
                   SELECT
                       COALESCE((SELECT SUM(quantity) FROM stock_receipts), 0) AS receipts,
                       COALESCE((SELECT SUM(quantity) FROM stock_issues), 0) AS issues,
                       (SELECT COUNT(*) FROM stock_receipts) AS cards,
                       (SELECT COUNT(DISTINCT trim(supplier)) FROM stock_receipts
                         WHERE trim(supplier) <> '') AS suppliers,
                       (SELECT COUNT(DISTINCT CASE
                            WHEN trim(equipment_type) <> '' THEN 'equipment:' || trim(equipment_type)
                            WHEN trim(component_type) <> '' THEN 'component:' || trim(component_type)
                            WHEN trim(cable_type) <> '' THEN 'cable:' || trim(cable_type)
                            ELSE 'other'
                        END) FROM stock_receipts) AS categories,
                       COALESCE((SELECT SUM(quantity) FROM stock_receipts), 0)
                         - COALESCE((SELECT SUM(quantity) FROM stock_issue_allocations), 0)
                         AS balance,
                       COALESCE((SELECT SUM(quantity) FROM stock_receipts
                                 WHERE receipt_date = date('now', 'localtime')), 0)
                         AS received_today,
                       COALESCE((SELECT SUM(a.quantity)
                                 FROM stock_issue_allocations a
                                 JOIN stock_issues i ON i.id = a.issue_id
                                 WHERE i.issue_date = date('now', 'localtime')), 0)
                         AS issued_today,
                       (SELECT COUNT(*) FROM deliveries) AS deliveries,
                       (SELECT COUNT(*) FROM positions WHERE balance > 0.0000001) AS positions,
                       COALESCE((SELECT SUM(balance) FROM positions
                                 WHERE balance > 0.0000001 AND cable_type = ''), 0)
                         AS equipment,
                       COALESCE((SELECT SUM(balance) FROM positions
                                 WHERE balance > 0.0000001 AND cable_type <> ''), 0)
                         AS cables
                """
            ).fetchone()
        return {
            "receipts": float(row["receipts"]),
            "issues": float(row["issues"]),
            "cards": int(row["cards"]),
            "suppliers": int(row["suppliers"]),
            "categories": int(row["categories"]),
            "balance": float(row["balance"]),
            "positions": int(row["positions"]),
            "equipment": float(row["equipment"]),
            "cables": float(row["cables"]),
            "received_today": float(row["received_today"]),
            "issued_today": float(row["issued_today"]),
            "deliveries": int(row["deliveries"]),
        }

    def operation_log(self, operation_type: str = "", limit: int | None = 100) -> list[dict[str, Any]]:
        sql = """SELECT o.id, o.operation_date, o.operation_type, o.equipment_id,
                        e.inventory_number, e.model, o.quantity, o.basis, o.responsible,
                        src.code AS from_location, dst.code AS to_location
                 FROM operations o
                 JOIN equipment e ON e.id = o.equipment_id
                 LEFT JOIN locations src ON src.id = o.from_location_id
                 LEFT JOIN locations dst ON dst.id = o.to_location_id"""
        params: list[Any] = []
        if operation_type:
            sql += " WHERE o.operation_type = ? COLLATE NOCASE"
            params.append(operation_type)
        sql += " ORDER BY o.operation_date DESC, o.id DESC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        with connect(self.db_path) as db:
            return [dict(row) for row in db.execute(sql, params).fetchall()]

    def balance_by_category(self) -> list[dict[str, Any]]:
        """Вернуть остатки, сгруппированные по категории и ЦОД."""
        with connect(self.db_path) as db:
            rows = db.execute(
                """SELECT c.name AS category, e.datacenter,
                          COUNT(*) AS positions, COALESCE(SUM(e.quantity), 0) AS quantity
                   FROM equipment e
                   JOIN categories c ON c.id = e.category_id
                   GROUP BY c.name, e.datacenter
                   ORDER BY c.name, e.datacenter"""
            ).fetchall()
            return [dict(row) for row in rows]

    def references(self, kind: str = "", active_only: bool = False) -> list[dict[str, Any]]:
        """Return form-safe canonical values from the existing Reference layer."""
        return self.reference_catalog.form_references(kind, active_only=active_only)

    def reference_groups(self) -> list[dict[str, Any]]:
        """Вернуть значения готовыми группами в порядке экранных справочников."""
        rows = self.references()
        return [
            {
                "kind": kind,
                "label": label,
                "values": [row for row in rows if row["kind"] == kind],
            }
            for kind, label in self.REFERENCE_KINDS.items()
        ]

    def add_reference(self, kind: str, name: str) -> int:
        with connect(self.db_path) as db:
            has_v2 = self.reference_catalog.has_v2(db)
        if not has_v2:
            self._require_write()
            if kind not in self.REFERENCE_KINDS:
                raise WarehouseError("Неизвестный справочник")
            name = self._required(name, "значение справочника")
            try:
                with connect(self.db_path) as db:
                    cursor = db.execute(
                        "INSERT INTO reference_values(kind,name) VALUES (?,?)", (kind, name)
                    )
                    reference_id = int(cursor.lastrowid)
                    self._audit(db, "REFERENCE_CREATE", "reference_value", reference_id,
                                {"kind": kind, "name": name})
                    return reference_id
            except sqlite3.IntegrityError as error:
                raise WarehouseError(f"Значение «{name}» уже существует") from error
        domain = self.reference_catalog._domain_for_kind(kind)
        if not domain:
            raise WarehouseError("Неизвестный canonical справочник")
        return self.reference_catalog.add_proposal(domain, name)

    def set_reference_active(self, reference_id: int, is_active: bool) -> None:
        with connect(self.db_path) as db:
            has_v2 = self.reference_catalog.has_v2(db)
        if not has_v2:
            self._require_write()
            with connect(self.db_path) as db:
                cursor = db.execute(
                    "UPDATE reference_values SET is_active=? WHERE id=?",
                    (1 if is_active else 0, reference_id),
                )
                if not cursor.rowcount:
                    raise WarehouseError("Значение справочника не найдено")
                self._audit(db, "REFERENCE_TOGGLE", "reference_value", reference_id,
                            {"is_active": bool(is_active)})
            return
        self.reference_catalog.set_active(reference_id, is_active)

    def _reference_sets(self, db: sqlite3.Connection) -> dict[str, set[str]]:
        return self.reference_catalog.form_reference_sets(db)

    def reference_editor_catalog(self) -> dict[str, Any]:
        return self.reference_catalog.editor_catalog()

    def reference_models(self, vendor: str) -> list[dict[str, Any]]:
        return self.reference_catalog.models_for_vendor(vendor)

    def propose_reference(self, domain: str, value: str, parent: str = "") -> int:
        return self.reference_catalog.add_proposal(domain, value, parent=parent)

    def rename_reference(self, reference_id: int, display_name: str) -> None:
        self.reference_catalog.rename(reference_id, display_name)

    def preview_reference_merge(self, source_id: int, target_id: int) -> dict[str, Any]:
        return self.reference_catalog.merge_preview(source_id, target_id)

    def merge_reference(self, source_id: int, target_id: int) -> dict[str, Any]:
        return self.reference_catalog.merge(source_id, target_id)

    def _reference(
        self,
        value: str,
        field: str,
        kind: str,
        references: dict[str, set[str]],
        optional: bool = False,
        strict: bool = True,
    ) -> str:
        value = value.strip()
        if optional and not value:
            return ""
        if not value:
            raise WarehouseError(f"Поле «{field}» не может быть пустым")
        if strict and value.casefold() not in references.get(kind, set()):
            raise WarehouseError(
                f"Поле «{field}»: значение «{value}» отсутствует в активном справочнике"
            )
        return value

    def _collect_references(
        self,
        db: sqlite3.Connection,
        row: dict[str, Any],
        fields: dict[str, str],
    ) -> None:
        """Store unknown values as pending v2 proposals, never active canonical values."""
        if self.reference_catalog.has_v2(db):
            self.reference_catalog.collect_pending(db, row, fields)
            return
        if self.strict_reference_validation:
            return
        for field, kind in fields.items():
            value = str(row.get(field, "")).strip()
            if not value:
                continue
            cursor = db.execute(
                "INSERT OR IGNORE INTO reference_values(kind, name) VALUES (?, ?)",
                (kind, value),
            )
            if cursor.rowcount:
                self._audit(
                    db, "REFERENCE_AUTO_CREATE", "reference_value", cursor.lastrowid,
                    {"kind": kind, "name": value},
                )

    @staticmethod
    def _positive_number(value: Any, field: str = "количество / метраж") -> float:
        try:
            number = float(str(value).replace(",", "."))
        except ValueError as error:
            raise WarehouseError(f"Поле «{field}» должно быть числом") from error
        if number <= 0:
            raise WarehouseError(f"Поле «{field}» должно быть больше нуля")
        return number

    @staticmethod
    def _soft_receipt_source(source: dict[str, Any]) -> dict[str, Any]:
        """Fill non-critical warehouse fields without changing supplied values."""
        row = dict(source)
        row["receipt_date"] = str(row.get("receipt_date") or date.today().isoformat())
        row["responsible"] = str(row.get("responsible") or "Не указан")
        row["supplier"] = str(row.get("supplier") or "Не указан")
        supplied_vendor = canonical_vendor(row.get("vendor"))
        inferred_vendor = infer_vendor(
            row.get("item_name"), row.get("model"), row.get("part_number") or row.get("pn")
        )
        row["vendor"] = supplied_vendor or inferred_vendor or "Не указан"
        row["object_name"] = str(row.get("object_name") or "Не указано")
        row["datacenter"] = str(row.get("datacenter") or "Ixcellerate")
        row["unit"] = str(row.get("unit") or "шт")
        if not any(str(row.get(key) or "").strip() for key in (
            "equipment_type", "component_type", "cable_type"
        )):
            classification = classify_card(
                item_name=row.get("item_name"), vendor=row.get("vendor"),
                model=row.get("model"),
                part_number=row.get("part_number") or row.get("pn"),
            )
            if classification.confidence != "LOW":
                row[classification.field] = classification.value
            elif str(row.get("serial_number") or "").strip():
                row["equipment_type"] = "Не указан"
            else:
                row["cable_type"] = "Не указан"
        return row

    @staticmethod
    def _soft_issue_source(source: dict[str, Any]) -> dict[str, Any]:
        row = dict(source)
        row["issue_date"] = str(row.get("issue_date") or date.today().isoformat())
        row["responsible"] = str(row.get("responsible") or "Не указан")
        return row

    def _prepare_receipt(
        self,
        source: dict[str, Any],
        references: dict[str, set[str]],
        line_number: int | None = None,
    ) -> dict[str, Any]:
        prefix = f"Строка {line_number}: " if line_number is not None else ""
        try:
            source = dict(source)
            category = str(source.get("category", "")).strip()
            item_type = str(source.get("item_type", "")).strip()
            category_fields = {
                "оборудование": "equipment_type",
                "компоненты": "component_type",
                "кабели": "cable_type",
            }
            if category or item_type:
                target = category_fields.get(category.casefold())
                if not target or not item_type:
                    raise WarehouseError("выберите «Что приехало?» и тип")
                for field in category_fields.values():
                    source[field] = item_type if field == target else ""
            source["supplier"] = str(source.get("supplier") or "Не указан")
            source["vendor"] = str(source.get("vendor") or "Не указан")
            source["object_name"] = str(source.get("object_name") or "Не указано")
            source["datacenter"] = str(source.get("datacenter") or "Ixcellerate")
            source["unit"] = str(source.get("unit") or "шт")
            if category and category.casefold() != "кабели":
                source["quantity"] = 1
            row: dict[str, Any] = {
                "receipt_date": self._date(str(source.get("receipt_date", "")), "дата"),
                "responsible": self._required(str(source.get("responsible", "")), "ФИО"),
                "order_date": str(source.get("order_date", "")).strip(),
                "request_number": str(source.get("request_number", "")).strip(),
                "order_number": str(source.get("order_number", "")).strip(),
                "plu": str(source.get("plu", "")).strip(),
                "item_name": self._reference(
                    str(source.get("item_name", "")), "наименование", "item_name", references,
                    strict=self.strict_reference_validation,
                ),
                "project": self._reference(
                    str(source.get("project", "")), "проект", "project", references,
                    optional=True, strict=self.strict_reference_validation,
                ),
                "serial_number": str(source.get("serial_number", "")).strip().upper(),
                "inventory_number": str(source.get("inventory_number", "")).strip().upper(),
                "supplier": self._reference(
                    str(source.get("supplier", "")), "поставщик", "supplier", references,
                    strict=self.strict_reference_validation,
                ),
                "vendor": self._reference(
                    str(source.get("vendor", "")), "вендор", "vendor", references,
                    strict=self.strict_reference_validation,
                ),
                "model": self._reference(
                    str(source.get("model", "")), "модель", "model", references,
                    optional=True, strict=self.strict_reference_validation,
                ),
                "shelf": self._reference(
                    str(source.get("shelf", "")), "стеллаж/полка", "shelf", references,
                    optional=True, strict=self.strict_reference_validation,
                ),
                "object_name": self._reference(
                    str(source.get("object_name", "")), "объект", "object", references,
                    strict=self.strict_reference_validation,
                ),
                "datacenter": self._reference(
                    str(source.get("datacenter", "Ixcellerate")), "ЦОД", "datacenter", references,
                    strict=self.strict_reference_validation,
                ),
                "equipment_type": self._reference(
                    str(source.get("equipment_type", "")), "тип оборудования",
                    "equipment_type", references, optional=True,
                    strict=self.strict_reference_validation,
                ),
                "component_type": self._reference(
                    str(source.get("component_type", "")), "тип компонента",
                    "component_type", references, optional=True,
                    strict=self.strict_reference_validation,
                ),
                "cable_type": self._reference(
                    str(source.get("cable_type", "")), "тип кабеля",
                    "cable_type", references, optional=True,
                    strict=self.strict_reference_validation,
                ),
                "unit": self._reference(
                    str(source.get("unit", "")), "единица учета", "unit", references,
                    strict=self.strict_reference_validation,
                ),
                "quantity": self._positive_number(source.get("quantity", "")),
            }
            if row["order_date"]:
                row["order_date"] = self._date(row["order_date"], "дата заказа")
            classifications = sum(bool(row[key]) for key in (
                "equipment_type", "component_type", "cable_type"
            ))
            if classifications != 1:
                raise WarehouseError(
                    "укажите ровно один классификатор: тип оборудования, компонента или кабеля"
                )
            if not row["cable_type"]:
                if not row["serial_number"]:
                    raise WarehouseError("S/N обязателен для оборудования и компонентов")
                if not float(row["quantity"]).is_integer():
                    raise WarehouseError("оборудование и компоненты учитываются целыми штуками")
            return row
        except WarehouseError as error:
            raise WarehouseError(prefix + str(error)) from error

    @staticmethod
    def _receipt_values(row: dict[str, Any]) -> tuple[Any, ...]:
        fields = (
            "receipt_date", "responsible", "order_date", "request_number", "order_number",
            "plu", "item_name", "project", "serial_number", "inventory_number", "supplier",
            "vendor", "model", "shelf", "object_name", "datacenter",
            "equipment_type", "component_type",
            "cable_type", "unit", "quantity",
        )
        return tuple(row[field] for field in fields)

    def _store_import_preview(
        self, kind: str, rows: list[dict[str, Any]], result: dict[str, Any]
    ) -> dict[str, Any]:
        author = self._actor_email.get() or "lokolis"
        preview_id = secrets.token_urlsafe(24)
        self._import_previews[preview_id] = {
            "kind": kind,
            "rows": rows,
            "mode": result.get("mode", "strict"),
            "author": author,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        # Последний загруженный набор остается доступен для экспорта и после confirm.
        # Хранятся исходные строки файла, а не вся таблица из базы.
        self._last_import_rows[(author, kind)] = rows
        while len(self._last_import_rows) > 6:
            self._last_import_rows.pop(next(iter(self._last_import_rows)))
        # Ограничиваем память локального долгоживущего процесса.
        while len(self._import_previews) > 3:
            self._import_previews.pop(next(iter(self._import_previews)))
        return {**result, "preview_id": preview_id, "can_confirm": not result["errors"]}

    def import_preview_rows(
        self, kind: str, preview_id: str = ""
    ) -> list[dict[str, Any]]:
        """Вернуть только строки выбранного preview или последнего загруженного файла."""
        if kind not in {"receipt", "issue"}:
            raise WarehouseError("Экспорт preview для этого типа не поддерживается")
        if preview_id:
            rows = self._import_preview(preview_id, kind)["rows"]
        else:
            key = (self._actor_email.get() or "lokolis", kind)
            rows = self._last_import_rows.get(key)
            if rows is None:
                raise WarehouseError("Сначала загрузите CSV и откройте предпросмотр")
        return [dict(row) for row in rows]

    def _import_preview(self, preview_id: str, kind: str) -> dict[str, Any]:
        preview = self._import_previews.get(preview_id)
        if preview is None or preview["kind"] != kind:
            raise WarehouseError("Предпросмотр не найден или устарел")
        if preview["author"] != (self._actor_email.get() or "lokolis"):
            raise WarehouseError("Предпросмотр создан другим пользователем")
        return preview

    def preview_stock_receipt_rows(
        self, rows: Iterable[dict[str, Any]], *, soft: bool = False
    ) -> dict[str, Any]:
        """Проверить CSV прихода без изменения базы и сохранить набор для confirm."""
        self._require_write()
        source_rows = [dict(row) for row in rows]
        errors: list[dict[str, Any]] = []
        preview_rows: list[dict[str, Any]] = []
        valid = duplicates = error_count = 0
        with connect(self.db_path) as db:
            references = self._reference_sets(db)
            existing_serials = {
                str(row[0]).casefold() for row in db.execute(
                    "SELECT serial_number FROM stock_receipts WHERE serial_number <> ''"
                )
            }
            existing_inventories = {
                str(row[0]).casefold() for row in db.execute(
                    "SELECT inventory_number FROM stock_receipts WHERE inventory_number <> ''"
                )
            }
            seen_serials: set[str] = set()
            seen_inventories: set[str] = set()
            total = 0
            for line, source in enumerate(source_rows, start=2):
                if not any(str(value or "").strip() for value in source.values()):
                    continue
                total += 1
                reason = ""
                prepared: dict[str, Any] | None = None
                try:
                    candidate = self._soft_receipt_source(source) if soft else source
                    prepared = self._prepare_receipt(candidate, references, line)
                    serial = prepared["serial_number"].casefold()
                    inventory = prepared["inventory_number"].casefold()
                    duplicate_reasons: list[str] = []
                    if serial and (serial in existing_serials or serial in seen_serials):
                        duplicate_reasons.append(f"S/N «{prepared['serial_number']}» уже используется")
                    if inventory and (
                        inventory in existing_inventories or inventory in seen_inventories
                    ):
                        duplicate_reasons.append(
                            f"инвентарный номер «{prepared['inventory_number']}» уже используется"
                        )
                    if duplicate_reasons:
                        duplicates += 1
                        raise WarehouseError(f"Строка {line}: " + "; ".join(duplicate_reasons))
                    if serial:
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
        return self._store_import_preview("receipt", source_rows, {
            "total": total, "valid": valid, "new": valid,
            "duplicates": duplicates, "error_count": error_count,
            "errors": errors, "rows": preview_rows, "mode": "soft" if soft else "strict",
        })

    def confirm_stock_receipt_preview(self, preview_id: str) -> int:
        self._require_write()
        preview = self._import_preview(preview_id, "receipt")
        # Повторная проверка защищает от изменения остатков между preview и confirm.
        soft = preview.get("mode") == "soft"
        check = self.preview_stock_receipt_rows(preview["rows"], soft=soft)
        self._import_previews.pop(check["preview_id"], None)
        if check["errors"]:
            raise WarehouseError(check["errors"][0]["reason"])
        imported = self.import_stock_receipt_rows(preview["rows"], soft=soft)
        self._import_previews.pop(preview_id, None)
        return imported

    def scan_receipt_serial(self, serial_number: str) -> dict[str, Any]:
        """Проверить один отсканированный S/N без изменения базы."""
        serial = self._required(str(serial_number).strip().upper(), "S/N")
        with connect(self.db_path) as db:
            exists = db.execute(
                "SELECT 1 FROM stock_receipts WHERE trim(serial_number) <> '' AND trim(serial_number) = trim(?) COLLATE NOCASE",
                (serial,),
            ).fetchone()
        return {
            "serial_number": serial,
            "valid": exists is None,
            "error": f"S/N «{serial}» уже есть на складе" if exists else "",
        }

    def confirm_scanned_receipts(
        self, common_fields: dict[str, Any], serial_numbers: Iterable[str]
    ) -> int:
        """Принять экранный скан-лист одной SQLite-транзакцией."""
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
        return self.import_stock_receipt_rows(rows, soft=False)

    def add_stock_receipt(self, **fields: Any) -> int:
        self._require_write()
        with connect(self.db_path) as db:
            row = self._prepare_receipt(fields, self._reference_sets(db))
            self._collect_references(db, row, self.RECEIPT_REFERENCE_FIELDS)
            try:
                cursor = db.execute(
                    """INSERT INTO stock_receipts(
                           receipt_date, responsible, order_date, request_number, order_number,
                           plu, item_name, project, serial_number, inventory_number, supplier,
                           vendor, model, shelf, object_name, datacenter, equipment_type,
                           component_type, cable_type, unit, quantity
                       ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    self._receipt_values(row),
                )
                receipt_id = int(cursor.lastrowid)
                self._audit(
                    db, "RECEIPT_CREATE", "stock_receipt", receipt_id,
                    {"item_name": row["item_name"], "quantity": row["quantity"],
                     "serial_number": row["serial_number"]},
                )
                return receipt_id
            except sqlite3.IntegrityError as error:
                raise WarehouseError("S/N или инвентарный номер уже используется") from error

    def import_stock_receipt_rows(
        self, rows: Iterable[dict[str, Any]], *, soft: bool = True
    ) -> int:
        self._require_write()
        with connect(self.db_path) as db:
            references = self._reference_sets(db)
            prepared: list[dict[str, Any]] = []
            for line, source in enumerate(rows, start=2):
                if not any(str(value or "").strip() for value in source.values()):
                    continue
                candidate = self._soft_receipt_source(source) if soft else source
                row = self._prepare_receipt(candidate, references, line)
                row["_line"] = line
                prepared.append(row)
            if not prepared:
                raise WarehouseError("В CSV-файле нет строк прихода")
            existing_serials = {
                str(row[0]).casefold() for row in db.execute(
                    "SELECT serial_number FROM stock_receipts WHERE serial_number <> ''"
                )
            }
            existing_inventories = {
                str(row[0]).casefold() for row in db.execute(
                    "SELECT inventory_number FROM stock_receipts WHERE inventory_number <> ''"
                )
            }
            seen_serials: set[str] = set()
            seen_inventories: set[str] = set()
            for row in prepared:
                serial = row["serial_number"].casefold()
                inventory = row["inventory_number"].casefold()
                if serial and (serial in existing_serials or serial in seen_serials):
                    raise WarehouseError(f"Строка {row['_line']}: S/N «{row['serial_number']}» уже используется")
                if inventory and (
                    inventory in existing_inventories or inventory in seen_inventories
                ):
                    raise WarehouseError(
                        f"Строка {row['_line']}: инвентарный номер "
                        f"«{row['inventory_number']}» уже используется"
                    )
                if serial:
                    seen_serials.add(serial)
                if inventory:
                    seen_inventories.add(inventory)
            for field, kind in self.RECEIPT_REFERENCE_FIELDS.items():
                for value in {str(row[field]).strip() for row in prepared if str(row[field]).strip()}:
                    self._collect_references(db, {field: value}, {field: kind})
            try:
                db.executemany(
                    """INSERT INTO stock_receipts(
                           receipt_date, responsible, order_date, request_number, order_number,
                           plu, item_name, project, serial_number, inventory_number, supplier,
                           vendor, model, shelf, object_name, datacenter, equipment_type,
                           component_type, cable_type, unit, quantity
                       ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    [self._receipt_values(row) for row in prepared],
                )
                self._audit(
                    db, "RECEIPT_IMPORT", "stock_receipt", details={"count": len(prepared)}
                )
            except sqlite3.IntegrityError as error:
                raise WarehouseError("S/N или инвентарный номер уже используется") from error
        return len(prepared)

    def stock_receipts(self) -> list[dict[str, Any]]:
        with connect(self.db_path) as db:
            rows = db.execute(
                """SELECT r.*,
                          r.quantity - COALESCE(SUM(a.quantity), 0) AS available
                   FROM stock_receipts r
                   LEFT JOIN stock_issue_allocations a ON a.receipt_id = r.id
                   GROUP BY r.id ORDER BY r.receipt_date DESC, r.id DESC"""
            ).fetchall()
            return [dict(row) for row in rows]

    @staticmethod
    def _delivery_serials(value: Any) -> list[str]:
        text = str(value or "").strip()
        if not text:
            return []
        parts = re.split(r"[,;\n\r]+", text)
        if len(parts) == 1:
            parts = re.split(r"\s+", text)
        return [part.strip() for part in parts if part.strip()]

    def preview_delivery_rows(self, rows: Iterable[dict[str, Any]], filename: str,
                              unknown_columns: Iterable[str] = (), *, auto_apply: bool = False) -> dict[str, Any]:
        self._require_write()
        expanded: list[dict[str, Any]] = []
        seen: set[str] = set()
        with connect(self.db_path) as db:
            existing = {str(row[0]).casefold() for row in db.execute(
                "SELECT serial_number FROM stock_receipts WHERE trim(serial_number) <> ''"
            )}
        for source_line, source in enumerate(rows, start=2):
            serials = self._delivery_serials(source.get("serial_number"))
            if not serials:
                candidate = dict(source)
                candidate.update({"source_line": source_line, "serial_number": "", "state": "Ошибка", "error_text": "Не указан S/N"})
                expanded.append(candidate)
                continue
            for serial in serials:
                candidate = dict(source)
                key = serial.casefold()
                state, error = "Ожидается", ""
                if key in seen:
                    state, error = "Дубль в файле", "S/N повторяется в файле"
                elif key in existing:
                    state, error = "Уже на складе", "S/N уже есть на складе"
                seen.add(key)
                candidate.update({"source_line": source_line, "serial_number": serial, "state": state, "error_text": error})
                expanded.append(candidate)
        if not expanded:
            raise WarehouseError("В файле поставки нет строк")
        counts = {name: sum(row["state"] == name for row in expanded) for name in ("Ожидается", "Уже на складе", "Дубль в файле", "Ошибка")}
        preview_id = secrets.token_urlsafe(18)
        self._import_previews[preview_id] = {
            "kind": "delivery", "rows": expanded, "filename": filename,
            "auto_apply": auto_apply,
            "author": self._actor_email.get() or "lokolis",
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        return {"preview_id": preview_id, "total": len(expanded), "counts": counts,
                "new": counts["Ожидается"], "updated": counts["Уже на складе"],
                "duplicates": counts["Дубль в файле"], "errors": counts["Ошибка"],
                "unknown_columns": list(unknown_columns), "rows": expanded[:PREVIEW_ROW_LIMIT],
                "can_confirm": counts["Ожидается"] > 0 or counts["Уже на складе"] > 0}

    def confirm_delivery_preview(self, preview_id: str) -> int:
        self._require_write()
        preview = self._import_preview(preview_id, "delivery")
        rows = preview["rows"]
        first = rows[0]
        actor = str(self.current_user()["email"])
        with connect(self.db_path) as db:
            references = self._reference_sets(db)
            cursor = db.execute(
                "INSERT INTO deliveries(source_filename, delivery_number, supplier, uploaded_by) VALUES (?,?,?,?)",
                (preview["filename"], str(first.get("delivery_number", "")), str(first.get("supplier", "")), actor),
            )
            delivery_id = int(cursor.lastrowid)
            for number, row in enumerate(rows, start=1):
                try:
                    quantity = float(str(row.get("quantity", 1) or 1).replace(",", "."))
                    if quantity <= 0:
                        raise ValueError
                except ValueError:
                    quantity = 1
                    row["state"], row["error_text"] = "Ошибка", "Некорректное количество"
                receipt_id = None
                if preview.get("auto_apply") and row["state"] == "Ожидается":
                    item_type = row.get("equipment_type") or row.get("component_type") or row.get("cable_type") or row.get("equipment_unit") or "Прочее"
                    candidate = {
                        "receipt_date": row.get("receipt_date") or row.get("work_date") or date.today().isoformat(),
                        "responsible": actor, "order_date": row.get("order_date", ""),
                        "request_number": row.get("request_number", ""), "order_number": row.get("order_number", ""),
                        "plu": row.get("plu", ""), "item_name": row.get("item_name") or " ".join(filter(None, (item_type, row.get("vendor"), row.get("model")))),
                        "project": row.get("project", ""), "serial_number": row.get("serial_number", ""),
                        "inventory_number": row.get("inventory_number") or row.get("asset_number", ""),
                        "supplier": row.get("supplier") or "Не указан", "vendor": row.get("vendor") or "Не указан",
                        "model": row.get("model", ""), "shelf": row.get("shelf", ""),
                        "object_name": row.get("object_name") or "Склад", "datacenter": row.get("datacenter") or "Ixcellerate",
                        "equipment_type": row.get("equipment_type") or item_type, "component_type": row.get("component_type", ""),
                        "cable_type": row.get("cable_type", ""), "unit": row.get("unit") or "шт", "quantity": quantity,
                    }
                    prepared = self._prepare_receipt(self._soft_receipt_source(candidate), references)
                    self._collect_references(db, prepared, self.RECEIPT_REFERENCE_FIELDS)
                    receipt_id = int(db.execute("""INSERT INTO stock_receipts(receipt_date,responsible,order_date,request_number,order_number,plu,item_name,project,serial_number,inventory_number,supplier,vendor,model,shelf,object_name,datacenter,equipment_type,component_type,cable_type,unit,quantity) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", self._receipt_values(prepared)).lastrowid)
                    row["state"] = "Принято"
                elif preview.get("auto_apply") and row["state"] == "Уже на складе":
                    existing = db.execute("SELECT * FROM stock_receipts WHERE trim(serial_number) <> '' AND trim(serial_number)=trim(?) COLLATE NOCASE", (row.get("serial_number", ""),)).fetchone()
                    if existing:
                        receipt_id = int(existing["id"])
                        mapping = {"inventory_number":"inventory_number", "supplier":"supplier", "order_number":"order_number", "request_number":"request_number", "plu":"plu", "project":"project", "model":"model", "vendor":"vendor", "shelf":"shelf", "datacenter":"datacenter", "item_name":"item_name", "equipment_type":"equipment_type"}
                        updates = {target: row.get(source, "") for source,target in mapping.items() if row.get(source) and not str(existing[target] or "").strip()}
                        if updates:
                            db.execute("UPDATE stock_receipts SET "+",".join(f"{key}=?" for key in updates)+" WHERE id=?", (*updates.values(), receipt_id))
                            self._audit(db, "DELIVERY_RECEIPT_UPDATE", "stock_receipt", receipt_id, {"fields": list(updates)})
                        row["state"] = "Принято"
                values = (
                    delivery_id, number, row.get("receipt_statement", ""), row.get("order_date", ""),
                    row.get("request_number", ""), row.get("order_number", ""), row.get("serial_number", ""),
                    row.get("delivery_number", ""), row.get("supplier", ""), row.get("planned_date", ""),
                    row.get("request_position", ""), row.get("order_position", ""), row.get("contract_number", ""),
                    row.get("plu", ""), row.get("accounting_object", ""), quantity, row.get("asset_number", ""),
                    row.get("equipment_unit", ""), row.get("equipment_unit", ""), row.get("supplier", ""),
                    row.get("accounting_object", ""), row.get("equipment_unit", "") or "шт", row["state"],
                    row.get("error_text", ""), actor,
                )
                db.execute(
                    """INSERT INTO delivery_lines(delivery_id,row_number,receipt_statement,order_date,
                       request_number,order_number,serial_number,delivery_number,supplier,planned_date,
                       request_position,order_position,contract_number,plu,accounting_object,quantity,
                       asset_number,equipment_unit,item_name,vendor,object_name,unit,state,error_text,updated_by)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", values,
                )
                if receipt_id:
                    db.execute("UPDATE delivery_lines SET receipt_id=? WHERE delivery_id=? AND row_number=?", (receipt_id, delivery_id, number))
            if preview.get("auto_apply"):
                db.execute("UPDATE deliveries SET status=CASE WHEN EXISTS(SELECT 1 FROM delivery_lines WHERE delivery_id=? AND state='Ожидается') THEN 'Частично принята' ELSE 'Принята' END WHERE id=?", (delivery_id, delivery_id))
            else:
                db.execute("UPDATE deliveries SET status='Ожидается' WHERE id=?", (delivery_id,))
            self._audit(db, "DELIVERY_UPLOAD", "delivery", delivery_id, {"filename": preview["filename"], "rows": len(rows)})
        self._import_previews.pop(preview_id, None)
        return delivery_id

    def deliveries(self, query: str = "") -> list[dict[str, Any]]:
        term = f"%{query.strip()}%"
        with connect(self.db_path) as db:
            rows = db.execute(
                """SELECT d.*, COUNT(l.id) AS total,
                          SUM(CASE WHEN l.state='Принято' THEN 1 ELSE 0 END) AS accepted,
                          SUM(CASE WHEN l.state IN ('Ошибка','Дубль в файле','Уже на складе') THEN 1 ELSE 0 END) AS problems
                   FROM deliveries d LEFT JOIN delivery_lines l ON l.delivery_id=d.id
                   WHERE ?='' OR d.delivery_number LIKE ? OR d.supplier LIKE ? OR d.source_filename LIKE ?
                      OR EXISTS(SELECT 1 FROM delivery_lines s WHERE s.delivery_id=d.id AND
                         (s.serial_number LIKE ? OR s.order_number LIKE ? OR s.request_number LIKE ?))
                   GROUP BY d.id ORDER BY d.uploaded_at DESC,d.id DESC""",
                (query.strip(), term, term, term, term, term, term),
            ).fetchall()
        return [dict(row) for row in rows]

    def delivery(self, delivery_id: int) -> dict[str, Any]:
        with connect(self.db_path) as db:
            head = db.execute("SELECT * FROM deliveries WHERE id=?", (delivery_id,)).fetchone()
            if head is None:
                raise WarehouseError("Поставка не найдена")
            lines = db.execute("SELECT * FROM delivery_lines WHERE delivery_id=? ORDER BY row_number,id", (delivery_id,)).fetchall()
        return {"delivery": dict(head), "lines": [dict(row) for row in lines]}

    def update_delivery_lines(self, delivery_id: int, line_ids: Iterable[int], values: dict[str, Any], *, only_empty: bool = False) -> int:
        self._require_write()
        clean = {key: values[key] for key in values if key in self.DELIVERY_EDITABLE_FIELDS}
        ids = [int(value) for value in line_ids]
        if not ids or not clean:
            raise WarehouseError("Выберите строки и поле для заполнения")
        actor = str(self.current_user()["email"])
        changed = 0
        with connect(self.db_path) as db:
            for line_id in ids:
                row = db.execute("SELECT * FROM delivery_lines WHERE id=? AND delivery_id=?", (line_id, delivery_id)).fetchone()
                if row is None or row["state"] == "Принято":
                    continue
                assignments, params = [], []
                for field, value in clean.items():
                    if only_empty and str(row[field] or "").strip():
                        continue
                    assignments.append(f"{field}=?")
                    params.append(value)
                if assignments:
                    params.extend((actor, line_id))
                    db.execute(f"UPDATE delivery_lines SET {','.join(assignments)},updated_by=?,updated_at=datetime('now','localtime') WHERE id=?", params)
                    self._audit(db, "DELIVERY_LINE_UPDATE", "delivery_line", line_id, clean)
                    changed += 1
        return changed

    def _refresh_delivery_status(self, db: sqlite3.Connection, delivery_id: int) -> None:
        current = db.execute("SELECT status FROM deliveries WHERE id=?", (delivery_id,)).fetchone()
        if current is None or current["status"] == "Закрыта":
            return
        counts = db.execute("SELECT COUNT(*) total,SUM(state='Принято') accepted,SUM(state='Ожидается') waiting FROM delivery_lines WHERE delivery_id=?", (delivery_id,)).fetchone()
        status = "Принята" if counts["accepted"] and not counts["waiting"] else ("Частично принята" if counts["accepted"] else "Ожидается")
        db.execute("UPDATE deliveries SET status=? WHERE id=?", (status, delivery_id))

    def accept_delivery_serial(self, delivery_id: int, serial_number: str, values: dict[str, Any] | None = None, *, unplanned: bool = False) -> dict[str, Any]:
        self._require_write()
        serial = self._required(serial_number, "S/N")
        values = values or {}
        actor = str(self.current_user()["email"])
        with connect(self.db_path) as db:
            delivery = db.execute("SELECT * FROM deliveries WHERE id=?", (delivery_id,)).fetchone()
            if delivery is None or delivery["status"] == "Закрыта":
                raise WarehouseError("Поставка не найдена или уже закрыта")
            existing = db.execute("SELECT id FROM stock_receipts WHERE trim(serial_number) <> '' AND trim(serial_number)=trim(?) COLLATE NOCASE", (serial,)).fetchone()
            if existing:
                raise WarehouseError("Этот S/N уже есть на складе")
            line = db.execute("SELECT * FROM delivery_lines WHERE delivery_id=? AND serial_number=? COLLATE NOCASE ORDER BY id LIMIT 1", (delivery_id, serial)).fetchone()
            if line is None:
                if not unplanned:
                    return {"found": False, "serial_number": serial}
                cursor = db.execute("INSERT INTO delivery_lines(delivery_id,row_number,serial_number,state,is_unplanned,updated_by) VALUES (?,(SELECT COALESCE(MAX(row_number),0)+1 FROM delivery_lines WHERE delivery_id=?),?,'Ожидается',1,?)", (delivery_id, delivery_id, serial, actor))
                line = db.execute("SELECT * FROM delivery_lines WHERE id=?", (cursor.lastrowid,)).fetchone()
            if line["state"] == "Принято":
                raise WarehouseError("Этот S/N уже принят")
            merged = dict(line)
            merged.update({key: value for key, value in values.items() if key in self.DELIVERY_EDITABLE_FIELDS})
            receipt = {
                "receipt_date": date.today().isoformat(), "responsible": actor,
                "order_date": merged["order_date"], "request_number": merged["request_number"],
                "order_number": merged["order_number"], "plu": merged["plu"],
                "item_name": merged.get("item_name") or merged.get("equipment_unit") or "Позиция поставки",
                "project": merged.get("project", ""), "serial_number": serial,
                "inventory_number": merged.get("asset_number", ""),
                "supplier": merged.get("supplier") or delivery["supplier"] or "Не указан",
                "vendor": merged.get("vendor") or "Не указан", "model": merged.get("model", ""),
                "shelf": merged.get("shelf", ""), "object_name": merged.get("object_name") or merged.get("accounting_object") or "Не указано",
                "datacenter": merged.get("datacenter") or "Ixcellerate",
                "equipment_type": merged.get("equipment_type", ""), "component_type": merged.get("component_type", ""),
                "cable_type": merged.get("cable_type", ""), "unit": merged.get("unit") or "шт", "quantity": merged.get("quantity") or 1,
            }
            if not any(receipt[key] for key in ("equipment_type", "component_type", "cable_type")):
                receipt["equipment_type"] = "Прочее"
            prepared = self._prepare_receipt(receipt, self._reference_sets(db))
            self._collect_references(db, prepared, self.RECEIPT_REFERENCE_FIELDS)
            cursor = db.execute("""INSERT INTO stock_receipts(receipt_date,responsible,order_date,request_number,order_number,plu,item_name,project,serial_number,inventory_number,supplier,vendor,model,shelf,object_name,datacenter,equipment_type,component_type,cable_type,unit,quantity) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", self._receipt_values(prepared))
            receipt_id = int(cursor.lastrowid)
            db.execute("UPDATE delivery_lines SET state='Принято',receipt_id=?,updated_by=?,updated_at=datetime('now','localtime') WHERE id=?", (receipt_id, actor, line["id"]))
            self._audit(db, "DELIVERY_ACCEPT", "delivery_line", line["id"], {"serial_number": serial, "receipt_id": receipt_id, "unplanned": bool(line["is_unplanned"])})
            self._refresh_delivery_status(db, delivery_id)
        return {"found": True, "accepted": True, "receipt_id": receipt_id, "line_id": int(line["id"])}

    def close_delivery(self, delivery_id: int) -> None:
        self._require_write()
        actor = str(self.current_user()["email"])
        with connect(self.db_path) as db:
            if db.execute("SELECT id FROM deliveries WHERE id=?", (delivery_id,)).fetchone() is None:
                raise WarehouseError("Поставка не найдена")
            db.execute("UPDATE deliveries SET status='Закрыта',closed_by=?,closed_at=datetime('now','localtime') WHERE id=?", (actor, delivery_id))
            self._audit(db, "DELIVERY_CLOSE", "delivery", delivery_id)

    def warehouse_categories(self) -> list[dict[str, Any]]:
        names = ("Серверы", "Диски", "Память", "Сетевое оборудование", "Кабели", "Прочее")
        totals = {name: 0.0 for name in names}

        def category_name(
            item_name: str, equipment_type: str, component_type: str, cable_type: str
        ) -> str:
            text = " ".join((
                str(item_name or ""), str(equipment_type or ""),
                str(component_type or ""), str(cable_type or ""),
            )).casefold()
            if cable_type:
                return "Кабели"
            if "сервер" in text:
                return "Серверы"
            if any(value in text for value in ("диск", "ssd", "hdd")):
                return "Диски"
            if any(value in text for value in ("памят", "ram", "dimm")):
                return "Память"
            if any(value in text for value in ("сет", "коммут", "switch", "маршрут")):
                return "Сетевое оборудование"
            return "Прочее"

        with connect(self.db_path) as db:
            db.create_function("ode_warehouse_category", 4, category_name, deterministic=True)
            rows = db.execute(
                """SELECT ode_warehouse_category(
                              r.item_name, r.equipment_type, r.component_type, r.cable_type
                          ) AS category,
                          SUM(r.quantity - COALESCE(a.issued, 0)) AS balance
                   FROM stock_receipts r
                   LEFT JOIN (
                       SELECT receipt_id, SUM(quantity) AS issued
                       FROM stock_issue_allocations GROUP BY receipt_id
                   ) a ON a.receipt_id = r.id
                   GROUP BY category"""
            ).fetchall()
        for row in rows:
            totals[str(row["category"])] = float(row["balance"])
        return [{"name": name, "quantity": totals[name]} for name in names]

    def warehouse_type_summary(self) -> list[dict[str, Any]]:
        """Вернуть точные остатки и число складских позиций по рабочим типам."""
        with connect(self.db_path) as db:
            rows = db.execute(
                """WITH allocations AS (
                       SELECT receipt_id, SUM(quantity) AS issued
                       FROM stock_issue_allocations GROUP BY receipt_id
                   ), lots AS (
                       SELECT r.project, r.item_name, r.supplier, r.vendor, r.model,
                              r.serial_number, r.inventory_number, r.unit, r.object_name,
                              r.equipment_type, r.component_type, r.cable_type, r.datacenter,
                              r.quantity - COALESCE(a.issued, 0) AS balance
                       FROM stock_receipts r
                       LEFT JOIN allocations a ON a.receipt_id = r.id
                   ), positions AS (
                       SELECT CASE
                                  WHEN lower(trim(cable_type)) IN ('aoc','dac') THEN 'Кабельные сборки'
                                  WHEN trim(cable_type) <> '' THEN 'Кабели'
                                  WHEN trim(COALESCE(NULLIF(trim(component_type),''),NULLIF(trim(equipment_type),''),'')) = 'Трансивер'
                                       OR lower(trim(COALESCE(NULLIF(trim(component_type),''),NULLIF(trim(equipment_type),''),''))) = 'transceiver'
                                      THEN 'Трансиверы'
                                  WHEN trim(COALESCE(NULLIF(trim(component_type),''),NULLIF(trim(equipment_type),''),'')) = 'Оперативная память'
                                       OR lower(trim(COALESCE(NULLIF(trim(component_type),''),NULLIF(trim(equipment_type),''),''))) IN ('memory','ram')
                                      THEN 'Память'
                                  WHEN lower(trim(COALESCE(NULLIF(component_type,''),NULLIF(equipment_type,''),'')))
                                       IN ('ssd','hdd') THEN 'Накопители'
                                  WHEN trim(COALESCE(NULLIF(trim(component_type),''),NULLIF(trim(equipment_type),''),''))
                                       IN ('Сетевой адаптер','HBA-адаптер','RAID-контроллер')
                                       OR lower(trim(COALESCE(NULLIF(trim(component_type),''),NULLIF(trim(equipment_type),''),'')))
                                       IN ('nic','hba','raid controller')
                                      THEN 'Адаптеры и контроллеры'
                                  WHEN trim(COALESCE(NULLIF(trim(component_type),''),NULLIF(trim(equipment_type),''),'')) = 'Аксессуар'
                                       OR lower(trim(COALESCE(NULLIF(trim(component_type),''),NULLIF(trim(equipment_type),''),''))) = 'accessory'
                                      THEN 'Другое оборудование'
                                  WHEN trim(component_type) = 'Прочий компонент'
                                       OR lower(trim(component_type)) = 'other'
                                      THEN 'Другое оборудование'
                                  WHEN trim(component_type) <> '' THEN 'Комплектующие'
                                  WHEN trim(equipment_type) = 'Прочее оборудование'
                                       OR lower(trim(equipment_type)) = 'other'
                                      THEN 'Другое оборудование'
                                  WHEN trim(equipment_type) <> '' THEN 'Оборудование'
                                  ELSE 'Другое оборудование'
                              END AS category,
                              COALESCE(
                                  NULLIF(trim(equipment_type), ''),
                                  NULLIF(trim(component_type), ''),
                                  NULLIF(trim(cable_type), ''),
                                  'Без типа'
                              ) AS item_type,
                              SUM(balance) AS balance
                       FROM lots
                       GROUP BY project, item_name, supplier, vendor, model,
                                serial_number, inventory_number, unit, object_name,
                                equipment_type, component_type, cable_type, datacenter
                   )
                   SELECT category, item_type, COUNT(*) AS positions,
                          SUM(balance) AS quantity
                   FROM positions
                   WHERE balance > 0.0000001
                   GROUP BY category, item_type
                   ORDER BY CASE category
                                WHEN 'Оборудование' THEN 1
                                WHEN 'Трансиверы' THEN 2
                                WHEN 'Память' THEN 3
                                WHEN 'Накопители' THEN 4
                                WHEN 'Адаптеры и контроллеры' THEN 5
                                WHEN 'Комплектующие' THEN 6
                                WHEN 'Кабели' THEN 7
                                WHEN 'Кабельные сборки' THEN 8
                                ELSE 9
                            END,
                            positions DESC, item_type COLLATE NOCASE"""
            ).fetchall()
        return [
            {
                "category": str(row["category"]),
                "item_type": str(row["item_type"]),
                "positions": int(row["positions"]),
                "quantity": float(row["quantity"]),
            }
            for row in rows
        ]

    def warehouse_model_options(self) -> list[dict[str, Any]]:
        """Return model choices scoped by the actually observed vendor and item type."""
        with connect(self.db_path) as db:
            rows = db.execute(
                """WITH allocations AS (
                       SELECT receipt_id, SUM(quantity) AS issued
                       FROM stock_issue_allocations GROUP BY receipt_id
                   ), lots AS (
                       SELECT trim(r.vendor) AS vendor, trim(r.model) AS model,
                              COALESCE(
                                  NULLIF(trim(r.equipment_type), ''),
                                  NULLIF(trim(r.component_type), ''),
                                  NULLIF(trim(r.cable_type), ''),
                                  'Без типа'
                              ) AS item_type,
                              r.quantity - COALESCE(a.issued, 0) AS balance
                       FROM stock_receipts r
                       LEFT JOIN allocations a ON a.receipt_id = r.id
                   )
                   SELECT vendor, model, item_type, COUNT(*) AS positions
                   FROM lots
                   WHERE balance > 0.0000001 AND vendor <> '' AND model <> ''
                   GROUP BY vendor, model, item_type
                   ORDER BY vendor COLLATE NOCASE, item_type COLLATE NOCASE,
                            positions DESC, model COLLATE NOCASE"""
            ).fetchall()
        return [dict(row) for row in rows]

    def stock_balance(
        self,
        query: str = "",
        project: str = "",
        object_name: str = "",
        equipment_type: str = "",
        component_type: str = "",
        cable_type: str = "",
        unit: str = "",
        datacenter: str = "",
        category: str = "",
        item_type: str = "",
        supplier: str = "",
        vendor: str = "",
        stock_state: str = "",
        sort_by: str = "item_name",
        sort_dir: str = "asc",
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Рассчитать баланс как приход минус распределенный расход, без учета полки."""
        filters = {
            "project": project, "object_name": object_name,
            "equipment_type": equipment_type, "component_type": component_type,
            "cable_type": cable_type, "unit": unit, "datacenter": datacenter,
            "supplier": supplier, "vendor": vendor,
        }
        where: list[str] = []
        params: list[Any] = []
        for field, value in filters.items():
            if value:
                where.append(f"{field} = ? COLLATE NOCASE")
                params.append(value)
        if query.strip():
            term = f"%{query.strip()}%"
            where.append(
                "(serial_number LIKE ? OR inventory_number LIKE ? OR item_name LIKE ? "
                "OR model LIKE ? OR vendor LIKE ? OR supplier LIKE ? OR project LIKE ? "
                "OR object_name LIKE ? OR shelf LIKE ?)"
            )
            params.extend([term] * 9)
        where_sql = "WHERE " + " AND ".join(where) if where else ""
        position_filters: list[str] = []
        if category:
            position_filters.append("category = ? COLLATE NOCASE")
            params.append(category)
        if item_type:
            position_filters.append("item_type = ? COLLATE NOCASE")
            params.append(item_type)
        if stock_state == "positive":
            position_filters.append("balance > 0.0000001")
        elif stock_state == "zero":
            position_filters.append("abs(balance) <= 0.0000001")
        position_where_sql = (
            "WHERE " + " AND ".join(position_filters) if position_filters else ""
        )
        sort_columns = {
            "item_name": "item_name COLLATE NOCASE",
            "item_type": "item_type COLLATE NOCASE",
            "category": "category COLLATE NOCASE",
            "balance": "balance",
            "serial_number": "serial_number COLLATE NOCASE",
            "shelf": "shelf COLLATE NOCASE",
            "vendor": "vendor COLLATE NOCASE",
            "model": "model COLLATE NOCASE",
            "supplier": "supplier COLLATE NOCASE",
            "project": "project COLLATE NOCASE",
        }
        order_column = sort_columns.get(sort_by, sort_columns["item_name"])
        order_direction = "DESC" if sort_dir.casefold() == "desc" else "ASC"
        with connect(self.db_path) as db:
            limit_sql = ""
            if limit is not None:
                limit = max(1, min(int(limit), 10_000))
                offset = max(0, int(offset))
                limit_sql = " LIMIT ? OFFSET ?"
                params.extend((limit, offset))
            rows = db.execute(
                f"""WITH allocations AS (
                       SELECT receipt_id, SUM(quantity) AS issued
                       FROM stock_issue_allocations GROUP BY receipt_id
                   ), lots AS (
                       SELECT r.id, r.project, r.item_name, r.supplier, r.vendor, r.model, r.serial_number,
                              r.inventory_number, r.shelf, r.object_name,
                              r.equipment_type, r.component_type, r.cable_type,
                              r.unit, r.datacenter,
                              r.quantity - COALESCE(a.issued, 0) AS balance
                       FROM stock_receipts r
                       LEFT JOIN allocations a ON a.receipt_id = r.id
                   ), positions AS (
                   SELECT GROUP_CONCAT(id) AS receipt_ids,
                          project, item_name, supplier, vendor, model, serial_number, inventory_number,
                          SUM(balance) AS balance, unit,
                          GROUP_CONCAT(DISTINCT NULLIF(shelf, '')) AS shelf,
                          object_name, equipment_type, component_type, cable_type,
                          datacenter,
                          CASE
                              WHEN lower(trim(cable_type)) IN ('aoc','dac') THEN 'Кабельные сборки'
                              WHEN trim(cable_type) <> '' THEN 'Кабели'
                              WHEN trim(COALESCE(NULLIF(trim(component_type),''),NULLIF(trim(equipment_type),''),'')) = 'Трансивер'
                                   OR lower(trim(COALESCE(NULLIF(trim(component_type),''),NULLIF(trim(equipment_type),''),''))) = 'transceiver'
                                  THEN 'Трансиверы'
                              WHEN trim(COALESCE(NULLIF(trim(component_type),''),NULLIF(trim(equipment_type),''),'')) = 'Оперативная память'
                                   OR lower(trim(COALESCE(NULLIF(trim(component_type),''),NULLIF(trim(equipment_type),''),''))) IN ('memory','ram')
                                  THEN 'Память'
                              WHEN lower(trim(COALESCE(NULLIF(component_type,''),NULLIF(equipment_type,''),'')))
                                   IN ('ssd','hdd') THEN 'Накопители'
                              WHEN trim(COALESCE(NULLIF(trim(component_type),''),NULLIF(trim(equipment_type),''),''))
                                   IN ('Сетевой адаптер','HBA-адаптер','RAID-контроллер')
                                   OR lower(trim(COALESCE(NULLIF(trim(component_type),''),NULLIF(trim(equipment_type),''),'')))
                                   IN ('nic','hba','raid controller')
                                  THEN 'Адаптеры и контроллеры'
                              WHEN trim(COALESCE(NULLIF(trim(component_type),''),NULLIF(trim(equipment_type),''),'')) = 'Аксессуар'
                                   OR lower(trim(COALESCE(NULLIF(trim(component_type),''),NULLIF(trim(equipment_type),''),''))) = 'accessory'
                                  THEN 'Другое оборудование'
                              WHEN trim(component_type) = 'Прочий компонент'
                                   OR lower(trim(component_type)) = 'other'
                                  THEN 'Другое оборудование'
                              WHEN trim(component_type) <> '' THEN 'Комплектующие'
                              WHEN trim(equipment_type) = 'Прочее оборудование'
                                   OR lower(trim(equipment_type)) = 'other'
                                  THEN 'Другое оборудование'
                              WHEN trim(equipment_type) <> '' THEN 'Оборудование'
                              ELSE 'Другое оборудование'
                          END AS category,
                          COALESCE(
                              NULLIF(trim(equipment_type), ''),
                              NULLIF(trim(component_type), ''),
                              NULLIF(trim(cable_type), ''),
                              'Без типа'
                          ) AS item_type
                   FROM lots {where_sql}
                   GROUP BY project, item_name, supplier, vendor, model, serial_number, inventory_number,
                            unit, object_name, equipment_type, component_type,
                            cable_type, datacenter
                   )
                   SELECT * FROM positions {position_where_sql}
                   ORDER BY {order_column} {order_direction},
                            item_name COLLATE NOCASE, model COLLATE NOCASE,
                            serial_number COLLATE NOCASE{limit_sql}""",
                params,
            ).fetchall()
            result = [dict(row) for row in rows]
            for row in result:
                row["position_key"] = (
                    f"sn:{row['serial_number']}" if row["serial_number"] else
                    "cable:" + "|".join(str(row.get(key) or "") for key in (
                        "item_name", "cable_type", "project", "datacenter"
                    ))
                )
            return result

    def search_stock_positions(self, query: str, limit: int = 100) -> list[dict[str, Any]]:
        query = self._required(query, "поисковый запрос")
        return self.stock_balance(query=query, limit=max(1, min(int(limit), 500)))

    def global_search(self, query: str, limit: int = 30) -> list[dict[str, Any]]:
        """Искать складские позиции, поставки и инженеров одной ограниченной выдачей."""
        query = self._required(query, "поисковый запрос")
        if len(query) < 2:
            raise WarehouseError("Введите не менее двух символов")
        if len(query) > 120:
            raise WarehouseError("Поисковый запрос слишком длинный")
        limit = max(1, min(int(limit), 50))
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        term = f"%{escaped}%"
        match = " LIKE ? ESCAPE '\\' COLLATE NOCASE"
        select_position = """SELECT r.id, r.serial_number, r.inventory_number, r.item_name,
                                    r.vendor, r.model, r.project, r.shelf, r.datacenter,
                                    r.equipment_type, r.component_type, r.cable_type,
                                    COALESCE((SELECT d.delivery_number
                                              FROM delivery_lines l
                                              JOIN deliveries d ON d.id = l.delivery_id
                                              WHERE l.receipt_id = r.id LIMIT 1), '') delivery_number
                             FROM stock_receipts r"""
        position_rows: list[sqlite3.Row] = []
        position_ids: set[int] = set()

        def add_positions(rows: Iterable[sqlite3.Row]) -> None:
            for row in rows:
                row_id = int(row["id"])
                if row_id not in position_ids and len(position_rows) < limit:
                    position_ids.add(row_id)
                    position_rows.append(row)

        with connect(self.db_path) as db:
            # Exact identifiers use the existing partial unique indexes. This is
            # the dominant scanner/search path and stays fast on large databases.
            add_positions(db.execute(
                select_position
                + " WHERE trim(r.serial_number) <> '' AND trim(r.serial_number) = trim(?) COLLATE NOCASE LIMIT ?",
                (query, limit),
            ))
            add_positions(db.execute(
                select_position
                + " WHERE trim(r.inventory_number) <> '' AND r.inventory_number = ? COLLATE NOCASE LIMIT ?",
                (query, limit),
            ))

            exact_position = bool(position_rows)
            remaining = 0 if exact_position else limit - len(position_rows)
            if remaining:
                base_fields = (
                    "r.serial_number", "r.inventory_number", "r.item_name", "r.equipment_type",
                    "r.component_type", "r.cable_type", "r.vendor", "r.model", "r.project",
                    "r.shelf", "r.object_name", "r.datacenter", "r.responsible",
                    "r.order_number", "r.request_number",
                )
                add_positions(db.execute(
                    select_position
                    + f" WHERE {' OR '.join(field + match for field in base_fields)} LIMIT ?",
                    [term] * len(base_fields) + [remaining],
                ))

            remaining = 0 if exact_position else limit - len(position_rows)
            if remaining:
                has_migration_identity = db.execute(
                    """SELECT 1 FROM sqlite_master
                       WHERE type='table' AND name='migration_full_identities'"""
                ).fetchone() is not None
                if has_migration_identity:
                    migration_ids = [int(row[0]) for row in db.execute(
                        f"""SELECT DISTINCT target_receipt_id
                             FROM migration_full_identities
                             WHERE target_receipt_id IS NOT NULL AND (
                               canonical_item_name{match} OR source_item_name{match} OR
                               part_number{match} OR vendor{match} OR model{match})
                             LIMIT ?""",
                        [term] * 5 + [remaining],
                    )]
                    if migration_ids:
                        placeholders = ",".join("?" for _ in migration_ids)
                        add_positions(db.execute(
                            select_position + f" WHERE r.id IN ({placeholders}) LIMIT ?",
                            [*migration_ids, remaining],
                        ))

            remaining = 0 if exact_position else limit - len(position_rows)
            if remaining:
                related_ids = [int(row[0]) for row in db.execute(
                    f"""SELECT DISTINCT l.receipt_id
                         FROM delivery_lines l JOIN deliveries d ON d.id = l.delivery_id
                         WHERE l.receipt_id IS NOT NULL AND (
                           d.delivery_number{match} OR d.supplier{match} OR
                           l.delivery_number{match} OR l.order_number{match} OR
                           l.request_number{match}) LIMIT ?""",
                    [term] * 5 + [remaining],
                )]
                related_ids.extend(int(row[0]) for row in db.execute(
                    f"""SELECT DISTINCT a.receipt_id
                         FROM stock_issues i
                         JOIN stock_issue_allocations a ON a.issue_id = i.id
                         WHERE i.responsible{match} LIMIT ?""",
                    (term, remaining),
                ))
                target_serials = [str(row[0]) for row in db.execute(
                    f"""SELECT DISTINCT target_serial_number FROM stock_issues
                         WHERE trim(target_serial_number) <> '' AND target_hostname{match} LIMIT ?""",
                    (term, remaining),
                )]
                if related_ids:
                    unique_ids = list(dict.fromkeys(related_ids))[:remaining]
                    placeholders = ",".join("?" for _ in unique_ids)
                    add_positions(db.execute(
                        select_position + f" WHERE r.id IN ({placeholders}) LIMIT ?",
                        [*unique_ids, remaining],
                    ))
                if target_serials and len(position_rows) < limit:
                    placeholders = ",".join("?" for _ in target_serials)
                    add_positions(db.execute(
                        select_position
                        + f" WHERE trim(r.serial_number) <> '' AND r.serial_number COLLATE NOCASE IN ({placeholders}) LIMIT ?",
                        [*target_serials, limit - len(position_rows)],
                    ))

            remaining = 0 if exact_position else max(0, limit - len(position_rows))
            delivery_fields = (
                "d.delivery_number", "d.supplier", "d.source_filename", "d.uploaded_by",
                "l.serial_number", "l.asset_number", "l.order_number", "l.request_number",
                "l.item_name", "l.vendor", "l.model", "l.project", "l.shelf", "l.datacenter",
            )
            delivery_rows = db.execute(
                f"""SELECT DISTINCT d.id, d.delivery_number, d.supplier, d.status,
                           d.source_filename
                    FROM deliveries d
                    LEFT JOIN delivery_lines l ON l.delivery_id = d.id
                    WHERE {" OR ".join(field + match for field in delivery_fields)}
                    ORDER BY d.uploaded_at DESC, d.id DESC LIMIT ?""",
                [term] * len(delivery_fields) + [remaining],
            ).fetchall() if remaining else []
            remaining = max(0, remaining - len(delivery_rows))
            engineer_rows: list[dict[str, Any]] = []
            seen_engineers: set[str] = set()
            for table, name_column, date_column in (
                ("stock_receipts", "responsible", "created_at"),
                ("stock_issues", "responsible", "created_at"),
                ("audit_log", "author", "event_date"),
            ):
                if len(engineer_rows) >= remaining:
                    break
                for row in db.execute(
                    f"""SELECT {name_column} engineer, {date_column} last_activity
                         FROM {table} WHERE trim({name_column}) <> ''
                           AND {name_column}{match} LIMIT ?""",
                    (term, remaining - len(engineer_rows)),
                ):
                    key = str(row["engineer"]).casefold()
                    if key not in seen_engineers:
                        seen_engineers.add(key)
                        engineer_rows.append(dict(row))
        results: list[dict[str, Any]] = []
        for row in position_rows:
            item = dict(row)
            item_type = item["equipment_type"] or item["component_type"] or item["cable_type"]
            item["category"] = self._operational_category(
                item["equipment_type"], item["component_type"], item["cable_type"]
            )
            item["item_type"] = item_type
            item["position_key"] = (
                f"sn:{item['serial_number']}" if item["serial_number"] else
                "cable:" + "|".join(str(item.get(key) or "") for key in (
                    "item_name", "cable_type", "project", "datacenter"
                ))
            )
            results.append({"kind": "position", "position": item})
        results.extend({"kind": "delivery", "delivery": dict(row)} for row in delivery_rows)
        results.extend({"kind": "engineer", "engineer": dict(row)} for row in engineer_rows)
        return results[:limit]

    def position_card(
        self,
        serial_number: str = "",
        item_name: str = "",
        cable_type: str = "",
        project: str = "",
        datacenter: str = "",
        receipt_id: int | None = None,
        include_migration_audit: bool = True,
    ) -> dict[str, Any]:
        """Вернуть карточку агрегированной позиции и связанную хронологию."""
        serial_number = serial_number.strip().upper()
        where: list[str] = []
        params: list[Any] = []
        if receipt_id is not None:
            if isinstance(receipt_id, bool) or not isinstance(receipt_id, int) or receipt_id <= 0:
                raise WarehouseError("Некорректный идентификатор складской позиции")
            where.append("r.id = ?")
            params.append(receipt_id)
        elif serial_number:
            where.extend(("trim(r.serial_number) <> ''", "trim(r.serial_number) = trim(?) COLLATE NOCASE"))
            params.append(serial_number)
        else:
            item_name = self._required(item_name, "наименование")
            cable_type = self._required(cable_type, "тип кабеля")
            where.extend((
                "r.serial_number = ''", "r.item_name = ? COLLATE NOCASE",
                "r.cable_type = ? COLLATE NOCASE",
            ))
            params.extend((item_name, cable_type))
            if project:
                where.append("r.project = ? COLLATE NOCASE")
                params.append(project)
            if datacenter:
                where.append("r.datacenter = ? COLLATE NOCASE")
                params.append(datacenter)
        where_sql = " AND ".join(where)
        with connect(self.db_path) as db:
            receipts = db.execute(
                f"""SELECT r.*,
                           r.quantity - COALESCE(SUM(a.quantity), 0) AS available
                    FROM stock_receipts r
                    LEFT JOIN stock_issue_allocations a ON a.receipt_id = r.id
                    WHERE {where_sql} GROUP BY r.id ORDER BY r.receipt_date, r.id""",
                params,
            ).fetchall()
            if not receipts:
                raise WarehouseError("Позиция не найдена")
            exact_serial_number = str(receipts[0]["serial_number"] or "")
            receipt_ids = [int(row["id"]) for row in receipts]
            placeholders = ",".join("?" for _ in receipt_ids)
            identity = None
            if db.execute(
                """SELECT 1 FROM sqlite_master
                   WHERE type='table' AND name='migration_full_identities'"""
            ).fetchone() is not None:
                identity = db.execute(
                    f"""SELECT source_item_name,canonical_item_name,part_number,
                               category,equipment_type,component_type,vendor,model
                        FROM migration_full_identities
                        WHERE target_receipt_id IN ({placeholders})
                        ORDER BY authoritative DESC,id LIMIT 1""",
                    receipt_ids,
                ).fetchone()
            issues = db.execute(
                f"""SELECT i.*, a.receipt_id, a.quantity AS allocated_quantity
                    FROM stock_issues i
                    JOIN stock_issue_allocations a ON a.issue_id = i.id
                    WHERE a.receipt_id IN ({placeholders})
                    ORDER BY i.issue_date, i.id, a.id""",
                receipt_ids,
            ).fetchall()
            delivery_rows = db.execute(
                f"""SELECT l.*, d.delivery_number AS parent_delivery_number,
                           d.source_filename, d.uploaded_by, d.uploaded_at
                    FROM delivery_lines l JOIN deliveries d ON d.id = l.delivery_id
                    WHERE l.receipt_id IN ({placeholders})
                    ORDER BY l.updated_at, l.id""",
                receipt_ids,
            ).fetchall()
            target_events = db.execute(
                """SELECT * FROM stock_issues
                   WHERE trim(target_serial_number) <> ''
                     AND target_serial_number = ? COLLATE NOCASE
                   ORDER BY issue_date, id""",
                (exact_serial_number,),
            ).fetchall() if exact_serial_number else []
            issue_ids = sorted({int(row["id"]) for row in issues})
            audit_terms = [
                "(entity_type = 'stock_receipt' AND entity_id IN ("
                + placeholders + "))"
            ]
            audit_params: list[Any] = [str(value) for value in receipt_ids]
            if issue_ids:
                issue_placeholders = ",".join("?" for _ in issue_ids)
                audit_terms.append(
                    "(entity_type = 'stock_issue' AND entity_id IN ("
                    + issue_placeholders + "))"
                )
                audit_params.extend(str(value) for value in issue_ids)
            delivery_line_ids = [int(row["id"]) for row in delivery_rows]
            if delivery_line_ids:
                line_placeholders = ",".join("?" for _ in delivery_line_ids)
                audit_terms.append(
                    "(entity_type = 'delivery_line' AND entity_id IN ("
                    + line_placeholders + "))"
                )
                audit_params.extend(str(value) for value in delivery_line_ids)
            migration_clause = (
                "" if include_migration_audit
                else " AND action NOT LIKE 'MIGRATION_%'"
            )
            audits = db.execute(
                "SELECT * FROM audit_log WHERE (" + " OR ".join(audit_terms)
                + ")" + migration_clause + " ORDER BY event_date, id",
                audit_params,
            ).fetchall()
        first = dict(receipts[0])
        card = {key: first.get(key, "") for key in (
            "serial_number", "inventory_number", "item_name", "vendor", "model",
            "project", "object_name", "datacenter", "equipment_type",
            "component_type", "cable_type", "unit", "supplier", "order_number",
            "request_number", "receipt_date", "responsible",
        )}
        card["category"] = self._operational_category(
            card["equipment_type"], card["component_type"], card["cable_type"]
        )
        card["item_type"] = (
            card["equipment_type"] or card["component_type"] or card["cable_type"]
        )
        card["shelf"] = ", ".join(sorted({str(row["shelf"]) for row in receipts if row["shelf"]}))
        card["current_balance"] = sum(float(row["available"]) for row in receipts)
        card["status"] = "В наличии" if card["current_balance"] > 1e-9 else "Списано"
        card["delivery_number"] = ""
        card["hostname"] = ""
        card["rack_row"] = ""
        card["rack_unit"] = ""
        card["comment"] = ""
        card["canonical_name"] = str(identity["canonical_item_name"] or "") if identity else card["item_name"]
        card["source_name"] = str(identity["source_item_name"] or "") if identity else card["item_name"]
        card["part_number"] = str(identity["part_number"] or "") if identity else ""
        if identity:
            card["vendor"] = card["vendor"] or str(identity["vendor"] or "")
            card["model"] = card["model"] or str(identity["model"] or "")
            card["category"] = card["category"] or str(identity["category"] or "")
        if delivery_rows:
            delivery = dict(delivery_rows[-1])
            card["delivery_number"] = (
                delivery.get("parent_delivery_number") or delivery.get("delivery_number") or ""
            )
            card["order_number"] = card["order_number"] or delivery.get("order_number", "")
            card["request_number"] = card["request_number"] or delivery.get("request_number", "")
            card["comment"] = delivery.get("error_text", "")
        if target_events:
            card["hostname"] = target_events[-1]["target_hostname"]
        history: list[dict[str, Any]] = []
        for row in receipts:
            opening_state = bool(int(row["is_opening_balance"] or 0))
            history.append({
                "date": row["receipt_date"],
                "event_type": "Начальный остаток" if opening_state else "Приход",
                "quantity": float(row["quantity"]), "task": "",
                "responsible": row["responsible"],
                "comment": (
                    "Восстановлено начальное состояние до доступной истории операций"
                    if opening_state
                    else row["order_number"] or row["request_number"] or ""
                ),
                "sort_id": int(row["id"]),
            })
        for row in issues:
            history.append({
                "date": row["issue_date"], "event_type": "Расход",
                "quantity": -float(row["allocated_quantity"]),
                "task": (
                    f"{row['task_type']}-{row['task_number']}" if row["task_type"] else ""
                ),
                "responsible": row["responsible"], "comment": row["comment"],
                "sort_id": 1_000_000 + int(row["id"]),
            })
        for row in target_events:
            history.append({
                "date": row["issue_date"], "event_type": "Установлен компонент",
                "quantity": float(row["quantity"]),
                "task": (
                    f"{row['task_type']}-{row['task_number']}" if row["task_type"] else ""
                ),
                "responsible": row["responsible"],
                "comment": " ".join(filter(None, (
                    str(row["source_serial_number"] or row["source_item_name"]),
                    str(row["comment"] or ""),
                ))),
                "sort_id": 1_250_000 + int(row["id"]),
            })
        for row in delivery_rows:
            history.append({
                "date": row["updated_at"] or row["uploaded_at"],
                "event_type": "Принято по поставке",
                "quantity": float(row["quantity"]),
                "task": row["parent_delivery_number"] or row["delivery_number"],
                "responsible": row["updated_by"] or row["uploaded_by"],
                "comment": row["source_filename"],
                "sort_id": 1_500_000 + int(row["id"]),
            })
        for row in audits:
            history.append({
                "date": row["event_date"], "event_type": f"Запись журнала: {row['action']}",
                "quantity": "", "task": "", "responsible": row["author"],
                "comment": row["details"], "sort_id": 2_000_000 + int(row["id"]),
            })
        history.sort(key=lambda row: (str(row["date"]), int(row["sort_id"])))
        for row in history:
            row.pop("sort_id", None)
        return {"position": card, "history": history}

    def update_position_card(
        self, serial_number: str, fields: dict[str, Any]
    ) -> dict[str, Any]:
        """Update descriptive fields of one serialized card without changing identity/history."""

        actor = self._require_write()
        serial_number = self._required(str(serial_number or ""), "S/N")
        editable = (
            "item_name", "supplier", "vendor", "model", "project", "shelf",
            "object_name", "datacenter", "equipment_type", "component_type",
            "cable_type", "unit",
        )
        normalized: dict[str, str] = {}
        for field in editable:
            value = str(fields.get(field, "") or "").strip()
            if len(value) > (1000 if field == "item_name" else 255):
                raise WarehouseError(f"Поле «{field}» слишком длинное")
            normalized[field] = value
        # Обязательны только идентификационно значимые поля: наименование и
        # тип (проверяется ниже). Остальные — описательные (поставщик, объект,
        # ЦОД, единица, вендор, модель, проект, полка) — могут быть пустыми:
        # у 99% исторических карточек «Объект» и у части «Поставщик» изначально
        # пусты, и требование их заполнения блокировало бы любое редактирование.
        normalized["item_name"] = self._required(normalized["item_name"], "наименование")
        selected_types = [
            field for field in ("equipment_type", "component_type", "cable_type")
            if normalized[field]
        ]
        if len(selected_types) != 1:
            raise WarehouseError("Выберите ровно один тип карточки")

        with self.lock, connect(self.db_path) as db:
            rows = db.execute(
                "SELECT * FROM stock_receipts WHERE serial_number=? COLLATE NOCASE ORDER BY id",
                (serial_number,),
            ).fetchall()
            if len(rows) != 1:
                raise WarehouseError(
                    "Карточка не найдена" if not rows
                    else "Для S/N найдено несколько карточек; автоматическое редактирование заблокировано"
                )
            row = rows[0]
            type_field = selected_types[0]
            if normalized[type_field] != str(row[type_field] or ""):
                if self.reference_catalog.has_v2(db):
                    exists = db.execute(
                        """SELECT 1 FROM reference_values_v2 v
                           JOIN reference_domains_v2 d ON d.id=v.domain_id
                           WHERE d.domain_key=? AND v.display_name=? COLLATE NOCASE
                             AND v.active=1 AND v.approval_status='APPROVED'""",
                        (type_field, normalized[type_field]),
                    ).fetchone()
                else:
                    exists = db.execute(
                        """SELECT 1 FROM reference_values
                           WHERE kind=? AND name=? COLLATE NOCASE AND is_active=1""",
                        (type_field, normalized[type_field]),
                    ).fetchone()
                if exists is None:
                    raise WarehouseError("Выбранный тип отсутствует в активном справочнике")
            before = {field: str(row[field] or "") for field in editable}
            changed = {
                field: {"before": before[field], "after": normalized[field]}
                for field in editable if before[field] != normalized[field]
            }
            if changed:
                assignments = ",".join(f"{field}=?" for field in editable)
                db.execute(
                    f"UPDATE stock_receipts SET {assignments} WHERE id=?",
                    (*[normalized[field] for field in editable], int(row["id"])),
                )
                self._audit(
                    db, "EQUIPMENT_CARD_UPDATED", "stock_receipt", int(row["id"]),
                    {"serial_number": str(row["serial_number"]), "changed": changed,
                     "actor_id": actor["id"]},
                )
        result = self.position_card(serial_number=serial_number)["position"]
        result["updated"] = bool(changed)
        return result

    def _prepare_issue(
        self, source: dict[str, Any], references: dict[str, set[str]], line: int | None = None
    ) -> dict[str, Any]:
        prefix = f"Строка {line}: " if line is not None else ""
        try:
            task_type = str(source.get("task_type", "")).strip()
            if task_type and self.strict_reference_validation:
                all_task_types = {
                    str(row).casefold() for row in self.TASK_TYPES
                } | references.get("task_type", set())
                if task_type.casefold() not in all_task_types:
                    raise WarehouseError(f"тип задачи «{task_type}» отсутствует в справочнике")
            return {
                "issue_date": self._date(str(source.get("issue_date", "")), "дата"),
                "responsible": self._required(str(source.get("responsible", "")), "ФИО"),
                "task_type": task_type,
                "task_number": str(source.get("task_number", "")).strip(),
                "target_serial_number": str(source.get("target_serial_number", "")).strip().upper(),
                "target_hostname": str(source.get("target_hostname", "")).strip(),
                "source_serial_number": str(source.get("source_serial_number", "")).strip().upper(),
                "source_item_name": self._reference(
                    str(source.get("source_item_name", "")), "наименование", "item_name",
                    references, optional=True, strict=self.strict_reference_validation,
                ),
                "source_cable_type": self._reference(
                    str(source.get("source_cable_type", "")), "тип кабеля", "cable_type",
                    references, optional=True, strict=self.strict_reference_validation,
                ),
                "quantity": self._positive_number(source.get("quantity", "")),
                "comment": str(source.get("comment", "")).strip(),
            }
        except WarehouseError as error:
            raise WarehouseError(prefix + str(error)) from error

    @staticmethod
    def _available_receipts(db: sqlite3.Connection, where: str, params: tuple[Any, ...]) -> list[sqlite3.Row]:
        return db.execute(
            f"""SELECT r.*, r.quantity - COALESCE(SUM(a.quantity), 0) AS available
                FROM stock_receipts r
                LEFT JOIN stock_issue_allocations a ON a.receipt_id = r.id
                WHERE {where}
                GROUP BY r.id HAVING available > 0.0000001
                ORDER BY r.receipt_date, r.id""",
            params,
        ).fetchall()

    def _create_stock_issue(
        self, db: sqlite3.Connection, row: dict[str, Any], line: int | None = None
    ) -> int:
        prefix = f"Строка {line}: " if line is not None else ""
        is_cable = not row["source_serial_number"]
        if is_cable:
            if not row["source_item_name"] or not row["source_cable_type"]:
                raise WarehouseError(prefix + "для кабеля укажите наименование и тип кабеля")
            candidates = self._available_receipts(
                db,
                "r.item_name = ? COLLATE NOCASE AND r.cable_type = ? COLLATE NOCASE",
                (row["source_item_name"], row["source_cable_type"]),
            )
            if (row["task_type"] and not row["task_number"]) or (
                row["task_number"] and not row["task_type"]
            ):
                raise WarehouseError(prefix + "тип и номер задачи заполняются вместе")
        else:
            source_exists = db.execute(
                "SELECT id FROM stock_receipts WHERE trim(serial_number) <> '' AND trim(serial_number) = trim(?) COLLATE NOCASE",
                (row["source_serial_number"],),
            ).fetchone()
            if source_exists is None:
                raise WarehouseError(prefix + f"позиция с S/N «{row['source_serial_number']}» не найдена")
            candidates = self._available_receipts(
                db, "trim(r.serial_number) = trim(?) COLLATE NOCASE", (row["source_serial_number"],)
            )
            if not candidates:
                raise WarehouseError(
                    prefix + f"недостаточный остаток для S/N «{row['source_serial_number']}»: доступно 0"
                )
            source = candidates[0]
            if source["cable_type"]:
                raise WarehouseError(prefix + "кабель списывается по наименованию и типу кабеля")
            if not row["task_type"] or not row["task_number"]:
                raise WarehouseError(prefix + "для оборудования и компонентов обязательна задача")
            if row["target_serial_number"] == row["source_serial_number"]:
                raise WarehouseError(prefix + "оборудование нельзя списать само на себя")
            if source["component_type"] and not row["target_serial_number"]:
                raise WarehouseError(prefix + "компонент должен списываться на целевое оборудование")
            if source["component_type"]:
                target = db.execute(
                    """SELECT id FROM stock_receipts
                       WHERE trim(serial_number) <> '' AND trim(serial_number) = trim(?) COLLATE NOCASE AND equipment_type <> ''""",
                    (row["target_serial_number"],),
                ).fetchone()
                if target is None:
                    raise WarehouseError(prefix + "целевое оборудование с указанным S/N не найдено")
            if not float(row["quantity"]).is_integer():
                raise WarehouseError(prefix + "оборудование и компоненты списываются целыми штуками")
        available = sum(float(candidate["available"]) for candidate in candidates)
        if available + 1e-9 < row["quantity"]:
            label = row["source_serial_number"] or f"{row['source_item_name']} / {row['source_cable_type']}"
            raise WarehouseError(
                prefix + f"недостаточный остаток для «{label}»: доступно {available:g}"
            )
        cursor = db.execute(
            """INSERT INTO stock_issues(
                   issue_date, responsible, task_type, task_number, target_serial_number,
                   target_hostname, source_serial_number, source_item_name,
                   source_cable_type, quantity, comment
               ) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            tuple(row[key] for key in (
                "issue_date", "responsible", "task_type", "task_number",
                "target_serial_number", "target_hostname", "source_serial_number",
                "source_item_name", "source_cable_type", "quantity", "comment",
            )),
        )
        issue_id = int(cursor.lastrowid)
        remaining = float(row["quantity"])
        for candidate in candidates:
            allocated = min(remaining, float(candidate["available"]))
            if allocated > 1e-9:
                db.execute(
                    "INSERT INTO stock_issue_allocations(issue_id, receipt_id, quantity) VALUES (?, ?, ?)",
                    (issue_id, candidate["id"], allocated),
                )
                remaining -= allocated
            if remaining <= 1e-9:
                break
        self._audit(
            db, "ISSUE_CREATE", "stock_issue", issue_id,
            {"quantity": row["quantity"], "source_serial_number": row["source_serial_number"],
             "source_item_name": row["source_item_name"], "task_number": row["task_number"]},
        )
        return issue_id

    def _create_unmatched_stock_issue(
        self, db: sqlite3.Connection, row: dict[str, Any], reason: str
    ) -> int:
        """Persist a soft-import issue without allocations for later reconciliation."""
        comment = row["comment"]
        marker = f"Не сопоставлено: {reason}"
        row = {**row, "comment": f"{comment}; {marker}".strip("; ")}
        cursor = db.execute(
            """INSERT INTO stock_issues(
                   issue_date, responsible, task_type, task_number, target_serial_number,
                   target_hostname, source_serial_number, source_item_name,
                   source_cable_type, quantity, comment
               ) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            tuple(row[key] for key in (
                "issue_date", "responsible", "task_type", "task_number",
                "target_serial_number", "target_hostname", "source_serial_number",
                "source_item_name", "source_cable_type", "quantity", "comment",
            )),
        )
        issue_id = int(cursor.lastrowid)
        self._audit(db, "ISSUE_UNMATCHED", "stock_issue", issue_id, {"reason": reason})
        return issue_id

    @staticmethod
    def _is_unmatched_issue(
        db: sqlite3.Connection, row: dict[str, Any], reason: str
    ) -> bool:
        if "не найдена" in reason:
            return True
        if "для кабеля укажите наименование и тип кабеля" in reason:
            return True
        if not row["source_serial_number"] and row["source_item_name"] and row["source_cable_type"]:
            exists = db.execute(
                """SELECT 1 FROM stock_receipts
                   WHERE item_name = ? COLLATE NOCASE AND cable_type = ? COLLATE NOCASE""",
                (row["source_item_name"], row["source_cable_type"]),
            ).fetchone()
            return exists is None
        return False

    def add_stock_issue(self, **fields: Any) -> int:
        self._require_write()
        with connect(self.db_path) as db:
            row = self._prepare_issue(fields, self._reference_sets(db))
            self._collect_references(db, row, self.ISSUE_REFERENCE_FIELDS)
            return self._create_stock_issue(db, row)

    def scan_issue_serial(self, serial_number: str) -> dict[str, Any]:
        """Найти остаток одного S/N для экранного скан-листа."""
        serial = self._required(str(serial_number).strip().upper(), "S/N")
        with connect(self.db_path) as db:
            item = db.execute(
                """SELECT r.item_name, r.model, r.shelf, r.cable_type,
                          r.quantity - COALESCE(SUM(a.quantity), 0) AS available
                   FROM stock_receipts r
                   LEFT JOIN stock_issue_allocations a ON a.receipt_id = r.id
                   WHERE trim(r.serial_number) <> '' AND trim(r.serial_number) = trim(?) COLLATE NOCASE
                   GROUP BY r.id""",
                (serial,),
            ).fetchone()
        if item is None:
            return {
                "serial_number": serial, "found": False, "valid": False,
                "error": "S/N не найден — расход запрещён",
                "item_name": "", "model": "", "shelf": "", "available": 0,
            }
        available = float(item["available"])
        error = ""
        if item["cable_type"]:
            error = "Кабель нельзя списывать сканированием S/N"
        elif available < 1 - 1e-9:
            error = "Позиция уже списана или не имеет остатка"
        return {
            "serial_number": serial, "found": True, "valid": not error,
            "warning": "", "error": error, "item_name": item["item_name"],
            "model": item["model"], "shelf": item["shelf"], "available": available,
        }

    def confirm_scanned_issues(
        self, common_fields: dict[str, Any], serial_numbers: Iterable[str]
    ) -> dict[str, int]:
        """Строго списать экранный скан-лист одной транзакцией."""
        self._require_write()
        serials = [str(value).strip().upper() for value in serial_numbers]
        if not serials or any(not value for value in serials):
            raise WarehouseError("Список S/N пуст или содержит пустое значение")
        folded = [value.casefold() for value in serials]
        if len(set(folded)) != len(folded):
            raise WarehouseError("Список содержит повторяющиеся S/N")
        with connect(self.db_path) as db:
            references = self._reference_sets(db)
            imported = 0
            for line, serial in enumerate(serials, start=1):
                row = self._prepare_issue(
                    {**common_fields, "source_serial_number": serial,
                     "source_item_name": "", "source_cable_type": "", "quantity": 1},
                    references, line,
                )
                self._create_stock_issue(db, row, line)
                imported += 1
            self._audit(
                db, "SCANNED_ISSUE_IMPORT", "stock_issue",
                details={"count": imported, "unmatched": 0},
            )
        return {"imported": imported, "unmatched": 0}

    def import_stock_issue_rows(
        self, rows: Iterable[dict[str, Any]], *, soft: bool = True
    ) -> int:
        self._require_write()
        with connect(self.db_path) as db:
            references = self._reference_sets(db)
            prepared = [
                (line, self._prepare_issue(
                    self._soft_issue_source(source) if soft else source, references, line
                ))
                for line, source in enumerate(rows, start=2)
                if any(str(value or "").strip() for value in source.values())
            ]
            if not prepared:
                raise WarehouseError("В CSV-файле нет строк расхода")
            for line, row in prepared:
                self._collect_references(db, row, self.ISSUE_REFERENCE_FIELDS)
                try:
                    self._create_stock_issue(db, row, line)
                except WarehouseError as error:
                    reason = str(error)
                    unmatched = self._is_unmatched_issue(db, row, reason)
                    if not soft or not unmatched:
                        raise
                    self._create_unmatched_stock_issue(db, row, reason)
        return len(prepared)

    def preview_stock_issue_rows(
        self, rows: Iterable[dict[str, Any]], *, soft: bool = False
    ) -> dict[str, Any]:
        """Проверить расход на временной транзакции, включая последовательный остаток."""
        self._require_write()
        source_rows = [dict(row) for row in rows]
        errors: list[dict[str, Any]] = []
        preview_rows: list[dict[str, Any]] = []
        valid = duplicates = total = error_count = 0
        seen_serials: set[str] = set()
        with connect(self.db_path) as db:
            references = self._reference_sets(db)
            db.execute("BEGIN")
            try:
                for line, source in enumerate(source_rows, start=2):
                    if not any(str(value or "").strip() for value in source.values()):
                        continue
                    total += 1
                    reason = ""
                    prepared: dict[str, Any] | None = None
                    db.execute("SAVEPOINT issue_preview_row")
                    try:
                        candidate = self._soft_issue_source(source) if soft else source
                        prepared = self._prepare_issue(candidate, references, line)
                        serial = prepared["source_serial_number"].casefold()
                        if serial and serial in seen_serials:
                            duplicates += 1
                        try:
                            self._create_stock_issue(db, prepared, line)
                        except WarehouseError as issue_error:
                            reason_text = str(issue_error)
                            unmatched = self._is_unmatched_issue(db, prepared, reason_text)
                            if not soft or not unmatched:
                                raise
                            self._create_unmatched_stock_issue(db, prepared, reason_text)
                            prepared["warning"] = reason_text
                        if serial:
                            seen_serials.add(serial)
                        valid += 1
                        db.execute("RELEASE issue_preview_row")
                    except WarehouseError as error:
                        reason = str(error)
                        error_count += 1
                        if len(errors) < PREVIEW_ERROR_LIMIT:
                            errors.append({"line": line, "reason": reason})
                        db.execute("ROLLBACK TO issue_preview_row")
                        db.execute("RELEASE issue_preview_row")
                    if len(preview_rows) < PREVIEW_ROW_LIMIT:
                        shown = dict(prepared or source)
                        shown.update({"line": line, "valid": not reason, "error": reason})
                        preview_rows.append(shown)
            finally:
                db.rollback()
        if total == 0:
            error_count += 1
            errors.append({"line": 1, "reason": "В CSV-файле нет строк расхода"})
        return self._store_import_preview("issue", source_rows, {
            "total": total, "valid": valid, "new": valid,
            "duplicates": duplicates, "error_count": error_count,
            "errors": errors, "rows": preview_rows, "mode": "soft" if soft else "strict",
        })

    def confirm_stock_issue_preview(self, preview_id: str) -> int:
        self._require_write()
        preview = self._import_preview(preview_id, "issue")
        soft = preview.get("mode") == "soft"
        check = self.preview_stock_issue_rows(preview["rows"], soft=soft)
        self._import_previews.pop(check["preview_id"], None)
        if check["errors"]:
            raise WarehouseError(check["errors"][0]["reason"])
        imported = self.import_stock_issue_rows(preview["rows"], soft=soft)
        self._import_previews.pop(preview_id, None)
        return imported

    def preview_bulk_issue_serials(
        self, rows: Iterable[dict[str, Any]]
    ) -> dict[str, Any]:
        """Проверить строгий скан-лист S/N оборудования и компонентов."""
        self._require_write()
        source_rows = [dict(row) for row in rows]
        errors: list[dict[str, Any]] = []
        preview_rows: list[dict[str, Any]] = []
        found = unavailable = duplicates = total = 0
        seen: set[str] = set()
        with connect(self.db_path) as db:
            for line, source in enumerate(source_rows, start=2):
                if not any(str(value or "").strip() for value in source.values()):
                    continue
                total += 1
                serial = str(
                    source.get("serial_number", source.get("source_serial_number", ""))
                ).strip().upper()
                reason = ""
                item: sqlite3.Row | None = None
                if not serial:
                    reason = "S/N не может быть пустым"
                elif serial.casefold() in seen:
                    duplicates += 1
                    reason = f"S/N «{serial}» повторяется в файле"
                else:
                    seen.add(serial.casefold())
                    item = db.execute(
                        """SELECT r.*,
                                  r.quantity - COALESCE(SUM(a.quantity), 0) AS available
                           FROM stock_receipts r
                           LEFT JOIN stock_issue_allocations a ON a.receipt_id = r.id
                           WHERE trim(r.serial_number) <> '' AND trim(r.serial_number) = trim(?) COLLATE NOCASE
                           GROUP BY r.id""",
                        (serial,),
                    ).fetchone()
                    if item is None:
                        reason = f"S/N «{serial}» не найден"
                    elif item["cable_type"]:
                        reason = f"S/N «{serial}»: кабели нельзя списывать скан-листом"
                    elif float(item["available"]) < 1 - 1e-9:
                        unavailable += 1
                        reason = f"S/N «{serial}» уже списан или не имеет остатка"
                    else:
                        found += 1
                if reason:
                    errors.append({"line": line, "reason": reason})
                if len(preview_rows) < 50:
                    preview_rows.append({
                        "line": line, "serial_number": serial,
                        "item_name": item["item_name"] if item is not None else "",
                        "model": item["model"] if item is not None else "",
                        "available": float(item["available"]) if item is not None else 0,
                        "comment": str(source.get("comment", "")).strip(),
                        "valid": not reason, "error": reason,
                    })
        if total == 0:
            errors.append({"line": 1, "reason": "В CSV-файле нет S/N"})
        return self._store_import_preview("bulk_issue", source_rows, {
            "total": total, "valid": found, "found": found,
            "not_found": sum("не найден" in e["reason"] for e in errors),
            "unavailable": unavailable, "duplicates": duplicates,
            "new": found, "error_count": len(errors),
            "errors": errors, "rows": preview_rows,
        })

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
        """Списать весь подтвержденный S/N-список одной SQLite-транзакцией."""
        self._require_write()
        preview = self._import_preview(preview_id, "bulk_issue")
        check = self.preview_bulk_issue_serials(preview["rows"])
        self._import_previews.pop(check["preview_id"], None)
        if check["errors"]:
            raise WarehouseError(check["errors"][0]["reason"])
        common = {
            "issue_date": issue_date, "responsible": responsible,
            "task_type": task_type, "task_number": task_number,
            "target_serial_number": target_serial_number,
            "target_hostname": "", "source_item_name": "",
            "source_cable_type": "", "quantity": 1, "comment": comment,
        }
        with connect(self.db_path) as db:
            references = self._reference_sets(db)
            count = 0
            for line, source in enumerate(preview["rows"], start=2):
                if not any(str(value or "").strip() for value in source.values()):
                    continue
                serial = str(
                    source.get("serial_number", source.get("source_serial_number", ""))
                ).strip().upper()
                row = self._prepare_issue(
                    {**common, "source_serial_number": serial,
                     "comment": str(source.get("comment", "")).strip() or comment},
                    references, line,
                )
                self._create_stock_issue(db, row, line)
                count += 1
            self._audit(
                db, "BULK_ISSUE_IMPORT", "stock_issue", details={"count": count}
            )
        self._import_previews.pop(preview_id, None)
        return count

    def stock_issue_rows(self, limit: int | None = None) -> list[dict[str, Any]]:
        """Вернуть одну строку на расход с полями источника и цели."""
        return IssueRepository(self.db_path).list_rows(limit=limit)

    def data_quality_problems(
        self, date_from: str = "", date_to: str = "", limit: int | None = None
    ) -> dict[str, list[dict[str, Any]]]:
        """Return warehouse inconsistencies without preventing normal balance reads."""
        start, end = self._validated_period(date_from, date_to, optional=True)
        issue_where = ""
        params: list[Any] = []
        if start:
            issue_where += " AND i.issue_date >= ?"
            params.append(start)
        if end:
            issue_where += " AND i.issue_date <= ?"
            params.append(end)
        limit_sql = ""
        if limit is not None:
            limit = max(1, min(int(limit), 5_000))
            limit_sql = " LIMIT ?"
        with connect(self.db_path) as db:
            unmatched = [dict(row) for row in db.execute(
                f"""SELECT i.id, i.issue_date AS date, i.source_serial_number AS serial_number,
                           i.source_item_name AS item_name, i.source_cable_type AS cable_type,
                           i.quantity, COALESCE(SUM(a.quantity), 0) AS matched_quantity,
                           i.quantity - COALESCE(SUM(a.quantity), 0) AS unmatched_quantity,
                           i.responsible, i.comment
                      FROM stock_issues i
                      LEFT JOIN stock_issue_allocations a ON a.issue_id = i.id
                     WHERE 1=1 {issue_where}
                     GROUP BY i.id
                    HAVING unmatched_quantity > 0.0000001
                     ORDER BY i.issue_date, i.id{limit_sql}""",
                [*params, *([limit] if limit is not None else [])],
            )]
            duplicates = [dict(row) for row in db.execute(
                f"""SELECT serial_number, COUNT(*) AS count
                     FROM stock_receipts WHERE trim(serial_number) <> ''
                     GROUP BY serial_number COLLATE NOCASE HAVING COUNT(*) > 1
                     {limit_sql}""",
                ([limit] if limit is not None else []),
            )]
            negative = [dict(row) for row in db.execute(
                f"""SELECT r.serial_number, r.item_name,
                           SUM(r.quantity - COALESCE(a.issued, 0)) AS balance
                    FROM stock_receipts r
                    LEFT JOIN (
                        SELECT receipt_id, SUM(quantity) AS issued
                        FROM stock_issue_allocations GROUP BY receipt_id
                    ) a ON a.receipt_id = r.id
                    GROUP BY r.project, r.item_name, r.vendor, r.model, r.serial_number,
                             r.inventory_number, r.unit, r.object_name, r.equipment_type,
                             r.component_type, r.cable_type, r.datacenter
                    HAVING balance < -0.0000001{limit_sql}""",
                ([limit] if limit is not None else []),
            )]
            receipt_where = ""
            receipt_params: list[Any] = []
            if start:
                receipt_where += " AND receipt_date >= ?"
                receipt_params.append(start)
            if end:
                receipt_where += " AND receipt_date <= ?"
                receipt_params.append(end)
            incomplete = [dict(row) for row in db.execute(
                f"""SELECT id, receipt_date AS date, item_name, serial_number,
                            inventory_number, project, shelf, vendor, model, quantity
                       FROM stock_receipts
                      WHERE (trim(project) = '' OR trim(shelf) = '' OR trim(vendor) = ''
                             OR trim(model) = '') {receipt_where}
                      ORDER BY receipt_date, id{limit_sql}""",
                [*receipt_params, *([limit] if limit is not None else [])],
            )]
        return {
            "unmatched_issues": unmatched, "duplicate_serials": duplicates,
            "negative_balances": negative, "incomplete_rows": incomplete,
        }

    def data_quality_problem_counts(self) -> dict[str, int]:
        """Count problem groups without materializing every problematic row."""
        with connect(self.db_path) as db:
            row = db.execute(
                """WITH allocations AS (
                       SELECT receipt_id, SUM(quantity) issued
                       FROM stock_issue_allocations GROUP BY receipt_id
                   ), grouped_balance AS (
                       SELECT SUM(r.quantity - COALESCE(a.issued, 0)) balance
                       FROM stock_receipts r LEFT JOIN allocations a ON a.receipt_id = r.id
                       GROUP BY r.project, r.item_name, r.vendor, r.model, r.serial_number,
                                r.inventory_number, r.unit, r.object_name, r.equipment_type,
                                r.component_type, r.cable_type, r.datacenter
                   ), issue_allocations AS (
                       SELECT issue_id, SUM(quantity) matched
                       FROM stock_issue_allocations GROUP BY issue_id
                   )
                   SELECT
                     (SELECT COUNT(*) FROM stock_issues i
                       LEFT JOIN issue_allocations a ON a.issue_id = i.id
                       WHERE i.quantity - COALESCE(a.matched, 0) > 0.0000001) unmatched_issues,
                     (SELECT COUNT(*) FROM (
                       SELECT 1 FROM stock_receipts WHERE trim(serial_number) <> ''
                       GROUP BY serial_number COLLATE NOCASE HAVING COUNT(*) > 1
                     )) duplicate_serials,
                     (SELECT COUNT(*) FROM grouped_balance WHERE balance < -0.0000001) negative_balances,
                     (SELECT COUNT(*) FROM stock_receipts
                       WHERE trim(shelf) = '' OR trim(vendor) = ''
                          OR trim(model) = '') incomplete_rows"""
            ).fetchone()
        return {key: int(row[key]) for key in (
            "unmatched_issues", "duplicate_serials", "negative_balances", "incomplete_rows"
        )}

    def data_quality_summary(self, limit: int = 200) -> dict[str, Any]:
        """Return bounded problem examples and exact counts in the same SQL passes."""
        limit = max(1, min(int(limit), 5_000))

        def rows_and_count(rows: list[sqlite3.Row]) -> tuple[list[dict[str, Any]], int]:
            count = int(rows[0]["_total_count"]) if rows else 0
            result: list[dict[str, Any]] = []
            for source in rows:
                item = dict(source)
                item.pop("_total_count", None)
                result.append(item)
            return result, count

        with connect(self.db_path) as db:
            unmatched_rows = db.execute(
                """WITH problems AS (
                       SELECT i.id, i.issue_date AS date,
                              i.source_serial_number AS serial_number,
                              i.source_item_name AS item_name,
                              i.source_cable_type AS cable_type, i.quantity,
                              COALESCE(SUM(a.quantity), 0) AS matched_quantity,
                              i.quantity - COALESCE(SUM(a.quantity), 0) AS unmatched_quantity,
                              i.responsible, i.comment
                         FROM stock_issues i
                         LEFT JOIN stock_issue_allocations a ON a.issue_id = i.id
                        GROUP BY i.id
                       HAVING unmatched_quantity > 0.0000001
                   )
                   SELECT problems.*, COUNT(*) OVER() AS _total_count
                     FROM problems ORDER BY date, id LIMIT ?""",
                (limit,),
            ).fetchall()
            duplicate_rows = db.execute(
                """WITH dup AS (
                       SELECT serial_number
                         FROM stock_receipts WHERE trim(serial_number) <> ''
                        GROUP BY serial_number COLLATE NOCASE HAVING COUNT(*) > 1
                   ), problems AS (
                       SELECT r.id, r.receipt_date AS date, r.item_name,
                              r.serial_number, r.inventory_number, r.vendor,
                              r.model, r.quantity
                         FROM stock_receipts r
                         JOIN dup ON r.serial_number = dup.serial_number COLLATE NOCASE
                   )
                   SELECT problems.*, (SELECT COUNT(*) FROM dup) AS _total_count
                     FROM problems
                    ORDER BY serial_number COLLATE NOCASE, id LIMIT ?""",
                (limit,),
            ).fetchall()
            negative_rows = db.execute(
                """WITH allocations AS (
                       SELECT receipt_id, SUM(quantity) AS issued
                         FROM stock_issue_allocations GROUP BY receipt_id
                   ), problems AS (
                       SELECT r.serial_number, r.item_name,
                              SUM(r.quantity - COALESCE(a.issued, 0)) AS balance
                         FROM stock_receipts r
                         LEFT JOIN allocations a ON a.receipt_id = r.id
                        GROUP BY r.project, r.item_name, r.vendor, r.model,
                                 r.serial_number, r.inventory_number, r.unit,
                                 r.object_name, r.equipment_type, r.component_type,
                                 r.cable_type, r.datacenter
                       HAVING balance < -0.0000001
                   )
                   SELECT problems.*, COUNT(*) OVER() AS _total_count
                     FROM problems LIMIT ?""",
                (limit,),
            ).fetchall()
            incomplete_rows = db.execute(
                """SELECT id, receipt_date AS date, item_name, serial_number,
                          inventory_number, project, shelf, vendor, model, quantity,
                          COUNT(*) OVER() AS _total_count
                     FROM stock_receipts
                    WHERE trim(shelf) = '' OR trim(vendor) = ''
                       OR trim(model) = ''
                    ORDER BY receipt_date, id LIMIT ?""",
                (limit,),
            ).fetchall()
        groups = {
            "unmatched_issues": rows_and_count(unmatched_rows),
            "duplicate_serials": rows_and_count(duplicate_rows),
            "negative_balances": rows_and_count(negative_rows),
            "incomplete_rows": rows_and_count(incomplete_rows),
        }
        return {
            "problems": {key: value[0] for key, value in groups.items()},
            "counts": {key: value[1] for key, value in groups.items()},
        }

    def inventory_compare(self, rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
        """Compare a scanned S/N list with positive serialized stock."""
        scanned: list[str] = []
        for source in rows:
            serial = str(source.get("serial_number", source.get("source_serial_number", ""))).strip().upper()
            if serial:
                scanned.append(serial)
        if not scanned:
            raise WarehouseError("В CSV-файле нет S/N для инвентаризации")
        counts: dict[str, int] = {}
        for serial in scanned:
            counts[serial] = counts.get(serial, 0) + 1
        balance = {
            str(row["serial_number"]).upper(): row
            for row in self.stock_balance()
            if row["serial_number"] and float(row["balance"]) > 1e-9
        }
        scanned_set = set(counts)
        found = [{"serial_number": serial, "status": "Найдено"}
                 for serial in sorted(scanned_set & set(balance))]
        not_found = [{"serial_number": serial, "status": "Не найдено в базе"}
                     for serial in sorted(scanned_set - set(balance))]
        missing = [{"serial_number": serial, "status": "Есть в базе, но не было в скане"}
                   for serial in sorted(set(balance) - scanned_set)]
        duplicates = [{"serial_number": serial, "status": "Дубль в скане", "count": count}
                      for serial, count in sorted(counts.items()) if count > 1]
        result_rows = found + not_found + missing + duplicates
        return {
            "total": len(scanned), "found": found, "not_found": not_found,
            "missing": missing, "duplicates": duplicates, "rows": result_rows,
            "stats": {"found": len(found), "not_found": len(not_found),
                      "missing": len(missing), "duplicates": len(duplicates)},
        }

    def _reports_boundary(self) -> Any:
        if self.reports is None:
            raise RuntimeError("Reports boundary is not attached")
        return self.reports

    def add_work_log(
        self,
        work_date: str,
        task_source: str,
        task_type: str,
        task_number: str,
        description: str,
        status: str,
        comment: str = "",
    ) -> int:
        # DEPRECATED: use ApplicationContext.reports.add_work_log.
        return int(self._reports_boundary().add_work_log(
            work_date,
            task_source,
            task_type,
            task_number,
            description,
            status,
            comment,
        ))

    def add_work_logs(self, rows: Iterable[dict[str, Any]]) -> int:
        # DEPRECATED: use ApplicationContext.reports.add_work_logs.
        return int(self._reports_boundary().add_work_logs(list(rows)))

    def work_logs(
        self, date_from: str = "", date_to: str = ""
    ) -> list[dict[str, Any]]:
        # DEPRECATED: use ApplicationContext.reports.list_work_logs.
        return self._reports_boundary().work_logs(date_from, date_to)

    def import_work_log_rows(
        self, rows: Iterable[dict[str, Any]], *, soft: bool = False
    ) -> int:
        # DEPRECATED: use ApplicationContext.reports.import_work_log_rows.
        return int(
            self._reports_boundary().import_work_log_rows(
                list(rows), soft=soft
            )
        )

    def preview_work_log_rows(
        self, rows: Iterable[dict[str, Any]], *, soft: bool = True
    ) -> dict[str, Any]:
        # DEPRECATED: use ApplicationContext.reports.preview_work_log_rows.
        return self._reports_boundary().preview_work_log_rows(
            list(rows), soft=soft
        )

    def confirm_work_log_preview(self, preview_id: str) -> int:
        # DEPRECATED: use ApplicationContext.reports.confirm_work_log_preview.
        return int(
            self._reports_boundary().confirm_work_log_preview(preview_id)
        )

    def _validated_period(
        self, date_from: str, date_to: str, optional: bool = False
    ) -> tuple[str, str]:
        if optional and not date_from and not date_to:
            return "", ""
        start = self._date(date_from, "дата начала") if date_from else ""
        end = self._date(date_to, "дата окончания") if date_to else ""
        if not optional and (not start or not end):
            raise WarehouseError("Укажите дату начала и дату окончания")
        if start and end and start > end:
            raise WarehouseError("Дата начала не может быть позже даты окончания")
        return start, end

    def daily_report(self, report_date: str) -> list[dict[str, Any]]:
        # DEPRECATED: use ApplicationContext.reports.daily_report.
        return self._reports_boundary().daily_report(report_date)

    def weekly_report(
        self, start_date: str, end_date: str
    ) -> dict[str, Any]:
        # DEPRECATED: use ApplicationContext.reports.weekly_report.
        return self._reports_boundary().weekly_report(start_date, end_date)

    def weekly_report_rows(
        self, start_date: str, end_date: str
    ) -> list[dict[str, Any]]:
        # DEPRECATED: use ApplicationContext.reports.weekly_report_rows.
        return self._reports_boundary().weekly_report_rows(
            start_date, end_date
        )

    def import_daily_report_rows(
        self, filename: str, rows: Iterable[dict[str, Any]]
    ) -> dict[str, Any]:
        # DEPRECATED: use ApplicationContext.reports.import_daily_report_rows.
        return self._reports_boundary().import_daily_report_rows(
            filename, list(rows)
        )

    def daily_report_uploads(self) -> list[dict[str, Any]]:
        # DEPRECATED: use ApplicationContext.reports.daily_report_uploads.
        return self._reports_boundary().daily_report_uploads()

    def uploaded_daily_report(self, upload_id: int) -> list[dict[str, Any]]:
        # DEPRECATED: use ApplicationContext.reports.uploaded_daily_report.
        return self._reports_boundary().uploaded_daily_report(upload_id)

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

    def export_work_logs_csv(
        self, output_file: str | Path, date_from: str = "", date_to: str = ""
    ) -> Path:
        # DEPRECATED: use ApplicationContext.reports.export_work_logs_csv.
        return self._reports_boundary().export_work_logs_csv(
            output_file, date_from, date_to
        )

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
