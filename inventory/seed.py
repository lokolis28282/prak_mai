"""Заполнение базы начальными данными."""

from __future__ import annotations

from pathlib import Path

from .db import DEFAULT_DB_PATH, connect, initialize
from .service import WarehouseService


CATEGORIES = [
    ("Серверы", "Серверное оборудование"),
    ("Коммутаторы", "Сетевое оборудование"),
    ("Системы хранения данных", "Оборудование хранения данных"),
    ("Комплектующие", "Запасные компоненты"),
    ("Провода — оптика", "Оптические кабели и патч-корды"),
    ("Провода — медь", "Медные кабели и патч-корды"),
]

LOCATIONS = [
    ("A-01", "Зона приемки", "Участок входного контроля"),
    ("B-01", "Стеллажная зона", "Участок длительного хранения"),
    ("C-01", "Зона выдачи", "Участок подготовки к выдаче"),
    ("Q-01", "Карантинная зона", "Изолированный участок"),
]

EQUIPMENT = [
    ("Серверы", "SRV-R220", "SN-SRV-260001", "INV-DC-1001", "B-01", 3),
    ("Серверы", "SRV-R240", "SN-SRV-260002", "INV-DC-1002", "B-01", 2),
    ("Коммутаторы", "SW-48T", "SN-NET-260001", "INV-DC-2001", "B-01", 4),
    ("Коммутаторы", "SW-24F", "SN-NET-260002", "INV-DC-2002", "C-01", 1),
    ("Системы хранения данных", "STG-S12", "SN-STG-260001", "INV-DC-3001", "B-01", 2),
    ("Комплектующие", "SSD 2TB", "SN-SSD-260001", "INV-DC-4001", "B-01", 12),
    ("Комплектующие", "RAM 32GB", "SN-RAM-260001", "INV-DC-4002", "A-01", 20),
    ("Комплектующие", "PSU 800W", "SN-PSU-260001", "INV-DC-4003", "Q-01", 0),
]


def seed_database(db_path: str | Path = DEFAULT_DB_PATH, reset: bool = False) -> None:
    path = Path(db_path)
    if reset and path.exists():
        path.unlink()
    initialize(path)
    service = WarehouseService(path)
    with connect(path) as db:
        has_equipment = bool(db.execute("SELECT COUNT(*) FROM equipment").fetchone()[0])
        for name, description in CATEGORIES:
            db.execute(
                "INSERT OR IGNORE INTO categories(name, description) VALUES (?, ?)",
                (name, description),
            )
        for code, name, description in LOCATIONS:
            db.execute(
                "INSERT OR IGNORE INTO locations(code, name, description) VALUES (?, ?, ?)",
                (code, name, description),
            )
    if has_equipment:
        return
    for item in EQUIPMENT:
        service.add_equipment(
            *item,
            basis="Поставка П-001",
            responsible="Кладовщик № 1",
            notes="",
        )
    service.issue(6, 2, "Заявка З-001", "Инженер № 1")
    service.move(2, "C-01", "Перемещение ПР-001", "Кладовщик № 1")


if __name__ == "__main__":
    seed_database(reset=True)
    print(f"База создана: {DEFAULT_DB_PATH}")
