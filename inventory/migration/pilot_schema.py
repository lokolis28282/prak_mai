"""Pilot-only SQLite schema layered on a disposable Stage 0.13.3A candidate."""

from __future__ import annotations

import sqlite3

from .pilot_models import PILOT_DECISIONS


PILOT_TABLES = (
    "migration_pilot_marker",
    "migration_pilot_selection",
    "migration_pilot_identities",
    "migration_pilot_provenance",
    "migration_pilot_quarantine",
    "migration_pilot_performance",
)

_DECISION_SQL = ", ".join(f"'{value}'" for value in PILOT_DECISIONS)

SCHEMA = f"""
PRAGMA foreign_keys = ON;

CREATE TABLE migration_pilot_marker (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    marker TEXT NOT NULL UNIQUE CHECK (marker = 'ODE_MIGRATION_PILOT'),
    stage TEXT NOT NULL CHECK (stage = '0.13.3A.5'),
    pilot_only INTEGER NOT NULL CHECK (pilot_only = 1),
    review_read_only INTEGER NOT NULL CHECK (review_read_only = 1),
    status TEXT NOT NULL CHECK (status = 'READY_FOR_REVIEW'),
    selection_seed TEXT NOT NULL,
    selection_sha256 TEXT NOT NULL CHECK (length(selection_sha256) = 64),
    source_candidate_sha256 TEXT NOT NULL CHECK (length(source_candidate_sha256) = 64),
    source_manifest_sha256 TEXT NOT NULL CHECK (length(source_manifest_sha256) = 64),
    serial_review_sha256 TEXT NOT NULL CHECK (length(serial_review_sha256) = 64),
    selected_count INTEGER NOT NULL CHECK (selected_count BETWEEN 100 AND 300),
    imported_count INTEGER NOT NULL CHECK (imported_count >= 0),
    quarantined_count INTEGER NOT NULL CHECK (quarantined_count >= 0),
    decision_counts TEXT NOT NULL,
    quota_counts TEXT NOT NULL,
    unavailable_requirements TEXT NOT NULL DEFAULT '[]',
    build_started_at TEXT NOT NULL,
    built_at TEXT NOT NULL
);

CREATE TABLE migration_pilot_selection (
    id INTEGER PRIMARY KEY,
    selection_order INTEGER NOT NULL UNIQUE,
    staging_row_id INTEGER NOT NULL UNIQUE
        REFERENCES migration_staging_rows(id),
    migration_batch_id INTEGER NOT NULL REFERENCES migration_batches(id),
    source_file TEXT NOT NULL,
    source_sheet TEXT NOT NULL,
    source_row INTEGER NOT NULL CHECK (source_row > 0),
    source_row_hash TEXT NOT NULL CHECK (length(source_row_hash) = 64),
    source_serial_value TEXT NOT NULL,
    normalized_match_value TEXT NOT NULL,
    serial_preservation_status TEXT NOT NULL,
    excel_cell_type TEXT NOT NULL,
    excel_number_format TEXT NOT NULL,
    raw_xml_value TEXT NOT NULL,
    source_display_value TEXT NOT NULL,
    source_serial_hash TEXT NOT NULL CHECK (length(source_serial_hash) = 64),
    source_item_name TEXT NOT NULL,
    canonical_item_name TEXT NOT NULL,
    object_kind TEXT NOT NULL,
    equipment_category TEXT NOT NULL,
    equipment_type TEXT NOT NULL,
    component_type TEXT NOT NULL,
    vendor TEXT NOT NULL,
    model TEXT NOT NULL,
    part_number TEXT NOT NULL,
    supplier TEXT NOT NULL,
    datacenter TEXT NOT NULL,
    shelf TEXT NOT NULL,
    quantity TEXT NOT NULL,
    source_receipt_date TEXT NOT NULL,
    source_receipt_date_raw TEXT NOT NULL,
    source_receipt_date_status TEXT NOT NULL,
    source_receipt_date_cell_type TEXT NOT NULL,
    source_receipt_date_number_format TEXT NOT NULL,
    migration_warnings TEXT NOT NULL,
    selection_reasons TEXT NOT NULL,
    quota_flags TEXT NOT NULL,
    conflict_types TEXT NOT NULL,
    duplicate_group_size INTEGER NOT NULL CHECK (duplicate_group_size >= 0),
    import_decision TEXT NOT NULL CHECK (import_decision IN ({_DECISION_SQL})),
    identity_key TEXT NOT NULL,
    target_receipt_id INTEGER REFERENCES stock_receipts(id),
    created_at TEXT NOT NULL
);

CREATE TABLE migration_pilot_identities (
    id INTEGER PRIMARY KEY,
    normalized_match_value TEXT NOT NULL UNIQUE,
    preserved_serial_value TEXT NOT NULL,
    primary_selection_id INTEGER NOT NULL UNIQUE
        REFERENCES migration_pilot_selection(id),
    target_receipt_id INTEGER NOT NULL UNIQUE REFERENCES stock_receipts(id),
    source_row_count INTEGER NOT NULL CHECK (source_row_count > 0),
    created_at TEXT NOT NULL
);

CREATE TABLE migration_pilot_provenance (
    id INTEGER PRIMARY KEY,
    selection_id INTEGER NOT NULL UNIQUE
        REFERENCES migration_pilot_selection(id),
    identity_id INTEGER REFERENCES migration_pilot_identities(id),
    target_receipt_id INTEGER REFERENCES stock_receipts(id),
    source_file TEXT NOT NULL,
    source_sheet TEXT NOT NULL,
    source_row INTEGER NOT NULL,
    source_row_hash TEXT NOT NULL,
    source_serial_value TEXT NOT NULL,
    normalized_match_value TEXT NOT NULL,
    source_item_name TEXT NOT NULL,
    canonical_item_name TEXT NOT NULL,
    source_receipt_date TEXT NOT NULL,
    source_receipt_date_raw TEXT NOT NULL,
    source_receipt_date_status TEXT NOT NULL,
    shelf TEXT NOT NULL,
    import_decision TEXT NOT NULL CHECK (import_decision IN ({_DECISION_SQL})),
    warnings TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE migration_pilot_quarantine (
    id INTEGER PRIMARY KEY,
    selection_id INTEGER NOT NULL UNIQUE
        REFERENCES migration_pilot_selection(id),
    reason_code TEXT NOT NULL,
    resolution_status TEXT NOT NULL DEFAULT 'PENDING'
        CHECK (resolution_status IN ('PENDING', 'APPROVED', 'REJECTED')),
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE migration_pilot_performance (
    id INTEGER PRIMARY KEY,
    metric TEXT NOT NULL UNIQUE,
    duration_ms TEXT NOT NULL,
    measured_at TEXT NOT NULL,
    details TEXT NOT NULL DEFAULT '{{}}'
);

CREATE INDEX idx_migration_pilot_selection_decision
    ON migration_pilot_selection(import_decision, selection_order);
CREATE INDEX idx_migration_pilot_selection_serial
    ON migration_pilot_selection(normalized_match_value, source_serial_value);
CREATE INDEX idx_migration_pilot_selection_receipt
    ON migration_pilot_selection(target_receipt_id);
CREATE INDEX idx_migration_pilot_provenance_receipt
    ON migration_pilot_provenance(target_receipt_id, source_row);
"""


def create_pilot_schema(connection: sqlite3.Connection) -> None:
    existing = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    overlap = existing.intersection(PILOT_TABLES)
    if overlap:
        raise RuntimeError(
            "pilot schema already exists: " + ", ".join(sorted(overlap))
        )
    connection.executescript(SCHEMA)
