"""Candidate-only schema for the full historical warehouse build.

The tables in this module are layered on the validated Stage 0.13.3A
candidate.  They are never created in ``data/warehouse.db``.
"""

from __future__ import annotations

import sqlite3


FULL_MARKER = "FULL_WAREHOUSE_CANDIDATE"
FULL_STAGE = "FULL_HISTORICAL_WAREHOUSE_CANDIDATE"
FULL_STATUS = "READY_FOR_MANUAL_ACCEPTANCE"

RECEIPT_STATUSES = (
    "IMPORTED",
    "LINKED_TO_EXISTING_IDENTITY",
    "EXACT_DUPLICATE",
    "CONFLICT_HISTORY_ONLY",
    "NUMERIC_PROVISIONAL_IMPORTED",
    "QUARANTINED",
    "SOURCE_CORRUPTED_REJECTED",
    "QUANTITY_DEFERRED",
    "FAILED_WITH_REASON",
)

ISSUE_STATUSES = (
    "IMPORTED",
    "LINKED_TO_IDENTITY",
    "EXACT_DUPLICATE",
    "CONFLICT_HISTORY_ONLY",
    "OPENING_STATE_CREATED",
    "UNRESOLVED_ISSUE",
    "NUMERIC_PROVISIONAL_LINKED",
    "QUARANTINED",
    "QUANTITY_DEFERRED",
    "FAILED_WITH_REASON",
)

FULL_TABLES = (
    "migration_full_marker",
    "migration_full_identities",
    "migration_full_reconciliation",
    "migration_full_warnings",
    "migration_full_quarantine",
    "migration_full_relationships",
    "migration_full_performance",
    "migration_full_cleanliness",
)

_RECEIPT_STATUS_SQL = ", ".join(f"'{value}'" for value in RECEIPT_STATUSES)
_ISSUE_STATUS_SQL = ", ".join(f"'{value}'" for value in ISSUE_STATUSES)


SCHEMA = f"""
PRAGMA foreign_keys = ON;

CREATE TABLE migration_full_marker (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    marker TEXT NOT NULL UNIQUE CHECK (marker = '{FULL_MARKER}'),
    stage TEXT NOT NULL CHECK (stage = '{FULL_STAGE}'),
    status TEXT NOT NULL CHECK (status = '{FULL_STATUS}'),
    review_read_only INTEGER NOT NULL CHECK (review_read_only = 1),
    source_candidate_sha256 TEXT NOT NULL CHECK (length(source_candidate_sha256) = 64),
    source_manifest_sha256 TEXT NOT NULL CHECK (length(source_manifest_sha256) = 64),
    source_workbook_sha256 TEXT NOT NULL CHECK (length(source_workbook_sha256) = 64),
    production_baseline_sha256 TEXT NOT NULL CHECK (length(production_baseline_sha256) = 64),
    receipt_source_rows INTEGER NOT NULL CHECK (receipt_source_rows = 51003),
    issue_source_rows INTEGER NOT NULL CHECK (issue_source_rows = 20357),
    reconciliation_rows INTEGER NOT NULL CHECK (reconciliation_rows = 71360),
    identity_count INTEGER NOT NULL CHECK (identity_count >= 0),
    receipt_count INTEGER NOT NULL CHECK (receipt_count >= 0),
    issue_count INTEGER NOT NULL CHECK (issue_count >= 0),
    opening_state_count INTEGER NOT NULL CHECK (opening_state_count >= 0),
    provisional_identity_count INTEGER NOT NULL CHECK (provisional_identity_count >= 0),
    quarantine_count INTEGER NOT NULL CHECK (quarantine_count >= 0),
    receipt_status_counts TEXT NOT NULL,
    issue_status_counts TEXT NOT NULL,
    raw_hashes TEXT NOT NULL,
    build_key TEXT NOT NULL UNIQUE,
    build_started_at TEXT NOT NULL,
    built_at TEXT NOT NULL
);

CREATE TABLE migration_full_identities (
    id INTEGER PRIMARY KEY,
    identity_key TEXT NOT NULL UNIQUE,
    normalized_match_value TEXT NOT NULL,
    preserved_serial_value TEXT NOT NULL,
    display_serial_value TEXT NOT NULL,
    raw_xml_value TEXT NOT NULL,
    preservation_status TEXT NOT NULL CHECK (
        preservation_status IN ('TEXT_EXACT', 'NUMERIC_FORMAT_UNPROVEN')
    ),
    identity_confidence TEXT NOT NULL CHECK (
        identity_confidence IN ('AUTHORITATIVE', 'PROVISIONAL')
    ),
    authoritative INTEGER NOT NULL CHECK (authoritative IN (0, 1)),
    requires_manual_review INTEGER NOT NULL CHECK (requires_manual_review IN (0, 1)),
    opening_state INTEGER NOT NULL DEFAULT 0 CHECK (opening_state IN (0, 1)),
    primary_staging_row_id INTEGER NOT NULL REFERENCES migration_staging_rows(id),
    target_receipt_id INTEGER NOT NULL UNIQUE REFERENCES stock_receipts(id),
    source_row_count INTEGER NOT NULL CHECK (source_row_count > 0),
    source_item_name TEXT NOT NULL,
    canonical_item_name TEXT NOT NULL,
    object_kind TEXT NOT NULL,
    category TEXT NOT NULL,
    equipment_type TEXT NOT NULL,
    component_type TEXT NOT NULL,
    vendor TEXT NOT NULL,
    model TEXT NOT NULL,
    part_number TEXT NOT NULL,
    normalization_rule TEXT NOT NULL,
    warnings TEXT NOT NULL DEFAULT '[]',
    conflicts TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);

CREATE TABLE migration_full_reconciliation (
    id INTEGER PRIMARY KEY,
    staging_row_id INTEGER NOT NULL UNIQUE REFERENCES migration_staging_rows(id),
    operation_kind TEXT NOT NULL CHECK (operation_kind IN ('RECEIPT', 'ISSUE')),
    source_file TEXT NOT NULL,
    source_sheet TEXT NOT NULL,
    source_row INTEGER NOT NULL CHECK (source_row > 0),
    source_row_hash TEXT NOT NULL CHECK (length(source_row_hash) = 64),
    source_serial_value TEXT NOT NULL,
    display_serial_value TEXT NOT NULL,
    normalized_match_value TEXT NOT NULL,
    raw_xml_value TEXT NOT NULL,
    preservation_status TEXT NOT NULL,
    identity_confidence TEXT NOT NULL,
    authoritative INTEGER NOT NULL CHECK (authoritative IN (0, 1)),
    requires_manual_review INTEGER NOT NULL CHECK (requires_manual_review IN (0, 1)),
    final_status TEXT NOT NULL CHECK (
        (operation_kind='RECEIPT' AND final_status IN ({_RECEIPT_STATUS_SQL})) OR
        (operation_kind='ISSUE' AND final_status IN ({_ISSUE_STATUS_SQL}))
    ),
    target_identity_id INTEGER REFERENCES migration_full_identities(id),
    target_receipt_id INTEGER REFERENCES stock_receipts(id),
    target_issue_id INTEGER REFERENCES stock_issues(id),
    source_item_name TEXT NOT NULL,
    canonical_item_name TEXT NOT NULL,
    source_inventory_number TEXT NOT NULL,
    object_kind TEXT NOT NULL,
    category TEXT NOT NULL,
    equipment_type TEXT NOT NULL,
    component_type TEXT NOT NULL,
    vendor TEXT NOT NULL,
    model TEXT NOT NULL,
    part_number TEXT NOT NULL,
    quantity TEXT NOT NULL,
    source_operation_date TEXT NOT NULL,
    source_operation_date_raw TEXT NOT NULL,
    source_operation_date_status TEXT NOT NULL,
    shelf TEXT NOT NULL,
    target_equipment_source_serial TEXT NOT NULL,
    target_equipment_display_serial TEXT NOT NULL,
    target_equipment_preservation_status TEXT NOT NULL,
    warnings TEXT NOT NULL DEFAULT '[]',
    conflicts TEXT NOT NULL DEFAULT '[]',
    non_application_reason TEXT NOT NULL DEFAULT '',
    raw_payload TEXT NOT NULL,
    normalized_payload TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE migration_full_warnings (
    id INTEGER PRIMARY KEY,
    reconciliation_id INTEGER NOT NULL REFERENCES migration_full_reconciliation(id),
    identity_id INTEGER REFERENCES migration_full_identities(id),
    warning_kind TEXT NOT NULL CHECK (warning_kind IN ('WARNING', 'CONFLICT')),
    code TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(reconciliation_id, warning_kind, code)
);

CREATE TABLE migration_full_quarantine (
    id INTEGER PRIMARY KEY,
    reconciliation_id INTEGER NOT NULL UNIQUE REFERENCES migration_full_reconciliation(id),
    reason_code TEXT NOT NULL,
    raw_token TEXT NOT NULL,
    source_file TEXT NOT NULL,
    source_sheet TEXT NOT NULL,
    source_row INTEGER NOT NULL,
    affects_balance INTEGER NOT NULL DEFAULT 0 CHECK (affects_balance = 0),
    resolution_status TEXT NOT NULL DEFAULT 'PENDING' CHECK (
        resolution_status IN ('PENDING', 'APPROVED', 'REJECTED')
    ),
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE migration_full_relationships (
    id INTEGER PRIMARY KEY,
    reconciliation_id INTEGER NOT NULL UNIQUE REFERENCES migration_full_reconciliation(id),
    source_identity_id INTEGER REFERENCES migration_full_identities(id),
    target_identity_id INTEGER REFERENCES migration_full_identities(id),
    relationship_type TEXT NOT NULL CHECK (relationship_type = 'INSTALLED_IN'),
    target_source_serial_value TEXT NOT NULL,
    target_display_serial_value TEXT NOT NULL,
    target_preservation_status TEXT NOT NULL,
    warning TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE migration_full_performance (
    id INTEGER PRIMARY KEY,
    metric TEXT NOT NULL UNIQUE,
    duration_ms TEXT NOT NULL,
    details TEXT NOT NULL DEFAULT '{{}}',
    measured_at TEXT NOT NULL
);

CREATE TABLE migration_full_cleanliness (
    id INTEGER PRIMARY KEY,
    check_kind TEXT NOT NULL,
    source_table TEXT NOT NULL DEFAULT '',
    source_id TEXT NOT NULL DEFAULT '',
    source_serial TEXT NOT NULL DEFAULT '',
    before_count INTEGER,
    after_count INTEGER,
    result TEXT NOT NULL CHECK (result IN ('PASS', 'INFO')),
    details TEXT NOT NULL DEFAULT '{{}}',
    created_at TEXT NOT NULL
);

CREATE INDEX idx_migration_full_identity_display
    ON migration_full_identities(display_serial_value COLLATE NOCASE);
CREATE INDEX idx_migration_full_identity_match
    ON migration_full_identities(preservation_status, normalized_match_value);
CREATE INDEX idx_migration_full_reconciliation_status
    ON migration_full_reconciliation(operation_kind, final_status, source_row);
CREATE INDEX idx_migration_full_reconciliation_identity
    ON migration_full_reconciliation(target_identity_id, source_row);
CREATE INDEX idx_migration_full_reconciliation_serial
    ON migration_full_reconciliation(display_serial_value COLLATE NOCASE);
CREATE INDEX idx_migration_full_warnings_code
    ON migration_full_warnings(warning_kind, code);
"""


def create_full_schema(connection: sqlite3.Connection) -> None:
    """Create full-candidate tables on a disposable Stage A copy."""

    existing = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    overlap = existing.intersection(FULL_TABLES)
    if overlap:
        raise RuntimeError(
            "full candidate schema already exists: " + ", ".join(sorted(overlap))
        )
    connection.executescript(SCHEMA)


__all__ = [
    "FULL_MARKER",
    "FULL_STAGE",
    "FULL_STATUS",
    "FULL_TABLES",
    "ISSUE_STATUSES",
    "RECEIPT_STATUSES",
    "create_full_schema",
]
