#!/usr/bin/env python3
"""Build or validate the full disposable historical warehouse candidate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import sys
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from inventory.db import DEFAULT_DB_PATH  # noqa: E402
from inventory.migration.full_builder import (  # noqa: E402
    DEFAULT_CLEANLINESS_MARKDOWN,
    DEFAULT_CLEANLINESS_XLSX,
    DEFAULT_FULL_DB,
    DEFAULT_REPORT_MARKDOWN,
    DEFAULT_REPORT_XLSX,
    DEFAULT_SERIAL_REVIEW,
    DEFAULT_SOURCE_CANDIDATE,
    DEFAULT_SOURCE_WORKBOOK,
    FullPaths,
    FullRuntimeHooks,
    build_full_candidate,
    default_full_paths,
    validate_full_database,
)
# Preserve the existing application package import ordering before importing a
# warehouse submodule directly.  The CLI never initializes data/warehouse.db.
import inventory.core.application as _application_wiring  # noqa: E402,F401
from inventory.warehouse.migration_full import (  # noqa: E402
    MigrationFullWarehouseWriter,
)


def _add_paths(parser: argparse.ArgumentParser) -> None:
    defaults = default_full_paths(production_db=DEFAULT_DB_PATH)
    parser.add_argument("--source-candidate", type=Path, default=DEFAULT_SOURCE_CANDIDATE)
    parser.add_argument("--production-db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--raw-dir", type=Path, default=defaults.raw_dir)
    parser.add_argument("--normalized-dir", type=Path, default=defaults.normalized_dir)
    parser.add_argument("--source-workbook", type=Path, default=DEFAULT_SOURCE_WORKBOOK)
    parser.add_argument("--serial-review", type=Path, default=DEFAULT_SERIAL_REVIEW)
    parser.add_argument("--full-db", type=Path, default=DEFAULT_FULL_DB)
    parser.add_argument("--report-xlsx", type=Path, default=DEFAULT_REPORT_XLSX)
    parser.add_argument("--report-markdown", type=Path, default=DEFAULT_REPORT_MARKDOWN)
    parser.add_argument("--cleanliness-xlsx", type=Path, default=DEFAULT_CLEANLINESS_XLSX)
    parser.add_argument(
        "--cleanliness-markdown", type=Path, default=DEFAULT_CLEANLINESS_MARKDOWN
    )


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        description=(
            "Full historical warehouse candidate; never writes data/warehouse.db"
        )
    )
    commands = root.add_subparsers(dest="command", required=True)
    build_parser = commands.add_parser(
        "build", help="Atomically create DB and all full migration reports"
    )
    _add_paths(build_parser)
    build_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace existing disposable full-candidate outputs",
    )
    validate_parser = commands.add_parser(
        "validate", help="Read-only validation of an existing full candidate"
    )
    _add_paths(validate_parser)
    return root


def _paths(arguments: argparse.Namespace) -> FullPaths:
    return FullPaths(
        source_candidate=arguments.source_candidate,
        production_db=arguments.production_db,
        raw_dir=arguments.raw_dir,
        normalized_dir=arguments.normalized_dir,
        source_workbook=arguments.source_workbook,
        serial_review=arguments.serial_review,
        full_db=arguments.full_db,
        report_xlsx=arguments.report_xlsx,
        report_markdown=arguments.report_markdown,
        cleanliness_xlsx=arguments.cleanliness_xlsx,
        cleanliness_markdown=arguments.cleanliness_markdown,
    )


def _hooks(database: Path) -> FullRuntimeHooks:
    writer = MigrationFullWarehouseWriter(database)
    return FullRuntimeHooks(
        write_receipt=writer.write_receipt,
        write_issue=writer.write_issue,
        write_event=writer.write_event,
    )


def _print(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    paths = _paths(arguments)
    try:
        if arguments.command == "build":
            result = build_full_candidate(
                paths,
                _hooks(paths.full_db),
                overwrite=bool(arguments.overwrite),
            )
            _print(result.report)
            return 0
        if arguments.command == "validate":
            _print(validate_full_database(
                paths.full_db, production_db=paths.production_db
            ))
            return 0
    except (
        FileExistsError,
        FileNotFoundError,
        RuntimeError,
        ValueError,
        sqlite3.Error,
    ) as error:
        print(f"migration-full-candidate: ERROR: {error}", file=sys.stderr)
        return 1
    raise AssertionError(f"unsupported command: {arguments.command}")


if __name__ == "__main__":
    raise SystemExit(main())
