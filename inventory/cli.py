"""Командная строка и интерактивное меню системы."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path
from typing import Any, Sequence

from .db import DEFAULT_DB_PATH
from .seed import seed_database
from .service import WarehouseError, WarehouseService
from .warehouse.baseline.posting_policy import PostingPolicy


HEADERS = {
    "id": "ID", "category": "Категория", "model": "Модель",
    "serial_number": "Серийный №", "inventory_number": "Инвентарный №",
    "status": "Статус", "location": "Место", "quantity": "Кол-во",
    "operation_date": "Дата", "operation_type": "Операция",
    "equipment_id": "ID обор.", "basis": "Основание",
    "responsible": "Ответственный", "from_location": "Откуда",
    "to_location": "Куда", "name": "Название", "code": "Код",
    "description": "Описание", "created_at": "Создано",
}


def print_table(rows: list[dict[str, Any]]) -> None:
    if not rows:
        print("Нет данных.")
        return
    keys = list(rows[0].keys())
    values = [["" if row[key] is None else str(row[key]) for key in keys] for row in rows]
    widths = [
        min(32, max(len(HEADERS.get(key, key)), *(len(row[index]) for row in values)))
        for index, key in enumerate(keys)
    ]

    def format_row(row: list[str]) -> str:
        return " | ".join(value[:width].ljust(width) for value, width in zip(row, widths))

    print(format_row([HEADERS.get(key, key) for key in keys]))
    print("-+-".join("-" * width for width in widths))
    for row in values:
        print(format_row(row))


def positive_int(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("значение должно быть больше нуля")
    return number


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python app.py",
        description="Система учета оборудования склада ЦОД",
    )
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="путь к файлу SQLite")
    parser.add_argument(
        "--warehouse-contour",
        choices=("production", "demo"),
        default="production",
        help="явный safety contour для складских записей",
    )
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("menu", help="открыть интерактивное меню")
    seed = commands.add_parser("seed", help="создать базу с начальными данными")
    seed.add_argument("--reset", action="store_true", help="пересоздать базу")

    add = commands.add_parser("add", help="добавить карточку оборудования")
    add.add_argument("--category", required=True)
    add.add_argument("--model", required=True)
    add.add_argument("--serial", required=True)
    add.add_argument("--inventory", required=True)
    add.add_argument("--location", required=True)
    add.add_argument("--quantity", type=int, default=0)
    add.add_argument("--basis", default="Карточка оборудования")
    add.add_argument("--responsible", default="Кладовщик № 1")

    for name, help_text in (("receipt", "оформить приход"), ("issue", "оформить выдачу")):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("equipment_id", type=int)
        command.add_argument("quantity", type=positive_int)
        command.add_argument("--basis", required=True)
        command.add_argument("--responsible", required=True)

    move = commands.add_parser("move", help="переместить оборудование")
    move.add_argument("equipment_id", type=int)
    move.add_argument("destination")
    move.add_argument("--basis", required=True)
    move.add_argument("--responsible", required=True)

    stock = commands.add_parser("stock", help="показать остатки")
    stock.add_argument("--category", default="")
    stock.add_argument("--status", default="")
    stock.add_argument("--location", default="")

    search = commands.add_parser("search", help="найти оборудование")
    search.add_argument("query")
    search.add_argument("--category", default="")
    search.add_argument("--status", default="")
    search.add_argument("--location", default="")

    log = commands.add_parser("log", help="показать журнал операций")
    log.add_argument("--type", default="", choices=("", "ADD", "RECEIPT", "ISSUE", "MOVE"))
    log.add_argument("--limit", type=positive_int, default=100)

    export = commands.add_parser("export", help="экспортировать остатки и журнал в CSV")
    export.add_argument("--output", default="exports")
    commands.add_parser("categories", help="показать категории")
    commands.add_parser("locations", help="показать места хранения")
    return parser


def run_command(args: argparse.Namespace) -> None:
    policy = PostingPolicy(
        args.db,
        mode=getattr(args, "warehouse_contour", "unknown"),
        production_db_path=DEFAULT_DB_PATH,
    )
    if args.command == "seed":
        policy.assert_mutation_allowed("cli:seed")
        seed_database(args.db, reset=args.reset)
        print(f"База готова: {Path(args.db).resolve()}")
        return
    service = WarehouseService(args.db)
    if args.command == "add":
        policy.assert_mutation_allowed("cli:add")
        item_id = service.add_equipment(
            args.category, args.model, args.serial, args.inventory, args.location,
            args.quantity, args.basis, args.responsible,
        )
        print(f"Карточка создана. ID оборудования: {item_id}")
    elif args.command == "receipt":
        policy.assert_mutation_allowed("cli:receipt")
        service.receipt(args.equipment_id, args.quantity, args.basis, args.responsible)
        print("Приход зарегистрирован.")
    elif args.command == "issue":
        policy.assert_mutation_allowed("cli:issue")
        service.issue(args.equipment_id, args.quantity, args.basis, args.responsible)
        print("Выдача зарегистрирована.")
    elif args.command == "move":
        policy.assert_mutation_allowed("cli:move")
        service.move(args.equipment_id, args.destination, args.basis, args.responsible)
        print("Перемещение зарегистрировано.")
    elif args.command == "stock":
        print_table(service.equipment(category=args.category, status=args.status, location=args.location))
    elif args.command == "search":
        print_table(service.equipment(args.query, args.category, args.status, args.location))
    elif args.command == "log":
        print_table(service.operation_log(args.type, args.limit))
    elif args.command == "export":
        stock_path, log_path = service.export_csv(args.output)
        print(f"Созданы файлы:\n- {stock_path.resolve()}\n- {log_path.resolve()}")
    elif args.command in ("categories", "locations"):
        print_table(service.reference_data(args.command))
    else:
        interactive_menu(service, policy)


def _ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{prompt}{suffix}: ").strip()
    return value or default


def interactive_menu(service: WarehouseService, policy: PostingPolicy | None = None) -> None:
    posting = policy or PostingPolicy(
        service.db_path,
        mode="unknown",
        production_db_path=DEFAULT_DB_PATH,
    )
    actions = {
        "1": "Остатки", "2": "Поиск", "3": "Добавить оборудование",
        "4": "Приход", "5": "Выдача", "6": "Перемещение",
        "7": "Журнал операций", "8": "Экспорт CSV", "9": "Справочники", "0": "Выход",
    }
    while True:
        print("\n=== УЧЕТ ОБОРУДОВАНИЯ СКЛАДА ЦОД ===")
        for key, title in actions.items():
            print(f"{key}. {title}")
        choice = input("Выберите действие: ").strip()
        try:
            if choice == "0":
                print("Работа завершена.")
                return
            if choice == "1":
                print_table(service.equipment(
                    category=_ask("Категория (Enter — все)"),
                    status=_ask("Статус (Enter — все)"),
                    location=_ask("Код места (Enter — все)"),
                ))
            elif choice == "2":
                print_table(service.equipment(_ask("Модель или номер")))
            elif choice == "3":
                posting.assert_mutation_allowed("menu:add")
                item_id = service.add_equipment(
                    _ask("Категория"), _ask("Модель"), _ask("Серийный номер"),
                    _ask("Инвентарный номер"), _ask("Код места"),
                    int(_ask("Начальное количество", "0")), _ask("Основание"),
                    _ask("Ответственный"), _ask("Примечание"),
                )
                print(f"Создана карточка ID {item_id}.")
            elif choice in ("4", "5"):
                posting.assert_mutation_allowed("menu:receipt_or_issue")
                method = service.receipt if choice == "4" else service.issue
                method(int(_ask("ID оборудования")), int(_ask("Количество")),
                       _ask("Основание"), _ask("Ответственный"))
                print("Операция зарегистрирована.")
            elif choice == "6":
                posting.assert_mutation_allowed("menu:move")
                service.move(int(_ask("ID оборудования")), _ask("Код нового места"),
                             _ask("Основание"), _ask("Ответственный"))
                print("Перемещение зарегистрировано.")
            elif choice == "7":
                print_table(service.operation_log())
            elif choice == "8":
                paths = service.export_csv(_ask("Папка экспорта", "exports"))
                print("Созданы: " + ", ".join(str(path) for path in paths))
            elif choice == "9":
                print("\nКатегории:")
                print_table(service.reference_data("categories"))
                print("\nМеста хранения:")
                print_table(service.reference_data("locations"))
            else:
                print("Неизвестный пункт меню.")
        except (WarehouseError, ValueError) as error:
            print(f"Ошибка: {error}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None and not sys.stdin.isatty():
        parser.print_help()
        return 0
    try:
        run_command(args)
        return 0
    except (WarehouseError, sqlite3.Error) as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        return 1
