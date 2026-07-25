-- APPROVED_FOR_IMPLEMENTATION. Never apply directly to data/warehouse.db.
-- Owner modules: imports, inventory.
PRAGMA foreign_keys = ON;
BEGIN IMMEDIATE;

CREATE TABLE import_commits (
    import_commit_id INTEGER PRIMARY KEY,
    public_id TEXT NOT NULL UNIQUE CHECK (length(public_id) BETWEEN 32 AND 40),
    import_kind TEXT NOT NULL CHECK (
        import_kind IN ('FULL_INVENTORY', 'PARTIAL_INVENTORY',
                        'LEGACY_MIGRATION', 'REFERENCE_IMPORT')
    ),
    source_object_key TEXT NOT NULL CHECK (
        length(source_object_key) BETWEEN 16 AND 200
        AND source_object_key NOT LIKE '%..%'
        AND source_object_key NOT GLOB '*[^A-Za-z0-9._:-]*'
    ),
    source_file_name TEXT NOT NULL CHECK (length(source_file_name) > 0),
    source_sha256 BLOB NOT NULL CHECK (length(source_sha256) = 32),
    source_size_bytes INTEGER NOT NULL CHECK (source_size_bytes >= 0),
    template_version TEXT NOT NULL,
    parser_version TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    preview_digest BLOB NOT NULL CHECK (length(preview_digest) = 32),
    manifest_json TEXT NOT NULL CHECK (json_valid(manifest_json)),
    committed_by_user_id INTEGER NOT NULL REFERENCES users(user_id),
    actor_display_name TEXT NOT NULL CHECK (length(trim(actor_display_name)) > 0),
    committed_at_us INTEGER NOT NULL CHECK (committed_at_us > 0),
    idempotency_key TEXT NOT NULL UNIQUE CHECK (length(idempotency_key) BETWEEN 16 AND 128),
    correlation_id TEXT NOT NULL UNIQUE
) STRICT;

CREATE UNIQUE INDEX ux_import_commits_source_kind_digest
ON import_commits(import_kind, source_sha256, preview_digest);

CREATE INDEX ix_import_commits_time
ON import_commits(committed_at_us, import_commit_id);

CREATE TABLE import_row_links (
    row_link_id INTEGER PRIMARY KEY,
    import_commit_id INTEGER NOT NULL REFERENCES import_commits(import_commit_id),
    source_sheet TEXT NOT NULL CHECK (length(source_sheet) > 0),
    source_row_number INTEGER NOT NULL CHECK (source_row_number > 0),
    source_row_key TEXT NOT NULL CHECK (length(source_row_key) > 0),
    source_row_sha256 BLOB NOT NULL CHECK (length(source_row_sha256) = 32),
    raw_payload_json TEXT NOT NULL CHECK (json_valid(raw_payload_json)),
    target_type TEXT NOT NULL,
    target_public_id TEXT NOT NULL,
    transform_version TEXT NOT NULL,
    UNIQUE (import_commit_id, source_sheet, source_row_number, source_row_key)
) STRICT;

CREATE INDEX ix_import_row_target
ON import_row_links(target_type, target_public_id, row_link_id);

CREATE INDEX ix_import_row_source_hash
ON import_row_links(import_commit_id, source_row_sha256, row_link_id);

CREATE TABLE import_findings (
    import_finding_id INTEGER PRIMARY KEY,
    import_commit_id INTEGER NOT NULL REFERENCES import_commits(import_commit_id),
    row_link_id INTEGER REFERENCES import_row_links(row_link_id),
    code TEXT NOT NULL CHECK (length(code) > 0),
    severity TEXT NOT NULL CHECK (severity IN ('INFO', 'WARNING', 'ERROR')),
    was_blocking INTEGER NOT NULL CHECK (was_blocking IN (0, 1)),
    evidence_json TEXT NOT NULL CHECK (json_valid(evidence_json)),
    finding_checksum BLOB NOT NULL CHECK (length(finding_checksum) = 32),
    UNIQUE (import_commit_id, finding_checksum)
) STRICT;

CREATE INDEX ix_import_findings_page
ON import_findings(import_commit_id, severity, was_blocking, import_finding_id);

CREATE TABLE import_resolutions (
    import_resolution_id INTEGER PRIMARY KEY,
    import_commit_id INTEGER NOT NULL REFERENCES import_commits(import_commit_id),
    import_finding_id INTEGER REFERENCES import_findings(import_finding_id),
    row_link_id INTEGER REFERENCES import_row_links(row_link_id),
    action_code TEXT NOT NULL CHECK (length(action_code) > 0),
    target_type TEXT,
    target_public_id TEXT,
    replacement_reference_value_id INTEGER REFERENCES reference_values(value_id),
    reason TEXT NOT NULL CHECK (length(trim(reason)) > 0),
    actor_user_id INTEGER NOT NULL REFERENCES users(user_id),
    actor_display_name TEXT NOT NULL CHECK (length(trim(actor_display_name)) > 0),
    resolved_at_us INTEGER NOT NULL CHECK (resolved_at_us > 0),
    resolution_checksum BLOB NOT NULL CHECK (length(resolution_checksum) = 32),
    UNIQUE (import_commit_id, resolution_checksum),
    CHECK (import_finding_id IS NOT NULL OR row_link_id IS NOT NULL)
) STRICT;

CREATE INDEX ix_import_resolutions_row
ON import_resolutions(import_commit_id, row_link_id, import_resolution_id);

CREATE TABLE inventory_sessions (
    session_id INTEGER PRIMARY KEY,
    public_id TEXT NOT NULL UNIQUE CHECK (length(public_id) BETWEEN 32 AND 40),
    import_commit_id INTEGER NOT NULL UNIQUE REFERENCES import_commits(import_commit_id),
    scope_type TEXT NOT NULL CHECK (scope_type IN ('FULL', 'PARTIAL')),
    scope_json TEXT NOT NULL CHECK (json_valid(scope_json)),
    status TEXT NOT NULL CHECK (status IN ('APPROVED', 'SUPERSEDED')),
    source_sha256 BLOB NOT NULL CHECK (length(source_sha256) = 32),
    template_version TEXT NOT NULL,
    parser_version TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    preview_digest BLOB NOT NULL CHECK (length(preview_digest) = 32),
    observed_active_snapshot_id INTEGER
        REFERENCES inventory_snapshots(snapshot_id),
    freeze_ledger_cutoff INTEGER NOT NULL CHECK (freeze_ledger_cutoff >= 0),
    freeze_started_at_us INTEGER NOT NULL CHECK (freeze_started_at_us > 0),
    effective_at_us INTEGER NOT NULL CHECK (effective_at_us = freeze_started_at_us),
    count_started_at_us INTEGER NOT NULL CHECK (count_started_at_us >= freeze_started_at_us),
    count_finished_at_us INTEGER NOT NULL CHECK (count_finished_at_us >= count_started_at_us),
    approved_by_user_id INTEGER NOT NULL REFERENCES users(user_id),
    actor_display_name TEXT NOT NULL CHECK (length(trim(actor_display_name)) > 0),
    approved_at_us INTEGER NOT NULL CHECK (approved_at_us >= count_finished_at_us),
    approval_idempotency_key TEXT NOT NULL UNIQUE
        CHECK (length(approval_idempotency_key) BETWEEN 16 AND 128),
    created_at_us INTEGER NOT NULL CHECK (created_at_us > 0),
    updated_at_us INTEGER NOT NULL CHECK (updated_at_us >= created_at_us)
) STRICT;

CREATE INDEX ix_inventory_sessions_page
ON inventory_sessions(scope_type, status, approved_at_us, session_id);

CREATE TABLE inventory_snapshots (
    snapshot_id INTEGER PRIMARY KEY,
    public_id TEXT NOT NULL UNIQUE CHECK (length(public_id) BETWEEN 32 AND 40),
    session_id INTEGER NOT NULL UNIQUE REFERENCES inventory_sessions(session_id),
    previous_snapshot_id INTEGER REFERENCES inventory_snapshots(snapshot_id),
    superseded_by_snapshot_id INTEGER UNIQUE
        REFERENCES inventory_snapshots(snapshot_id)
        DEFERRABLE INITIALLY DEFERRED,
    ledger_cutoff INTEGER NOT NULL CHECK (ledger_cutoff >= 0),
    effective_at_us INTEGER NOT NULL CHECK (effective_at_us > 0),
    status TEXT NOT NULL CHECK (status IN ('APPROVED', 'SUPERSEDED')),
    is_active INTEGER NOT NULL CHECK (is_active IN (0, 1)),
    item_count INTEGER NOT NULL CHECK (item_count >= 0),
    totals_json TEXT NOT NULL CHECK (json_valid(totals_json)),
    content_checksum BLOB NOT NULL CHECK (length(content_checksum) = 32),
    approved_by_user_id INTEGER NOT NULL REFERENCES users(user_id),
    actor_display_name TEXT NOT NULL CHECK (length(trim(actor_display_name)) > 0),
    approved_at_us INTEGER NOT NULL CHECK (approved_at_us >= effective_at_us),
    CHECK (
        (status = 'APPROVED' AND is_active = 1 AND superseded_by_snapshot_id IS NULL)
        OR
        (status = 'SUPERSEDED' AND is_active = 0
            AND superseded_by_snapshot_id IS NOT NULL)
    ),
    CHECK (previous_snapshot_id IS NULL OR previous_snapshot_id <> snapshot_id),
    CHECK (superseded_by_snapshot_id IS NULL OR superseded_by_snapshot_id <> snapshot_id)
) STRICT;

CREATE UNIQUE INDEX ux_inventory_snapshot_active
ON inventory_snapshots(is_active)
WHERE is_active = 1;

CREATE INDEX ix_inventory_snapshots_page
ON inventory_snapshots(approved_at_us, snapshot_id);

CREATE TABLE inventory_snapshot_items (
    snapshot_item_id INTEGER PRIMARY KEY,
    snapshot_id INTEGER NOT NULL REFERENCES inventory_snapshots(snapshot_id),
    row_link_id INTEGER NOT NULL REFERENCES import_row_links(row_link_id),
    equipment_id INTEGER REFERENCES equipment(equipment_id),
    catalog_item_id INTEGER REFERENCES catalog_items(catalog_item_id),
    warehouse_id INTEGER NOT NULL REFERENCES warehouses(warehouse_id),
    location_id INTEGER NOT NULL REFERENCES warehouse_locations(location_id),
    condition_value_id INTEGER NOT NULL REFERENCES reference_values(value_id),
    lot_key TEXT NOT NULL DEFAULT '',
    uom_id INTEGER NOT NULL REFERENCES uoms(uom_id),
    quantity_minor INTEGER NOT NULL CHECK (quantity_minor > 0),
    identity_evidence_json TEXT NOT NULL CHECK (json_valid(identity_evidence_json)),
    row_checksum BLOB NOT NULL CHECK (length(row_checksum) = 32),
    CHECK ((equipment_id IS NOT NULL) <> (catalog_item_id IS NOT NULL)),
    UNIQUE (snapshot_id, row_link_id)
) STRICT;

CREATE UNIQUE INDEX ux_snapshot_item_equipment
ON inventory_snapshot_items(snapshot_id, equipment_id)
WHERE equipment_id IS NOT NULL;

CREATE UNIQUE INDEX ux_snapshot_item_bulk_key
ON inventory_snapshot_items(
    snapshot_id, catalog_item_id, warehouse_id, location_id,
    condition_value_id, lot_key, uom_id
)
WHERE catalog_item_id IS NOT NULL;

CREATE INDEX ix_snapshot_items_page
ON inventory_snapshot_items(snapshot_id, snapshot_item_id);

CREATE INDEX ix_snapshot_items_location
ON inventory_snapshot_items(snapshot_id, warehouse_id, location_id, snapshot_item_id);

CREATE TABLE inventory_cycle_counts (
    cycle_count_id INTEGER PRIMARY KEY,
    public_id TEXT NOT NULL UNIQUE CHECK (length(public_id) BETWEEN 32 AND 40),
    session_id INTEGER NOT NULL UNIQUE REFERENCES inventory_sessions(session_id),
    scope_json TEXT NOT NULL CHECK (json_valid(scope_json)),
    result_checksum BLOB NOT NULL CHECK (length(result_checksum) = 32),
    approved_at_us INTEGER NOT NULL CHECK (approved_at_us > 0)
) STRICT;

CREATE TABLE inventory_cycle_count_items (
    cycle_count_item_id INTEGER PRIMARY KEY,
    cycle_count_id INTEGER NOT NULL REFERENCES inventory_cycle_counts(cycle_count_id),
    row_link_id INTEGER NOT NULL REFERENCES import_row_links(row_link_id),
    equipment_id INTEGER REFERENCES equipment(equipment_id),
    catalog_item_id INTEGER REFERENCES catalog_items(catalog_item_id),
    warehouse_id INTEGER NOT NULL REFERENCES warehouses(warehouse_id),
    location_id INTEGER NOT NULL REFERENCES warehouse_locations(location_id),
    condition_value_id INTEGER NOT NULL REFERENCES reference_values(value_id),
    lot_key TEXT NOT NULL DEFAULT '',
    uom_id INTEGER NOT NULL REFERENCES uoms(uom_id),
    quantity_minor INTEGER NOT NULL CHECK (quantity_minor > 0),
    row_checksum BLOB NOT NULL CHECK (length(row_checksum) = 32),
    CHECK ((equipment_id IS NOT NULL) <> (catalog_item_id IS NOT NULL)),
    UNIQUE (cycle_count_id, row_link_id)
) STRICT;

CREATE INDEX ix_cycle_count_items_page
ON inventory_cycle_count_items(cycle_count_id, cycle_count_item_id);

CREATE TABLE inventory_reconciliation_items (
    reconciliation_id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES inventory_sessions(session_id),
    snapshot_id INTEGER REFERENCES inventory_snapshots(snapshot_id),
    cycle_count_id INTEGER REFERENCES inventory_cycle_counts(cycle_count_id),
    equipment_id INTEGER REFERENCES equipment(equipment_id),
    catalog_item_id INTEGER REFERENCES catalog_items(catalog_item_id),
    warehouse_id INTEGER NOT NULL REFERENCES warehouses(warehouse_id),
    location_id INTEGER NOT NULL REFERENCES warehouse_locations(location_id),
    condition_value_id INTEGER NOT NULL REFERENCES reference_values(value_id),
    lot_key TEXT NOT NULL DEFAULT '',
    uom_id INTEGER NOT NULL REFERENCES uoms(uom_id),
    expected_quantity_minor INTEGER NOT NULL CHECK (expected_quantity_minor >= 0),
    counted_quantity_minor INTEGER NOT NULL CHECK (counted_quantity_minor >= 0),
    delta_quantity_minor INTEGER NOT NULL,
    classification TEXT NOT NULL CHECK (
        classification IN ('MATCH', 'NEW', 'MISSING', 'LOCATION_CHANGED',
                           'CONDITION_CHANGED', 'QUANTITY_CHANGED',
                           'IDENTITY_CONFLICT')
    ),
    explanation_json TEXT NOT NULL CHECK (json_valid(explanation_json)),
    import_resolution_id INTEGER REFERENCES import_resolutions(import_resolution_id),
    CHECK ((equipment_id IS NOT NULL) <> (catalog_item_id IS NOT NULL)),
    CHECK ((snapshot_id IS NOT NULL) <> (cycle_count_id IS NOT NULL)),
    CHECK (delta_quantity_minor = counted_quantity_minor - expected_quantity_minor)
) STRICT;

CREATE UNIQUE INDEX ux_reconciliation_equipment
ON inventory_reconciliation_items(session_id, equipment_id, warehouse_id,
    location_id, condition_value_id, lot_key, uom_id, classification)
WHERE equipment_id IS NOT NULL;

CREATE UNIQUE INDEX ux_reconciliation_bulk
ON inventory_reconciliation_items(session_id, catalog_item_id, warehouse_id,
    location_id, condition_value_id, lot_key, uom_id, classification)
WHERE catalog_item_id IS NOT NULL;

CREATE INDEX ix_reconciliation_page
ON inventory_reconciliation_items(session_id, classification, reconciliation_id);

CREATE TRIGGER trg_snapshot_requires_full_session
BEFORE INSERT ON inventory_snapshots
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM inventory_sessions s
        WHERE s.session_id = NEW.session_id
          AND s.scope_type = 'FULL'
          AND s.status = 'APPROVED'
          AND s.freeze_ledger_cutoff = NEW.ledger_cutoff
          AND s.effective_at_us = NEW.effective_at_us
          AND ifnull(s.observed_active_snapshot_id, -1)
              = ifnull(NEW.previous_snapshot_id, -1)
          AND ifnull(s.observed_active_snapshot_id, -1) = ifnull(
              (SELECT active_snapshot_id FROM app_state WHERE singleton_id = 1), -1
          )
          AND s.freeze_ledger_cutoff = (
              SELECT last_ledger_sequence FROM app_state WHERE singleton_id = 1
          )
    ) THEN RAISE(ABORT, 'snapshot requires approved FULL session') END;
END;

CREATE TRIGGER trg_cycle_count_requires_partial_session
BEFORE INSERT ON inventory_cycle_counts
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM inventory_sessions s
        WHERE s.session_id = NEW.session_id
          AND s.scope_type = 'PARTIAL'
          AND s.status = 'APPROVED'
          AND s.observed_active_snapshot_id IS NOT NULL
          AND s.observed_active_snapshot_id = (
              SELECT active_snapshot_id FROM app_state WHERE singleton_id = 1
          )
          AND s.freeze_ledger_cutoff = (
              SELECT last_ledger_sequence FROM app_state WHERE singleton_id = 1
          )
    ) THEN RAISE(ABORT, 'cycle count requires approved PARTIAL session') END;
END;

CREATE TRIGGER trg_snapshot_item_serialized_quantity
BEFORE INSERT ON inventory_snapshot_items
WHEN NEW.equipment_id IS NOT NULL
BEGIN
    SELECT CASE WHEN NEW.quantity_minor <> 1 OR NOT EXISTS (
        SELECT 1 FROM uoms u
        WHERE u.uom_id = NEW.uom_id AND u.dimension = 'COUNT' AND u.scale = 0
    ) THEN RAISE(ABORT, 'serialized snapshot quantity must equal one COUNT unit') END;
END;

CREATE TRIGGER trg_cycle_item_serialized_quantity
BEFORE INSERT ON inventory_cycle_count_items
WHEN NEW.equipment_id IS NOT NULL
BEGIN
    SELECT CASE WHEN NEW.quantity_minor <> 1 OR NOT EXISTS (
        SELECT 1 FROM uoms u
        WHERE u.uom_id = NEW.uom_id AND u.dimension = 'COUNT' AND u.scale = 0
    ) THEN RAISE(ABORT, 'serialized cycle quantity must equal one COUNT unit') END;
END;

CREATE TRIGGER trg_snapshot_item_location_warehouse
BEFORE INSERT ON inventory_snapshot_items
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM warehouse_locations l
        WHERE l.location_id = NEW.location_id
          AND l.warehouse_id = NEW.warehouse_id
    ) THEN RAISE(ABORT, 'snapshot location belongs to another warehouse') END;
END;

CREATE TRIGGER trg_cycle_item_location_warehouse
BEFORE INSERT ON inventory_cycle_count_items
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM warehouse_locations l
        WHERE l.location_id = NEW.location_id
          AND l.warehouse_id = NEW.warehouse_id
    ) THEN RAISE(ABORT, 'cycle-count location belongs to another warehouse') END;
END;

CREATE TRIGGER trg_reconciliation_location_warehouse
BEFORE INSERT ON inventory_reconciliation_items
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM warehouse_locations l
        WHERE l.location_id = NEW.location_id
          AND l.warehouse_id = NEW.warehouse_id
    ) THEN RAISE(ABORT, 'reconciliation location belongs to another warehouse') END;
END;

CREATE TRIGGER trg_snapshot_items_immutable_update
BEFORE UPDATE ON inventory_snapshot_items
BEGIN SELECT RAISE(ABORT, 'approved snapshot items are immutable'); END;

CREATE TRIGGER trg_snapshot_items_immutable_delete
BEFORE DELETE ON inventory_snapshot_items
BEGIN SELECT RAISE(ABORT, 'approved snapshot items are retained'); END;

CREATE TRIGGER trg_snapshot_immutable_fields
BEFORE UPDATE ON inventory_snapshots
WHEN NEW.public_id <> OLD.public_id
  OR NEW.session_id <> OLD.session_id
  OR ifnull(NEW.previous_snapshot_id, -1) <> ifnull(OLD.previous_snapshot_id, -1)
  OR NEW.ledger_cutoff <> OLD.ledger_cutoff
  OR NEW.effective_at_us <> OLD.effective_at_us
  OR NEW.item_count <> OLD.item_count
  OR NEW.totals_json <> OLD.totals_json
  OR NEW.content_checksum <> OLD.content_checksum
  OR NEW.approved_by_user_id <> OLD.approved_by_user_id
  OR NEW.actor_display_name <> OLD.actor_display_name
  OR NEW.approved_at_us <> OLD.approved_at_us
BEGIN SELECT RAISE(ABORT, 'snapshot immutable fields cannot change'); END;

CREATE TRIGGER trg_snapshot_no_delete
BEFORE DELETE ON inventory_snapshots
BEGIN SELECT RAISE(ABORT, 'snapshots are retained'); END;

CREATE TRIGGER trg_snapshot_only_supersede
BEFORE UPDATE ON inventory_snapshots
WHEN NOT (
    OLD.status = 'APPROVED' AND OLD.is_active = 1
    AND NEW.status = 'SUPERSEDED' AND NEW.is_active = 0
    AND NEW.superseded_by_snapshot_id IS NOT NULL
)
BEGIN SELECT RAISE(ABORT, 'snapshot may only transition to SUPERSEDED'); END;

CREATE TRIGGER trg_inventory_session_only_supersede
BEFORE UPDATE OF status ON inventory_sessions
WHEN NOT (OLD.status = 'APPROVED' AND NEW.status = 'SUPERSEDED')
BEGIN SELECT RAISE(ABORT, 'inventory session may only be superseded'); END;

CREATE TRIGGER trg_cycle_count_items_no_update
BEFORE UPDATE ON inventory_cycle_count_items
BEGIN SELECT RAISE(ABORT, 'cycle count items are immutable'); END;

CREATE TRIGGER trg_cycle_count_items_no_delete
BEFORE DELETE ON inventory_cycle_count_items
BEGIN SELECT RAISE(ABORT, 'cycle count items are retained'); END;

CREATE TRIGGER trg_import_commits_immutable_update
BEFORE UPDATE ON import_commits
BEGIN SELECT RAISE(ABORT, 'committed imports are immutable'); END;

CREATE TRIGGER trg_import_commits_immutable_delete
BEFORE DELETE ON import_commits
BEGIN SELECT RAISE(ABORT, 'committed imports are retained'); END;

CREATE TRIGGER trg_import_rows_immutable_update
BEFORE UPDATE ON import_row_links
BEGIN SELECT RAISE(ABORT, 'committed import rows are immutable'); END;

CREATE TRIGGER trg_import_rows_immutable_delete
BEFORE DELETE ON import_row_links
BEGIN SELECT RAISE(ABORT, 'committed import rows are retained'); END;

CREATE TRIGGER trg_import_findings_immutable_update
BEFORE UPDATE ON import_findings
BEGIN SELECT RAISE(ABORT, 'committed findings are immutable'); END;

CREATE TRIGGER trg_import_findings_immutable_delete
BEFORE DELETE ON import_findings
BEGIN SELECT RAISE(ABORT, 'committed findings are retained'); END;

CREATE TRIGGER trg_import_resolutions_immutable_update
BEFORE UPDATE ON import_resolutions
BEGIN SELECT RAISE(ABORT, 'committed resolutions are immutable'); END;

CREATE TRIGGER trg_import_resolutions_immutable_delete
BEFORE DELETE ON import_resolutions
BEGIN SELECT RAISE(ABORT, 'committed resolutions are retained'); END;

CREATE TRIGGER trg_inventory_session_immutable_fields
BEFORE UPDATE ON inventory_sessions
WHEN NEW.public_id <> OLD.public_id
  OR NEW.import_commit_id <> OLD.import_commit_id
  OR NEW.scope_type <> OLD.scope_type
  OR NEW.scope_json <> OLD.scope_json
  OR NEW.source_sha256 <> OLD.source_sha256
  OR NEW.template_version <> OLD.template_version
  OR NEW.parser_version <> OLD.parser_version
  OR NEW.schema_version <> OLD.schema_version
  OR NEW.preview_digest <> OLD.preview_digest
  OR ifnull(NEW.observed_active_snapshot_id, -1)
     <> ifnull(OLD.observed_active_snapshot_id, -1)
  OR NEW.freeze_ledger_cutoff <> OLD.freeze_ledger_cutoff
  OR NEW.freeze_started_at_us <> OLD.freeze_started_at_us
  OR NEW.effective_at_us <> OLD.effective_at_us
  OR NEW.count_started_at_us <> OLD.count_started_at_us
  OR NEW.count_finished_at_us <> OLD.count_finished_at_us
  OR NEW.approved_by_user_id <> OLD.approved_by_user_id
  OR NEW.actor_display_name <> OLD.actor_display_name
  OR NEW.approved_at_us <> OLD.approved_at_us
  OR NEW.approval_idempotency_key <> OLD.approval_idempotency_key
  OR NEW.created_at_us <> OLD.created_at_us
BEGIN SELECT RAISE(ABORT, 'approved inventory session facts are immutable'); END;

CREATE TRIGGER trg_inventory_session_no_delete
BEFORE DELETE ON inventory_sessions
BEGIN SELECT RAISE(ABORT, 'inventory sessions are retained'); END;

CREATE TRIGGER trg_cycle_count_no_update
BEFORE UPDATE ON inventory_cycle_counts
BEGIN SELECT RAISE(ABORT, 'cycle counts are immutable'); END;

CREATE TRIGGER trg_cycle_count_no_delete
BEFORE DELETE ON inventory_cycle_counts
BEGIN SELECT RAISE(ABORT, 'cycle counts are retained'); END;

CREATE TRIGGER trg_reconciliation_no_update
BEFORE UPDATE ON inventory_reconciliation_items
BEGIN SELECT RAISE(ABORT, 'inventory reconciliation is immutable'); END;

CREATE TRIGGER trg_reconciliation_no_delete
BEFORE DELETE ON inventory_reconciliation_items
BEGIN SELECT RAISE(ABORT, 'inventory reconciliation is retained'); END;

COMMIT;
PRAGMA user_version = 5;
