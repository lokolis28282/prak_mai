-- APPROVED_FOR_IMPLEMENTATION. Never apply directly to data/warehouse.db.
-- Owner module: balance.
PRAGMA foreign_keys = ON;
BEGIN IMMEDIATE;

CREATE TABLE balance_projection_versions (
    projection_version_id INTEGER PRIMARY KEY,
    public_id TEXT NOT NULL UNIQUE CHECK (length(public_id) BETWEEN 32 AND 40),
    snapshot_id INTEGER NOT NULL REFERENCES inventory_snapshots(snapshot_id),
    build_status TEXT NOT NULL CHECK (
        build_status IN ('BUILDING', 'READY', 'ACTIVE', 'FAILED', 'RETIRED')
    ),
    built_through_sequence INTEGER NOT NULL CHECK (built_through_sequence >= 0),
    row_count INTEGER NOT NULL DEFAULT 0 CHECK (row_count >= 0),
    total_checksum BLOB CHECK (total_checksum IS NULL OR length(total_checksum) = 32),
    created_at_us INTEGER NOT NULL CHECK (created_at_us > 0),
    ready_at_us INTEGER,
    activated_at_us INTEGER,
    failure_code TEXT,
    CHECK (
        (build_status = 'BUILDING' AND ready_at_us IS NULL
            AND activated_at_us IS NULL AND failure_code IS NULL)
        OR
        (build_status = 'READY' AND ready_at_us IS NOT NULL
            AND activated_at_us IS NULL AND failure_code IS NULL)
        OR
        (build_status = 'ACTIVE' AND ready_at_us IS NOT NULL
            AND activated_at_us IS NOT NULL AND failure_code IS NULL)
        OR
        (build_status = 'FAILED' AND failure_code IS NOT NULL)
        OR
        build_status = 'RETIRED'
    )
) STRICT;

CREATE UNIQUE INDEX ux_projection_active
ON balance_projection_versions(build_status)
WHERE build_status = 'ACTIVE';

CREATE INDEX ix_projection_snapshot_status
ON balance_projection_versions(snapshot_id, build_status, projection_version_id);

CREATE TABLE balance_projection_rows (
    projection_row_id INTEGER PRIMARY KEY,
    projection_version_id INTEGER NOT NULL
        REFERENCES balance_projection_versions(projection_version_id),
    equipment_id INTEGER REFERENCES equipment(equipment_id),
    catalog_item_id INTEGER REFERENCES catalog_items(catalog_item_id),
    warehouse_id INTEGER NOT NULL REFERENCES warehouses(warehouse_id),
    location_id INTEGER NOT NULL REFERENCES warehouse_locations(location_id),
    condition_value_id INTEGER NOT NULL REFERENCES reference_values(value_id),
    lot_key TEXT NOT NULL DEFAULT '',
    uom_id INTEGER NOT NULL REFERENCES uoms(uom_id),
    quantity_minor INTEGER NOT NULL CHECK (quantity_minor > 0),
    last_applied_sequence INTEGER NOT NULL CHECK (last_applied_sequence >= 0),
    row_checksum BLOB NOT NULL CHECK (length(row_checksum) = 32),
    CHECK ((equipment_id IS NOT NULL) <> (catalog_item_id IS NOT NULL))
) STRICT;

CREATE UNIQUE INDEX ux_projection_equipment_key
ON balance_projection_rows(
    projection_version_id, equipment_id, warehouse_id, location_id,
    condition_value_id, lot_key, uom_id
)
WHERE equipment_id IS NOT NULL;

CREATE UNIQUE INDEX ux_projection_bulk_key
ON balance_projection_rows(
    projection_version_id, catalog_item_id, warehouse_id, location_id,
    condition_value_id, lot_key, uom_id
)
WHERE catalog_item_id IS NOT NULL;

CREATE INDEX ix_projection_balance_page
ON balance_projection_rows(
    projection_version_id, warehouse_id, location_id,
    condition_value_id, projection_row_id
);

CREATE INDEX ix_projection_equipment
ON balance_projection_rows(projection_version_id, equipment_id, projection_row_id)
WHERE equipment_id IS NOT NULL;

CREATE INDEX ix_projection_catalog_location
ON balance_projection_rows(
    projection_version_id, catalog_item_id, warehouse_id, location_id,
    projection_row_id
)
WHERE catalog_item_id IS NOT NULL;

INSERT INTO app_state (
    singleton_id, balance_state, last_ledger_sequence, state_version, updated_at_us
) VALUES (1, 'NOT_INITIALIZED', 0, 1, 1);

CREATE VIEW v_balance_truth_deltas AS
SELECT
    s.snapshot_id,
    s.ledger_cutoff,
    i.equipment_id,
    i.catalog_item_id,
    i.warehouse_id,
    i.location_id,
    i.condition_value_id,
    i.lot_key,
    i.uom_id,
    i.quantity_minor AS delta_minor,
    s.ledger_cutoff AS source_sequence
FROM app_state a
JOIN inventory_snapshots s ON s.snapshot_id = a.active_snapshot_id
JOIN inventory_snapshot_items i ON i.snapshot_id = s.snapshot_id
WHERE a.singleton_id = 1
UNION ALL
SELECT
    s.snapshot_id,
    s.ledger_cutoff,
    l.equipment_id,
    l.catalog_item_id,
    l.to_warehouse_id,
    l.to_location_id,
    l.to_condition_value_id,
    l.lot_key,
    l.uom_id,
    l.quantity_minor,
    t.ledger_sequence
FROM app_state a
JOIN inventory_snapshots s ON s.snapshot_id = a.active_snapshot_id
JOIN warehouse_transactions t
  ON t.active_snapshot_id = s.snapshot_id
 AND t.ledger_sequence > s.ledger_cutoff
JOIN warehouse_transaction_lines l ON l.ledger_sequence = t.ledger_sequence
WHERE a.singleton_id = 1 AND l.to_location_id IS NOT NULL
UNION ALL
SELECT
    s.snapshot_id,
    s.ledger_cutoff,
    l.equipment_id,
    l.catalog_item_id,
    l.from_warehouse_id,
    l.from_location_id,
    l.from_condition_value_id,
    l.lot_key,
    l.uom_id,
    -l.quantity_minor,
    t.ledger_sequence
FROM app_state a
JOIN inventory_snapshots s ON s.snapshot_id = a.active_snapshot_id
JOIN warehouse_transactions t
  ON t.active_snapshot_id = s.snapshot_id
 AND t.ledger_sequence > s.ledger_cutoff
JOIN warehouse_transaction_lines l ON l.ledger_sequence = t.ledger_sequence
WHERE a.singleton_id = 1 AND l.from_location_id IS NOT NULL;

CREATE VIEW v_balance_truth AS
SELECT
    snapshot_id,
    equipment_id,
    catalog_item_id,
    warehouse_id,
    location_id,
    condition_value_id,
    lot_key,
    uom_id,
    sum(delta_minor) AS quantity_minor,
    max(source_sequence) AS last_applied_sequence
FROM v_balance_truth_deltas
GROUP BY snapshot_id, equipment_id, catalog_item_id, warehouse_id, location_id,
         condition_value_id, lot_key, uom_id
HAVING sum(delta_minor) <> 0;

CREATE VIEW v_active_balance AS
SELECT r.*
FROM app_state a
JOIN balance_projection_rows r
  ON r.projection_version_id = a.active_projection_version_id
WHERE a.singleton_id = 1;

CREATE TRIGGER trg_projection_row_serialized_quantity
BEFORE INSERT ON balance_projection_rows
WHEN NEW.equipment_id IS NOT NULL
BEGIN
    SELECT CASE WHEN NEW.quantity_minor <> 1 OR NOT EXISTS (
        SELECT 1 FROM uoms u
        WHERE u.uom_id = NEW.uom_id AND u.dimension = 'COUNT' AND u.scale = 0
    ) THEN RAISE(ABORT, 'serialized projection quantity must equal one COUNT unit') END;
END;

CREATE TRIGGER trg_projection_location_warehouse
BEFORE INSERT ON balance_projection_rows
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM warehouse_locations l
        WHERE l.location_id = NEW.location_id
          AND l.warehouse_id = NEW.warehouse_id
    ) THEN RAISE(ABORT, 'projection location belongs to another warehouse') END;
END;

COMMIT;
PRAGMA user_version = 7;
