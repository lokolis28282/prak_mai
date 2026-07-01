"""Бизнес-логика складского учета."""

from __future__ import annotations

import csv
import json
import os
import shutil
import sqlite3
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

from .db import DEFAULT_DB_PATH, connect, hash_password, initialize, verify_password


class WarehouseError(ValueError):
    """Ошибка проверки или выполнения складской операции."""


class WarehouseService:
    ROLES = ("admin", "engineer", "viewer")
    STATUSES = ("IN_STOCK", "ISSUED", "RESERVED", "MAINTENANCE", "WRITTEN_OFF")
    TASK_SOURCES = ("DCIM", "ITSM", "Outlook", "Zabbix", "Складские операции")
    TASK_TYPES = ("ИЗМ", "ПНР", "ЗНР", "ЗНО", "ИНЦ")
    WORK_LOG_STATUSES = ("Выполнено", "В работе", "В ожидании")
    REFERENCE_KINDS = {
        "project": "Проекты",
        "object": "Объекты",
        "equipment_type": "Типы оборудования",
        "component_type": "Типы компонентов",
        "cable_type": "Типы кабеля",
        "supplier": "Поставщики",
        "vendor": "Вендоры",
        "unit": "Единицы учета",
        "task_source": "Источники задач",
        "task_type": "Типы задач",
        "work_log_status": "Статусы логов",
    }
    KEY_TABLES = {
        "categories", "locations", "equipment", "operations", "work_logs",
        "reference_values", "stock_receipts", "stock_issues",
        "stock_issue_allocations", "audit_log", "users",
        "daily_report_uploads", "daily_report_rows",
    }
    RESTORE_BASE_TABLES = {"categories", "locations", "equipment", "operations"}

    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH):
        self.db_path = Path(db_path)
        self.lock = threading.RLock()
        self._actor_email: ContextVar[str | None] = ContextVar(
            f"warehouse_actor_{id(self)}", default=None
        )
        self.default_admin_created = initialize(self.db_path)
        if self.default_admin_created:
            print(
                "Создан администратор ODE: email lokolis, пароль lokolis. "
                "Смените пароль после первого входа."
            )

    @staticmethod
    def _public_user(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        data = dict(row)
        data.pop("password_hash", None)
        return data

    def authenticate(self, email: str, password: str) -> dict[str, Any]:
        email = self._required(email, "email")
        with connect(self.db_path) as db:
            row = db.execute(
                "SELECT * FROM users WHERE email = ? COLLATE NOCASE AND is_active = 1",
                (email,),
            ).fetchone()
            if row is None or not verify_password(password, str(row["password_hash"])):
                raise WarehouseError("Неверный email или пароль")
            token = self._actor_email.set(str(row["email"]))
            try:
                self._audit(db, "LOGIN", "user", row["id"])
            finally:
                self._actor_email.reset(token)
            return self._public_user(row)

    def user_by_email(self, email: str) -> dict[str, Any]:
        with connect(self.db_path) as db:
            row = db.execute(
                "SELECT * FROM users WHERE email = ? COLLATE NOCASE AND is_active = 1",
                (email,),
            ).fetchone()
        if row is None:
            raise WarehouseError("Пользователь не найден или отключен")
        return self._public_user(row)

    def current_user(self) -> dict[str, Any]:
        # Прямые вызовы сервиса и CLI выполняются от встроенного администратора.
        return self.user_by_email(self._actor_email.get() or "lokolis")

    @contextmanager
    def user_context(self, email: str) -> Iterable[dict[str, Any]]:
        user = self.user_by_email(email)
        token = self._actor_email.set(str(user["email"]))
        try:
            yield user
        finally:
            self._actor_email.reset(token)

    def _require_role(self, *roles: str) -> dict[str, Any]:
        user = self.current_user()
        if user["role"] not in roles:
            raise WarehouseError("Недостаточно прав для выполнения операции")
        return user

    def _require_write(self) -> dict[str, Any]:
        return self._require_role("admin", "engineer")

    def users(self) -> list[dict[str, Any]]:
        self._require_role("admin")
        with connect(self.db_path) as db:
            return [self._public_user(row) for row in db.execute(
                """SELECT * FROM users
                   ORDER BY last_name COLLATE NOCASE, first_name COLLATE NOCASE, email"""
            )]

    def create_user(
        self, first_name: str, last_name: str, position: str,
        email: str, password: str, role: str,
    ) -> int:
        self._require_role("admin")
        if role not in self.ROLES:
            raise WarehouseError("Неизвестная роль")
        values = (
            self._required(first_name, "имя"), self._required(last_name, "фамилия"),
            self._required(position, "должность"), self._required(email, "email"),
            hash_password(self._required(password, "пароль")), role,
        )
        try:
            with connect(self.db_path) as db:
                cursor = db.execute(
                    """INSERT INTO users(
                           first_name, last_name, position, email, password_hash, role
                       ) VALUES (?, ?, ?, ?, ?, ?)""",
                    values,
                )
                self._audit(db, "USER_CREATE", "user", cursor.lastrowid, {"email": email, "role": role})
                return int(cursor.lastrowid)
        except sqlite3.IntegrityError as error:
            raise WarehouseError("Пользователь с таким email уже существует") from error

    def change_password(self, old_password: str, new_password: str) -> None:
        user = self.current_user()
        if len(new_password) < 6:
            raise WarehouseError("Новый пароль должен содержать не менее 6 символов")
        with connect(self.db_path) as db:
            row = db.execute("SELECT password_hash FROM users WHERE id = ?", (user["id"],)).fetchone()
            if row is None or not verify_password(old_password, str(row["password_hash"])):
                raise WarehouseError("Текущий пароль указан неверно")
            db.execute(
                "UPDATE users SET password_hash = ?, must_change_password = 0 WHERE id = ?",
                (hash_password(new_password), user["id"]),
            )
            self._audit(db, "PASSWORD_CHANGE", "user", user["id"])

    def update_profile(self, first_name: str, last_name: str, position: str) -> dict[str, Any]:
        user = self.current_user()
        values = (
            self._required(first_name, "имя"),
            self._required(last_name, "фамилия"),
            self._required(position, "должность"),
        )
        with connect(self.db_path) as db:
            db.execute(
                "UPDATE users SET first_name = ?, last_name = ?, position = ? WHERE id = ?",
                (*values, user["id"]),
            )
            self._audit(db, "PROFILE_UPDATE", "user", user["id"])
        return self.current_user()

    def _audit(
        self,
        db: sqlite3.Connection,
        action: str,
        entity_type: str,
        entity_id: int | str | None = None,
        details: dict[str, Any] | str | None = None,
    ) -> None:
        serialized = (
            json.dumps(details, ensure_ascii=False, sort_keys=True)
            if isinstance(details, dict)
            else str(details or "")
        )
        db.execute(
            """INSERT INTO audit_log(action, entity_type, entity_id, details, author)
               VALUES (?, ?, ?, ?, ?)""",
            (
                action, entity_type, "" if entity_id is None else str(entity_id),
                serialized, self._actor_email.get() or "lokolis",
            ),
        )

    def audit_entries(self, limit: int = 200) -> list[dict[str, Any]]:
        self._require_role("admin")
        if limit <= 0 or limit > 5000:
            raise WarehouseError("Лимит аудита должен быть от 1 до 5000")
        with connect(self.db_path) as db:
            return [
                dict(row) for row in db.execute(
                    """SELECT id, event_date, action, entity_type, entity_id, details, author
                       FROM audit_log ORDER BY event_date DESC, id DESC LIMIT ?""",
                    (limit,),
                )
            ]

    @property
    def backup_dir(self) -> Path:
        return self.db_path.parent / "backups"

    def list_backups(self) -> list[dict[str, Any]]:
        self._require_role("admin")
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        result = []
        for path in sorted(self.backup_dir.glob("*.db"), key=lambda item: item.stat().st_mtime, reverse=True):
            stat = path.stat()
            result.append({
                "name": path.name,
                "size": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
            })
        return result

    def _next_backup_path(self, prefix: str) -> Path:
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        candidate = self.backup_dir / f"{prefix}_{timestamp}.db"
        counter = 2
        while candidate.exists():
            candidate = self.backup_dir / f"{prefix}_{timestamp}_{counter}.db"
            counter += 1
        return candidate

    @staticmethod
    def _database_check(path: Path, required_tables: set[str]) -> dict[str, Any]:
        try:
            db = sqlite3.connect(path)
            messages = [str(row[0]) for row in db.execute("PRAGMA integrity_check")]
            tables = {
                str(row[0]) for row in db.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            db.close()
        except sqlite3.Error as error:
            return {"ok": False, "messages": [str(error)], "missing_tables": sorted(required_tables)}
        missing = sorted(required_tables - tables)
        return {
            "ok": messages == ["ok"] and not missing,
            "messages": messages,
            "missing_tables": missing,
        }

    def check_integrity(self) -> dict[str, Any]:
        self._require_role("admin")
        with self.lock:
            result = self._database_check(self.db_path, self.KEY_TABLES)
            try:
                with connect(self.db_path) as db:
                    self._audit(db, "INTEGRITY_CHECK", "database", details=result)
            except sqlite3.Error:
                # Результат проверки должен быть доступен даже при повреждении audit_log.
                pass
            return result

    def create_backup(self, prefix: str = "warehouse") -> dict[str, Any]:
        self._require_role("admin")
        with self.lock:
            destination = self._next_backup_path(prefix)
            try:
                source_db = sqlite3.connect(self.db_path)
                backup_db = sqlite3.connect(destination)
                source_db.backup(backup_db)
                backup_db.close()
                source_db.close()
                check = self._database_check(destination, self.KEY_TABLES)
                if not check["ok"]:
                    destination.unlink(missing_ok=True)
                    raise WarehouseError("Созданный backup не прошел проверку целостности")
                with connect(self.db_path) as db:
                    self._audit(
                        db, "BACKUP_CREATE", "database_backup", destination.name,
                        {"path": str(destination), "size": destination.stat().st_size},
                    )
                return next(item for item in self.list_backups() if item["name"] == destination.name)
            except (OSError, sqlite3.Error) as error:
                destination.unlink(missing_ok=True)
                raise WarehouseError(f"Не удалось создать backup: {error}") from error

    def _backup_by_name(self, filename: str) -> Path:
        if not filename or Path(filename).name != filename:
            raise WarehouseError("Некорректное имя backup-файла")
        path = self.backup_dir / filename
        if not path.is_file() or path.suffix.lower() != ".db":
            raise WarehouseError("Backup-файл не найден")
        return path

    def restore_backup(self, filename: str, confirmed: bool = False) -> dict[str, Any]:
        self._require_role("admin")
        if not confirmed:
            raise WarehouseError("Восстановление требует явного подтверждения")
        with self.lock:
            selected = self._backup_by_name(filename)
            check = self._database_check(selected, self.RESTORE_BASE_TABLES)
            if not check["ok"]:
                raise WarehouseError("Выбранный backup поврежден или не содержит ключевые таблицы")
            with connect(self.db_path) as db:
                self._audit(db, "RESTORE_START", "database_backup", selected.name)
            safety = self.create_backup(prefix="warehouse_before_restore")
            temporary = self.db_path.with_name(f".{self.db_path.name}.restore_tmp")
            try:
                shutil.copy2(selected, temporary)
                os.replace(temporary, self.db_path)
                for suffix in ("-wal", "-shm"):
                    Path(str(self.db_path) + suffix).unlink(missing_ok=True)
                initialize(self.db_path)
                final_check = self._database_check(self.db_path, self.KEY_TABLES)
                if not final_check["ok"]:
                    raise WarehouseError("Восстановленная база не прошла проверку целостности")
                with connect(self.db_path) as db:
                    self._audit(
                        db, "RESTORE_SUCCESS", "database_backup", selected.name,
                        {"safety_backup": safety["name"]},
                    )
                return {
                    "ok": True,
                    "restored_from": selected.name,
                    "safety_backup": safety["name"],
                    "integrity": final_check,
                }
            except Exception as error:
                temporary.unlink(missing_ok=True)
                safety_path = self._backup_by_name(safety["name"])
                shutil.copy2(safety_path, temporary)
                os.replace(temporary, self.db_path)
                initialize(self.db_path)
                with connect(self.db_path) as db:
                    self._audit(
                        db, "RESTORE_ROLLBACK", "database_backup", selected.name,
                        {"error": str(error), "safety_backup": safety["name"]},
                    )
                if isinstance(error, WarehouseError):
                    raise
                raise WarehouseError(f"Не удалось восстановить backup: {error}") from error

    def replace_production_database(
        self, uploaded_path: str | Path, confirmed: bool = False,
    ) -> dict[str, Any]:
        """Безопасно заменить рабочую БД загруженным SQLite-файлом."""
        actor = self._require_role("admin")
        if not confirmed:
            raise WarehouseError("Загрузка базы в прод требует явного подтверждения")
        source = Path(uploaded_path)
        if not source.is_file() or source.suffix.lower() != ".db":
            raise WarehouseError("Выберите SQLite-файл с расширением .db")
        source_check = self._database_check(source, self.RESTORE_BASE_TABLES)
        if not source_check["ok"]:
            raise WarehouseError("Загруженная база повреждена или не содержит ключевые таблицы")
        with self.lock:
            safety = self.create_backup(prefix="warehouse_before_prod_upload")
            temporary = self.db_path.with_name(f".{self.db_path.name}.prod_upload_tmp")
            try:
                shutil.copy2(source, temporary)
                os.replace(temporary, self.db_path)
                for suffix in ("-wal", "-shm"):
                    Path(str(self.db_path) + suffix).unlink(missing_ok=True)
                initialize(self.db_path)
                final_check = self._database_check(self.db_path, self.KEY_TABLES)
                if not final_check["ok"]:
                    raise WarehouseError("Загруженная база не прошла итоговую проверку")
                with connect(self.db_path) as db:
                    active_admins = int(db.execute(
                        "SELECT count(*) FROM users WHERE role = 'admin' AND is_active = 1"
                    ).fetchone()[0])
                    if active_admins == 0:
                        raise WarehouseError("В загруженной базе нет активного администратора")
                    self._audit(
                        db, "PRODUCTION_DATABASE_UPLOAD", "database", source.name,
                        {"safety_backup": safety["name"], "uploaded_by": actor["email"]},
                    )
                return {
                    "ok": True, "uploaded": source.name,
                    "safety_backup": safety["name"], "integrity": final_check,
                }
            except Exception as error:
                temporary.unlink(missing_ok=True)
                safety_path = self._backup_by_name(safety["name"])
                shutil.copy2(safety_path, temporary)
                os.replace(temporary, self.db_path)
                initialize(self.db_path)
                with connect(self.db_path) as db:
                    self._audit(
                        db, "PRODUCTION_DATABASE_ROLLBACK", "database", source.name,
                        {"error": str(error), "safety_backup": safety["name"]},
                    )
                if isinstance(error, WarehouseError):
                    raise
                raise WarehouseError(f"Не удалось загрузить базу в прод: {error}") from error

    @staticmethod
    def _required(value: str, field: str) -> str:
        value = value.strip()
        if not value:
            raise WarehouseError(f"Поле «{field}» не может быть пустым")
        return value

    @staticmethod
    def _date(value: str, field: str = "дата") -> str:
        value = value.strip()
        for date_format in ("%Y-%m-%d", "%d.%m.%Y"):
            try:
                return datetime.strptime(value, date_format).date().isoformat()
            except ValueError:
                pass
        raise WarehouseError(
            f"Поле «{field}» должно содержать дату в формате ГГГГ-ММ-ДД или ДД.ММ.ГГГГ"
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
                """SELECT
                       COALESCE((SELECT SUM(quantity) FROM stock_receipts), 0) AS receipts,
                       COALESCE((SELECT SUM(quantity) FROM stock_issues), 0) AS issues,
                       COALESCE((SELECT SUM(quantity) FROM stock_receipts), 0)
                         - COALESCE((SELECT SUM(quantity) FROM stock_issue_allocations), 0)
                         AS balance
                """
            ).fetchone()
        balances = self.stock_balance()
        return {
            "receipts": float(row["receipts"]),
            "issues": float(row["issues"]),
            "balance": float(row["balance"]),
            "positions": sum(float(item["balance"]) > 1e-9 for item in balances),
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
        """Получить редактируемые справочники Этапа 2."""
        if kind and kind not in self.REFERENCE_KINDS:
            raise WarehouseError("Неизвестный справочник")
        sql = "SELECT id, kind, name, is_active FROM reference_values WHERE 1 = 1"
        params: list[Any] = []
        if kind:
            sql += " AND kind = ?"
            params.append(kind)
        else:
            placeholders = ",".join("?" for _ in self.REFERENCE_KINDS)
            sql += f" AND kind IN ({placeholders})"
            params.extend(self.REFERENCE_KINDS)
        if active_only:
            sql += " AND is_active = 1"
        sql += " ORDER BY kind, is_active DESC, name COLLATE NOCASE"
        with connect(self.db_path) as db:
            return [dict(row) for row in db.execute(sql, params)]

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
        self._require_write()
        if kind not in self.REFERENCE_KINDS:
            raise WarehouseError("Неизвестный справочник")
        name = self._required(name, "значение справочника")
        if kind == "unit" and name not in {"шт", "м"}:
            raise WarehouseError("Поддерживаются единицы учета только «шт» и «м»")
        try:
            with connect(self.db_path) as db:
                cursor = db.execute(
                    "INSERT INTO reference_values(kind, name) VALUES (?, ?)", (kind, name)
                )
                reference_id = int(cursor.lastrowid)
                self._audit(
                    db, "REFERENCE_CREATE", "reference_value", reference_id,
                    {"kind": kind, "name": name},
                )
                return reference_id
        except sqlite3.IntegrityError as error:
            raise WarehouseError(f"Значение «{name}» уже существует") from error

    def set_reference_active(self, reference_id: int, is_active: bool) -> None:
        self._require_write()
        with connect(self.db_path) as db:
            cursor = db.execute(
                "UPDATE reference_values SET is_active = ? WHERE id = ?",
                (1 if is_active else 0, reference_id),
            )
            if not cursor.rowcount:
                raise WarehouseError("Значение справочника не найдено")
            self._audit(
                db, "REFERENCE_TOGGLE", "reference_value", reference_id,
                {"is_active": bool(is_active)},
            )

    @staticmethod
    def _reference_sets(db: sqlite3.Connection) -> dict[str, set[str]]:
        result: dict[str, set[str]] = {}
        for row in db.execute(
            "SELECT kind, name FROM reference_values WHERE is_active = 1"
        ):
            result.setdefault(str(row["kind"]), set()).add(str(row["name"]).casefold())
        return result

    @staticmethod
    def _reference(
        value: str, field: str, kind: str, references: dict[str, set[str]], optional: bool = False
    ) -> str:
        value = value.strip()
        if optional and not value:
            return ""
        if not value:
            raise WarehouseError(f"Поле «{field}» не может быть пустым")
        if value.casefold() not in references.get(kind, set()):
            raise WarehouseError(
                f"Поле «{field}»: значение «{value}» отсутствует в активном справочнике"
            )
        return value

    @staticmethod
    def _positive_number(value: Any, field: str = "количество / метраж") -> float:
        try:
            number = float(str(value).replace(",", "."))
        except ValueError as error:
            raise WarehouseError(f"Поле «{field}» должно быть числом") from error
        if number <= 0:
            raise WarehouseError(f"Поле «{field}» должно быть больше нуля")
        return number

    def _prepare_receipt(
        self,
        source: dict[str, Any],
        references: dict[str, set[str]],
        line_number: int | None = None,
    ) -> dict[str, Any]:
        prefix = f"Строка {line_number}: " if line_number is not None else ""
        try:
            row: dict[str, Any] = {
                "receipt_date": self._date(str(source.get("receipt_date", "")), "дата"),
                "responsible": self._required(str(source.get("responsible", "")), "ФИО"),
                "order_date": str(source.get("order_date", "")).strip(),
                "request_number": str(source.get("request_number", "")).strip(),
                "order_number": str(source.get("order_number", "")).strip(),
                "plu": str(source.get("plu", "")).strip(),
                "item_name": self._required(str(source.get("item_name", "")), "наименование"),
                "project": self._reference(
                    str(source.get("project", "")), "проект", "project", references, optional=True
                ),
                "serial_number": str(source.get("serial_number", "")).strip().upper(),
                "inventory_number": str(source.get("inventory_number", "")).strip().upper(),
                "supplier": self._reference(
                    str(source.get("supplier", "")), "поставщик", "supplier", references
                ),
                "vendor": self._reference(
                    str(source.get("vendor", "")), "вендор", "vendor", references
                ),
                "model": str(source.get("model", "")).strip(),
                "shelf": str(source.get("shelf", "")).strip(),
                "object_name": self._reference(
                    str(source.get("object_name", "")), "объект", "object", references
                ),
                "datacenter": self._required(
                    str(source.get("datacenter", "Ixcellerate")), "ЦОД"
                ),
                "equipment_type": self._reference(
                    str(source.get("equipment_type", "")), "тип оборудования",
                    "equipment_type", references, optional=True,
                ),
                "component_type": self._reference(
                    str(source.get("component_type", "")), "тип компонента",
                    "component_type", references, optional=True,
                ),
                "cable_type": self._reference(
                    str(source.get("cable_type", "")), "тип кабеля",
                    "cable_type", references, optional=True,
                ),
                "unit": self._reference(
                    str(source.get("unit", "")), "единица учета", "unit", references
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
            if row["cable_type"]:
                if row["unit"] != "м":
                    raise WarehouseError("для кабеля единица учета должна быть «м»")
            else:
                if not row["serial_number"]:
                    raise WarehouseError("S/N обязателен для оборудования и компонентов")
                if row["unit"] != "шт":
                    raise WarehouseError("для оборудования и компонентов единица учета должна быть «шт»")
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

    def add_stock_receipt(self, **fields: Any) -> int:
        self._require_write()
        with connect(self.db_path) as db:
            row = self._prepare_receipt(fields, self._reference_sets(db))
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

    def import_stock_receipt_rows(self, rows: Iterable[dict[str, Any]]) -> int:
        self._require_write()
        with connect(self.db_path) as db:
            references = self._reference_sets(db)
            prepared: list[dict[str, Any]] = []
            for line, source in enumerate(rows, start=2):
                if not any(str(value or "").strip() for value in source.values()):
                    continue
                row = self._prepare_receipt(source, references, line)
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

    def stock_balance(
        self,
        project: str = "",
        object_name: str = "",
        equipment_type: str = "",
        component_type: str = "",
        cable_type: str = "",
        unit: str = "",
        datacenter: str = "",
    ) -> list[dict[str, Any]]:
        """Рассчитать баланс как приход минус распределенный расход, без учета полки."""
        filters = {
            "project": project, "object_name": object_name,
            "equipment_type": equipment_type, "component_type": component_type,
            "cable_type": cable_type, "unit": unit, "datacenter": datacenter,
        }
        where: list[str] = []
        params: list[Any] = []
        for field, value in filters.items():
            if value:
                where.append(f"{field} = ? COLLATE NOCASE")
                params.append(value)
        where_sql = "WHERE " + " AND ".join(where) if where else ""
        with connect(self.db_path) as db:
            rows = db.execute(
                f"""WITH lots AS (
                       SELECT r.id, r.project, r.item_name, r.model, r.serial_number,
                              r.inventory_number, r.shelf, r.object_name,
                              r.equipment_type, r.component_type, r.cable_type,
                              r.unit, r.datacenter,
                              r.quantity - COALESCE(SUM(a.quantity), 0) AS balance
                       FROM stock_receipts r
                       LEFT JOIN stock_issue_allocations a ON a.receipt_id = r.id
                       GROUP BY r.id
                   )
                   SELECT project, item_name, model, serial_number, inventory_number,
                          SUM(balance) AS balance, unit,
                          GROUP_CONCAT(DISTINCT NULLIF(shelf, '')) AS shelf,
                          object_name, equipment_type, component_type, cable_type,
                          datacenter
                   FROM lots {where_sql}
                   GROUP BY project, item_name, model, serial_number, inventory_number,
                            unit, object_name, equipment_type, component_type,
                            cable_type, datacenter
                   ORDER BY item_name COLLATE NOCASE, model COLLATE NOCASE,
                            serial_number COLLATE NOCASE""",
                params,
            ).fetchall()
            return [dict(row) for row in rows]

    def _prepare_issue(
        self, source: dict[str, Any], references: dict[str, set[str]], line: int | None = None
    ) -> dict[str, Any]:
        prefix = f"Строка {line}: " if line is not None else ""
        try:
            task_type = str(source.get("task_type", "")).strip()
            if task_type:
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
                "source_item_name": str(source.get("source_item_name", "")).strip(),
                "source_cable_type": self._reference(
                    str(source.get("source_cable_type", "")), "тип кабеля", "cable_type",
                    references, optional=True,
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
                "SELECT id FROM stock_receipts WHERE serial_number = ? COLLATE NOCASE",
                (row["source_serial_number"],),
            ).fetchone()
            if source_exists is None:
                raise WarehouseError(prefix + f"позиция с S/N «{row['source_serial_number']}» не найдена")
            candidates = self._available_receipts(
                db, "r.serial_number = ? COLLATE NOCASE", (row["source_serial_number"],)
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
                       WHERE serial_number = ? COLLATE NOCASE AND equipment_type <> ''""",
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

    def add_stock_issue(self, **fields: Any) -> int:
        self._require_write()
        with connect(self.db_path) as db:
            row = self._prepare_issue(fields, self._reference_sets(db))
            return self._create_stock_issue(db, row)

    def import_stock_issue_rows(self, rows: Iterable[dict[str, Any]]) -> int:
        self._require_write()
        with connect(self.db_path) as db:
            references = self._reference_sets(db)
            prepared = [
                (line, self._prepare_issue(source, references, line))
                for line, source in enumerate(rows, start=2)
                if any(str(value or "").strip() for value in source.values())
            ]
            if not prepared:
                raise WarehouseError("В CSV-файле нет строк расхода")
            for line, row in prepared:
                self._create_stock_issue(db, row, line)
        return len(prepared)

    def stock_issue_rows(self) -> list[dict[str, Any]]:
        """Вернуть расход с автоматически подтянутыми полями прихода."""
        with connect(self.db_path) as db:
            rows = db.execute(
                """SELECT i.id, i.issue_date, i.responsible,
                          CASE WHEN i.task_type <> '' THEN i.task_type || '-' || i.task_number
                               ELSE '' END AS task_number,
                          i.target_serial_number, i.target_hostname,
                          COALESCE(target.model, '') AS target_model,
                          r.item_name, r.model AS component_model, a.quantity,
                          r.serial_number, r.inventory_number, r.shelf, r.object_name,
                          r.equipment_type, r.component_type, r.cable_type, r.project,
                          r.unit, i.comment
                   FROM stock_issues i
                   JOIN stock_issue_allocations a ON a.issue_id = i.id
                   JOIN stock_receipts r ON r.id = a.receipt_id
                   LEFT JOIN stock_receipts target
                     ON i.target_serial_number <> ''
                    AND target.serial_number = i.target_serial_number COLLATE NOCASE
                   ORDER BY i.issue_date DESC, i.id DESC, a.id"""
            ).fetchall()
            return [dict(row) for row in rows]

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
        self._require_write()
        """Добавить запись о выполненной работе."""
        with connect(self.db_path) as db:
            row = self._prepare_work_log({
                "work_date": work_date,
                "task_source": task_source,
                "task_type": task_type,
                "task_number": task_number,
                "description": description,
                "status": status,
                "comment": comment,
            }, references=self._reference_sets(db))
            cursor = db.execute(
                """INSERT INTO work_logs(
                       work_date, task_source, task_type, task_number,
                       description, status, comment
                   ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                self._work_log_values(row),
            )
            log_id = int(cursor.lastrowid)
            self._audit(
                db, "WORK_LOG_CREATE", "work_log", log_id,
                {"task": f"{row['task_type']}-{row['task_number']}"},
            )
            return log_id

    def _prepare_work_log(
        self, source: dict[str, Any], line_number: int | None = None,
        references: dict[str, set[str]] | None = None,
    ) -> dict[str, str]:
        prefix = f"Строка {line_number}: " if line_number is not None else ""
        try:
            return {
                "work_date": self._date(str(source.get("work_date", "")), "дата"),
                "task_source": self._reference(
                    str(source.get("task_source", "")), "источник задачи", "task_source",
                    references or {"task_source": {x.casefold() for x in self.TASK_SOURCES}},
                ),
                "task_type": self._reference(
                    str(source.get("task_type", "")), "тип задачи", "task_type",
                    references or {"task_type": {x.casefold() for x in self.TASK_TYPES}},
                ),
                "task_number": self._required(
                    str(source.get("task_number", "")), "номер задачи"
                ),
                "description": self._required(
                    str(source.get("description", "")), "описание работы"
                ),
                "status": self._reference(
                    str(source.get("status", "")), "статус", "work_log_status",
                    references or {
                        "work_log_status": {x.casefold() for x in self.WORK_LOG_STATUSES}
                    },
                ),
                "comment": str(source.get("comment", "")).strip(),
            }
        except WarehouseError as error:
            raise WarehouseError(prefix + str(error)) from error

    @staticmethod
    def _work_log_values(row: dict[str, str]) -> tuple[str, ...]:
        return (
            row["work_date"], row["task_source"], row["task_type"],
            row["task_number"], row["description"], row["status"], row["comment"],
        )

    def work_logs(self, date_from: str = "", date_to: str = "") -> list[dict[str, Any]]:
        """Получить логи работ за необязательный период."""
        date_from, date_to = self._validated_period(date_from, date_to, optional=True)
        sql = """SELECT id, work_date, task_source, task_type, task_number,
                        task_type || '-' || task_number AS full_task_name,
                        description, status, comment, created_at
                 FROM work_logs WHERE 1 = 1"""
        params: list[Any] = []
        if date_from:
            sql += " AND work_date >= ?"
            params.append(date_from)
        if date_to:
            sql += " AND work_date <= ?"
            params.append(date_to)
        sql += " ORDER BY work_date DESC, id DESC"
        with connect(self.db_path) as db:
            return [dict(row) for row in db.execute(sql, params).fetchall()]

    def import_work_log_rows(self, rows: Iterable[dict[str, Any]]) -> int:
        self._require_write()
        """Проверить весь набор и атомарно импортировать логи работ."""
        with connect(self.db_path) as db:
            references = self._reference_sets(db)
            prepared: list[dict[str, str]] = []
            for line_number, source in enumerate(rows, start=2):
                if not any(str(value or "").strip() for value in source.values()):
                    continue
                prepared.append(self._prepare_work_log(source, line_number, references))
            if not prepared:
                raise WarehouseError("В CSV-файле нет логов работ")
            db.executemany(
                """INSERT INTO work_logs(
                       work_date, task_source, task_type, task_number,
                       description, status, comment
                   ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                [self._work_log_values(row) for row in prepared],
            )
            self._audit(
                db, "WORK_LOG_IMPORT", "work_log", details={"count": len(prepared)}
            )
        return len(prepared)

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

    def daily_report(self, date_from: str, date_to: str) -> list[dict[str, Any]]:
        """Собрать сменный отчет: логи работ, затем приход и расход."""
        start, end = self._validated_period(date_from, date_to)
        result: list[dict[str, Any]] = []
        for row in reversed(self.work_logs(start, end)):
            result.append({
                "date": row["work_date"],
                "report_block": "Логи работ",
                "task_number": row["full_task_name"],
                "description": row["description"],
                "quantity": "",
                "serial_number": "",
                "responsible": "",
                "comment": row["comment"],
            })
        with connect(self.db_path) as db:
            new_receipts = db.execute(
                """SELECT receipt_date AS report_date, item_name, model,
                          inventory_number, serial_number, quantity, unit,
                          responsible, order_number, request_number
                   FROM stock_receipts
                   WHERE is_opening_balance = 0
                     AND receipt_date BETWEEN ? AND ?
                   ORDER BY receipt_date, id""",
                (start, end),
            ).fetchall()
            new_issues = db.execute(
                """SELECT i.issue_date AS report_date, i.task_type, i.task_number,
                          COALESCE(NULLIF(i.source_item_name, ''), MIN(r.item_name)) AS item_name,
                          COALESCE(NULLIF(i.source_serial_number, ''), MIN(r.serial_number)) AS serial_number,
                          i.quantity, MIN(r.unit) AS unit, i.responsible, i.comment
                   FROM stock_issues i
                   JOIN stock_issue_allocations a ON a.issue_id = i.id
                   JOIN stock_receipts r ON r.id = a.receipt_id
                   WHERE i.issue_date BETWEEN ? AND ?
                   GROUP BY i.id ORDER BY i.issue_date, i.id""",
                (start, end),
            ).fetchall()
        receipts: list[dict[str, Any]] = []
        issues: list[dict[str, Any]] = []
        for row in new_receipts:
            receipts.append({
                "date": row["report_date"], "report_block": "Приход", "task_number": "",
                "description": row["item_name"] + (f" / {row['model']}" if row["model"] else ""),
                "quantity": f"{float(row['quantity']):g} {row['unit']}",
                "serial_number": row["serial_number"], "responsible": row["responsible"],
                "comment": row["order_number"] or row["request_number"],
            })
        for row in new_issues:
            issues.append({
                "date": row["report_date"], "report_block": "Расход",
                "task_number": (
                    f"{row['task_type']}-{row['task_number']}" if row["task_type"] else ""
                ),
                "description": row["item_name"],
                "quantity": f"{float(row['quantity']):g} {row['unit']}",
                "serial_number": row["serial_number"], "responsible": row["responsible"],
                "comment": row["comment"],
            })
        receipts.sort(key=lambda row: row["date"])
        issues.sort(key=lambda row: row["date"])
        result.extend(receipts)
        result.extend(issues)
        return result

    def import_daily_report_rows(
        self, filename: str, rows: Iterable[dict[str, Any]],
    ) -> dict[str, Any]:
        """Атомарно сохранить готовый отчет отдельно от журналов работ."""
        user = self._require_write()
        filename = self._required(Path(filename).name, "имя файла")
        prepared: list[dict[str, str]] = []
        for line_number, source in enumerate(rows, start=2):
            if not any(str(value or "").strip() for value in source.values()):
                continue
            try:
                prepared.append({
                    "date": self._date(str(source.get("date", "")), "дата"),
                    "report_block": str(source.get("report_block", "")).strip(),
                    "task_number": str(source.get("task_number", "")).strip(),
                    "description": self._required(
                        str(source.get("description", "")), "описание / наименование"
                    ),
                    "quantity": str(source.get("quantity", "")).strip(),
                    "serial_number": str(source.get("serial_number", "")).strip(),
                    "responsible": str(source.get("responsible", "")).strip(),
                    "comment": str(source.get("comment", "")).strip(),
                })
            except WarehouseError as error:
                raise WarehouseError(f"Строка {line_number}: {error}") from error
        if not prepared:
            raise WarehouseError("В CSV-файле нет строк ежедневного отчета")
        with connect(self.db_path) as db:
            cursor = db.execute(
                """INSERT INTO daily_report_uploads(filename, uploaded_by, row_count)
                   VALUES (?, ?, ?)""",
                (filename, user["email"], len(prepared)),
            )
            upload_id = int(cursor.lastrowid)
            db.executemany(
                """INSERT INTO daily_report_rows(
                       upload_id, row_order, report_date, report_block, task_number,
                       description, quantity, serial_number, responsible, comment
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        upload_id, order, row["date"], row["report_block"],
                        row["task_number"], row["description"], row["quantity"],
                        row["serial_number"], row["responsible"], row["comment"],
                    )
                    for order, row in enumerate(prepared, start=1)
                ],
            )
            self._audit(
                db, "DAILY_REPORT_UPLOAD", "daily_report_upload", upload_id,
                {"filename": filename, "rows": len(prepared)},
            )
        return {"id": upload_id, "filename": filename, "row_count": len(prepared)}

    def daily_report_uploads(self) -> list[dict[str, Any]]:
        with connect(self.db_path) as db:
            return [dict(row) for row in db.execute(
                """SELECT id, filename, uploaded_at, uploaded_by, row_count
                   FROM daily_report_uploads ORDER BY uploaded_at DESC, id DESC"""
            )]

    def uploaded_daily_report(self, upload_id: int) -> list[dict[str, Any]]:
        with connect(self.db_path) as db:
            exists = db.execute(
                "SELECT 1 FROM daily_report_uploads WHERE id = ?", (upload_id,)
            ).fetchone()
            if exists is None:
                raise WarehouseError("Загруженный отчет не найден")
            return [dict(row) for row in db.execute(
                """SELECT report_date AS date, report_block, task_number, description,
                          quantity, serial_number, responsible, comment
                   FROM daily_report_rows WHERE upload_id = ? ORDER BY row_order""",
                (upload_id,),
            )]

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
        """Выгрузить логи работ в Excel-совместимый CSV с русскими заголовками."""
        path = Path(output_file)
        rows = [
            {
                "Дата": row["work_date"],
                "Источник задачи": row["task_source"],
                "Тип задачи": row["task_type"],
                "Номер задачи": row["task_number"],
                "Описание работы": row["description"],
                "Статус": row["status"],
                "Комментарий": row["comment"],
            }
            for row in self.work_logs(date_from, date_to)
        ]
        path.parent.mkdir(parents=True, exist_ok=True)
        self._write_csv(path, rows)
        return path

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
