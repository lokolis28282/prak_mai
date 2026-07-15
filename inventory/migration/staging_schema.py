"""Candidate-only schema for reference data and migration staging.

These tables deliberately do not belong to :mod:`inventory.db`.  They are
created only in a disposable candidate database and cannot be reached from the
ODE runtime.
"""

from __future__ import annotations

import sqlite3


STAGING_TABLES = (
    "migration_batches",
    "migration_source_files",
    "reference_domains_v2",
    "reference_values_v2",
    "reference_aliases_v2",
    "catalog_items_v2",
    "migration_staging_rows",
    "migration_serial_cells",
    "migration_validation_results",
)


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE migration_batches (
    id INTEGER PRIMARY KEY,
    batch_key TEXT NOT NULL UNIQUE,
    stage TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('BUILDING', 'REVIEW_REQUIRED', 'VALIDATED', 'REJECTED')
    ),
    source_manifest_sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL,
    completed_at TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT ''
);

CREATE TABLE migration_source_files (
    id INTEGER PRIMARY KEY,
    batch_id INTEGER NOT NULL REFERENCES migration_batches(id) ON DELETE CASCADE,
    source_path TEXT NOT NULL,
    file_name TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0),
    immutable INTEGER NOT NULL DEFAULT 1 CHECK (immutable = 1),
    created_at TEXT NOT NULL,
    UNIQUE(batch_id, source_path)
);

CREATE TABLE reference_domains_v2 (
    id INTEGER PRIMARY KEY,
    domain_key TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    source TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE reference_values_v2 (
    id INTEGER PRIMARY KEY,
    domain_id INTEGER NOT NULL REFERENCES reference_domains_v2(id),
    canonical_value TEXT NOT NULL,
    display_name TEXT NOT NULL,
    normalized_key TEXT NOT NULL,
    scope_key TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    approval_status TEXT NOT NULL CHECK (
        approval_status IN ('APPROVED', 'CANDIDATE', 'REJECTED')
    ),
    source TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(domain_id, scope_key, normalized_key)
);

CREATE TABLE reference_aliases_v2 (
    id INTEGER PRIMARY KEY,
    domain_id INTEGER NOT NULL REFERENCES reference_domains_v2(id),
    source_value TEXT NOT NULL,
    normalized_source_key TEXT NOT NULL,
    canonical_id INTEGER NOT NULL REFERENCES reference_values_v2(id),
    source_file TEXT NOT NULL,
    source_sheet TEXT NOT NULL,
    usage_count INTEGER NOT NULL DEFAULT 0 CHECK (usage_count >= 0),
    confidence TEXT NOT NULL CHECK (confidence IN ('HIGH', 'MEDIUM', 'LOW')),
    resolution_status TEXT NOT NULL CHECK (
        resolution_status IN ('AUTO_APPROVED', 'APPROVED', 'PENDING', 'REJECTED')
    ),
    approved_by TEXT NOT NULL DEFAULT '',
    approved_at TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    UNIQUE(domain_id, source_value, canonical_id, source_file, source_sheet)
);

CREATE TABLE catalog_items_v2 (
    id INTEGER PRIMARY KEY,
    reference_value_id INTEGER NOT NULL UNIQUE REFERENCES reference_values_v2(id),
    canonical_item_name TEXT NOT NULL,
    object_kind_id INTEGER REFERENCES reference_values_v2(id),
    equipment_category_id INTEGER REFERENCES reference_values_v2(id),
    equipment_type_id INTEGER REFERENCES reference_values_v2(id),
    component_type_id INTEGER REFERENCES reference_values_v2(id),
    vendor_id INTEGER REFERENCES reference_values_v2(id),
    model_id INTEGER REFERENCES reference_values_v2(id),
    part_number TEXT NOT NULL DEFAULT '',
    primary_characteristic TEXT NOT NULL DEFAULT '',
    normalization_rule TEXT NOT NULL,
    confidence TEXT NOT NULL CHECK (confidence IN ('HIGH', 'MEDIUM', 'LOW')),
    requires_manual_review INTEGER NOT NULL DEFAULT 1 CHECK (
        requires_manual_review IN (0, 1)
    ),
    resolution_status TEXT NOT NULL CHECK (
        resolution_status IN ('APPROVED', 'PENDING', 'REJECTED')
    ),
    source TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(canonical_item_name, part_number)
);

CREATE TABLE migration_staging_rows (
    id INTEGER PRIMARY KEY,
    batch_id INTEGER NOT NULL REFERENCES migration_batches(id) ON DELETE CASCADE,
    source_file_id INTEGER NOT NULL REFERENCES migration_source_files(id),
    source_sheet TEXT NOT NULL,
    source_row INTEGER NOT NULL CHECK (source_row > 0),
    source_row_hash TEXT NOT NULL,
    operation_kind TEXT NOT NULL CHECK (
        operation_kind IN ('RECEIPT', 'ISSUE', 'REFERENCE_ONLY')
    ),
    raw_payload TEXT NOT NULL,
    normalized_payload TEXT NOT NULL,
    source_serial_value TEXT NOT NULL DEFAULT '',
    normalized_matching_serial TEXT NOT NULL DEFAULT '',
    serial_preservation_status TEXT NOT NULL DEFAULT 'EMPTY',
    proposed_object_kind TEXT NOT NULL DEFAULT '',
    proposed_equipment_category TEXT NOT NULL DEFAULT '',
    proposed_equipment_type TEXT NOT NULL DEFAULT '',
    proposed_component_type TEXT NOT NULL DEFAULT '',
    proposed_vendor TEXT NOT NULL DEFAULT '',
    proposed_model TEXT NOT NULL DEFAULT '',
    proposed_catalog_item TEXT NOT NULL DEFAULT '',
    proposed_catalog_key TEXT NOT NULL DEFAULT '',
    proposed_catalog_item_id INTEGER REFERENCES catalog_items_v2(id),
    proposed_canonical_name TEXT NOT NULL DEFAULT '',
    warnings TEXT NOT NULL DEFAULT '[]',
    conflicts TEXT NOT NULL DEFAULT '[]',
    resolution_status TEXT NOT NULL CHECK (
        resolution_status IN ('UNREVIEWED', 'AUTO_REVIEWED', 'MANUAL_REVIEW', 'BLOCKED', 'APPROVED', 'REJECTED')
    ),
    decision TEXT NOT NULL DEFAULT '',
    target_entity_id TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE(batch_id, source_file_id, source_sheet, source_row, operation_kind)
);

CREATE TABLE migration_serial_cells (
    id INTEGER PRIMARY KEY,
    staging_row_id INTEGER NOT NULL REFERENCES migration_staging_rows(id) ON DELETE CASCADE,
    serial_role TEXT NOT NULL CHECK (
        serial_role IN ('SOURCE_SERIAL', 'TARGET_EQUIPMENT_SERIAL')
    ),
    source_file TEXT NOT NULL,
    source_file_hash TEXT NOT NULL,
    source_sheet TEXT NOT NULL,
    source_row INTEGER NOT NULL,
    source_column TEXT NOT NULL,
    excel_cell_coordinate TEXT NOT NULL,
    excel_cell_type TEXT NOT NULL,
    excel_number_format TEXT NOT NULL,
    raw_xml_value TEXT NOT NULL,
    source_display_value TEXT NOT NULL,
    source_serial_value TEXT NOT NULL,
    normalized_match_value TEXT NOT NULL,
    preservation_status TEXT NOT NULL,
    warning TEXT NOT NULL DEFAULT '',
    source_hash TEXT NOT NULL,
    extraction_rule TEXT NOT NULL,
    confidence TEXT NOT NULL CHECK (confidence IN ('HIGH', 'MEDIUM', 'LOW', 'NONE')),
    requires_manual_review INTEGER NOT NULL CHECK (requires_manual_review IN (0, 1)),
    UNIQUE(staging_row_id, serial_role, excel_cell_coordinate)
);

CREATE TABLE migration_validation_results (
    id INTEGER PRIMARY KEY,
    batch_id INTEGER NOT NULL REFERENCES migration_batches(id) ON DELETE CASCADE,
    severity TEXT NOT NULL CHECK (severity IN ('INFO', 'WARNING', 'ERROR')),
    code TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL DEFAULT '',
    message TEXT NOT NULL,
    details TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE INDEX idx_reference_values_v2_domain
    ON reference_values_v2(domain_id, active, display_name);
CREATE INDEX idx_reference_aliases_v2_lookup
    ON reference_aliases_v2(domain_id, normalized_source_key, resolution_status);
CREATE INDEX idx_staging_rows_source
    ON migration_staging_rows(source_file_id, source_sheet, source_row);
CREATE INDEX idx_staging_rows_serial
    ON migration_staging_rows(normalized_matching_serial, serial_preservation_status);
CREATE INDEX idx_serial_cells_match
    ON migration_serial_cells(normalized_match_value, preservation_status);
CREATE INDEX idx_validation_results_batch
    ON migration_validation_results(batch_id, severity, code);
"""


def create_staging_schema(connection: sqlite3.Connection) -> None:
    """Create the candidate-only tables on a new disposable database."""
    existing = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    overlap = existing.intersection(STAGING_TABLES)
    if overlap:
        raise RuntimeError(
            "candidate staging schema already exists: " + ", ".join(sorted(overlap))
        )
    connection.executescript(SCHEMA)


def assert_staging_schema_absent(connection: sqlite3.Connection) -> None:
    """Fail if a production-like database unexpectedly contains staging tables."""
    present = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }.intersection(STAGING_TABLES)
    if present:
        raise RuntimeError(
            "migration staging tables must not exist in production: "
            + ", ".join(sorted(present))
        )
