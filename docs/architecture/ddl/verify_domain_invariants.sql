-- Zero violations are expected for every query.
PRAGMA query_only = ON;

SELECT 'app_state_consistency' AS invariant, count(*) AS violations
FROM app_state
WHERE NOT (
    (balance_state = 'NOT_INITIALIZED'
      AND active_snapshot_id IS NULL
      AND active_projection_version_id IS NULL
      AND last_ledger_sequence = 0)
    OR
    (balance_state IN ('ACTIVE', 'INCONSISTENT')
      AND active_snapshot_id IS NOT NULL
      AND active_projection_version_id IS NOT NULL)
);

SELECT 'single_active_snapshot' AS invariant,
       max(count_value - 1, 0) AS violations
FROM (SELECT count(*) AS count_value FROM inventory_snapshots WHERE is_active = 1);

SELECT 'partial_snapshot_forbidden' AS invariant, count(*) AS violations
FROM inventory_snapshots s
JOIN inventory_sessions i ON i.session_id = s.session_id
WHERE i.scope_type <> 'FULL';

SELECT 'serialized_snapshot_quantity' AS invariant, count(*) AS violations
FROM inventory_snapshot_items i
JOIN uoms u ON u.uom_id = i.uom_id
WHERE i.equipment_id IS NOT NULL
  AND (i.quantity_minor <> 1 OR u.dimension <> 'COUNT' OR u.scale <> 0);

SELECT 'serialized_ledger_quantity' AS invariant, count(*) AS violations
FROM warehouse_transaction_lines l
JOIN uoms u ON u.uom_id = l.uom_id
WHERE l.equipment_id IS NOT NULL
  AND (l.quantity_minor <> 1 OR u.dimension <> 'COUNT' OR u.scale <> 0);

SELECT 'posted_transaction_without_lines' AS invariant, count(*) AS violations
FROM warehouse_transactions t
WHERE NOT EXISTS (
    SELECT 1 FROM warehouse_transaction_lines l
    WHERE l.ledger_sequence = t.ledger_sequence
);

SELECT 'ledger_before_or_at_cutoff' AS invariant, count(*) AS violations
FROM warehouse_transactions t
JOIN inventory_snapshots s ON s.snapshot_id = t.active_snapshot_id
WHERE t.ledger_sequence <= s.ledger_cutoff;

SELECT 'legacy_schema_balance_dependency' AS invariant, count(*) AS violations
FROM sqlite_master
WHERE (name LIKE 'legacy_%' OR tbl_name LIKE 'legacy_%')
  AND lower(ifnull(sql, '')) GLOB '*balance_projection*';

SELECT 'legacy_schema_ledger_dependency' AS invariant, count(*) AS violations
FROM sqlite_master
WHERE (name LIKE 'legacy_%' OR tbl_name LIKE 'legacy_%')
  AND lower(ifnull(sql, '')) GLOB '*warehouse_transaction*';

SELECT 'negative_balance_truth' AS invariant, count(*) AS violations
FROM v_balance_truth
WHERE quantity_minor < 0;

SELECT 'projection_missing_or_different' AS invariant, count(*) AS violations
FROM (
    SELECT equipment_id, catalog_item_id, warehouse_id, location_id,
           condition_value_id, lot_key, uom_id, quantity_minor
    FROM v_balance_truth
    EXCEPT
    SELECT equipment_id, catalog_item_id, warehouse_id, location_id,
           condition_value_id, lot_key, uom_id, quantity_minor
    FROM v_active_balance
);

SELECT 'projection_extra_or_different' AS invariant, count(*) AS violations
FROM (
    SELECT equipment_id, catalog_item_id, warehouse_id, location_id,
           condition_value_id, lot_key, uom_id, quantity_minor
    FROM v_active_balance
    EXCEPT
    SELECT equipment_id, catalog_item_id, warehouse_id, location_id,
           condition_value_id, lot_key, uom_id, quantity_minor
    FROM v_balance_truth
);

SELECT 'active_projection_head_lag' AS invariant, count(*) AS violations
FROM app_state a
JOIN balance_projection_versions p
  ON p.projection_version_id = a.active_projection_version_id
WHERE p.built_through_sequence <> a.last_ledger_sequence;

SELECT 'app_state_ledger_head' AS invariant, count(*) AS violations
FROM app_state a
WHERE a.last_ledger_sequence <> ifnull(
    (SELECT max(ledger_sequence) FROM warehouse_transactions), 0
);

SELECT 'snapshot_item_count' AS invariant, count(*) AS violations
FROM inventory_snapshots s
WHERE s.item_count <> (
    SELECT count(*) FROM inventory_snapshot_items i
    WHERE i.snapshot_id = s.snapshot_id
);

SELECT 'reversal_target_or_line_mismatch' AS invariant, count(*) AS violations
FROM warehouse_transactions r
WHERE r.kind = 'REVERSAL'
  AND (
    EXISTS (
        SELECT 1 FROM warehouse_transactions o
        WHERE o.ledger_sequence = r.reverses_ledger_sequence
          AND o.kind = 'REVERSAL'
    )
    OR EXISTS (
        SELECT 1
        FROM warehouse_transaction_lines rl
        WHERE rl.ledger_sequence = r.ledger_sequence
          AND NOT EXISTS (
              SELECT 1
              FROM warehouse_transaction_lines ol
              WHERE ol.ledger_sequence = r.reverses_ledger_sequence
                AND ol.line_no = rl.line_no
                AND ifnull(ol.equipment_id, -1) = ifnull(rl.equipment_id, -1)
                AND ifnull(ol.catalog_item_id, -1) = ifnull(rl.catalog_item_id, -1)
                AND ol.quantity_minor = rl.quantity_minor
                AND ifnull(ol.from_location_id, -1) = ifnull(rl.to_location_id, -1)
                AND ifnull(ol.to_location_id, -1) = ifnull(rl.from_location_id, -1)
          )
    )
  );

SELECT 'serialized_without_active_identity' AS invariant, count(*) AS violations
FROM equipment e
JOIN catalog_items c ON c.catalog_item_id = e.catalog_item_id
WHERE c.item_kind = 'SERIALIZED'
  AND e.lifecycle_status = 'ACTIVE'
  AND NOT EXISTS (
      SELECT 1 FROM equipment_identities i
      WHERE i.equipment_id = e.equipment_id
        AND i.status = 'ACTIVE'
        AND i.kind IN ('SERIAL_NUMBER', 'INVENTORY_NUMBER')
  );

WITH RECURSIVE location_walk(
    start_id, location_id, parent_location_id, path, cycle
) AS (
    SELECT location_id, location_id, parent_location_id,
           printf(',%d,', location_id), 0
    FROM warehouse_locations
    UNION ALL
    SELECT w.start_id, p.location_id, p.parent_location_id,
           w.path || p.location_id || ',',
           instr(w.path, printf(',%d,', p.location_id)) > 0
    FROM location_walk w
    JOIN warehouse_locations p ON p.location_id = w.parent_location_id
    WHERE w.parent_location_id IS NOT NULL AND w.cycle = 0
)
SELECT 'location_parent_cycle' AS invariant, count(*) AS violations
FROM location_walk
WHERE cycle = 1;

WITH RECURSIVE reference_walk(
    start_id, value_id, parent_value_id, path, cycle
) AS (
    SELECT value_id, value_id, parent_value_id,
           printf(',%d,', value_id), 0
    FROM reference_values
    UNION ALL
    SELECT w.start_id, p.value_id, p.parent_value_id,
           w.path || p.value_id || ',',
           instr(w.path, printf(',%d,', p.value_id)) > 0
    FROM reference_walk w
    JOIN reference_values p ON p.value_id = w.parent_value_id
    WHERE w.parent_value_id IS NOT NULL AND w.cycle = 0
)
SELECT 'reference_parent_cycle' AS invariant, count(*) AS violations
FROM reference_walk
WHERE cycle = 1;

SELECT 'reference_parent_cross_domain' AS invariant, count(*) AS violations
FROM reference_values child
JOIN reference_values parent ON parent.value_id = child.parent_value_id
WHERE child.domain_id <> parent.domain_id;

SELECT 'location_parent_cross_warehouse' AS invariant, count(*) AS violations
FROM warehouse_locations child
JOIN warehouse_locations parent ON parent.location_id = child.parent_location_id
WHERE child.warehouse_id <> parent.warehouse_id;

SELECT 'equipment_merge_balance_without_adjustments' AS invariant,
       count(*) AS violations
FROM equipment_merges m
WHERE EXISTS (
    SELECT 1
    FROM app_state a
    JOIN balance_projection_rows p
      ON p.projection_version_id = a.active_projection_version_id
    WHERE a.singleton_id = 1
      AND p.equipment_id = m.source_equipment_id
      AND p.quantity_minor > 0
)
AND (m.out_adjustment_sequence IS NULL OR m.in_adjustment_sequence IS NULL);

SELECT 'equipment_merge_adjustment_kind' AS invariant, count(*) AS violations
FROM equipment_merges m
WHERE m.out_adjustment_sequence IS NOT NULL
  AND (
      NOT EXISTS (
          SELECT 1 FROM warehouse_transactions t
          WHERE t.ledger_sequence = m.out_adjustment_sequence
            AND t.kind = 'ADJUSTMENT_OUT'
      )
      OR NOT EXISTS (
          SELECT 1 FROM warehouse_transactions t
          WHERE t.ledger_sequence = m.in_adjustment_sequence
            AND t.kind = 'ADJUSTMENT_IN'
      )
  );
