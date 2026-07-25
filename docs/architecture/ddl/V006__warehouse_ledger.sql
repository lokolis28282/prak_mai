-- APPROVED_FOR_IMPLEMENTATION. Never apply directly to data/warehouse.db.
-- Owner module: warehouse ledger.
PRAGMA foreign_keys = ON;
BEGIN IMMEDIATE;

CREATE TABLE warehouse_transactions (
    ledger_sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    public_id TEXT NOT NULL UNIQUE CHECK (length(public_id) BETWEEN 32 AND 40),
    kind TEXT NOT NULL CHECK (
        kind IN ('RECEIPT', 'ISSUE', 'TRANSFER', 'ADJUSTMENT_IN',
                 'ADJUSTMENT_OUT', 'REVERSAL')
    ),
    posting_status TEXT NOT NULL CHECK (posting_status = 'POSTED'),
    active_snapshot_id INTEGER NOT NULL REFERENCES inventory_snapshots(snapshot_id),
    occurred_at_us INTEGER NOT NULL CHECK (occurred_at_us > 0),
    posted_at_us INTEGER NOT NULL CHECK (posted_at_us > 0),
    actor_user_id INTEGER NOT NULL REFERENCES users(user_id),
    actor_display_name TEXT NOT NULL CHECK (length(trim(actor_display_name)) > 0),
    actor_role_code TEXT NOT NULL CHECK (
        actor_role_code IN ('operator', 'admin', 'auditor')
    ),
    permission_code TEXT NOT NULL CHECK (length(permission_code) > 0),
    comment TEXT NOT NULL DEFAULT '',
    reason_code TEXT,
    source_document_ref TEXT,
    reverses_ledger_sequence INTEGER UNIQUE
        REFERENCES warehouse_transactions(ledger_sequence),
    idempotency_scope TEXT NOT NULL CHECK (length(idempotency_scope) > 0),
    idempotency_key TEXT NOT NULL CHECK (length(idempotency_key) BETWEEN 16 AND 128),
    request_checksum BLOB NOT NULL CHECK (length(request_checksum) = 32),
    correlation_id TEXT NOT NULL UNIQUE,
    CHECK (
        (kind = 'REVERSAL' AND reverses_ledger_sequence IS NOT NULL)
        OR
        (kind <> 'REVERSAL' AND reverses_ledger_sequence IS NULL)
    ),
    CHECK (reverses_ledger_sequence IS NULL OR reverses_ledger_sequence <> ledger_sequence),
    UNIQUE (idempotency_scope, idempotency_key)
) STRICT;

CREATE INDEX ix_ledger_transactions_page
ON warehouse_transactions(posted_at_us, ledger_sequence);

CREATE INDEX ix_ledger_transactions_kind_page
ON warehouse_transactions(kind, posted_at_us, ledger_sequence);

CREATE INDEX ix_ledger_transactions_snapshot_sequence
ON warehouse_transactions(active_snapshot_id, ledger_sequence);

CREATE TABLE warehouse_transaction_lines (
    line_id INTEGER PRIMARY KEY,
    ledger_sequence INTEGER NOT NULL
        REFERENCES warehouse_transactions(ledger_sequence),
    line_no INTEGER NOT NULL CHECK (line_no > 0),
    equipment_id INTEGER REFERENCES equipment(equipment_id),
    catalog_item_id INTEGER REFERENCES catalog_items(catalog_item_id),
    lot_key TEXT NOT NULL DEFAULT '',
    uom_id INTEGER NOT NULL REFERENCES uoms(uom_id),
    quantity_minor INTEGER NOT NULL CHECK (quantity_minor > 0),
    from_warehouse_id INTEGER REFERENCES warehouses(warehouse_id),
    from_location_id INTEGER REFERENCES warehouse_locations(location_id),
    from_condition_value_id INTEGER REFERENCES reference_values(value_id),
    to_warehouse_id INTEGER REFERENCES warehouses(warehouse_id),
    to_location_id INTEGER REFERENCES warehouse_locations(location_id),
    to_condition_value_id INTEGER REFERENCES reference_values(value_id),
    line_comment TEXT NOT NULL DEFAULT '',
    line_checksum BLOB NOT NULL CHECK (length(line_checksum) = 32),
    CHECK ((equipment_id IS NOT NULL) <> (catalog_item_id IS NOT NULL)),
    UNIQUE (ledger_sequence, line_no),
    CHECK (
        (from_warehouse_id IS NULL AND from_location_id IS NULL
            AND from_condition_value_id IS NULL)
        OR
        (from_warehouse_id IS NOT NULL AND from_location_id IS NOT NULL
            AND from_condition_value_id IS NOT NULL)
    ),
    CHECK (
        (to_warehouse_id IS NULL AND to_location_id IS NULL
            AND to_condition_value_id IS NULL)
        OR
        (to_warehouse_id IS NOT NULL AND to_location_id IS NOT NULL
            AND to_condition_value_id IS NOT NULL)
    ),
    CHECK (from_location_id IS NOT NULL OR to_location_id IS NOT NULL)
) STRICT;

CREATE INDEX ix_ledger_lines_equipment
ON warehouse_transaction_lines(equipment_id, ledger_sequence, line_id)
WHERE equipment_id IS NOT NULL;

CREATE INDEX ix_ledger_lines_catalog
ON warehouse_transaction_lines(catalog_item_id, ledger_sequence, line_id)
WHERE catalog_item_id IS NOT NULL;

CREATE INDEX ix_ledger_lines_from_location
ON warehouse_transaction_lines(from_location_id, ledger_sequence, line_id)
WHERE from_location_id IS NOT NULL;

CREATE INDEX ix_ledger_lines_to_location
ON warehouse_transaction_lines(to_location_id, ledger_sequence, line_id)
WHERE to_location_id IS NOT NULL;

CREATE TABLE warehouse_late_operation_evidence (
    late_evidence_id INTEGER PRIMARY KEY,
    public_id TEXT NOT NULL UNIQUE CHECK (length(public_id) BETWEEN 32 AND 40),
    operation_kind TEXT NOT NULL CHECK (
        operation_kind IN ('RECEIPT', 'ISSUE', 'TRANSFER', 'UNKNOWN')
    ),
    occurred_at_us INTEGER NOT NULL CHECK (occurred_at_us > 0),
    discovered_at_us INTEGER NOT NULL CHECK (discovered_at_us >= occurred_at_us),
    cutoff_snapshot_id INTEGER NOT NULL REFERENCES inventory_snapshots(snapshot_id),
    source_document_ref TEXT NOT NULL CHECK (length(source_document_ref) > 0),
    raw_payload_json TEXT NOT NULL CHECK (json_valid(raw_payload_json)),
    resolution TEXT NOT NULL CHECK (
        resolution IN ('NO_BALANCE_EFFECT', 'ADJUSTMENT_POSTED')
    ),
    adjustment_ledger_sequence INTEGER
        REFERENCES warehouse_transactions(ledger_sequence),
    actor_user_id INTEGER NOT NULL REFERENCES users(user_id),
    actor_display_name TEXT NOT NULL CHECK (length(trim(actor_display_name)) > 0),
    reason TEXT NOT NULL CHECK (length(trim(reason)) > 0),
    correlation_id TEXT NOT NULL UNIQUE,
    CHECK (
        (resolution = 'NO_BALANCE_EFFECT' AND adjustment_ledger_sequence IS NULL)
        OR
        (resolution = 'ADJUSTMENT_POSTED' AND adjustment_ledger_sequence IS NOT NULL)
    )
) STRICT;

CREATE INDEX ix_late_operation_snapshot
ON warehouse_late_operation_evidence(cutoff_snapshot_id, discovered_at_us, late_evidence_id);

CREATE TRIGGER trg_ledger_requires_active_baseline
BEFORE INSERT ON warehouse_transactions
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM app_state a
        JOIN inventory_snapshots s ON s.snapshot_id = a.active_snapshot_id
        WHERE a.singleton_id = 1
          AND a.balance_state = 'ACTIVE'
          AND s.is_active = 1
          AND s.status = 'APPROVED'
          AND s.snapshot_id = NEW.active_snapshot_id
    ) THEN RAISE(ABORT, 'warehouse posting requires active baseline') END;
END;

CREATE TRIGGER trg_reversal_header_target
BEFORE INSERT ON warehouse_transactions
WHEN NEW.kind = 'REVERSAL'
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM warehouse_transactions original
        WHERE original.ledger_sequence = NEW.reverses_ledger_sequence
          AND original.kind <> 'REVERSAL'
          AND original.active_snapshot_id = NEW.active_snapshot_id
    ) THEN RAISE(ABORT, 'reversal must target non-reversal in active baseline') END;
END;

CREATE TRIGGER trg_ledger_line_kind_semantics
BEFORE INSERT ON warehouse_transaction_lines
BEGIN
    SELECT CASE
      WHEN (SELECT kind FROM warehouse_transactions
            WHERE ledger_sequence = NEW.ledger_sequence)
           IN ('RECEIPT', 'ADJUSTMENT_IN')
       AND NOT (NEW.from_location_id IS NULL AND NEW.to_location_id IS NOT NULL)
        THEN RAISE(ABORT, 'inbound line location semantics invalid')
      WHEN (SELECT kind FROM warehouse_transactions
            WHERE ledger_sequence = NEW.ledger_sequence)
           IN ('ISSUE', 'ADJUSTMENT_OUT')
       AND NOT (NEW.from_location_id IS NOT NULL AND NEW.to_location_id IS NULL)
        THEN RAISE(ABORT, 'outbound line location semantics invalid')
      WHEN (SELECT kind FROM warehouse_transactions
            WHERE ledger_sequence = NEW.ledger_sequence) = 'TRANSFER'
       AND NOT (NEW.from_location_id IS NOT NULL
                AND NEW.to_location_id IS NOT NULL
                AND NEW.from_location_id <> NEW.to_location_id)
        THEN RAISE(ABORT, 'transfer line location semantics invalid')
    END;
END;

CREATE TRIGGER trg_ledger_line_location_warehouse
BEFORE INSERT ON warehouse_transaction_lines
BEGIN
    SELECT CASE
      WHEN NEW.from_location_id IS NOT NULL AND NOT EXISTS (
          SELECT 1 FROM warehouse_locations l
          WHERE l.location_id = NEW.from_location_id
            AND l.warehouse_id = NEW.from_warehouse_id
      ) THEN RAISE(ABORT, 'ledger from-location belongs to another warehouse')
      WHEN NEW.to_location_id IS NOT NULL AND NOT EXISTS (
          SELECT 1 FROM warehouse_locations l
          WHERE l.location_id = NEW.to_location_id
            AND l.warehouse_id = NEW.to_warehouse_id
      ) THEN RAISE(ABORT, 'ledger to-location belongs to another warehouse')
    END;
END;

CREATE TRIGGER trg_ledger_line_serialized_quantity
BEFORE INSERT ON warehouse_transaction_lines
WHEN NEW.equipment_id IS NOT NULL
BEGIN
    SELECT CASE WHEN NEW.quantity_minor <> 1 OR NOT EXISTS (
        SELECT 1 FROM uoms u
        WHERE u.uom_id = NEW.uom_id AND u.dimension = 'COUNT' AND u.scale = 0
    ) THEN RAISE(ABORT, 'serialized ledger quantity must equal one COUNT unit') END;
END;

CREATE TRIGGER trg_reversal_line_exact_inverse
BEFORE INSERT ON warehouse_transaction_lines
WHEN (SELECT kind FROM warehouse_transactions
      WHERE ledger_sequence = NEW.ledger_sequence) = 'REVERSAL'
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1
        FROM warehouse_transactions reversal
        JOIN warehouse_transaction_lines original
          ON original.ledger_sequence = reversal.reverses_ledger_sequence
         AND original.line_no = NEW.line_no
        WHERE reversal.ledger_sequence = NEW.ledger_sequence
          AND ifnull(original.equipment_id, -1) = ifnull(NEW.equipment_id, -1)
          AND ifnull(original.catalog_item_id, -1) = ifnull(NEW.catalog_item_id, -1)
          AND original.lot_key = NEW.lot_key
          AND original.uom_id = NEW.uom_id
          AND original.quantity_minor = NEW.quantity_minor
          AND ifnull(original.from_warehouse_id, -1) = ifnull(NEW.to_warehouse_id, -1)
          AND ifnull(original.from_location_id, -1) = ifnull(NEW.to_location_id, -1)
          AND ifnull(original.from_condition_value_id, -1)
              = ifnull(NEW.to_condition_value_id, -1)
          AND ifnull(original.to_warehouse_id, -1) = ifnull(NEW.from_warehouse_id, -1)
          AND ifnull(original.to_location_id, -1) = ifnull(NEW.from_location_id, -1)
          AND ifnull(original.to_condition_value_id, -1)
              = ifnull(NEW.from_condition_value_id, -1)
    ) THEN RAISE(ABORT, 'reversal line must be exact inverse') END;
END;

CREATE TRIGGER trg_ledger_transaction_no_update
BEFORE UPDATE ON warehouse_transactions
BEGIN SELECT RAISE(ABORT, 'posted transactions are immutable'); END;

CREATE TRIGGER trg_ledger_transaction_no_delete
BEFORE DELETE ON warehouse_transactions
BEGIN SELECT RAISE(ABORT, 'posted transactions are retained'); END;

CREATE TRIGGER trg_ledger_line_no_update
BEFORE UPDATE ON warehouse_transaction_lines
BEGIN SELECT RAISE(ABORT, 'posted transaction lines are immutable'); END;

CREATE TRIGGER trg_ledger_line_no_delete
BEFORE DELETE ON warehouse_transaction_lines
BEGIN SELECT RAISE(ABORT, 'posted transaction lines are retained'); END;

CREATE TRIGGER trg_late_evidence_no_update
BEFORE UPDATE ON warehouse_late_operation_evidence
BEGIN SELECT RAISE(ABORT, 'late operation evidence is immutable'); END;

CREATE TRIGGER trg_late_evidence_no_delete
BEFORE DELETE ON warehouse_late_operation_evidence
BEGIN SELECT RAISE(ABORT, 'late operation evidence is retained'); END;

COMMIT;
PRAGMA user_version = 6;
