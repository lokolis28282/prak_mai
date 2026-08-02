#!/usr/bin/env python3
"""Create an empty, isolated Vacations database for the ODE test contour."""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import tempfile
from contextlib import closing
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from inventory.vacations.schema import (  # noqa: E402
    DEFAULT_VACATIONS_DB_PATH,
    VACATION_TABLES,
    install_vacations_schema,
)


DEFAULT_OUTPUT_PATH = ROOT / "data" / "vacations_test_clean.db"
SIDECAR_SUFFIXES = ("-wal", "-shm", "-journal")


def _sidecars(path: Path) -> list[Path]:
    return [Path(str(path) + suffix) for suffix in SIDECAR_SUFFIXES]


def _validate_target(output: Path, *, overwrite: bool) -> None:
    working = DEFAULT_VACATIONS_DB_PATH.resolve()
    if output == working:
        raise RuntimeError("тестовая Vacations DB не может быть рабочей data/vacations.db")
    if output.is_symlink():
        raise RuntimeError("тестовая Vacations DB не может быть symbolic link")
    if output.exists() and working.exists() and output.samefile(working):
        raise RuntimeError("тестовая Vacations DB не может быть hardlink рабочей базы")
    present = [path for path in _sidecars(output) if path.exists()]
    if present:
        raise RuntimeError(
            "рядом с тестовой Vacations DB найдены SQLite sidecar-файлы: "
            + ", ".join(str(path) for path in present)
        )
    if output.exists() and not overwrite:
        raise RuntimeError(
            f"выходной файл уже существует: {output}. Укажите --overwrite"
        )


def build(output: Path, *, overwrite: bool = False) -> Path:
    target = output.expanduser().resolve()
    _validate_target(target, overwrite=overwrite)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, staging_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    os.close(fd)
    staging = Path(staging_name)
    try:
        install_vacations_schema(staging)
        with closing(sqlite3.connect(staging)) as connection:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()
            foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
            tables = {
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            missing = sorted(VACATION_TABLES - tables)
            if integrity is None or str(integrity[0]) != "ok":
                raise RuntimeError("integrity_check тестовой Vacations DB не прошёл")
            if foreign_keys:
                raise RuntimeError("foreign_key_check тестовой Vacations DB не пуст")
            if missing:
                raise RuntimeError(
                    "в тестовой Vacations DB отсутствуют таблицы: "
                    + ", ".join(missing)
                )
        os.chmod(staging, 0o600)
        os.replace(staging, target)
        return target
    finally:
        if staging.exists():
            staging.unlink()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        output = build(args.output, overwrite=args.overwrite)
    except (OSError, sqlite3.Error, RuntimeError) as error:
        print(f"ошибка: {error}", file=sys.stderr)
        return 1
    print(f"тестовая Vacations DB: {output}")
    print("integrity_check: ok")
    print("foreign_key_check: пусто (ошибок нет)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
