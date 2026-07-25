-- APPROVED_FOR_IMPLEMENTATION. Never apply directly to data/warehouse.db.
-- Owner modules: audit, reports, infrastructure/operations.
PRAGMA foreign_keys = ON;
BEGIN IMMEDIATE;

CREATE TABLE audit_events (
    audit_event_id INTEGER PRIMARY KEY,
    public_id TEXT NOT NULL UNIQUE CHECK (length(public_id) BETWEEN 32 AND 40),
    occurred_at_us INTEGER NOT NULL CHECK (occurred_at_us > 0),
    action_code TEXT NOT NULL CHECK (length(action_code) > 0),
    outcome TEXT NOT NULL CHECK (outcome IN ('SUCCESS', 'DENIED', 'FAILED')),
    actor_user_id INTEGER REFERENCES users(user_id),
    actor_display_name TEXT NOT NULL CHECK (length(trim(actor_display_name)) > 0),
    actor_role_code TEXT CHECK (
        actor_role_code IS NULL OR actor_role_code IN ('operator', 'admin', 'auditor')
    ),
    session_id TEXT REFERENCES sessions(session_id),
    permission_code TEXT REFERENCES permissions(permission_code),
    correlation_id TEXT NOT NULL,
    subject_type TEXT NOT NULL CHECK (length(subject_type) > 0),
    subject_public_id TEXT,
    ip_hash BLOB CHECK (ip_hash IS NULL OR length(ip_hash) = 32),
    user_agent_family TEXT,
    details_json TEXT NOT NULL CHECK (json_valid(details_json)),
    previous_event_hash BLOB CHECK (
        previous_event_hash IS NULL OR length(previous_event_hash) = 32
    ),
    event_hash BLOB NOT NULL UNIQUE CHECK (length(event_hash) = 32),
    CHECK (actor_user_id IS NOT NULL OR actor_display_name = 'SYSTEM')
) STRICT;

CREATE INDEX ix_audit_events_page
ON audit_events(occurred_at_us, audit_event_id);

CREATE INDEX ix_audit_events_actor
ON audit_events(actor_user_id, occurred_at_us, audit_event_id);

CREATE INDEX ix_audit_events_action
ON audit_events(action_code, occurred_at_us, audit_event_id);

CREATE INDEX ix_audit_events_subject
ON audit_events(subject_type, subject_public_id, occurred_at_us, audit_event_id);

CREATE INDEX ix_audit_events_correlation
ON audit_events(correlation_id, audit_event_id);

CREATE TABLE report_jobs (
    report_job_id INTEGER PRIMARY KEY,
    public_id TEXT NOT NULL UNIQUE CHECK (length(public_id) BETWEEN 32 AND 40),
    report_type TEXT NOT NULL CHECK (length(report_type) > 0),
    parameters_json TEXT NOT NULL CHECK (json_valid(parameters_json)),
    requested_by_user_id INTEGER NOT NULL REFERENCES users(user_id),
    status TEXT NOT NULL CHECK (
        status IN ('QUEUED', 'RUNNING', 'COMPLETED', 'FAILED', 'CANCELLED')
    ),
    source_fingerprint_json TEXT NOT NULL CHECK (json_valid(source_fingerprint_json)),
    artifact_object_key TEXT CHECK (
        artifact_object_key IS NULL OR (
            artifact_object_key NOT LIKE '%..%'
            AND artifact_object_key NOT GLOB '*[^A-Za-z0-9._:-]*'
        )
    ),
    artifact_sha256 BLOB CHECK (
        artifact_sha256 IS NULL OR length(artifact_sha256) = 32
    ),
    created_at_us INTEGER NOT NULL CHECK (created_at_us > 0),
    started_at_us INTEGER,
    completed_at_us INTEGER,
    failure_code TEXT,
    CHECK (
        (status = 'COMPLETED' AND artifact_object_key IS NOT NULL
            AND artifact_sha256 IS NOT NULL AND completed_at_us IS NOT NULL)
        OR status <> 'COMPLETED'
    )
) STRICT;

CREATE INDEX ix_report_jobs_user_page
ON report_jobs(requested_by_user_id, created_at_us, report_job_id);

CREATE INDEX ix_report_jobs_status
ON report_jobs(status, created_at_us, report_job_id);

CREATE TABLE backup_records (
    backup_record_id INTEGER PRIMARY KEY,
    public_id TEXT NOT NULL UNIQUE CHECK (length(public_id) BETWEEN 32 AND 40),
    storage_object_key TEXT NOT NULL UNIQUE CHECK (
        length(storage_object_key) BETWEEN 16 AND 200
        AND storage_object_key NOT LIKE '%..%'
        AND storage_object_key NOT GLOB '*[^A-Za-z0-9._:-]*'
    ),
    database_sha256 BLOB NOT NULL CHECK (length(database_sha256) = 32),
    manifest_sha256 BLOB NOT NULL CHECK (length(manifest_sha256) = 32),
    database_size_bytes INTEGER NOT NULL CHECK (database_size_bytes > 0),
    schema_version INTEGER NOT NULL CHECK (schema_version >= 1),
    snapshot_id INTEGER REFERENCES inventory_snapshots(snapshot_id),
    ledger_sequence INTEGER NOT NULL CHECK (ledger_sequence >= 0),
    status TEXT NOT NULL CHECK (
        status IN ('VERIFIED', 'EXPIRED', 'RESTORED', 'FAILED')
    ),
    created_by_user_id INTEGER NOT NULL REFERENCES users(user_id),
    actor_display_name TEXT NOT NULL CHECK (length(trim(actor_display_name)) > 0),
    created_at_us INTEGER NOT NULL CHECK (created_at_us > 0),
    verified_at_us INTEGER,
    retention_until_us INTEGER NOT NULL CHECK (retention_until_us > created_at_us),
    CHECK (
        (status IN ('VERIFIED', 'EXPIRED', 'RESTORED') AND verified_at_us IS NOT NULL)
        OR status = 'FAILED'
    )
) STRICT;

CREATE INDEX ix_backup_records_page
ON backup_records(created_at_us, backup_record_id);

CREATE INDEX ix_backup_records_retention
ON backup_records(status, retention_until_us, backup_record_id);

CREATE TRIGGER trg_audit_events_no_update
BEFORE UPDATE ON audit_events
BEGIN SELECT RAISE(ABORT, 'audit events are immutable'); END;

CREATE TRIGGER trg_audit_events_no_delete
BEFORE DELETE ON audit_events
BEGIN SELECT RAISE(ABORT, 'audit events are retained'); END;

CREATE TRIGGER trg_uom_scale_immutable_after_use
BEFORE UPDATE OF scale, dimension ON uoms
WHEN EXISTS (SELECT 1 FROM catalog_items c WHERE c.default_uom_id = OLD.uom_id)
  OR EXISTS (SELECT 1 FROM inventory_snapshot_items s WHERE s.uom_id = OLD.uom_id)
  OR EXISTS (SELECT 1 FROM inventory_cycle_count_items c WHERE c.uom_id = OLD.uom_id)
  OR EXISTS (SELECT 1 FROM inventory_reconciliation_items r WHERE r.uom_id = OLD.uom_id)
  OR EXISTS (SELECT 1 FROM warehouse_transaction_lines l WHERE l.uom_id = OLD.uom_id)
  OR EXISTS (SELECT 1 FROM balance_projection_rows p WHERE p.uom_id = OLD.uom_id)
BEGIN
    SELECT RAISE(ABORT, 'used UOM dimension and scale are immutable');
END;

COMMIT;
PRAGMA user_version = 8;
