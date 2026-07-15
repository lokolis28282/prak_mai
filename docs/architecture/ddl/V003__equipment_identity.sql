-- APPROVED_FOR_IMPLEMENTATION. Never apply directly to data/warehouse.db.
-- Owner module: equipment.
PRAGMA foreign_keys = ON;
BEGIN IMMEDIATE;

CREATE TABLE equipment (
    equipment_id INTEGER PRIMARY KEY,
    public_id TEXT NOT NULL UNIQUE CHECK (length(public_id) BETWEEN 32 AND 40),
    catalog_item_id INTEGER NOT NULL REFERENCES catalog_items(catalog_item_id),
    lifecycle_status TEXT NOT NULL CHECK (
        lifecycle_status IN ('ACTIVE', 'QUARANTINED', 'RETIRED', 'MERGED')
    ),
    identity_status TEXT NOT NULL CHECK (
        identity_status IN ('VERIFIED', 'MISSING_SERIAL', 'CONFLICT', 'UNVERIFIED')
    ),
    merged_into_equipment_id INTEGER REFERENCES equipment(equipment_id),
    created_at_us INTEGER NOT NULL CHECK (created_at_us > 0),
    updated_at_us INTEGER NOT NULL CHECK (updated_at_us >= created_at_us),
    CHECK (
        (lifecycle_status = 'MERGED' AND merged_into_equipment_id IS NOT NULL
            AND merged_into_equipment_id <> equipment_id)
        OR
        (lifecycle_status <> 'MERGED' AND merged_into_equipment_id IS NULL)
    )
) STRICT;

CREATE INDEX ix_equipment_catalog_page
ON equipment(catalog_item_id, lifecycle_status, equipment_id);

CREATE INDEX ix_equipment_lifecycle_page
ON equipment(lifecycle_status, equipment_id);

CREATE TRIGGER trg_equipment_requires_serialized_catalog
BEFORE INSERT ON equipment
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM catalog_items c
        WHERE c.catalog_item_id = NEW.catalog_item_id
          AND c.item_kind = 'SERIALIZED'
    ) THEN RAISE(ABORT, 'equipment requires SERIALIZED catalog item') END;
END;

CREATE TABLE equipment_identities (
    identity_id INTEGER PRIMARY KEY,
    equipment_id INTEGER NOT NULL REFERENCES equipment(equipment_id),
    kind TEXT NOT NULL CHECK (
        kind IN ('SERIAL_NUMBER', 'INVENTORY_NUMBER')
    ),
    raw_value TEXT NOT NULL CHECK (length(raw_value) > 0),
    normalized_key TEXT NOT NULL CHECK (length(normalized_key) > 0),
    scope_key TEXT NOT NULL CHECK (length(scope_key) > 0),
    status TEXT NOT NULL CHECK (
        status IN ('ACTIVE', 'RETIRED', 'CONFLICT', 'UNVERIFIED')
    ),
    valid_from_us INTEGER NOT NULL CHECK (valid_from_us > 0),
    valid_to_us INTEGER CHECK (valid_to_us IS NULL OR valid_to_us >= valid_from_us),
    source_type TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    changed_by_user_id INTEGER REFERENCES users(user_id),
    reason TEXT NOT NULL,
    supersedes_identity_id INTEGER UNIQUE
        REFERENCES equipment_identities(identity_id),
    CHECK (
        (kind = 'INVENTORY_NUMBER' AND scope_key = 'GLOBAL')
        OR
        (kind = 'SERIAL_NUMBER'
            AND (scope_key = 'UNSCOPED' OR scope_key GLOB 'VENDOR:[0-9]*'))
    ),
    CHECK (
        (status = 'ACTIVE' AND valid_to_us IS NULL)
        OR status <> 'ACTIVE'
    )
) STRICT;

CREATE UNIQUE INDEX ux_equipment_serial_active
ON equipment_identities(scope_key, normalized_key)
WHERE kind = 'SERIAL_NUMBER' AND status = 'ACTIVE';

CREATE UNIQUE INDEX ux_equipment_inventory_active
ON equipment_identities(normalized_key)
WHERE kind = 'INVENTORY_NUMBER' AND status = 'ACTIVE';

CREATE INDEX ix_equipment_identity_exact
ON equipment_identities(kind, normalized_key, status, scope_key, equipment_id);

CREATE INDEX ix_equipment_identity_equipment
ON equipment_identities(equipment_id, status, kind, identity_id);

CREATE TABLE equipment_identity_aliases (
    identity_alias_id INTEGER PRIMARY KEY,
    identity_id INTEGER NOT NULL REFERENCES equipment_identities(identity_id),
    alias_raw TEXT NOT NULL CHECK (length(alias_raw) > 0),
    alias_key TEXT NOT NULL CHECK (length(alias_key) > 0),
    scope_key TEXT NOT NULL CHECK (length(scope_key) > 0),
    status TEXT NOT NULL CHECK (status IN ('ACTIVE', 'RETIRED')),
    source_type TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    created_at_us INTEGER NOT NULL CHECK (created_at_us > 0),
    retired_at_us INTEGER CHECK (retired_at_us IS NULL OR retired_at_us >= created_at_us),
    CHECK (
        (status = 'ACTIVE' AND retired_at_us IS NULL)
        OR (status = 'RETIRED' AND retired_at_us IS NOT NULL)
    )
) STRICT;

CREATE UNIQUE INDEX ux_equipment_identity_alias_active
ON equipment_identity_aliases(scope_key, alias_key)
WHERE status = 'ACTIVE';

CREATE INDEX ix_equipment_identity_alias_lookup
ON equipment_identity_aliases(alias_key, status, scope_key, identity_id);

CREATE TABLE equipment_merges (
    merge_id INTEGER PRIMARY KEY,
    source_equipment_id INTEGER NOT NULL UNIQUE REFERENCES equipment(equipment_id),
    survivor_equipment_id INTEGER NOT NULL REFERENCES equipment(equipment_id),
    effective_at_us INTEGER NOT NULL CHECK (effective_at_us > 0),
    actor_user_id INTEGER NOT NULL REFERENCES users(user_id),
    actor_display_name TEXT NOT NULL CHECK (length(trim(actor_display_name)) > 0),
    reason TEXT NOT NULL CHECK (length(trim(reason)) > 0),
    out_adjustment_sequence INTEGER
        REFERENCES warehouse_transactions(ledger_sequence),
    in_adjustment_sequence INTEGER
        REFERENCES warehouse_transactions(ledger_sequence),
    correlation_id TEXT NOT NULL UNIQUE,
    CHECK (source_equipment_id <> survivor_equipment_id),
    CHECK (
        (out_adjustment_sequence IS NULL AND in_adjustment_sequence IS NULL)
        OR
        (out_adjustment_sequence IS NOT NULL AND in_adjustment_sequence IS NOT NULL)
    )
) STRICT;

CREATE TRIGGER trg_equipment_identity_immutable_fields
BEFORE UPDATE OF equipment_id, kind, raw_value, normalized_key, scope_key,
    valid_from_us, source_type, source_ref, changed_by_user_id, reason,
    supersedes_identity_id
ON equipment_identities
BEGIN
    SELECT RAISE(ABORT, 'equipment identity immutable fields cannot change');
END;

CREATE TRIGGER trg_equipment_identity_no_delete
BEFORE DELETE ON equipment_identities
BEGIN
    SELECT RAISE(ABORT, 'equipment identities are retained');
END;

CREATE TRIGGER trg_equipment_identity_status_transition
BEFORE UPDATE OF status, valid_to_us ON equipment_identities
WHEN NOT (
    OLD.status = 'ACTIVE' AND NEW.status = 'RETIRED'
    AND OLD.valid_to_us IS NULL AND NEW.valid_to_us IS NOT NULL
)
BEGIN
    SELECT RAISE(ABORT, 'identity correction creates a new row; active may only retire');
END;

CREATE TRIGGER trg_equipment_alias_immutable_fields
BEFORE UPDATE OF identity_id, alias_raw, alias_key, scope_key,
    source_type, source_ref, created_at_us
ON equipment_identity_aliases
BEGIN SELECT RAISE(ABORT, 'identity alias facts are immutable'); END;

CREATE TRIGGER trg_equipment_alias_only_retire
BEFORE UPDATE OF status, retired_at_us ON equipment_identity_aliases
WHEN NOT (
    OLD.status = 'ACTIVE' AND NEW.status = 'RETIRED'
    AND OLD.retired_at_us IS NULL AND NEW.retired_at_us IS NOT NULL
)
BEGIN SELECT RAISE(ABORT, 'identity alias may only retire'); END;

CREATE TRIGGER trg_equipment_alias_no_delete
BEFORE DELETE ON equipment_identity_aliases
BEGIN SELECT RAISE(ABORT, 'identity aliases are retained'); END;

CREATE TRIGGER trg_equipment_merges_no_update
BEFORE UPDATE ON equipment_merges
BEGIN SELECT RAISE(ABORT, 'equipment merge records are immutable'); END;

CREATE TRIGGER trg_equipment_merges_no_delete
BEFORE DELETE ON equipment_merges
BEGIN SELECT RAISE(ABORT, 'equipment merge records are retained'); END;

COMMIT;
PRAGMA user_version = 3;
