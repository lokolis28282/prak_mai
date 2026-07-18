#!/usr/bin/env python3
"""Apply the idempotent knowledge base schema migration."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from inventory.db import DEFAULT_DB_PATH, install_knowledge_schema


def main() -> int:
    parser = argparse.ArgumentParser(description="Миграция базы знаний ODE")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="путь к SQLite-базе")
    args = parser.parse_args()
    db_path = Path(args.db).resolve()
    if not db_path.is_file() or db_path.is_symlink():
        print(f"Некорректный путь к существующей SQLite-базе: {db_path}")
        return 1
    install_knowledge_schema(db_path)
    with sqlite3.connect(db_path) as connection:
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    required = {
        "knowledge_articles", "knowledge_attachments", "knowledge_article_tags"
    }
    missing = required - tables
    if missing:
        print("Миграция не завершена: " + ", ".join(sorted(missing)))
        return 1
    print(f"Миграция базы знаний применена: {db_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
