-- APPROVED_FOR_IMPLEMENTATION. Never apply directly to data/warehouse.db.
-- Owner module: legacy history.
PRAGMA foreign_keys = ON;
BEGIN IMMEDIATE;

CREATE TABLE legacy_source_files (
    source_file_id INTEGER PRIMARY KEY,
    public_id TEXT NOT NULL UNIQUE CHECK (length(public_id) BETWEEN 32 AND 40),
    file_name TEXT NOT NULL CHECK (length(file_name) > 0),
    source_object_key TEXT NOT NULL UNIQUE CHECK (
        length(source_object_key) BETWEEN 16 AND 200
        AND source_object_key NOT LIKE '%..%'
        AND source_object_key NOT GLOB '*[^A-Za-z0-9._:-]*'
    ),
    sha256 BLOB NOT NULL UNIQUE CHECK (length(sha256) = 32),
    size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0),
    media_type TEXT NOT NULL,
    workbook_metadata_json TEXT NOT NULL CHECK (json_valid(workbook_metadata_json)),
    imported_at_us INTEGER NOT NULL CHECK (imported_at_us > 0),
    import_batch_key TEXT NOT NULL CHECK (length(import_batch_key) > 0)
) STRICT;

CREATE TABLE legacy_history_events (
    event_id INTEGER PRIMARY KEY,
    public_id TEXT NOT NULL UNIQUE CHECK (length(public_id) BETWEEN 32 AND 40),
    source_file_id INTEGER NOT NULL REFERENCES legacy_source_files(source_file_id),
    source_sheet TEXT NOT NULL CHECK (length(source_sheet) > 0),
    source_row_number INTEGER NOT NULL CHECK (source_row_number > 0),
    source_row_key TEXT NOT NULL CHECK (length(source_row_key) > 0),
    source_row_sha256 BLOB NOT NULL CHECK (length(source_row_sha256) = 32),
    record_status TEXT NOT NULL CHECK (
        record_status IN ('IMPORTED', 'QUARANTINED', 'EXCLUDED')
    ),
    exclusion_reason TEXT,
    event_type TEXT NOT NULL CHECK (event_type IN ('RECEIPT', 'ISSUE', 'UNKNOWN')),
    serial_raw TEXT NOT NULL DEFAULT '',
    serial_key TEXT NOT NULL DEFAULT '',
    inventory_number_raw TEXT NOT NULL DEFAULT '',
    part_number_raw TEXT NOT NULL DEFAULT '',
    vendor_raw TEXT NOT NULL DEFAULT '',
    model_raw TEXT NOT NULL DEFAULT '',
    source_item_name_raw TEXT NOT NULL DEFAULT '',
    performed_by_name_raw TEXT NOT NULL DEFAULT '',
    personnel_code_raw TEXT NOT NULL DEFAULT '',
    performed_by_quality TEXT NOT NULL CHECK (
        performed_by_quality IN ('EXACT', 'MISSING', 'CODE_ONLY', 'CORRUPTED')
    ),
    accepted_by_name_raw TEXT,
    occurred_at_us INTEGER,
    date_raw TEXT NOT NULL DEFAULT '',
    date_quality TEXT NOT NULL CHECK (
        date_quality IN ('EXACT', 'MISSING', 'ESTIMATED', 'CORRUPTED')
    ),
    estimation_basis TEXT,
    comment_raw TEXT NOT NULL DEFAULT '',
    quantity_raw TEXT NOT NULL DEFAULT '',
    location_raw TEXT NOT NULL DEFAULT '',
    raw_payload_json TEXT NOT NULL CHECK (json_valid(raw_payload_json)),
    normalized_payload_json TEXT NOT NULL CHECK (json_valid(normalized_payload_json)),
    imported_at_us INTEGER NOT NULL CHECK (imported_at_us > 0),
    CHECK (
        (record_status = 'EXCLUDED' AND length(trim(exclusion_reason)) > 0)
        OR
        (record_status <> 'EXCLUDED' AND exclusion_reason IS NULL)
    ),
    CHECK (
        (date_quality = 'EXACT' AND occurred_at_us IS NOT NULL
            AND estimation_basis IS NULL)
        OR
        (date_quality = 'ESTIMATED' AND occurred_at_us IS NOT NULL
            AND length(trim(estimation_basis)) > 0)
        OR
        (date_quality IN ('MISSING', 'CORRUPTED')
            AND occurred_at_us IS NULL AND estimation_basis IS NULL)
    ),
    UNIQUE (source_file_id, source_sheet, source_row_number, source_row_key)
) STRICT;

CREATE INDEX ix_legacy_history_serial
ON legacy_history_events(serial_key, occurred_at_us, event_id);

CREATE INDEX ix_legacy_history_source
ON legacy_history_events(source_file_id, source_sheet, source_row_number, event_id);

CREATE INDEX ix_legacy_history_status_quality
ON legacy_history_events(record_status, date_quality, event_id);

CREATE TABLE legacy_history_warnings (
    warning_id INTEGER PRIMARY KEY,
    event_id INTEGER NOT NULL REFERENCES legacy_history_events(event_id),
    severity TEXT NOT NULL CHECK (severity IN ('WARNING', 'CONFLICT')),
    code TEXT NOT NULL CHECK (length(code) > 0),
    message TEXT NOT NULL CHECK (length(message) > 0),
    source_raw TEXT,
    UNIQUE (event_id, severity, code)
) STRICT;

CREATE INDEX ix_legacy_history_warnings_code
ON legacy_history_warnings(code, event_id);

CREATE TABLE legacy_history_equipment_links (
    link_id INTEGER PRIMARY KEY,
    event_id INTEGER NOT NULL REFERENCES legacy_history_events(event_id),
    equipment_id INTEGER NOT NULL REFERENCES equipment(equipment_id),
    confidence TEXT NOT NULL CHECK (confidence IN ('EXACT', 'REVIEWED')),
    reason TEXT NOT NULL CHECK (length(trim(reason)) > 0),
    decided_by_user_id INTEGER NOT NULL REFERENCES users(user_id),
    actor_display_name TEXT NOT NULL CHECK (length(trim(actor_display_name)) > 0),
    decided_at_us INTEGER NOT NULL CHECK (decided_at_us > 0),
    supersedes_link_id INTEGER UNIQUE
        REFERENCES legacy_history_equipment_links(link_id),
    CHECK (supersedes_link_id IS NULL OR supersedes_link_id <> link_id)
) STRICT;

CREATE INDEX ix_legacy_equipment_links_event
ON legacy_history_equipment_links(event_id, decided_at_us, link_id);

CREATE INDEX ix_legacy_equipment_links_equipment
ON legacy_history_equipment_links(equipment_id, event_id, link_id);

CREATE TRIGGER trg_legacy_link_chain
BEFORE INSERT ON legacy_history_equipment_links
BEGIN
    SELECT CASE
      WHEN NEW.supersedes_link_id IS NULL AND EXISTS (
          SELECT 1 FROM legacy_history_equipment_links old
          WHERE old.event_id = NEW.event_id
      ) THEN RAISE(ABORT, 'subsequent legacy link must supersede current link')
      WHEN NEW.supersedes_link_id IS NOT NULL AND NOT EXISTS (
          SELECT 1 FROM legacy_history_equipment_links old
          WHERE old.link_id = NEW.supersedes_link_id
            AND old.event_id = NEW.event_id
            AND NOT EXISTS (
                SELECT 1 FROM legacy_history_equipment_links newer
                WHERE newer.supersedes_link_id = old.link_id
            )
      ) THEN RAISE(ABORT, 'legacy link must extend current chain for same event')
    END;
END;

CREATE TRIGGER trg_legacy_source_files_immutable_update
BEFORE UPDATE ON legacy_source_files
BEGIN SELECT RAISE(ABORT, 'legacy source files are immutable'); END;

CREATE TRIGGER trg_legacy_source_files_immutable_delete
BEFORE DELETE ON legacy_source_files
BEGIN SELECT RAISE(ABORT, 'legacy source files are retained'); END;

CREATE TRIGGER trg_legacy_events_immutable_update
BEFORE UPDATE ON legacy_history_events
BEGIN SELECT RAISE(ABORT, 'legacy history events are immutable'); END;

CREATE TRIGGER trg_legacy_events_immutable_delete
BEFORE DELETE ON legacy_history_events
BEGIN SELECT RAISE(ABORT, 'legacy history events are retained'); END;

CREATE TRIGGER trg_legacy_warnings_immutable_update
BEFORE UPDATE ON legacy_history_warnings
BEGIN SELECT RAISE(ABORT, 'legacy history warnings are immutable'); END;

CREATE TRIGGER trg_legacy_warnings_immutable_delete
BEFORE DELETE ON legacy_history_warnings
BEGIN SELECT RAISE(ABORT, 'legacy history warnings are retained'); END;

CREATE TRIGGER trg_legacy_links_immutable_update
BEFORE UPDATE ON legacy_history_equipment_links
BEGIN SELECT RAISE(ABORT, 'legacy links are additive'); END;

CREATE TRIGGER trg_legacy_links_immutable_delete
BEFORE DELETE ON legacy_history_equipment_links
BEGIN SELECT RAISE(ABORT, 'legacy links are retained'); END;

COMMIT;
PRAGMA user_version = 4;
