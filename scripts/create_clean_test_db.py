#!/usr/bin/env python3
"""Собрать чистую тестовую копию БД ODE из рабочей базы.

Скрипт создает согласованный SQLite snapshot рабочей базы и очищает в копии
только операционные (складские/отчетные) данные. Пользователи, хеши паролей,
справочники и категории/полки сохраняются без изменений. Рабочая база
(`--source`) никогда не изменяется этим скриптом — открывается SQLite в
принудительном read-only режиме, а snapshot создается Backup API с учетом
committed WAL.

Примеры:

    python3 scripts/create_clean_test_db.py --dry-run
    python3 scripts/create_clean_test_db.py --profile empty
    python3 scripts/create_clean_test_db.py --profile demo --overwrite
    python3 scripts/create_clean_test_db.py --source data/warehouse.db \\
        --output data/warehouse_test_disposable_v1.db --profile demo --overwrite

Гарантии:

- `--source` и `--output` никогда не могут указывать на один и тот же файл;
- существующий `--output` не будет перезаписан без явного `--overwrite`;
- `--dry-run` не создает и не изменяет файлы;
- после работы выполняются `PRAGMA integrity_check` и
  `PRAGMA foreign_key_check` на итоговой базе;
- SHA-256 main DB, WAL и rollback journal источника проверяются до и после
  запуска и обязаны совпадать (`-shm` — только transient coordination state).
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sqlite3
import sys
import tempfile
from contextlib import closing
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from inventory.db import DEFAULT_DB_PATH  # noqa: E402
from inventory.shared.runtime_paths import (  # noqa: E402
    DisposableDatabaseTargetState,
    capture_disposable_database_target_state,
    disposable_database_target,
    install_test_contour_marker,
    revalidate_disposable_database_target_state,
)

DEFAULT_OUTPUT_PATH = ROOT / "data" / "warehouse_test_disposable_v1.db"

# Миграционный provenance связан FK с promoted receipts/issues. В чистом
# контуре он не может пережить удаление operational rows и сам не должен
# выглядеть как доступный full-migration review. Порядок важен: сначала дети.
MIGRATION_TABLES_IN_DROP_ORDER = [
    "migration_full_warnings",
    "migration_full_quarantine",
    "migration_full_relationships",
    "migration_full_reconciliation",
    "migration_full_identities",
    "migration_serial_cells",
    "migration_staging_rows",
    "migration_validation_results",
    "migration_source_files",
    "migration_batches",
    "migration_full_cleanliness",
    "migration_full_performance",
    "migration_full_marker",
]

# Складские и отчетные таблицы: операционные данные, которые очищаются.
# Порядок важен — сначала таблицы, ссылающиеся на другие (FK потомки).
OPERATIONAL_TABLES_IN_DELETE_ORDER = [
    *MIGRATION_TABLES_IN_DROP_ORDER,
    "knowledge_article_tags",
    "knowledge_attachments",
    "knowledge_articles",
    "stock_issue_allocations",
    "stock_issues",
    "delivery_lines",
    "deliveries",
    "stock_receipts",
    "operations",
    "equipment",
    "daily_report_rows",
    "daily_report_uploads",
    "work_logs",
    "audit_log",
]
# Справочники, пользователи и настройки: сохраняются без изменений.
PRESERVED_TABLES = ["users", "categories", "locations", "reference_values"]

TEST_CIRCUIT_LABEL = "ТЕСТОВЫЙ КОНТУР"

# SQLite data that can affect the logical database contents.  ``-shm`` is
# deliberately not included: it is transient shared-memory coordination state
# and can change when a read-only connection obtains/releases a read mark.  The
# main database, WAL and rollback journal must remain byte-for-byte unchanged.
SOURCE_CONTENT_SUFFIXES = ("", "-wal", "-journal")


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_content_state(db_path: Path) -> dict[str, dict[str, Any] | None]:
    """Hash the SQLite files that carry durable database contents.

    A WAL may contain committed rows which are not present in the main ``.db``
    file yet.  Hashing only the main file would therefore be an incomplete
    source-invariance check.
    """
    state: dict[str, dict[str, Any] | None] = {}
    for suffix in SOURCE_CONTENT_SUFFIXES:
        path = Path(str(db_path) + suffix)
        label = "database" if not suffix else suffix
        state[label] = (
            {"path": str(path), "size": path.stat().st_size, "sha256": sha256_of(path)}
            if path.exists()
            else None
        )
    return state


def print_source_content_state(label: str, state: dict[str, dict[str, Any] | None]) -> None:
    print(f"файлы источника ({label}):")
    for name, details in state.items():
        if details is None:
            print(f"  - {name}: отсутствует")
        else:
            print(f"  - {name}: {details['size']} байт, SHA-256 {details['sha256']}")


def connect_source_readonly(db_path: Path) -> sqlite3.Connection:
    """Open source read-only without creating sidecars for an idle WAL DB.

    A present WAL may contain committed rows, so SQLite must process it through
    an ordinary read-only connection.  With no WAL/rollback journal, immutable
    mode is safe and prevents persistent-WAL databases from creating an empty
    ``-wal``/``-shm`` pair merely because the snapshot reader connected.
    """
    durable_sidecar_present = any(
        Path(str(db_path) + suffix).exists() for suffix in ("-wal", "-journal")
    )
    immutable = "" if durable_sidecar_present else "&immutable=1"
    connection = sqlite3.connect(
        f"{db_path.resolve().as_uri()}?mode=ro{immutable}", uri=True
    )
    connection.execute("PRAGMA query_only = ON")
    return connection


def snapshot_source_database(source: Path, destination: Path) -> None:
    """Create a transactionally consistent SQLite snapshot, including WAL."""
    with closing(connect_source_readonly(source)) as source_connection:
        with closing(sqlite3.connect(destination)) as destination_connection:
            source_connection.backup(destination_connection)
            destination_connection.commit()


def table_counts_from_connection(
    connection: sqlite3.Connection, tables: list[str]
) -> dict[str, int]:
    existing = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    return {
        table: (
            int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            if table in existing
            else 0
        )
        for table in tables
    }


def clear_operational_data(connection: sqlite3.Connection) -> None:
    if int(connection.execute("PRAGMA foreign_keys").fetchone()[0]) != 1:
        raise RuntimeError("foreign_keys должен быть включен до очистки тестовой базы")
    existing = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    # These tables belong to the offline/full-migration candidate. Leaving an
    # empty marker table would make ordinary runtime fail closed as a corrupt
    # candidate, so a disposable clean contour removes the candidate surface
    # completely instead of preserving empty shells.
    for table in MIGRATION_TABLES_IN_DROP_ORDER:
        if table not in existing:
            continue
        connection.execute(f'DROP TABLE "{table}"')
        connection.execute("DELETE FROM sqlite_sequence WHERE name = ?", (table,))
        existing.remove(table)
    for table in OPERATIONAL_TABLES_IN_DELETE_ORDER:
        if table not in existing:
            continue
        connection.execute(f"DELETE FROM {table}")
        connection.execute("DELETE FROM sqlite_sequence WHERE name = ?", (table,))
    errors = connection.execute("PRAGMA foreign_key_check").fetchall()
    if errors:
        raise RuntimeError(
            f"foreign_key_check не пуст после очистки операционных данных: {errors}"
        )


def seed_demo_data(connection: sqlite3.Connection) -> None:
    """Добавить небольшой демонстрационный набор поверх очищенной базы.

    Пишет напрямую в текущую (S/N-first) модель `stock_receipts` /
    `stock_issues`, а не в legacy `equipment`/`operations`, чтобы демо-данные
    были видны в баланс, приход, расход и карточку оборудования так же, как
    реальные данные.
    """
    receipts = [
        dict(
            receipt_date="2026-07-01", responsible="Демо Инженер",
            item_name="PowerEdge R650", project="Digital", serial_number="DEMO-SRV-0001",
            inventory_number="INV-DEMO-0001", supplier="Demo Supplier", vendor="Dell",
            model="PowerEdge R650", shelf="A-01", object_name="Склад",
            datacenter="Ixcellerate", equipment_type="Сервер", component_type="",
            cable_type="", unit="шт", quantity=1,
        ),
        dict(
            receipt_date="2026-07-01", responsible="Демо Инженер",
            item_name="PowerEdge R650", project="Digital", serial_number="DEMO-SRV-0002",
            inventory_number="INV-DEMO-0002", supplier="Demo Supplier", vendor="Dell",
            model="PowerEdge R650", shelf="A-01", object_name="Склад",
            datacenter="Ixcellerate", equipment_type="Сервер", component_type="",
            cable_type="", unit="шт", quantity=1,
        ),
        dict(
            receipt_date="2026-07-02", responsible="Демо Инженер",
            item_name="SSD 2TB", project="Tech", serial_number="DEMO-SSD-0001",
            inventory_number="INV-DEMO-0003", supplier="Demo Supplier", vendor="Samsung",
            model="PM893", shelf="A-02", object_name="Склад",
            datacenter="Ixcellerate", equipment_type="", component_type="SSD",
            cable_type="", unit="шт", quantity=1,
        ),
        dict(
            receipt_date="2026-07-02", responsible="Демо Инженер",
            item_name="Оптический патч-корд", project="", serial_number="",
            inventory_number="", supplier="Demo Supplier", vendor="Не указан",
            model="", shelf="B-01", object_name="Склад",
            datacenter="Ixcellerate", equipment_type="", component_type="",
            cable_type="Оптика", unit="м", quantity=50,
        ),
    ]
    receipt_ids: dict[str, int] = {}
    for row in receipts:
        cursor = connection.execute(
            """INSERT INTO stock_receipts(
                   receipt_date, responsible, item_name, project, serial_number,
                   inventory_number, supplier, vendor, model, shelf, object_name,
                   datacenter, equipment_type, component_type, cable_type, unit, quantity
               ) VALUES (
                   :receipt_date, :responsible, :item_name, :project, :serial_number,
                   :inventory_number, :supplier, :vendor, :model, :shelf, :object_name,
                   :datacenter, :equipment_type, :component_type, :cable_type, :unit, :quantity
               )""",
            row,
        )
        key = row["serial_number"] or row["item_name"]
        receipt_ids[key] = int(cursor.lastrowid)

    # Списываем один из двух демо-серверов, чтобы баланс и история были не пустыми.
    issued_receipt_id = receipt_ids["DEMO-SRV-0002"]
    issue_cursor = connection.execute(
        """INSERT INTO stock_issues(
               issue_date, responsible, task_type, task_number,
               source_serial_number, quantity, comment
           ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            "2026-07-03", "Демо Инженер", "ПНР", "ДЕМО-001",
            "DEMO-SRV-0002", 1, "Демонстрационное списание",
        ),
    )
    connection.execute(
        "INSERT INTO stock_issue_allocations(issue_id, receipt_id, quantity) VALUES (?, ?, ?)",
        (int(issue_cursor.lastrowid), issued_receipt_id, 1),
    )

    connection.execute(
        """INSERT INTO work_logs(work_date, task_source, task_type, task_number, description, status, comment)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            "2026-07-03", "Rooms", "ПНР", "ДЕМО-001",
            "Демонстрационная задача для тестового контура", "Выполнено", "",
        ),
    )

    delivery_cursor = connection.execute(
        """INSERT INTO deliveries(source_filename, delivery_number, supplier, status, uploaded_by)
           VALUES (?, ?, ?, ?, ?)""",
        ("demo_delivery.csv", "ДЕМО-ПОСТ-001", "Demo Supplier", "Загружена", "Демо Инженер"),
    )
    connection.execute(
        """INSERT INTO delivery_lines(delivery_id, row_number, serial_number, item_name,
               vendor, model, datacenter, shelf, object_name, equipment_type, quantity, state)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            int(delivery_cursor.lastrowid), 1, "DEMO-SRV-0003", "PowerEdge R650",
            "Dell", "PowerEdge R650", "Ixcellerate", "", "Склад", "Сервер", 1, "Ожидается",
        ),
    )


def ensure_admin_password_known(connection: sqlite3.Connection) -> None:
    """Не менять существующих пользователей; только предупредить, если админов нет."""
    count = int(connection.execute(
        "SELECT COUNT(*) FROM users WHERE role = 'admin' AND is_active = 1"
    ).fetchone()[0])
    if count == 0:
        print(
            "предупреждение: в скопированной базе нет активного администратора "
            "(источник не содержал ни одного); тестовый вход будет недоступен, "
            "пока пользователь не будет создан вручную.",
            file=sys.stderr,
        )


def atomic_install_verified_database(
    source: Path,
    output: Path,
    initial_target_state: DisposableDatabaseTargetState,
) -> None:
    """Copy a verified DB beside ``output`` and atomically replace the target."""
    fd, staging_name = tempfile.mkstemp(
        prefix=f".{output.name}.", suffix=".tmp", dir=output.parent
    )
    os.close(fd)
    staging = Path(staging_name)
    try:
        shutil.copyfile(source, staging)
        with open(staging, "r+b") as handle:
            os.fsync(handle.fileno())
        if sha256_of(staging) != sha256_of(source):
            raise RuntimeError("проверка SHA-256 временной копии перед установкой не прошла")
        revalidate_disposable_database_target_state(output, initial_target_state)
        os.replace(staging, output)
    finally:
        if staging.exists():
            staging.unlink()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", type=Path, default=DEFAULT_DB_PATH, help="Рабочая база-источник (по умолчанию data/warehouse.db). Никогда не изменяется.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH, help="Путь к создаваемой тестовой базе (по умолчанию data/warehouse_test_disposable_v1.db).")
    parser.add_argument("--profile", choices=["empty", "demo"], default="empty", help="empty — только очистка операционных данных; demo — очистка и небольшой демонстрационный набор.")
    parser.add_argument("--dry-run", action="store_true", help="Ничего не создавать и не изменять; только показать, что было бы сделано.")
    parser.add_argument("--overwrite", action="store_true", help="Разрешить перезапись существующего --output.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    source = args.source.resolve()
    try:
        output = disposable_database_target(args.output)
    except RuntimeError as error:
        print(f"ошибка: {error}", file=sys.stderr)
        return 1

    if not source.exists():
        print(f"ошибка: источник не найден: {source}", file=sys.stderr)
        return 1
    same_existing_file = output.exists() and os.path.samefile(source, output)
    if source == output or same_existing_file:
        print("ошибка: --source и --output не могут указывать на один и тот же файл", file=sys.stderr)
        return 1

    source_state_before = source_content_state(source)
    source_sha_before = str(source_state_before["database"]["sha256"])
    print(f"источник: {source}")
    print(f"источник SHA-256 (до): {source_sha_before}")
    print_source_content_state("до", source_state_before)
    print(f"выходной файл: {output}")
    print(f"профиль: {args.profile}")

    if not args.dry_run and output.exists() and not args.overwrite:
        print(
            f"ошибка: выходной файл уже существует: {output}. "
            "Укажите --overwrite для перезаписи.",
            file=sys.stderr,
        )
        return 1

    if args.dry_run:
        try:
            with closing(connect_source_readonly(source)) as connection:
                connection.execute("BEGIN")
                operational_before = table_counts_from_connection(
                    connection, OPERATIONAL_TABLES_IN_DELETE_ORDER
                )
                preserved_before = table_counts_from_connection(connection, PRESERVED_TABLES)
                connection.rollback()
        except (OSError, sqlite3.Error, RuntimeError) as error:
            print(f"ошибка: не удалось прочитать источник: {error}", file=sys.stderr)
            return 1
        print("--dry-run: файлы не создавались и не изменялись")
        print("будут очищены (операционные данные):")
        for table in OPERATIONAL_TABLES_IN_DELETE_ORDER:
            print(f"  - {table}: {operational_before.get(table, 0)} строк -> 0")
        print("будут сохранены без изменений (пользователи и справочники):")
        for table in PRESERVED_TABLES:
            print(f"  - {table}: {preserved_before.get(table, 0)} строк")
        if args.profile == "demo":
            print("профиль demo: после очистки будет добавлен небольшой демонстрационный набор "
                  "(2 сервера, 1 SSD, 1 кабель, 1 списание, 1 лог работ, 1 поставка)")
        source_state_after = source_content_state(source)
        source_sha_after = str(source_state_after["database"]["sha256"])
        print(f"источник SHA-256 (после): {source_sha_after}")
        print_source_content_state("после", source_state_after)
        if source_state_after != source_state_before:
            print(
                "ошибка: main DB/WAL/journal источника изменились во время dry-run",
                file=sys.stderr,
            )
            return 1
        print("источник main DB/WAL/journal: без изменений")
        return 0

    try:
        initial_target_state = capture_disposable_database_target_state(
            output, "warehouse"
        )
    except (OSError, sqlite3.Error, RuntimeError) as error:
        print(f"ошибка: {error}", file=sys.stderr)
        return 1

    output.parent.mkdir(parents=True, exist_ok=True)
    # The working copy is built in the system temp directory (not next to
    # --output) because SQLite needs normal journal/fsync support while it
    # writes, which some synced/network mounts of the project folder do not
    # provide. Only a plain file copy (no SQLite writes) ever touches the
    # --output path itself.
    fd, tmp_name = tempfile.mkstemp(prefix="ode_clean_test_", suffix=".db", dir=tempfile.gettempdir())
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        try:
            snapshot_source_database(source, tmp_path)
            connection = sqlite3.connect(tmp_path)
            try:
                connection.execute("PRAGMA foreign_keys = ON")
                operational_before = table_counts_from_connection(
                    connection, OPERATIONAL_TABLES_IN_DELETE_ORDER
                )
                preserved_before = table_counts_from_connection(connection, PRESERVED_TABLES)
                with connection:
                    clear_operational_data(connection)
                    if args.profile == "demo":
                        seed_demo_data(connection)
                    ensure_admin_password_known(connection)
                    install_test_contour_marker(connection, "warehouse")
            finally:
                connection.close()
            connection = sqlite3.connect(tmp_path)
            try:
                connection.execute("PRAGMA foreign_keys = ON")
                integrity = connection.execute("PRAGMA integrity_check").fetchall()
                integrity_ok = len(integrity) == 1 and str(integrity[0][0]) == "ok"
                fk_errors = connection.execute("PRAGMA foreign_key_check").fetchall()
                operational_after = table_counts_from_connection(
                    connection, OPERATIONAL_TABLES_IN_DELETE_ORDER
                )
                preserved_after = table_counts_from_connection(connection, PRESERVED_TABLES)
            finally:
                connection.close()

            if not integrity_ok or fk_errors:
                print("ошибка: проверка целостности тестовой базы не прошла", file=sys.stderr)
                print(f"  integrity_check: {integrity}", file=sys.stderr)
                print(f"  foreign_key_check: {fk_errors}", file=sys.stderr)
                return 1

            source_state_before_install = source_content_state(source)
            if source_state_before_install != source_state_before:
                print(
                    "ошибка: main DB/WAL/journal источника изменились во время создания snapshot",
                    file=sys.stderr,
                )
                return 1

            atomic_install_verified_database(tmp_path, output, initial_target_state)
        except (OSError, sqlite3.Error, RuntimeError) as error:
            print(f"ошибка: не удалось создать тестовую базу: {error}", file=sys.stderr)
            return 1
    finally:
        if tmp_path.exists():
            tmp_path.unlink()

    source_state_after = source_content_state(source)
    source_sha_after = str(source_state_after["database"]["sha256"])
    output_sha = sha256_of(output)

    print(f"источник SHA-256 (после): {source_sha_after}")
    print_source_content_state("после", source_state_after)
    if source_state_after != source_state_before:
        print(
            "ошибка: main DB/WAL/journal источника изменились во время работы скрипта!",
            file=sys.stderr,
        )
        return 1
    print("источник main DB/WAL/journal: без изменений")
    print(f"выходной файл SHA-256: {output_sha}")
    print("integrity_check: ok")
    print("foreign_key_check: пусто (ошибок нет)")
    print("операционные таблицы после очистки:")
    for table in OPERATIONAL_TABLES_IN_DELETE_ORDER:
        print(f"  - {table}: {operational_before.get(table, 0)} -> {operational_after.get(table, 0)}")
    print("сохраненные таблицы (без изменений количества строк):")
    for table in PRESERVED_TABLES:
        before = preserved_before.get(table, 0)
        after = preserved_after.get(table, 0)
        mismatch = " (!) не совпадает" if before != after else ""
        print(f"  - {table}: {before} -> {after}{mismatch}")
    print(f"метка интерфейса тестового контура: {TEST_CIRCUIT_LABEL}")
    print("готово")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
