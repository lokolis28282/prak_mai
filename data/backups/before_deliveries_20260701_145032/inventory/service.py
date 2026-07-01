"""Бизнес-логика складского учета."""

from __future__ import annotations

import csv
import json
import os
import secrets
import shutil
import sqlite3
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

from .db import DEFAULT_DB_PATH, connect, hash_password, initialize, verify_password
from .importing import PREVIEW_ERROR_LIMIT, PREVIEW_ROW_LIMIT


STRICT_REFERENCES = False


class WarehouseError(ValueError):
    """Ошибка проверки или выполнения складской операции."""


class WarehouseService:
    STRICT_REFERENCE_VALIDATION = STRICT_REFERENCES
    STRICT_REFERENCES = STRICT_REFERENCES
    ROLES = ("admin", "engineer", "viewer")
    STATUSES = ("IN_STOCK", "ISSUED", "RESERVED", "MAINTENANCE", "WRITTEN_OFF")
    TASK_SOURCES = ("DCIM", "ITSM", "Outlook", "Zabbix", "Складские операции")
    TASK_TYPES = ("ИЗМ", "ПНР", "ЗНР", "ЗНО", "ИНЦ")
    WORK_LOG_STATUSES = ("Выполнено", "В работе", "В ожидании")
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
    }
    RESTORE_BASE_TABLES = {"categories", "locations", "equipment", "operations"}

    def __init__(
        self,
        db_path: str | Path = DEFAULT_DB_PATH,
        *,
        strict_reference_validation: bool = STRICT_REFERENCE_VALIDATION,
    ):
        self.db_path = Path(db_path)
        self.strict_reference_validation = strict_reference_validation
        self.lock = threading.RLock()
        # Preview хранится только в памяти процесса: просмотр не создает строк в БД
        # и автоматически исчезает после перезапуска сервиса.
        self._import_previews: dict[str, dict[str, Any]] = {}
        self._last_import_rows: dict[tuple[str, str], list[dict[str, Any]]] = {}
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
        """Добавить новые фактические значения, не включая отключенные вручную."""
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
        row["vendor"] = str(row.get("vendor") or "Не указан")
        row["object_name"] = str(row.get("object_name") or "Не указано")
        row["datacenter"] = str(row.get("datacenter") or "Ixcellerate")
        row["unit"] = str(row.get("unit") or "шт")
        if not any(str(row.get(key) or "").strip() for key in (
            "equipment_type", "component_type", "cable_type"
        )):
            if str(row.get("serial_number") or "").strip():
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

    @staticmethod
    def _soft_work_log_source(source: dict[str, Any]) -> dict[str, Any]:
        row = dict(source)
        row["work_date"] = str(row.get("work_date") or date.today().isoformat())
        row["task_source"] = str(row.get("task_source") or "Не указан")
        row["task_type"] = str(row.get("task_type") or "")
        row["task_number"] = str(row.get("task_number") or "")
        row["status"] = str(row.get("status") or "Выполнено")
        return row

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
        if query.strip():
            term = f"%{query.strip()}%"
            where.append(
                "(serial_number LIKE ? OR inventory_number LIKE ? OR item_name LIKE ? "
                "OR model LIKE ? OR vendor LIKE ? OR project LIKE ? OR object_name LIKE ? "
                "OR shelf LIKE ?)"
            )
            params.extend([term] * 8)
        where_sql = "WHERE " + " AND ".join(where) if where else ""
        with connect(self.db_path) as db:
            rows = db.execute(
                f"""WITH lots AS (
                       SELECT r.id, r.project, r.item_name, r.vendor, r.model, r.serial_number,
                              r.inventory_number, r.shelf, r.object_name,
                              r.equipment_type, r.component_type, r.cable_type,
                              r.unit, r.datacenter,
                              r.quantity - COALESCE(SUM(a.quantity), 0) AS balance
                       FROM stock_receipts r
                       LEFT JOIN stock_issue_allocations a ON a.receipt_id = r.id
                       GROUP BY r.id
                   )
                   SELECT GROUP_CONCAT(id) AS receipt_ids,
                          project, item_name, vendor, model, serial_number, inventory_number,
                          SUM(balance) AS balance, unit,
                          GROUP_CONCAT(DISTINCT NULLIF(shelf, '')) AS shelf,
                          object_name, equipment_type, component_type, cable_type,
                          datacenter
                   FROM lots {where_sql}
                   GROUP BY project, item_name, vendor, model, serial_number, inventory_number,
                            unit, object_name, equipment_type, component_type,
                            cable_type, datacenter
                   ORDER BY item_name COLLATE NOCASE, model COLLATE NOCASE,
                            serial_number COLLATE NOCASE""",
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
        return self.stock_balance(query=query)[:max(1, min(int(limit), 500))]

    def position_card(
        self,
        serial_number: str = "",
        item_name: str = "",
        cable_type: str = "",
        project: str = "",
        datacenter: str = "",
    ) -> dict[str, Any]:
        """Вернуть карточку агрегированной позиции и связанную хронологию."""
        serial_number = serial_number.strip().upper()
        where: list[str] = []
        params: list[Any] = []
        if serial_number:
            where.append("r.serial_number = ? COLLATE NOCASE")
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
            receipt_ids = [int(row["id"]) for row in receipts]
            placeholders = ",".join("?" for _ in receipt_ids)
            issues = db.execute(
                f"""SELECT i.*, a.receipt_id, a.quantity AS allocated_quantity
                    FROM stock_issues i
                    JOIN stock_issue_allocations a ON a.issue_id = i.id
                    WHERE a.receipt_id IN ({placeholders})
                    ORDER BY i.issue_date, i.id, a.id""",
                receipt_ids,
            ).fetchall()
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
            audits = db.execute(
                "SELECT * FROM audit_log WHERE " + " OR ".join(audit_terms)
                + " ORDER BY event_date, id",
                audit_params,
            ).fetchall()
        first = dict(receipts[0])
        card = {key: first.get(key, "") for key in (
            "serial_number", "inventory_number", "item_name", "vendor", "model",
            "project", "object_name", "datacenter", "equipment_type",
            "component_type", "cable_type", "unit",
        )}
        card["shelf"] = ", ".join(sorted({str(row["shelf"]) for row in receipts if row["shelf"]}))
        card["current_balance"] = sum(float(row["available"]) for row in receipts)
        card["status"] = "В наличии" if card["current_balance"] > 1e-9 else "Списано"
        card["comment"] = ""
        history: list[dict[str, Any]] = []
        for row in receipts:
            history.append({
                "date": row["receipt_date"], "event_type": "Приход",
                "quantity": float(row["quantity"]), "task": "",
                "responsible": row["responsible"],
                "comment": row["order_number"] or row["request_number"] or "",
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
                           WHERE r.serial_number = ? COLLATE NOCASE
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

    def data_quality_problems(
        self, date_from: str = "", date_to: str = ""
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
                     ORDER BY i.issue_date, i.id""",
                params,
            )]
            duplicates = [dict(row) for row in db.execute(
                """SELECT serial_number, COUNT(*) AS count
                     FROM stock_receipts WHERE trim(serial_number) <> ''
                     GROUP BY serial_number COLLATE NOCASE HAVING COUNT(*) > 1"""
            )]
            negative = [row for row in self.stock_balance() if float(row["balance"]) < -1e-9]
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
                      ORDER BY receipt_date, id""",
                receipt_params,
            )]
        return {
            "unmatched_issues": unmatched, "duplicate_serials": duplicates,
            "negative_balances": negative, "incomplete_rows": incomplete,
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
        strict_references: bool | None = None,
    ) -> dict[str, str]:
        prefix = f"Строка {line_number}: " if line_number is not None else ""
        strict = self.strict_reference_validation if strict_references is None else strict_references
        try:
            return {
                "work_date": self._date(str(source.get("work_date", "")), "дата"),
                "task_source": self._reference(
                    str(source.get("task_source", "")), "источник задачи", "task_source",
                    references or {"task_source": {x.casefold() for x in self.TASK_SOURCES}},
                    strict=strict,
                ),
                "task_type": self._reference(
                    str(source.get("task_type", "")), "тип задачи", "task_type",
                    references or {"task_type": {x.casefold() for x in self.TASK_TYPES}},
                    optional=True, strict=strict,
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

    def import_work_log_rows(
        self, rows: Iterable[dict[str, Any]], *, soft: bool = False
    ) -> int:
        self._require_write()
        """Проверить весь набор и атомарно импортировать логи работ."""
        with connect(self.db_path) as db:
            references = self._reference_sets(db)
            prepared: list[dict[str, str]] = []
            for line_number, source in enumerate(rows, start=2):
                if not any(str(value or "").strip() for value in source.values()):
                    continue
                candidate = self._soft_work_log_source(source) if soft else source
                prepared.append(self._prepare_work_log(
                    candidate, line_number, references, strict_references=not soft
                ))
            if not prepared:
                raise WarehouseError("В CSV-файле нет логов работ")
            for field, kind in {
                "task_source": "task_source", "task_type": "task_type",
                "status": "work_log_status",
            }.items():
                for value in {str(row[field]).strip() for row in prepared if str(row[field]).strip()}:
                    self._collect_references(db, {field: value}, {field: kind})
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

    def preview_work_log_rows(
        self, rows: Iterable[dict[str, Any]], *, soft: bool = True
    ) -> dict[str, Any]:
        """Validate work logs without database writes and keep them for confirm."""
        self._require_write()
        source_rows = [dict(row) for row in rows]
        shown: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        error_count = valid = total = duplicates = 0
        seen: set[tuple[str, ...]] = set()
        with connect(self.db_path) as db:
            references = self._reference_sets(db)
            for line, source in enumerate(source_rows, start=2):
                if not any(str(value or "").strip() for value in source.values()):
                    continue
                total += 1
                reason = ""
                prepared: dict[str, Any] | None = None
                try:
                    candidate = self._soft_work_log_source(source) if soft else source
                    prepared = self._prepare_work_log(
                        candidate, line, references, strict_references=not soft
                    )
                    signature = self._work_log_values(prepared)
                    if signature in seen:
                        duplicates += 1
                    seen.add(signature)
                    valid += 1
                except WarehouseError as error:
                    reason = str(error)
                    error_count += 1
                    if len(errors) < PREVIEW_ERROR_LIMIT:
                        errors.append({"line": line, "reason": reason})
                if len(shown) < PREVIEW_ROW_LIMIT:
                    item = dict(prepared or source)
                    item.update({"line": line, "valid": not reason, "error": reason})
                    shown.append(item)
        if not total:
            error_count = 1
            errors.append({"line": 1, "reason": "В CSV-файле нет логов работ"})
        return self._store_import_preview("work_logs", source_rows, {
            "total": total, "valid": valid, "new": valid, "duplicates": duplicates,
            "error_count": error_count, "errors": errors, "rows": shown,
            "mode": "soft" if soft else "strict",
        })

    def confirm_work_log_preview(self, preview_id: str) -> int:
        self._require_write()
        preview = self._import_preview(preview_id, "work_logs")
        soft = preview.get("mode") == "soft"
        check = self.preview_work_log_rows(preview["rows"], soft=soft)
        self._import_previews.pop(check["preview_id"], None)
        if check["errors"]:
            raise WarehouseError(check["errors"][0]["reason"])
        imported = self.import_work_log_rows(preview["rows"], soft=soft)
        self._import_previews.pop(preview_id, None)
        return imported

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
        for row in self.data_quality_problems(start, end)["unmatched_issues"]:
            result.append({
                "date": row["date"], "report_block": "Проблемные строки",
                "task_number": "", "description": row["item_name"] or "Не сопоставленный расход",
                "quantity": f"{float(row['unmatched_quantity']):g}",
                "serial_number": row["serial_number"], "responsible": row["responsible"],
                "comment": row["comment"],
            })
        return result

    def weekly_report(self, date_from: str, date_to: str) -> dict[str, Any]:
        """Агрегировать существующие журналы и складские движения за период."""
        start, end = self._validated_period(date_from, date_to)
        with connect(self.db_path) as db:
            summary = dict(db.execute(
                """SELECT
                       (SELECT COUNT(*) FROM work_logs WHERE work_date BETWEEN ? AND ?) AS work_logs,
                       (SELECT COUNT(*) FROM stock_receipts
                         WHERE is_opening_balance = 0 AND receipt_date BETWEEN ? AND ?) AS receipts,
                       (SELECT COALESCE(SUM(quantity), 0) FROM stock_receipts
                         WHERE is_opening_balance = 0 AND receipt_date BETWEEN ? AND ?) AS received_quantity,
                       (SELECT COUNT(*) FROM stock_issues WHERE issue_date BETWEEN ? AND ?) AS issues,
                       (SELECT COALESCE(SUM(quantity), 0) FROM stock_issues
                         WHERE issue_date BETWEEN ? AND ?) AS issued_quantity,
                       (SELECT COALESCE(SUM(quantity), 0) FROM stock_receipts
                         WHERE is_opening_balance = 0 AND cable_type <> ''
                           AND receipt_date BETWEEN ? AND ?) AS cable_received,
                       (SELECT COALESCE(SUM(a.quantity), 0)
                          FROM stock_issues i
                          JOIN stock_issue_allocations a ON a.issue_id = i.id
                          JOIN stock_receipts r ON r.id = a.receipt_id
                         WHERE r.cable_type <> '' AND i.issue_date BETWEEN ? AND ?) AS cable_issued""",
                (start, end) * 7,
            ).fetchone())
            project_rows = db.execute(
                """WITH movements AS (
                       SELECT project, SUM(quantity) AS received, 0 AS issued
                         FROM stock_receipts
                        WHERE is_opening_balance = 0 AND receipt_date BETWEEN ? AND ?
                        GROUP BY project
                       UNION ALL
                       SELECT r.project, 0, SUM(a.quantity)
                         FROM stock_issues i
                         JOIN stock_issue_allocations a ON a.issue_id = i.id
                         JOIN stock_receipts r ON r.id = a.receipt_id
                        WHERE i.issue_date BETWEEN ? AND ? GROUP BY r.project
                   )
                   SELECT COALESCE(NULLIF(project, ''), 'Без проекта') AS name,
                          SUM(received) AS received, SUM(issued) AS issued
                     FROM movements GROUP BY project ORDER BY name COLLATE NOCASE""",
                (start, end, start, end),
            ).fetchall()
            type_rows = db.execute(
                """WITH receipt_types AS (
                       SELECT CASE WHEN equipment_type <> '' THEN 'Оборудование: ' || equipment_type
                                   WHEN component_type <> '' THEN 'Компонент: ' || component_type
                                   ELSE 'Кабель: ' || cable_type END AS name,
                              SUM(quantity) AS received, 0 AS issued
                         FROM stock_receipts
                        WHERE is_opening_balance = 0 AND receipt_date BETWEEN ? AND ?
                        GROUP BY name
                       UNION ALL
                       SELECT CASE WHEN r.equipment_type <> '' THEN 'Оборудование: ' || r.equipment_type
                                   WHEN r.component_type <> '' THEN 'Компонент: ' || r.component_type
                                   ELSE 'Кабель: ' || r.cable_type END,
                              0, SUM(a.quantity)
                         FROM stock_issues i
                         JOIN stock_issue_allocations a ON a.issue_id = i.id
                         JOIN stock_receipts r ON r.id = a.receipt_id
                        WHERE i.issue_date BETWEEN ? AND ? GROUP BY 1
                   )
                   SELECT name, SUM(received) AS received, SUM(issued) AS issued
                     FROM receipt_types GROUP BY name ORDER BY name COLLATE NOCASE""",
                (start, end, start, end),
            ).fetchall()
        problems = self.data_quality_problems(start, end)
        summary["problem_rows"] = sum(len(rows) for rows in problems.values())
        return {
            "date_from": start, "date_to": end, "summary": summary,
            "projects": [dict(row) for row in project_rows],
            "types": [dict(row) for row in type_rows],
            "problems": problems,
        }

    def weekly_report_rows(self, date_from: str, date_to: str) -> list[dict[str, Any]]:
        report = self.weekly_report(date_from, date_to)
        labels = {
            "work_logs": "Логи работ", "receipts": "Операции прихода",
            "received_quantity": "Принято позиций", "issues": "Операции расхода",
            "issued_quantity": "Списано позиций", "cable_received": "Кабеля принято",
            "cable_issued": "Кабеля списано", "problem_rows": "Проблемные строки",
        }
        rows = [
            {"Блок": "Итоги", "Показатель": labels[key], "Принято": value, "Списано": ""}
            for key, value in report["summary"].items()
        ]
        rows.extend(
            {"Блок": "Проекты", "Показатель": row["name"],
             "Принято": row["received"], "Списано": row["issued"]}
            for row in report["projects"]
        )
        rows.extend(
            {"Блок": "Типы", "Показатель": row["name"],
             "Принято": row["received"], "Списано": row["issued"]}
            for row in report["types"]
        )
        for kind, problem_rows in report["problems"].items():
            rows.extend({
                "Блок": "Проблемные строки", "Показатель": kind,
                "Принято": row.get("serial_number", row.get("item_name", "")),
                "Списано": row.get("unmatched_quantity", row.get("count", "")),
            } for row in problem_rows)
        return rows

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
