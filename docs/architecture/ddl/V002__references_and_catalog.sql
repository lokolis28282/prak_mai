-- APPROVED_FOR_IMPLEMENTATION. Never apply directly to data/warehouse.db.
-- Owner module: references/catalog.
PRAGMA foreign_keys = ON;
BEGIN IMMEDIATE;

CREATE TABLE reference_domains (
    domain_id INTEGER PRIMARY KEY,
    code TEXT NOT NULL UNIQUE CHECK (length(trim(code)) > 0),
    display_name TEXT NOT NULL CHECK (length(trim(display_name)) > 0),
    normalization_policy TEXT NOT NULL,
    scope_policy TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('ACTIVE', 'INACTIVE')),
    created_at_us INTEGER NOT NULL CHECK (created_at_us > 0),
    updated_at_us INTEGER NOT NULL CHECK (updated_at_us >= created_at_us)
) STRICT;

CREATE TABLE reference_values (
    value_id INTEGER PRIMARY KEY,
    public_id TEXT NOT NULL UNIQUE CHECK (length(public_id) BETWEEN 32 AND 40),
    domain_id INTEGER NOT NULL REFERENCES reference_domains(domain_id),
    code TEXT NOT NULL CHECK (length(trim(code)) > 0),
    display_name TEXT NOT NULL CHECK (length(trim(display_name)) > 0),
    normalized_key TEXT NOT NULL CHECK (length(normalized_key) > 0),
    scope_key TEXT NOT NULL DEFAULT 'GLOBAL' CHECK (length(scope_key) > 0),
    scope_value_id INTEGER REFERENCES reference_values(value_id),
    parent_value_id INTEGER REFERENCES reference_values(value_id),
    status TEXT NOT NULL CHECK (
        status IN ('PENDING', 'APPROVED', 'REJECTED', 'INACTIVE', 'MERGED')
    ),
    merged_into_value_id INTEGER REFERENCES reference_values(value_id),
    source_type TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    created_by_user_id INTEGER REFERENCES users(user_id),
    created_at_us INTEGER NOT NULL CHECK (created_at_us > 0),
    updated_at_us INTEGER NOT NULL CHECK (updated_at_us >= created_at_us),
    CHECK (scope_value_id IS NULL OR scope_value_id <> value_id),
    CHECK (parent_value_id IS NULL OR parent_value_id <> value_id),
    CHECK (
        (status = 'MERGED' AND merged_into_value_id IS NOT NULL
            AND merged_into_value_id <> value_id)
        OR
        (status <> 'MERGED' AND merged_into_value_id IS NULL)
    )
) STRICT;

CREATE UNIQUE INDEX ux_reference_values_scope_key
ON reference_values(domain_id, scope_key, normalized_key);

CREATE INDEX ix_reference_values_browse
ON reference_values(domain_id, status, scope_key, normalized_key, value_id);

CREATE INDEX ix_reference_values_parent
ON reference_values(parent_value_id, value_id)
WHERE parent_value_id IS NOT NULL;

CREATE TRIGGER trg_reference_parent_domain_insert
BEFORE INSERT ON reference_values
WHEN NEW.parent_value_id IS NOT NULL
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM reference_values p
        WHERE p.value_id = NEW.parent_value_id
          AND p.domain_id = NEW.domain_id
    ) THEN RAISE(ABORT, 'reference parent belongs to another domain') END;
END;

CREATE TRIGGER trg_reference_parent_domain_update
BEFORE UPDATE OF parent_value_id, domain_id ON reference_values
BEGIN
    SELECT CASE WHEN
        (NEW.parent_value_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM reference_values p
            WHERE p.value_id = NEW.parent_value_id
              AND p.domain_id = NEW.domain_id
        ))
        OR EXISTS (
            SELECT 1 FROM reference_values child
            WHERE child.parent_value_id = OLD.value_id
              AND child.domain_id <> NEW.domain_id
        )
    THEN RAISE(ABORT, 'reference parent belongs to another domain') END;
END;

CREATE TRIGGER trg_reference_parent_acyclic_insert
BEFORE INSERT ON reference_values
WHEN NEW.parent_value_id IS NOT NULL
  AND EXISTS (SELECT 1 FROM reference_values WHERE value_id = NEW.parent_value_id)
BEGIN
    SELECT CASE WHEN EXISTS (
        WITH RECURSIVE ancestors(value_id) AS (
            SELECT NEW.parent_value_id
            UNION
            SELECT p.parent_value_id
            FROM reference_values p
            JOIN ancestors a ON a.value_id = p.value_id
            WHERE p.parent_value_id IS NOT NULL
        )
        SELECT 1
        FROM ancestors
        WHERE value_id = NEW.value_id
           OR NOT EXISTS (
               SELECT 1
               FROM ancestors a
               JOIN reference_values root ON root.value_id = a.value_id
               WHERE root.parent_value_id IS NULL
           )
        LIMIT 1
    ) THEN RAISE(ABORT, 'reference parent hierarchy must be acyclic') END;
END;

CREATE TRIGGER trg_reference_parent_acyclic_update
BEFORE UPDATE OF parent_value_id ON reference_values
WHEN NEW.parent_value_id IS NOT NULL
  AND EXISTS (SELECT 1 FROM reference_values WHERE value_id = NEW.parent_value_id)
BEGIN
    SELECT CASE WHEN EXISTS (
        WITH RECURSIVE ancestors(value_id) AS (
            SELECT NEW.parent_value_id
            UNION
            SELECT p.parent_value_id
            FROM reference_values p
            JOIN ancestors a ON a.value_id = p.value_id
            WHERE p.parent_value_id IS NOT NULL
        )
        SELECT 1
        FROM ancestors
        WHERE value_id = NEW.value_id
           OR NOT EXISTS (
               SELECT 1
               FROM ancestors a
               JOIN reference_values root ON root.value_id = a.value_id
               WHERE root.parent_value_id IS NULL
           )
        LIMIT 1
    ) THEN RAISE(ABORT, 'reference parent hierarchy must be acyclic') END;
END;

CREATE TABLE reference_aliases (
    alias_id INTEGER PRIMARY KEY,
    domain_id INTEGER NOT NULL REFERENCES reference_domains(domain_id),
    source_raw TEXT NOT NULL CHECK (length(source_raw) > 0),
    source_key TEXT NOT NULL CHECK (length(source_key) > 0),
    scope_key TEXT NOT NULL DEFAULT 'GLOBAL' CHECK (length(scope_key) > 0),
    canonical_value_id INTEGER REFERENCES reference_values(value_id),
    status TEXT NOT NULL CHECK (
        status IN ('PENDING', 'APPROVED', 'REJECTED', 'RETIRED')
    ),
    source_file_sha256 BLOB
        CHECK (source_file_sha256 IS NULL OR length(source_file_sha256) = 32),
    source_sheet TEXT,
    first_source_row INTEGER CHECK (first_source_row IS NULL OR first_source_row > 0),
    decision_by_user_id INTEGER REFERENCES users(user_id),
    decision_at_us INTEGER,
    reason TEXT,
    created_at_us INTEGER NOT NULL CHECK (created_at_us > 0),
    CHECK (
        (status = 'APPROVED' AND canonical_value_id IS NOT NULL
            AND decision_by_user_id IS NOT NULL AND decision_at_us IS NOT NULL)
        OR
        status <> 'APPROVED'
    )
) STRICT;

CREATE UNIQUE INDEX ux_reference_aliases_source
ON reference_aliases(domain_id, scope_key, source_key, ifnull(source_file_sha256, X''));

CREATE INDEX ix_reference_aliases_resolve
ON reference_aliases(domain_id, scope_key, source_key, status, alias_id);

CREATE TABLE uoms (
    uom_id INTEGER PRIMARY KEY,
    code TEXT NOT NULL UNIQUE CHECK (length(trim(code)) > 0),
    display_name TEXT NOT NULL CHECK (length(trim(display_name)) > 0),
    dimension TEXT NOT NULL CHECK (dimension IN ('COUNT', 'LENGTH', 'MASS')),
    scale INTEGER NOT NULL CHECK (scale BETWEEN 0 AND 6),
    status TEXT NOT NULL CHECK (status IN ('ACTIVE', 'INACTIVE')),
    created_at_us INTEGER NOT NULL CHECK (created_at_us > 0)
) STRICT;

CREATE TABLE catalog_items (
    catalog_item_id INTEGER PRIMARY KEY,
    public_id TEXT NOT NULL UNIQUE CHECK (length(public_id) BETWEEN 32 AND 40),
    item_kind TEXT NOT NULL CHECK (
        item_kind IN ('SERIALIZED', 'BULK', 'CABLE', 'CONSUMABLE')
    ),
    vendor_value_id INTEGER REFERENCES reference_values(value_id),
    vendor_scope_key TEXT NOT NULL DEFAULT 'UNSCOPED'
        CHECK (length(vendor_scope_key) > 0),
    model_value_id INTEGER REFERENCES reference_values(value_id),
    part_number_raw TEXT NOT NULL DEFAULT '',
    part_number_key TEXT NOT NULL DEFAULT '',
    equipment_type_value_id INTEGER REFERENCES reference_values(value_id),
    component_type_value_id INTEGER REFERENCES reference_values(value_id),
    default_uom_id INTEGER NOT NULL REFERENCES uoms(uom_id),
    display_name TEXT NOT NULL CHECK (length(trim(display_name)) > 0),
    status TEXT NOT NULL CHECK (
        status IN ('PENDING', 'APPROVED', 'INACTIVE', 'MERGED')
    ),
    merged_into_catalog_item_id INTEGER REFERENCES catalog_items(catalog_item_id),
    source_ref TEXT NOT NULL,
    created_at_us INTEGER NOT NULL CHECK (created_at_us > 0),
    updated_at_us INTEGER NOT NULL CHECK (updated_at_us >= created_at_us),
    CHECK (
        (status = 'MERGED' AND merged_into_catalog_item_id IS NOT NULL
            AND merged_into_catalog_item_id <> catalog_item_id)
        OR
        (status <> 'MERGED' AND merged_into_catalog_item_id IS NULL)
    )
) STRICT;

CREATE UNIQUE INDEX ux_catalog_items_vendor_part
ON catalog_items(vendor_scope_key, part_number_key)
WHERE part_number_key <> '' AND status IN ('APPROVED', 'INACTIVE');

CREATE INDEX ix_catalog_items_vendor_part_lookup
ON catalog_items(vendor_scope_key, part_number_key, status, catalog_item_id);

CREATE INDEX ix_catalog_items_browse
ON catalog_items(status, item_kind, vendor_scope_key, display_name, catalog_item_id);

CREATE TABLE warehouses (
    warehouse_id INTEGER PRIMARY KEY,
    public_id TEXT NOT NULL UNIQUE CHECK (length(public_id) BETWEEN 32 AND 40),
    code TEXT NOT NULL UNIQUE CHECK (length(trim(code)) > 0),
    display_name TEXT NOT NULL CHECK (length(trim(display_name)) > 0),
    status TEXT NOT NULL CHECK (status IN ('ACTIVE', 'INACTIVE')),
    created_at_us INTEGER NOT NULL CHECK (created_at_us > 0),
    updated_at_us INTEGER NOT NULL CHECK (updated_at_us >= created_at_us)
) STRICT;

CREATE TABLE warehouse_locations (
    location_id INTEGER PRIMARY KEY,
    public_id TEXT NOT NULL UNIQUE CHECK (length(public_id) BETWEEN 32 AND 40),
    warehouse_id INTEGER NOT NULL REFERENCES warehouses(warehouse_id),
    code TEXT NOT NULL CHECK (length(trim(code)) > 0),
    display_name TEXT NOT NULL CHECK (length(trim(display_name)) > 0),
    parent_location_id INTEGER REFERENCES warehouse_locations(location_id),
    location_kind TEXT NOT NULL CHECK (
        location_kind IN ('ZONE', 'AISLE', 'RACK', 'SHELF', 'BIN', 'VIRTUAL')
    ),
    status TEXT NOT NULL CHECK (status IN ('ACTIVE', 'INACTIVE')),
    created_at_us INTEGER NOT NULL CHECK (created_at_us > 0),
    updated_at_us INTEGER NOT NULL CHECK (updated_at_us >= created_at_us),
    CHECK (parent_location_id IS NULL OR parent_location_id <> location_id)
) STRICT;

CREATE UNIQUE INDEX ux_locations_warehouse_code
ON warehouse_locations(warehouse_id, code);

CREATE INDEX ix_locations_parent
ON warehouse_locations(warehouse_id, parent_location_id, location_id);

CREATE INDEX ix_locations_browse
ON warehouse_locations(warehouse_id, status, location_kind, code, location_id);

CREATE TRIGGER trg_location_parent_same_warehouse_insert
BEFORE INSERT ON warehouse_locations
WHEN NEW.parent_location_id IS NOT NULL
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM warehouse_locations p
        WHERE p.location_id = NEW.parent_location_id
          AND p.warehouse_id = NEW.warehouse_id
    ) THEN RAISE(ABORT, 'location parent belongs to another warehouse') END;
END;

CREATE TRIGGER trg_location_parent_same_warehouse_update
BEFORE UPDATE OF parent_location_id, warehouse_id ON warehouse_locations
BEGIN
    SELECT CASE WHEN
        (NEW.parent_location_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM warehouse_locations p
            WHERE p.location_id = NEW.parent_location_id
              AND p.warehouse_id = NEW.warehouse_id
        ))
        OR EXISTS (
            SELECT 1 FROM warehouse_locations child
            WHERE child.parent_location_id = OLD.location_id
              AND child.warehouse_id <> NEW.warehouse_id
        )
    THEN RAISE(ABORT, 'location parent belongs to another warehouse') END;
END;

CREATE TRIGGER trg_location_parent_acyclic_insert
BEFORE INSERT ON warehouse_locations
WHEN NEW.parent_location_id IS NOT NULL
  AND EXISTS (
      SELECT 1 FROM warehouse_locations WHERE location_id = NEW.parent_location_id
  )
BEGIN
    SELECT CASE WHEN EXISTS (
        WITH RECURSIVE ancestors(location_id) AS (
            SELECT NEW.parent_location_id
            UNION
            SELECT p.parent_location_id
            FROM warehouse_locations p
            JOIN ancestors a ON a.location_id = p.location_id
            WHERE p.parent_location_id IS NOT NULL
        )
        SELECT 1
        FROM ancestors
        WHERE location_id = NEW.location_id
           OR NOT EXISTS (
               SELECT 1
               FROM ancestors a
               JOIN warehouse_locations root ON root.location_id = a.location_id
               WHERE root.parent_location_id IS NULL
           )
        LIMIT 1
    ) THEN RAISE(ABORT, 'location parent hierarchy must be acyclic') END;
END;

CREATE TRIGGER trg_location_parent_acyclic_update
BEFORE UPDATE OF parent_location_id ON warehouse_locations
WHEN NEW.parent_location_id IS NOT NULL
  AND EXISTS (
      SELECT 1 FROM warehouse_locations WHERE location_id = NEW.parent_location_id
  )
BEGIN
    SELECT CASE WHEN EXISTS (
        WITH RECURSIVE ancestors(location_id) AS (
            SELECT NEW.parent_location_id
            UNION
            SELECT p.parent_location_id
            FROM warehouse_locations p
            JOIN ancestors a ON a.location_id = p.location_id
            WHERE p.parent_location_id IS NOT NULL
        )
        SELECT 1
        FROM ancestors
        WHERE location_id = NEW.location_id
           OR NOT EXISTS (
               SELECT 1
               FROM ancestors a
               JOIN warehouse_locations root ON root.location_id = a.location_id
               WHERE root.parent_location_id IS NULL
           )
        LIMIT 1
    ) THEN RAISE(ABORT, 'location parent hierarchy must be acyclic') END;
END;

COMMIT;
PRAGMA user_version = 2;
