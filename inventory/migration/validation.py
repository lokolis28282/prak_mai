"""Validation primitives for disposable migration candidates."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
from contextlib import closing
from pathlib import Path
from typing import Any, Iterable

from .reference_data import DOMAIN_KEYS
from .staging_schema import STAGING_TABLES, assert_staging_schema_absent


PRODUCTION_OPERATIONAL_TABLES = (
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
)
SQLITE_CONTENT_SUFFIXES = ("", "-wal", "-journal")
SQLITE_SIDECAR_SUFFIXES = ("-wal", "-shm", "-journal")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def source_content_state(path: Path) -> dict[str, dict[str, Any] | None]:
    """Capture every SQLite file which can contain durable source changes."""
    result: dict[str, dict[str, Any] | None] = {}
    for suffix in SQLITE_CONTENT_SUFFIXES:
        candidate = Path(str(path) + suffix)
        key = "database" if not suffix else suffix
        result[key] = (
            {
                "size": candidate.stat().st_size,
                "sha256": sha256_file(candidate),
            }
            if candidate.exists()
            else None
        )
    return result


def connect_readonly(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise FileNotFoundError(path)
    connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def sqlite_health(connection: sqlite3.Connection) -> tuple[str, list[tuple[Any, ...]]]:
    integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
    foreign_keys = [tuple(row) for row in connection.execute("PRAGMA foreign_key_check")]
    return integrity, foreign_keys


def assert_source_database_safe(path: Path) -> dict[str, Any]:
    """Inspect a working DB without invoking ODE initialization or services."""
    before = source_content_state(path)
    with closing(connect_readonly(path)) as connection:
        if int(connection.execute("PRAGMA query_only").fetchone()[0]) != 1:
            raise RuntimeError("source database is not query-only")
        integrity, foreign_keys = sqlite_health(connection)
        assert_staging_schema_absent(connection)
    after = source_content_state(path)
    if after != before:
        raise RuntimeError("source database content changed during read-only validation")
    if integrity != "ok":
        raise RuntimeError(f"source integrity_check failed: {integrity}")
    if foreign_keys:
        raise RuntimeError(f"source foreign_key_check failed: {foreign_keys}")
    return {
        "sha256": str(before["database"]["sha256"]),
        "size_bytes": int(before["database"]["size"]),
        "integrity_check": integrity,
        "foreign_key_errors": 0,
        "content_state_unchanged": True,
    }


def candidate_sidecars(path: Path) -> list[str]:
    return [suffix for suffix in SQLITE_SIDECAR_SUFFIXES if Path(str(path) + suffix).exists()]


def _table_names(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }


def _counts(connection: sqlite3.Connection, tables: Iterable[str]) -> dict[str, int]:
    return {
        table: int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
        for table in tables
    }


def validate_candidate(path: Path) -> dict[str, Any]:
    """Return a secret-free validation report and fail on structural violations."""
    with closing(connect_readonly(path)) as connection:
        integrity, foreign_keys = sqlite_health(connection)
        tables = _table_names(connection)
        missing = sorted(set(STAGING_TABLES).difference(tables))
        operation_counts = _counts(connection, PRODUCTION_OPERATIONAL_TABLES)
        domain_keys = {
            str(row[0]) for row in connection.execute(
                "SELECT domain_key FROM reference_domains_v2 WHERE active=1"
            )
        }
        missing_domains = sorted(set(DOMAIN_KEYS).difference(domain_keys))
        user_count = int(connection.execute("SELECT COUNT(*) FROM users").fetchone()[0])
        active_admins = int(
            connection.execute(
                "SELECT COUNT(*) FROM users WHERE role='admin' AND is_active=1"
            ).fetchone()[0]
        )
        staging_count = int(
            connection.execute("SELECT COUNT(*) FROM migration_staging_rows").fetchone()[0]
        )
        serial_count = int(
            connection.execute("SELECT COUNT(*) FROM migration_serial_cells").fetchone()[0]
        )
        corrupted_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM migration_serial_cells "
                "WHERE preservation_status='SOURCE_CORRUPTED'"
            ).fetchone()[0]
        )
        unsafe_corrupted_matches = int(
            connection.execute(
                "SELECT COUNT(*) FROM migration_serial_cells "
                "WHERE preservation_status='SOURCE_CORRUPTED' "
                "AND normalized_match_value<>''"
            ).fetchone()[0]
        )
        non_text_identifiers = int(
            connection.execute(
                "SELECT COUNT(*) FROM migration_serial_cells "
                "WHERE typeof(source_serial_value)<>'text' "
                "OR typeof(normalized_match_value)<>'text'"
            ).fetchone()[0]
        )
        unsafe_numeric_serials = int(
            connection.execute(
                "SELECT COUNT(*) FROM migration_serial_cells "
                "WHERE excel_cell_type='n' AND raw_xml_value<>'' AND "
                "(normalized_match_value<>'' OR requires_manual_review<>1)"
            ).fetchone()[0]
        )
        production_reference_rows = int(
            connection.execute("SELECT COUNT(*) FROM reference_values").fetchone()[0]
        )
        target_links = int(
            connection.execute(
                "SELECT COUNT(*) FROM migration_staging_rows "
                "WHERE decision<>'' OR target_entity_id<>''"
            ).fetchone()[0]
        )
        active_unknown_candidates = int(
            connection.execute(
                "SELECT COUNT(*) FROM reference_values_v2 "
                "WHERE approval_status='CANDIDATE' AND active<>0"
            ).fetchone()[0]
        )
        unsafe_auto_aliases = int(
            connection.execute(
                """SELECT COUNT(*)
                   FROM reference_aliases_v2 a
                   JOIN reference_values_v2 v ON v.id=a.canonical_id
                   WHERE a.resolution_status='AUTO_APPROVED'
                     AND a.normalized_source_key<>v.normalized_key"""
            ).fetchone()[0]
        )
        batches = int(connection.execute("SELECT COUNT(*) FROM migration_batches").fetchone()[0])
        source_files = int(
            connection.execute("SELECT COUNT(*) FROM migration_source_files").fetchone()[0]
        )
        ref_values = int(
            connection.execute("SELECT COUNT(*) FROM reference_values_v2").fetchone()[0]
        )
        aliases = {
            str(row[0]): int(row[1])
            for row in connection.execute(
                "SELECT resolution_status, COUNT(*) FROM reference_aliases_v2 "
                "GROUP BY resolution_status"
            )
        }

    errors: list[str] = []
    if integrity != "ok":
        errors.append(f"integrity_check={integrity}")
    if foreign_keys:
        errors.append(f"foreign_key_check returned {len(foreign_keys)} row(s)")
    if missing:
        errors.append("missing candidate tables: " + ", ".join(missing))
    nonempty_operations = {key: value for key, value in operation_counts.items() if value}
    if nonempty_operations:
        errors.append("candidate contains operational data: " + json.dumps(nonempty_operations))
    if missing_domains:
        errors.append("missing reference domains: " + ", ".join(missing_domains))
    if active_admins < 1:
        errors.append("candidate has no active administrator")
    if unsafe_corrupted_matches:
        errors.append("SOURCE_CORRUPTED serials have matching values")
    if non_text_identifiers:
        errors.append("serial identifiers are not stored as SQLite TEXT")
    if unsafe_numeric_serials:
        errors.append("numeric serial cells bypass manual/no-match policy")
    if production_reference_rows:
        errors.append("candidate populated legacy production reference_values")
    if target_links:
        errors.append("Stage 0.13.3A staging contains import decisions/target IDs")
    if active_unknown_candidates:
        errors.append("unapproved candidate reference values are active")
    if unsafe_auto_aliases:
        errors.append("auto-approved aliases are not safe normalized equivalents")
    if batches != 1:
        errors.append(f"expected one migration batch, got {batches}")

    sidecars = candidate_sidecars(path)
    if sidecars:
        errors.append("candidate has SQLite sidecars: " + ", ".join(sidecars))
    file_mode = stat.S_IMODE(path.stat().st_mode)
    if os.name != "nt" and file_mode & 0o077:
        errors.append(f"candidate permissions expose security data: {file_mode:o}")
    report = {
        "candidate_path": str(path),
        "candidate_sha256": sha256_file(path),
        "candidate_size_bytes": path.stat().st_size,
        "candidate_file_mode": f"{file_mode:o}",
        "integrity_check": integrity,
        "foreign_key_errors": len(foreign_keys),
        "sidecars": sidecars,
        "operational_rows": operation_counts,
        "users": user_count,
        "active_admins": active_admins,
        "reference_domains": len(domain_keys),
        "reference_values": ref_values,
        "legacy_production_reference_values": production_reference_rows,
        "alias_status_counts": aliases,
        "source_files": source_files,
        "staging_rows": staging_count,
        "serial_cells": serial_count,
        "source_corrupted_serial_cells": corrupted_count,
        "unsafe_numeric_serial_cells": unsafe_numeric_serials,
        "staging_target_links": target_links,
        "errors": errors,
        "valid": not errors,
    }
    if errors:
        raise RuntimeError("; ".join(errors))
    return report
