#!/usr/bin/env python3
"""Fail when the Git index contains runtime or company data artifacts."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SQLITE_HEADER = b"SQLite format 3\x00"

ALLOWED_DATA_FILES = {
    "data/README.md",
    "migration_inputs/README.md",
}
FORBIDDEN_PREFIXES = (
    ".local/",
    ".stabilization/",
    "acceptance_backups/",
    "backups/",
    "data/",
    "exports/",
    "migration_inputs/",
    "release/",
    "release_backups/",
    "screenshots/",
)
FORBIDDEN_SUFFIXES = (
    ".candidate.db",
    ".db",
    ".db-journal",
    ".db-shm",
    ".db-wal",
    ".sqlite",
    ".sqlite3",
    ".xls",
    ".xlsm",
    ".xlsx",
    ".zip",
)


def tracked_paths(root: Path = ROOT) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        check=True,
        stdout=subprocess.PIPE,
    )
    return [
        item.decode("utf-8", errors="surrogateescape")
        for item in result.stdout.split(b"\0")
        if item
    ]


def forbidden_path(path: str) -> bool:
    normalized = path.replace("\\", "/")
    if normalized in ALLOWED_DATA_FILES:
        return False
    lowered = normalized.casefold()
    return (
        lowered.startswith(FORBIDDEN_PREFIXES)
        or lowered.endswith(FORBIDDEN_SUFFIXES)
    )


def audit_tracked_files(root: Path = ROOT) -> list[str]:
    violations: list[str] = []
    for relative in tracked_paths(root):
        if forbidden_path(relative):
            violations.append(f"forbidden tracked path: {relative}")
            continue
        path = root / relative
        if not path.is_file():
            continue
        with path.open("rb") as handle:
            if handle.read(len(SQLITE_HEADER)) == SQLITE_HEADER:
                violations.append(f"SQLite content in tracked file: {relative}")
    return violations


def main() -> int:
    try:
        paths = tracked_paths()
        violations = audit_tracked_files()
    except (OSError, subprocess.CalledProcessError) as error:
        print(f"repository-data: audit failed: {error}", file=sys.stderr)
        return 2
    if violations:
        print("repository-data: FAILED", file=sys.stderr)
        for violation in violations:
            print(f"  - {violation}", file=sys.stderr)
        return 1
    print(
        f"repository-data: OK, {len(paths)} tracked files; "
        "runtime/company data artifacts absent"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
