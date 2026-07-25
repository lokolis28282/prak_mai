"""Подключение к SQLite и создание структуры базы данных."""

from __future__ import annotations

import sqlite3
import base64
import hashlib
import hmac
import secrets
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "warehouse.db"
PASSWORD_ITERATIONS = 260_000


def hash_password(password: str, *, salt: bytes | None = None) -> str:
    """Создать переносимый PBKDF2-SHA256 хеш пароля со случайной солью."""
    if not password:
        raise ValueError("Пароль не может быть пустым")
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)
    return "$".join((
        "pbkdf2_sha256", str(PASSWORD_ITERATIONS),
        base64.urlsafe_b64encode(salt).decode("ascii"),
        base64.urlsafe_b64encode(digest).decode("ascii"),
    ))


def verify_password(password: str, encoded: str) -> bool:
    """Проверить пароль без раскрытия хеша через compare_digest."""
    try:
        algorithm, iterations, salt_text, digest_text = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        salt = base64.urlsafe_b64decode(salt_text.encode("ascii"))
        expected = base64.urlsafe_b64decode(digest_text.encode("ascii"))
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations))
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS locations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS equipment (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category_id INTEGER NOT NULL REFERENCES categories(id),
    model TEXT NOT NULL,
    serial_number TEXT NOT NULL UNIQUE,
    inventory_number TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'IN_STOCK'
        CHECK (status IN ('IN_STOCK', 'ISSUED', 'RESERVED', 'MAINTENANCE', 'WRITTEN_OFF')),
    location_id INTEGER REFERENCES locations(id),
    quantity INTEGER NOT NULL DEFAULT 0 CHECK (quantity >= 0),
    notes TEXT NOT NULL DEFAULT '',
    datacenter TEXT NOT NULL DEFAULT 'Ixcellerate',
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS operations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    operation_date TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    operation_type TEXT NOT NULL
        CHECK (operation_type IN ('ADD', 'RECEIPT', 'ISSUE', 'MOVE')),
    equipment_id INTEGER NOT NULL REFERENCES equipment(id),
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    basis TEXT NOT NULL,
    responsible TEXT NOT NULL,
    from_location_id INTEGER REFERENCES locations(id),
    to_location_id INTEGER REFERENCES locations(id),
    comment TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS work_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    work_date TEXT NOT NULL,
    task_source TEXT NOT NULL,
    task_type TEXT NOT NULL,
    task_number TEXT NOT NULL,
    description TEXT NOT NULL,
    status TEXT NOT NULL,
    section TEXT NOT NULL DEFAULT '',
    needs_review INTEGER NOT NULL DEFAULT 0 CHECK (needs_review IN (0, 1)),
    comment TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS knowledge_articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL,
    category TEXT NOT NULL CHECK (category IN ('instructions', 'specifications')),
    created_by INTEGER REFERENCES users(id),
    created_by_name TEXT NOT NULL DEFAULT '',
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS knowledge_attachments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id INTEGER NOT NULL REFERENCES knowledge_articles(id) ON DELETE CASCADE,
    original_name TEXT NOT NULL,
    stored_name TEXT NOT NULL UNIQUE,
    relative_path TEXT NOT NULL UNIQUE,
    content_type TEXT NOT NULL,
    size_bytes INTEGER NOT NULL CHECK (size_bytes > 0),
    uploaded_by INTEGER REFERENCES users(id),
    uploaded_by_name TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS knowledge_article_tags (
    article_id INTEGER NOT NULL REFERENCES knowledge_articles(id) ON DELETE CASCADE,
    tag TEXT NOT NULL,
    tag_key TEXT NOT NULL,
    PRIMARY KEY (article_id, tag_key)
);

CREATE TABLE IF NOT EXISTS reference_values (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    name TEXT NOT NULL COLLATE NOCASE,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    UNIQUE(kind, name)
);

CREATE TABLE IF NOT EXISTS stock_receipts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    receipt_date TEXT NOT NULL,
    responsible TEXT NOT NULL,
    order_date TEXT NOT NULL DEFAULT '',
    request_number TEXT NOT NULL DEFAULT '',
    order_number TEXT NOT NULL DEFAULT '',
    plu TEXT NOT NULL DEFAULT '',
    item_name TEXT NOT NULL,
    project TEXT NOT NULL DEFAULT '',
    serial_number TEXT NOT NULL DEFAULT '',
    inventory_number TEXT NOT NULL DEFAULT '',
    supplier TEXT NOT NULL,
    vendor TEXT NOT NULL,
    model TEXT NOT NULL DEFAULT '',
    shelf TEXT NOT NULL DEFAULT '',
    object_name TEXT NOT NULL,
    datacenter TEXT NOT NULL DEFAULT 'Ixcellerate',
    equipment_type TEXT NOT NULL DEFAULT '',
    component_type TEXT NOT NULL DEFAULT '',
    cable_type TEXT NOT NULL DEFAULT '',
    unit TEXT NOT NULL,
    quantity REAL NOT NULL CHECK (quantity >= 0),
    legacy_equipment_id INTEGER UNIQUE REFERENCES equipment(id),
    is_opening_balance INTEGER NOT NULL DEFAULT 0 CHECK (is_opening_balance IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS stock_issues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    issue_date TEXT NOT NULL,
    responsible TEXT NOT NULL,
    task_type TEXT NOT NULL DEFAULT '',
    task_number TEXT NOT NULL DEFAULT '',
    target_serial_number TEXT NOT NULL DEFAULT '',
    target_hostname TEXT NOT NULL DEFAULT '',
    source_serial_number TEXT NOT NULL DEFAULT '',
    source_item_name TEXT NOT NULL DEFAULT '',
    source_cable_type TEXT NOT NULL DEFAULT '',
    quantity REAL NOT NULL CHECK (quantity > 0),
    comment TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS stock_issue_allocations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    issue_id INTEGER NOT NULL REFERENCES stock_issues(id) ON DELETE CASCADE,
    receipt_id INTEGER NOT NULL REFERENCES stock_receipts(id),
    quantity REAL NOT NULL CHECK (quantity > 0)
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_date TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL DEFAULT '',
    details TEXT NOT NULL DEFAULT '',
    author TEXT NOT NULL DEFAULT 'system'
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    position TEXT NOT NULL,
    email TEXT NOT NULL COLLATE NOCASE UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('admin', 'engineer', 'viewer')),
    must_change_password INTEGER NOT NULL DEFAULT 0 CHECK (must_change_password IN (0, 1)),
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS daily_report_uploads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL,
    uploaded_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    uploaded_by TEXT NOT NULL,
    row_count INTEGER NOT NULL DEFAULT 0 CHECK (row_count >= 0)
);

CREATE TABLE IF NOT EXISTS daily_report_rows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    upload_id INTEGER NOT NULL REFERENCES daily_report_uploads(id) ON DELETE CASCADE,
    row_order INTEGER NOT NULL,
    report_date TEXT NOT NULL,
    report_block TEXT NOT NULL DEFAULT '',
    task_number TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL,
    quantity TEXT NOT NULL DEFAULT '',
    serial_number TEXT NOT NULL DEFAULT '',
    responsible TEXT NOT NULL DEFAULT '',
    comment TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS deliveries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_filename TEXT NOT NULL,
    delivery_number TEXT NOT NULL DEFAULT '',
    supplier TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'Загружена'
        CHECK (status IN ('Загружена', 'Ожидается', 'Частично принята', 'Принята', 'Закрыта')),
    uploaded_by TEXT NOT NULL,
    uploaded_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    closed_by TEXT NOT NULL DEFAULT '',
    closed_at TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS delivery_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    delivery_id INTEGER NOT NULL REFERENCES deliveries(id) ON DELETE CASCADE,
    row_number INTEGER NOT NULL,
    receipt_statement TEXT NOT NULL DEFAULT '',
    order_date TEXT NOT NULL DEFAULT '',
    request_number TEXT NOT NULL DEFAULT '',
    order_number TEXT NOT NULL DEFAULT '',
    serial_number TEXT NOT NULL DEFAULT '',
    delivery_number TEXT NOT NULL DEFAULT '',
    supplier TEXT NOT NULL DEFAULT '',
    planned_date TEXT NOT NULL DEFAULT '',
    request_position TEXT NOT NULL DEFAULT '',
    order_position TEXT NOT NULL DEFAULT '',
    contract_number TEXT NOT NULL DEFAULT '',
    plu TEXT NOT NULL DEFAULT '',
    accounting_object TEXT NOT NULL DEFAULT '',
    quantity REAL NOT NULL DEFAULT 1 CHECK (quantity > 0),
    asset_number TEXT NOT NULL DEFAULT '',
    equipment_unit TEXT NOT NULL DEFAULT '',
    item_name TEXT NOT NULL DEFAULT '', model TEXT NOT NULL DEFAULT '',
    vendor TEXT NOT NULL DEFAULT '', project TEXT NOT NULL DEFAULT '',
    datacenter TEXT NOT NULL DEFAULT 'Ixcellerate', shelf TEXT NOT NULL DEFAULT '',
    object_name TEXT NOT NULL DEFAULT '', equipment_type TEXT NOT NULL DEFAULT '',
    component_type TEXT NOT NULL DEFAULT '', cable_type TEXT NOT NULL DEFAULT '',
    unit TEXT NOT NULL DEFAULT 'шт',
    state TEXT NOT NULL DEFAULT 'Ожидается'
        CHECK (state IN ('Ожидается', 'Принято', 'Уже на складе', 'Дубль в файле', 'Ошибка')),
    error_text TEXT NOT NULL DEFAULT '',
    receipt_id INTEGER UNIQUE REFERENCES stock_receipts(id),
    is_unplanned INTEGER NOT NULL DEFAULT 0 CHECK (is_unplanned IN (0, 1)),
    updated_by TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_equipment_category ON equipment(category_id);
CREATE INDEX IF NOT EXISTS idx_equipment_location ON equipment(location_id);
CREATE INDEX IF NOT EXISTS idx_equipment_status ON equipment(status);
CREATE INDEX IF NOT EXISTS idx_operations_date ON operations(operation_date);
CREATE INDEX IF NOT EXISTS idx_operations_equipment ON operations(equipment_id);
CREATE INDEX IF NOT EXISTS idx_operations_type ON operations(operation_type);
CREATE INDEX IF NOT EXISTS idx_work_logs_date ON work_logs(work_date);
CREATE INDEX IF NOT EXISTS idx_work_logs_source ON work_logs(task_source);
CREATE INDEX IF NOT EXISTS idx_work_logs_status ON work_logs(status);
CREATE INDEX IF NOT EXISTS idx_knowledge_articles_category_updated
    ON knowledge_articles(category, is_active, updated_at DESC, title COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_knowledge_attachments_article
    ON knowledge_attachments(article_id, id);
CREATE INDEX IF NOT EXISTS idx_knowledge_article_tags_tag
    ON knowledge_article_tags(tag_key, article_id);
CREATE INDEX IF NOT EXISTS idx_reference_values_kind ON reference_values(kind, is_active, name);
CREATE UNIQUE INDEX IF NOT EXISTS idx_stock_receipts_serial_unique
    ON stock_receipts(serial_number COLLATE NOCASE) WHERE trim(serial_number) <> '';
CREATE INDEX IF NOT EXISTS idx_stock_receipts_serial_trim_nocase
    ON stock_receipts(trim(serial_number) COLLATE NOCASE) WHERE trim(serial_number) <> '';
CREATE UNIQUE INDEX IF NOT EXISTS idx_stock_receipts_inventory_unique
    ON stock_receipts(inventory_number COLLATE NOCASE) WHERE trim(inventory_number) <> '';
CREATE INDEX IF NOT EXISTS idx_stock_receipts_date ON stock_receipts(receipt_date);
CREATE INDEX IF NOT EXISTS idx_stock_receipts_cable ON stock_receipts(item_name, cable_type);
CREATE INDEX IF NOT EXISTS idx_stock_receipts_supplier_nocase ON stock_receipts(supplier COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_stock_receipts_vendor_nocase ON stock_receipts(vendor COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_stock_receipts_model_nocase ON stock_receipts(model COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_stock_receipts_item_name_nocase ON stock_receipts(item_name COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_stock_receipts_project_nocase ON stock_receipts(project COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_stock_receipts_equipment_type_nocase ON stock_receipts(equipment_type COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_stock_receipts_component_type_nocase ON stock_receipts(component_type COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_stock_receipts_cable_type_nocase ON stock_receipts(cable_type COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_stock_issues_date ON stock_issues(issue_date);
CREATE INDEX IF NOT EXISTS idx_stock_issue_allocations_issue ON stock_issue_allocations(issue_id);
CREATE INDEX IF NOT EXISTS idx_stock_issue_allocations_receipt ON stock_issue_allocations(receipt_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_date ON audit_log(event_date);
CREATE INDEX IF NOT EXISTS idx_audit_log_action ON audit_log(action);
CREATE INDEX IF NOT EXISTS idx_audit_log_entity ON audit_log(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_daily_report_uploads_date ON daily_report_uploads(uploaded_at);
CREATE INDEX IF NOT EXISTS idx_daily_report_rows_upload ON daily_report_rows(upload_id, row_order);
CREATE INDEX IF NOT EXISTS idx_daily_report_rows_date ON daily_report_rows(report_date);
CREATE INDEX IF NOT EXISTS idx_deliveries_search ON deliveries(delivery_number, supplier, status);
CREATE INDEX IF NOT EXISTS idx_delivery_lines_delivery ON delivery_lines(delivery_id, row_number);
CREATE INDEX IF NOT EXISTS idx_delivery_lines_serial ON delivery_lines(serial_number COLLATE NOCASE);
"""

# Promoted historical databases deliberately skip the legacy SCHEMA replay.
# Knowledge owns this additive schema and must still be installed there.
KNOWLEDGE_SCHEMA = """
CREATE TABLE IF NOT EXISTS knowledge_articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL,
    category TEXT NOT NULL CHECK (category IN ('instructions', 'specifications')),
    created_by INTEGER REFERENCES users(id),
    created_by_name TEXT NOT NULL DEFAULT '',
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE TABLE IF NOT EXISTS knowledge_attachments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id INTEGER NOT NULL REFERENCES knowledge_articles(id) ON DELETE CASCADE,
    original_name TEXT NOT NULL,
    stored_name TEXT NOT NULL UNIQUE,
    relative_path TEXT NOT NULL UNIQUE,
    content_type TEXT NOT NULL,
    size_bytes INTEGER NOT NULL CHECK (size_bytes > 0),
    uploaded_by INTEGER REFERENCES users(id),
    uploaded_by_name TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE TABLE IF NOT EXISTS knowledge_article_tags (
    article_id INTEGER NOT NULL REFERENCES knowledge_articles(id) ON DELETE CASCADE,
    tag TEXT NOT NULL,
    tag_key TEXT NOT NULL,
    PRIMARY KEY (article_id, tag_key)
);
CREATE INDEX IF NOT EXISTS idx_knowledge_articles_category_updated
    ON knowledge_articles(category, is_active, updated_at DESC, title COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_knowledge_attachments_article
    ON knowledge_attachments(article_id, id);
CREATE INDEX IF NOT EXISTS idx_knowledge_article_tags_tag
    ON knowledge_article_tags(tag_key, article_id);
"""

REPORTS_UVR_REFERENCES = {
    "task_source": (
        "PNR", "ИЗМ", "ЗНР", "ЗНО", "Сопровождение", "ROOMS", "Time",
        "Zabbix", "Заказ", "Волна", "DCIM", "ITSM", "Outlook", "Rooms",
        "Склад", "Другое",
    ),
    "task_type": (
        "ЗНО", "ЗНР", "ИЗМ", "ИНЦ", "Ночные работы", "ПНР", "Работа",
        "Другое",
    ),
    "work_log_status": (
        "Выполнено", "В работе", "В ожидании", "Ожидание", "Отложено",
    ),
    "work_log_section": (
        "Solar", "Виртуализация", "SALT", "BigData", "ТОРГ", "БД", "Linux",
        "NTP", "Exchange", "Digital", "USB-hub", "Cognos", "QlikView",
        "АССД", "X5ID", "CIP", "Подписки микросервис", "Loymax",
        "GPU-инфраструктура", "УЦ", "Голограмма", "Пополнение TC5",
        "FnR (F&R)", "Видеоконференции", "Серверы интеграции УПГУ",
        "Серверы СРК", "WAF Pro — система контроля и защиты веб-приложений",
        "1C", "APM",
    ),
}


@contextmanager
def connect(db_path: str | Path = DEFAULT_DB_PATH) -> Iterator[sqlite3.Connection]:
    """Открыть БД, включить внешние ключи и возвращать строки по именам полей."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize(db_path: str | Path = DEFAULT_DB_PATH) -> bool:
    """Создать таблицы и индексы, если они еще не существуют."""
    default_admin_created = False
    with connect(db_path) as connection:
        full_marker = connection.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type='table' AND name='migration_full_marker'"
        ).fetchone()
        # The promoted full database already carries the compatible operational
        # schema plus preservation-aware serial indexes. Replaying the legacy
        # schema would attempt to impose NOCASE uniqueness that the historical
        # build intentionally did not claim.
        if full_marker is None:
            connection.executescript(SCHEMA)
        if full_marker is not None and connection.execute(
            "SELECT 1 FROM reference_values LIMIT 1"
        ).fetchone() is not None:
            # A promoted full DB needs the compatibility/reference population
            # exactly once. Repeating INSERT OR IGNORE would advance
            # sqlite_sequence even though no business row changes.
            return False
        work_log_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'work_logs'"
        ).fetchone()[0]
        if "CHECK (task_source" in str(work_log_sql):
            connection.executescript(
                """ALTER TABLE work_logs RENAME TO work_logs_stage1;
                   CREATE TABLE work_logs (
                       id INTEGER PRIMARY KEY AUTOINCREMENT,
                       work_date TEXT NOT NULL,
                       task_source TEXT NOT NULL,
                       task_type TEXT NOT NULL,
                       task_number TEXT NOT NULL,
                       description TEXT NOT NULL,
                       status TEXT NOT NULL,
                       comment TEXT NOT NULL DEFAULT '',
                       created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
                   );
                   INSERT INTO work_logs(
                       id, work_date, task_source, task_type, task_number,
                       description, status, comment, created_at
                   )
                   SELECT id, work_date, task_source, task_type, task_number,
                          description, status, comment, created_at
                   FROM work_logs_stage1;
                   DROP TABLE work_logs_stage1;
                   CREATE INDEX idx_work_logs_date ON work_logs(work_date);
                   CREATE INDEX idx_work_logs_source ON work_logs(task_source);
                   CREATE INDEX idx_work_logs_status ON work_logs(status);"""
            )
        work_log_columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(work_logs)").fetchall()
        }
        if "section" not in work_log_columns:
            connection.execute(
                "ALTER TABLE work_logs ADD COLUMN section TEXT NOT NULL DEFAULT ''"
            )
        if "needs_review" not in work_log_columns:
            connection.execute(
                "ALTER TABLE work_logs ADD COLUMN needs_review INTEGER NOT NULL "
                "DEFAULT 0 CHECK (needs_review IN (0, 1))"
            )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_work_logs_section ON work_logs(section)"
        )
        columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(equipment)").fetchall()
        }
        if "datacenter" not in columns:
            connection.execute(
                "ALTER TABLE equipment ADD COLUMN datacenter "
                "TEXT NOT NULL DEFAULT 'Ixcellerate'"
            )
        connection.execute(
            "UPDATE equipment SET datacenter = 'Ixcellerate' "
            "WHERE datacenter IS NULL OR trim(datacenter) = ''"
        )
        receipt_columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(stock_receipts)").fetchall()
        }
        if "datacenter" not in receipt_columns:
            connection.execute(
                "ALTER TABLE stock_receipts ADD COLUMN datacenter "
                "TEXT NOT NULL DEFAULT 'Ixcellerate'"
            )
        receipt_sql = str(connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'stock_receipts'"
        ).fetchone()[0])
        if "CHECK (unit IN ('шт', 'м'))" in receipt_sql:
            # PRAGMA foreign_keys меняется только вне активной транзакции.
            connection.commit()
            connection.execute("PRAGMA foreign_keys = OFF")
            connection.executescript(
                """BEGIN;
                   CREATE TABLE stock_receipts_stage421 (
                       id INTEGER PRIMARY KEY AUTOINCREMENT,
                       receipt_date TEXT NOT NULL,
                       responsible TEXT NOT NULL,
                       order_date TEXT NOT NULL DEFAULT '',
                       request_number TEXT NOT NULL DEFAULT '',
                       order_number TEXT NOT NULL DEFAULT '',
                       plu TEXT NOT NULL DEFAULT '',
                       item_name TEXT NOT NULL,
                       project TEXT NOT NULL DEFAULT '',
                       serial_number TEXT NOT NULL DEFAULT '',
                       inventory_number TEXT NOT NULL DEFAULT '',
                       supplier TEXT NOT NULL,
                       vendor TEXT NOT NULL,
                       model TEXT NOT NULL DEFAULT '',
                       shelf TEXT NOT NULL DEFAULT '',
                       object_name TEXT NOT NULL,
                       datacenter TEXT NOT NULL DEFAULT 'Ixcellerate',
                       equipment_type TEXT NOT NULL DEFAULT '',
                       component_type TEXT NOT NULL DEFAULT '',
                       cable_type TEXT NOT NULL DEFAULT '',
                       unit TEXT NOT NULL,
                       quantity REAL NOT NULL CHECK (quantity >= 0),
                       legacy_equipment_id INTEGER UNIQUE REFERENCES equipment(id),
                       is_opening_balance INTEGER NOT NULL DEFAULT 0
                           CHECK (is_opening_balance IN (0, 1)),
                       created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
                   );
                   INSERT INTO stock_receipts_stage421(
                       id, receipt_date, responsible, order_date, request_number,
                       order_number, plu, item_name, project, serial_number,
                       inventory_number, supplier, vendor, model, shelf, object_name,
                       datacenter, equipment_type, component_type, cable_type, unit,
                       quantity, legacy_equipment_id, is_opening_balance, created_at
                   )
                   SELECT id, receipt_date, responsible, order_date, request_number,
                          order_number, plu, item_name, project, serial_number,
                          inventory_number, supplier, vendor, model, shelf, object_name,
                          datacenter, equipment_type, component_type, cable_type, unit,
                          quantity, legacy_equipment_id, is_opening_balance, created_at
                   FROM stock_receipts;
                   DROP TABLE stock_receipts;
                   ALTER TABLE stock_receipts_stage421 RENAME TO stock_receipts;
                   CREATE UNIQUE INDEX idx_stock_receipts_serial_unique
                       ON stock_receipts(serial_number COLLATE NOCASE)
                       WHERE trim(serial_number) <> '';
                   CREATE UNIQUE INDEX idx_stock_receipts_inventory_unique
                       ON stock_receipts(inventory_number COLLATE NOCASE)
                       WHERE trim(inventory_number) <> '';
                   CREATE INDEX idx_stock_receipts_date ON stock_receipts(receipt_date);
                   CREATE INDEX idx_stock_receipts_cable
                       ON stock_receipts(item_name, cable_type);
                   COMMIT;"""
            )
            connection.execute("PRAGMA foreign_keys = ON")
            foreign_key_errors = connection.execute("PRAGMA foreign_key_check").fetchall()
            if foreign_key_errors:
                raise sqlite3.IntegrityError("Ошибка внешних ключей после миграции единиц учета")
        connection.execute(
            """UPDATE stock_receipts
               SET datacenter = COALESCE((
                   SELECT e.datacenter FROM equipment e
                   WHERE e.id = stock_receipts.legacy_equipment_id
               ), 'Ixcellerate')
               WHERE trim(datacenter) = '' OR legacy_equipment_id IS NOT NULL"""
        )
        connection.executemany(
            "INSERT OR IGNORE INTO categories(name, description) VALUES (?, ?)",
            [
                ("Провода — оптика", "Оптические кабели и патч-корды"),
                ("Провода — медь", "Медные кабели и патч-корды"),
            ],
        )
        references = {
            "item_name": (),
            "model": (),
            "shelf": (),
            "project": (),
            "object": ("Не указано", "Ixcellerate"),
            "datacenter": ("Ixcellerate",),
            "equipment_type": ("Серверы", "Коммутаторы", "Системы хранения данных"),
            "component_type": ("Комплектующие",),
            "cable_type": ("Оптика", "Медь"),
            "task_source": (
                "PNR", "ИЗМ", "ЗНР", "ЗНО", "Сопровождение", "ROOMS", "Time",
                "Zabbix", "Заказ", "Волна", "DCIM", "ITSM", "Outlook",
                "Rooms", "Склад", "Другое",
            ),
            "task_type": (
                "ЗНО", "ЗНР", "ИЗМ", "ИНЦ", "Ночные работы", "ПНР", "Работа",
                "Другое",
            ),
            "work_log_status": ("Выполнено", "В работе", "В ожидании", "Ожидание", "Отложено"),
            "work_log_section": (
                "Solar", "Виртуализация", "SALT", "BigData", "ТОРГ", "БД",
                "Linux", "NTP", "Exchange", "Digital", "USB-hub", "Cognos",
                "QlikView", "АССД", "X5ID", "CIP", "Подписки микросервис",
                "Loymax", "GPU-инфраструктура", "УЦ", "Голограмма",
                "Пополнение TC5", "FnR (F&R)", "Видеоконференции",
                "Серверы интеграции УПГУ", "Серверы СРК",
                "WAF Pro — система контроля и защиты веб-приложений",
                "1C", "APM",
            ),
            "supplier": ("Не указан",),
            "vendor": ("Не указан",),
            "unit": ("шт", "м"),
        }
        connection.executemany(
            "INSERT OR IGNORE INTO reference_values(kind, name) VALUES (?, ?)",
            [(kind, name) for kind, names in references.items() for name in names],
        )
        connection.execute(
            """INSERT OR IGNORE INTO reference_values(kind, name)
               SELECT 'equipment_type', c.name FROM categories c
               WHERE c.name <> 'Комплектующие' AND c.name NOT LIKE 'Провода — %'"""
        )
        connection.execute(
            """INSERT OR IGNORE INTO stock_receipts(
                   receipt_date, responsible, item_name, project, serial_number,
                   inventory_number, supplier, vendor, model, shelf, object_name,
                   datacenter, equipment_type, component_type, cable_type, unit, quantity,
                   legacy_equipment_id, is_opening_balance
               )
               SELECT substr(e.created_at, 1, 10), 'Миграция существующего остатка',
                      e.model, '', e.serial_number, e.inventory_number,
                      'Не указан', 'Не указан', e.model, COALESCE(l.code, ''),
                      'Не указано', e.datacenter,
                      CASE WHEN c.name <> 'Комплектующие' AND c.name NOT LIKE 'Провода — %'
                           THEN c.name ELSE '' END,
                      CASE WHEN c.name = 'Комплектующие' THEN c.name ELSE '' END,
                      CASE WHEN c.name = 'Провода — оптика' THEN 'Оптика'
                           WHEN c.name = 'Провода — медь' THEN 'Медь' ELSE '' END,
                      CASE WHEN c.name LIKE 'Провода — %' THEN 'м' ELSE 'шт' END,
                      e.quantity, e.id, 1
               FROM equipment e
               JOIN categories c ON c.id = e.category_id
               LEFT JOIN locations l ON l.id = e.location_id
               WHERE e.quantity > 0"""
        )
        receipt_reference_columns = {
            "item_name": "item_name", "model": "model", "shelf": "shelf",
            "project": "project", "supplier": "supplier", "vendor": "vendor",
            "object": "object_name", "datacenter": "datacenter",
            "equipment_type": "equipment_type", "component_type": "component_type",
            "cable_type": "cable_type", "unit": "unit",
        }
        for kind, column in receipt_reference_columns.items():
            connection.execute(
                f"""INSERT OR IGNORE INTO reference_values(kind, name)
                    SELECT ?, trim({column}) FROM stock_receipts
                    WHERE trim({column}) <> ''""",
                (kind,),
            )
        user_count = int(connection.execute("SELECT count(*) FROM users").fetchone()[0])
        if user_count == 0:
            connection.execute(
                """INSERT INTO users(
                       first_name, last_name, position, email, password_hash, role,
                       must_change_password
                   ) VALUES (?, ?, ?, ?, ?, 'admin', 1)""",
                (
                    "Александр", "Мерненко", "Дежурный инженер",
                    "lokolis", hash_password("lokolis"),
                ),
            )
            default_admin_created = True
    return default_admin_created


def install_knowledge_schema(db_path: str | Path = DEFAULT_DB_PATH) -> None:
    """Install the optional Knowledge schema only when explicitly requested."""
    with connect(db_path) as connection:
        connection.executescript(KNOWLEDGE_SCHEMA)


def install_reports_uvr_schema(db_path: str | Path = DEFAULT_DB_PATH) -> None:
    """Install the additive Reports/UVR schema and canonical reference values."""
    with connect(db_path) as connection:
        table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='work_logs'"
        ).fetchone()
        if table is None:
            raise sqlite3.OperationalError("work_logs table is missing")
        columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(work_logs)").fetchall()
        }
        if "section" not in columns:
            connection.execute(
                "ALTER TABLE work_logs ADD COLUMN section TEXT NOT NULL DEFAULT ''"
            )
        if "needs_review" not in columns:
            connection.execute(
                "ALTER TABLE work_logs ADD COLUMN needs_review INTEGER NOT NULL "
                "DEFAULT 0 CHECK (needs_review IN (0, 1))"
            )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_work_logs_section ON work_logs(section)"
        )
        connection.executemany(
            "INSERT OR IGNORE INTO reference_values(kind, name) VALUES (?, ?)",
            [
                (kind, name)
                for kind, names in REPORTS_UVR_REFERENCES.items()
                for name in names
            ],
        )
