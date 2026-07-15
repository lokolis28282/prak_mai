-- Run after synthetic_inventory_proof.sql. Empty/synthetic plans prove access
-- paths only; they do not establish p95.

EXPLAIN QUERY PLAN
SELECT equipment_id
FROM equipment_identities
WHERE kind = 'SERIAL_NUMBER'
  AND normalized_key = 'SN-0001'
  AND status = 'ACTIVE'
ORDER BY scope_key, equipment_id;

EXPLAIN QUERY PLAN
SELECT equipment_id
FROM equipment_identities
WHERE kind = 'INVENTORY_NUMBER'
  AND normalized_key = 'INV-0001'
  AND status = 'ACTIVE';

EXPLAIN QUERY PLAN
SELECT public_id, lifecycle_status
FROM equipment
WHERE lifecycle_status = 'ACTIVE' AND equipment_id > 0
ORDER BY equipment_id
LIMIT 100;

EXPLAIN QUERY PLAN
SELECT projection_row_id, equipment_id, catalog_item_id, quantity_minor
FROM balance_projection_rows
WHERE projection_version_id = (
    SELECT active_projection_version_id FROM app_state WHERE singleton_id = 1
)
  AND warehouse_id = 1
  AND location_id >= 1
  AND projection_row_id > 0
ORDER BY location_id, condition_value_id, projection_row_id
LIMIT 100;

EXPLAIN QUERY PLAN
SELECT event_id, event_type, occurred_at_us
FROM legacy_history_events
WHERE serial_key = ?1
ORDER BY occurred_at_us, event_id
LIMIT ?2;

EXPLAIN QUERY PLAN
SELECT event_id, event_type, occurred_at_us
FROM legacy_history_events
WHERE serial_key COLLATE BINARY = 'SN-0001'
ORDER BY occurred_at_us, event_id
LIMIT 100;

EXPLAIN QUERY PLAN
SELECT catalog_item_id
FROM catalog_items
WHERE vendor_scope_key = ?1
  AND part_number_key = ?2
  AND status IN ('APPROVED', 'INACTIVE')
ORDER BY status, catalog_item_id
LIMIT ?3;

EXPLAIN QUERY PLAN
SELECT t.ledger_sequence, t.kind, l.line_id
FROM warehouse_transaction_lines l
JOIN warehouse_transactions t ON t.ledger_sequence = l.ledger_sequence
WHERE l.equipment_id = 1 AND l.ledger_sequence > 0
ORDER BY l.ledger_sequence, l.line_id
LIMIT 100;

EXPLAIN QUERY PLAN
SELECT i.snapshot_item_id, i.equipment_id, i.catalog_item_id
FROM inventory_sessions s
JOIN inventory_snapshots p ON p.session_id = s.session_id
JOIN inventory_snapshot_items i ON i.snapshot_id = p.snapshot_id
WHERE s.session_id = 1 AND i.snapshot_item_id > 0
ORDER BY i.snapshot_item_id
LIMIT 100;

-- Projection rebuild is intentionally a bounded full truth scan/aggregate.
EXPLAIN QUERY PLAN
SELECT equipment_id, catalog_item_id, warehouse_id, location_id,
       condition_value_id, lot_key, uom_id, quantity_minor
FROM v_balance_truth;
