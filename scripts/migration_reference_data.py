#!/usr/bin/env python3
"""Build and validate the offline Stage 0.13.3A migration candidate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from inventory.migration.candidate_db import (  # noqa: E402
    DEFAULT_CANDIDATE_PATH,
    DEFAULT_NORMALIZED_DIR,
    DEFAULT_RAW_DIR,
    DEFAULT_REFERENCE_PACKAGE_PATH,
    DEFAULT_REPORT_PATH,
    DEFAULT_SERIAL_EXPORT_PATH,
    CandidatePaths,
    assert_safe_candidate_paths,
    build_candidate,
    candidate_report_details,
    inspect_sources,
    verify_candidate_source_files,
    write_json_report,
)
from inventory.db import DEFAULT_DB_PATH  # noqa: E402
from inventory.migration.validation import validate_candidate  # noqa: E402


def _add_paths(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--source-db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    parser.add_argument("--normalized-dir", type=Path, default=DEFAULT_NORMALIZED_DIR)
    parser.add_argument("--candidate", type=Path, default=DEFAULT_CANDIDATE_PATH)
    parser.add_argument(
        "--reference-package", type=Path, default=DEFAULT_REFERENCE_PACKAGE_PATH
    )
    parser.add_argument("--serial-export", type=Path, default=DEFAULT_SERIAL_EXPORT_PATH)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT_PATH)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        description=(
            "Offline reference/staging candidate; never writes data/warehouse.db"
        )
    )
    commands = root.add_subparsers(dest="command", required=True)
    inspect_parser = commands.add_parser(
        "inspect-sources", help="Verify raw SHA and the working DB read-only"
    )
    _add_paths(inspect_parser)
    build_parser = commands.add_parser(
        "build-candidate", help="Atomically create a disposable candidate DB"
    )
    _add_paths(build_parser)
    build_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace existing ignored candidate artifacts (never the source DB)",
    )
    validate_parser = commands.add_parser(
        "validate-candidate", help="Validate a previously built candidate"
    )
    _add_paths(validate_parser)
    report_parser = commands.add_parser(
        "report", help="Validate and refresh the secret-free JSON report"
    )
    _add_paths(report_parser)
    return root


def _paths(arguments: argparse.Namespace) -> CandidatePaths:
    return CandidatePaths(
        source_db=arguments.source_db,
        raw_dir=arguments.raw_dir,
        normalized_dir=arguments.normalized_dir,
        candidate_db=arguments.candidate,
        reference_package=arguments.reference_package,
        serial_export=arguments.serial_export,
        report=arguments.report,
    )


def _portable(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.name


def _print(report: object) -> None:
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    paths = _paths(arguments)
    try:
        if arguments.command == "inspect-sources":
            _print(inspect_sources(paths))
            return 0
        if arguments.command == "build-candidate":
            result = build_candidate(paths, overwrite=bool(arguments.overwrite))
            _print(result.report)
            return 0
        if arguments.command == "validate-candidate":
            report = {
                **validate_candidate(paths.candidate_db),
                **candidate_report_details(paths.candidate_db, paths),
            }
            report["candidate_path"] = _portable(paths.candidate_db)
            report["source_inspection"] = inspect_sources(paths)
            report["registered_sources"] = verify_candidate_source_files(
                paths.candidate_db, paths
            )
            _print(report)
            return 0
        if arguments.command == "report":
            # Report is a generated output too: apply the same inode/path
            # boundary as candidate publication and never trust/merge an old
            # JSON file, which may contain injected secrets or local paths.
            assert_safe_candidate_paths(paths)
            report = {
                **validate_candidate(paths.candidate_db),
                **candidate_report_details(paths.candidate_db, paths),
            }
            report["candidate_path"] = _portable(paths.candidate_db)
            report["source_inspection"] = inspect_sources(paths)
            report["registered_sources"] = verify_candidate_source_files(
                paths.candidate_db, paths
            )
            write_json_report(paths.report, report)
            _print({**report, "report_path": _portable(paths.report)})
            return 0
    except (FileNotFoundError, FileExistsError, RuntimeError, ValueError) as error:
        print(f"migration-reference-data: ERROR: {error}", file=sys.stderr)
        return 1
    raise AssertionError(f"unsupported command: {arguments.command}")


if __name__ == "__main__":
    raise SystemExit(main())
