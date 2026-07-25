-- REVIEW-ONLY. Separate external Preview workspace; never apply to operational DB.
PRAGMA foreign_keys = ON;
PRAGMA application_id = 0x4F445057;
BEGIN IMMEDIATE;

CREATE TABLE preview_runs (
    run_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    attempt INTEGER NOT NULL CHECK (attempt > 0),
    session_status TEXT NOT NULL CHECK (
        session_status IN ('DRAFT', 'UPLOADED', 'PREVIEWING', 'REVIEW_REQUIRED',
                           'READY_FOR_APPROVAL', 'APPROVING', 'APPROVED',
                           'REJECTED', 'FAILED', 'SUPERSEDED')
    ),
    run_status TEXT NOT NULL CHECK (
        run_status IN ('QUEUED', 'RUNNING', 'READY', 'FAILED', 'STALE', 'CANCELLED')
    ),
    source_object_key TEXT NOT NULL CHECK (
        length(source_object_key) BETWEEN 16 AND 200
        AND source_object_key NOT LIKE '%..%'
        AND source_object_key NOT GLOB '*[^A-Za-z0-9._:-]*'
    ),
    source_sha256 BLOB NOT NULL CHECK (length(source_sha256) = 32),
    source_size_bytes INTEGER NOT NULL CHECK (source_size_bytes >= 0),
    template_version TEXT NOT NULL,
    parser_version TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    reference_fingerprint BLOB NOT NULL CHECK (length(reference_fingerprint) = 32),
    observed_snapshot_public_id TEXT,
    observed_ledger_head INTEGER NOT NULL CHECK (observed_ledger_head >= 0),
    freeze_token_hash BLOB NOT NULL CHECK (length(freeze_token_hash) = 32),
    started_at_us INTEGER,
    completed_at_us INTEGER,
    last_checkpoint_row INTEGER NOT NULL DEFAULT 0 CHECK (last_checkpoint_row >= 0),
    row_count INTEGER NOT NULL DEFAULT 0 CHECK (row_count >= 0),
    finding_count INTEGER NOT NULL DEFAULT 0 CHECK (finding_count >= 0),
    preview_digest BLOB CHECK (preview_digest IS NULL OR length(preview_digest) = 32),
    failure_code TEXT,
    failure_message TEXT,
    UNIQUE (session_id, attempt)
) STRICT;

CREATE INDEX ix_preview_runs_session
ON preview_runs(session_id, attempt, run_id);

CREATE UNIQUE INDEX ux_preview_ready_digest
ON preview_runs(session_id, preview_digest)
WHERE run_status = 'READY' AND preview_digest IS NOT NULL;

CREATE TABLE preview_rows (
    row_id INTEGER PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES preview_runs(run_id) ON DELETE CASCADE,
    source_sheet TEXT NOT NULL,
    source_row_number INTEGER NOT NULL CHECK (source_row_number > 0),
    source_row_id TEXT NOT NULL,
    row_sha256 BLOB NOT NULL CHECK (length(row_sha256) = 32),
    raw_payload_json TEXT NOT NULL CHECK (json_valid(raw_payload_json)),
    normalized_payload_json TEXT NOT NULL CHECK (json_valid(normalized_payload_json)),
    row_status TEXT NOT NULL CHECK (row_status IN ('VALID', 'WARNING', 'BLOCKED')),
    stock_subject_kind TEXT NOT NULL CHECK (
        stock_subject_kind IN ('SERIALIZED', 'BULK', 'CABLE', 'CONSUMABLE')
    ),
    proposed_match_key TEXT NOT NULL DEFAULT '',
    processed_at_us INTEGER NOT NULL CHECK (processed_at_us > 0),
    UNIQUE (run_id, source_sheet, source_row_number),
    UNIQUE (run_id, source_row_id)
) STRICT;

CREATE INDEX ix_preview_rows_status_page
ON preview_rows(run_id, row_status, row_id);

CREATE INDEX ix_preview_rows_match
ON preview_rows(run_id, proposed_match_key, row_id);

CREATE TABLE preview_cells (
    cell_id INTEGER PRIMARY KEY,
    row_id INTEGER NOT NULL REFERENCES preview_rows(row_id) ON DELETE CASCADE,
    column_code TEXT NOT NULL,
    coordinate TEXT NOT NULL,
    excel_cell_type TEXT NOT NULL,
    number_format TEXT NOT NULL,
    raw_xml_value TEXT NOT NULL,
    display_value TEXT NOT NULL,
    preservation_status TEXT NOT NULL,
    cell_sha256 BLOB NOT NULL CHECK (length(cell_sha256) = 32),
    UNIQUE (row_id, column_code)
) STRICT;

CREATE TABLE preview_findings (
    finding_id INTEGER PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES preview_runs(run_id) ON DELETE CASCADE,
    row_id INTEGER REFERENCES preview_rows(row_id) ON DELETE CASCADE,
    code TEXT NOT NULL,
    severity TEXT NOT NULL CHECK (severity IN ('INFO', 'WARNING', 'ERROR')),
    blocking INTEGER NOT NULL CHECK (blocking IN (0, 1)),
    field_code TEXT,
    message TEXT NOT NULL,
    evidence_json TEXT NOT NULL CHECK (json_valid(evidence_json)),
    finding_checksum BLOB NOT NULL CHECK (length(finding_checksum) = 32),
    finding_status TEXT NOT NULL CHECK (
        finding_status IN ('OPEN', 'RESOLVED', 'WAIVED')
    ),
    UNIQUE (run_id, row_id, code, finding_checksum)
) STRICT;

CREATE INDEX ix_preview_findings_page
ON preview_findings(run_id, blocking, finding_status, severity, finding_id);

CREATE TABLE preview_matches (
    match_id INTEGER PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES preview_runs(run_id) ON DELETE CASCADE,
    row_id INTEGER NOT NULL REFERENCES preview_rows(row_id) ON DELETE CASCADE,
    candidate_type TEXT NOT NULL,
    candidate_public_id TEXT,
    match_kind TEXT NOT NULL CHECK (
        match_kind IN ('EXACT', 'ALIAS', 'SIMILAR', 'CONFLICT', 'NONE')
    ),
    score_basis_json TEXT NOT NULL CHECK (json_valid(score_basis_json)),
    is_selected INTEGER NOT NULL DEFAULT 0 CHECK (is_selected IN (0, 1)),
    match_checksum BLOB NOT NULL CHECK (length(match_checksum) = 32),
    UNIQUE (run_id, row_id, candidate_type, candidate_public_id)
) STRICT;

CREATE INDEX ix_preview_matches_row
ON preview_matches(run_id, row_id, match_kind, match_id);

CREATE TABLE preview_resolutions (
    resolution_id INTEGER PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES preview_runs(run_id) ON DELETE CASCADE,
    finding_id INTEGER REFERENCES preview_findings(finding_id),
    row_id INTEGER REFERENCES preview_rows(row_id),
    action_code TEXT NOT NULL,
    target_public_id TEXT,
    replacement_value_public_id TEXT,
    reason TEXT NOT NULL CHECK (length(trim(reason)) > 0),
    actor_user_public_id TEXT NOT NULL,
    actor_display_name TEXT NOT NULL,
    created_at_us INTEGER NOT NULL CHECK (created_at_us > 0),
    supersedes_resolution_id INTEGER UNIQUE
        REFERENCES preview_resolutions(resolution_id),
    resolution_checksum BLOB NOT NULL CHECK (length(resolution_checksum) = 32),
    UNIQUE (run_id, resolution_checksum),
    CHECK (finding_id IS NOT NULL OR row_id IS NOT NULL)
) STRICT;

CREATE INDEX ix_preview_resolutions_row
ON preview_resolutions(run_id, row_id, resolution_id);

CREATE TABLE preview_statistics (
    run_id TEXT NOT NULL REFERENCES preview_runs(run_id) ON DELETE CASCADE,
    metric_code TEXT NOT NULL,
    dimension_key TEXT NOT NULL DEFAULT '',
    value_integer INTEGER,
    value_json TEXT CHECK (value_json IS NULL OR json_valid(value_json)),
    statistics_checksum BLOB NOT NULL CHECK (length(statistics_checksum) = 32),
    PRIMARY KEY (run_id, metric_code, dimension_key),
    CHECK ((value_integer IS NOT NULL) <> (value_json IS NOT NULL))
) STRICT, WITHOUT ROWID;

COMMIT;
PRAGMA user_version = 1;
