#!/usr/bin/env python3
"""Select, build and validate the Stage 0.13.3A.5 disposable pilot."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from inventory.db import DEFAULT_DB_PATH  # noqa: E402
from inventory.migration.pilot_builder import (  # noqa: E402
    DEFAULT_PILOT_DB,
    DEFAULT_SELECTION_MARKDOWN,
    DEFAULT_SELECTION_XLSX,
    DEFAULT_SERIAL_REVIEW,
    DEFAULT_SOURCE_CANDIDATE,
    PilotRuntimeHooks,
    build_pilot,
    default_pilot_paths,
    select_and_report,
    validate_pilot_database,
)
from inventory.migration.pilot_models import PilotPaths  # noqa: E402
# Initialize the existing application package ordering before importing a
# warehouse submodule directly.  This avoids the legacy eager
# ``inventory.warehouse.__init__`` / ``inventory.core.__init__`` cycle without
# changing either production package for an offline CLI.
import inventory.core.application as _application_wiring  # noqa: E402,F401
from inventory.warehouse.migration_pilot import (  # noqa: E402
    MigrationPilotReceiptWriter,
    write_migration_conflict_recorded,
    write_migration_exact_duplicate_skipped,
    write_migration_serial_quarantined,
    write_migration_source_row_linked,
)
from inventory.warehouse.receipt_repository import ReceiptRepository  # noqa: E402


def _add_paths(parser: argparse.ArgumentParser) -> None:
    defaults = default_pilot_paths(production_db=DEFAULT_DB_PATH)
    parser.add_argument("--source-candidate", type=Path, default=DEFAULT_SOURCE_CANDIDATE)
    parser.add_argument("--production-db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--raw-dir", type=Path, default=defaults.raw_dir)
    parser.add_argument("--normalized-dir", type=Path, default=defaults.normalized_dir)
    parser.add_argument("--serial-review", type=Path, default=DEFAULT_SERIAL_REVIEW)
    parser.add_argument("--pilot-db", type=Path, default=DEFAULT_PILOT_DB)
    parser.add_argument("--selection-xlsx", type=Path, default=DEFAULT_SELECTION_XLSX)
    parser.add_argument(
        "--selection-markdown", type=Path, default=DEFAULT_SELECTION_MARKDOWN
    )


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        description=(
            "Preservation-aware receipt pilot; never writes data/warehouse.db"
        )
    )
    commands = root.add_subparsers(dest="command", required=True)
    select_parser = commands.add_parser(
        "select", help="Create deterministic XLSX/Markdown selection reports only"
    )
    _add_paths(select_parser)
    select_parser.add_argument("--overwrite", action="store_true")
    build_parser = commands.add_parser(
        "build", help="Atomically create the marker-guarded disposable pilot DB"
    )
    _add_paths(build_parser)
    build_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace an existing disposable pilot DB and derived reports",
    )
    validate_parser = commands.add_parser(
        "validate", help="Read-only validation of an existing pilot DB"
    )
    _add_paths(validate_parser)
    return root


def _paths(arguments: argparse.Namespace) -> PilotPaths:
    return PilotPaths(
        source_candidate=arguments.source_candidate,
        production_db=arguments.production_db,
        raw_dir=arguments.raw_dir,
        normalized_dir=arguments.normalized_dir,
        serial_review=arguments.serial_review,
        pilot_db=arguments.pilot_db,
        selection_xlsx=arguments.selection_xlsx,
        selection_markdown=arguments.selection_markdown,
    )


def _hooks(pilot_db: Path) -> PilotRuntimeHooks:
    writer = MigrationPilotReceiptWriter(ReceiptRepository(pilot_db))
    return PilotRuntimeHooks(
        write_receipt=writer.write_receipt,
        write_source_row_linked=write_migration_source_row_linked,
        write_conflict_recorded=write_migration_conflict_recorded,
        write_exact_duplicate_skipped=write_migration_exact_duplicate_skipped,
        write_serial_quarantined=write_migration_serial_quarantined,
    )


def _print(report: object) -> None:
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    paths = _paths(arguments)
    try:
        if arguments.command == "select":
            _print(select_and_report(paths, overwrite=bool(arguments.overwrite)))
            return 0
        if arguments.command == "build":
            result = build_pilot(
                paths,
                _hooks(paths.pilot_db),
                overwrite=bool(arguments.overwrite),
            )
            _print(result.report)
            return 0
        if arguments.command == "validate":
            _print(validate_pilot_database(paths.pilot_db))
            return 0
    except (
        FileExistsError,
        FileNotFoundError,
        RuntimeError,
        ValueError,
    ) as error:
        print(f"migration-pilot: ERROR: {error}", file=sys.stderr)
        return 1
    raise AssertionError(f"unsupported command: {arguments.command}")


if __name__ == "__main__":
    raise SystemExit(main())
