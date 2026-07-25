-- REVIEW-ONLY correction-after-rebaseline proof.
-- Run after synthetic_inventory_proof.sql and synthetic_rebaseline_proof.sql.
-- The negative old-baseline REVERSAL attempt is executed by the review runner;
-- this file proves the permitted forward correction under the active baseline.
PRAGMA foreign_keys = ON;
BEGIN IMMEDIATE;

INSERT INTO permissions(permission_code, display_name, risk_level, active, created_at_us)
VALUES ('WAREHOUSE_ADJUST', 'Post warehouse adjustment', 'SENSITIVE', 1, 260);
INSERT INTO role_permissions(role_id, permission_code, granted_at_us, granted_by_user_id)
VALUES (1, 'WAREHOUSE_ADJUST', 260, 1);

INSERT INTO warehouse_transactions(
    public_id, kind, posting_status, active_snapshot_id, occurred_at_us,
    posted_at_us, actor_user_id, actor_display_name, actor_role_code,
    permission_code, reason_code, idempotency_scope, idempotency_key,
    request_checksum, correlation_id
) VALUES (
    '00000000-0000-7000-8000-000000003001', 'ADJUSTMENT_IN', 'POSTED', 2,
    260, 260, 1, 'Review Admin', 'admin', 'WAREHOUSE_ADJUST',
    'POST_REBASELINE_PHYSICAL_CORRECTION', 'proof:adjustment',
    'adjustment-proof-0001', zeroblob(32), 'corr-adjustment-proof-0001'
);

INSERT INTO warehouse_transaction_lines(
    line_id, ledger_sequence, line_no, catalog_item_id, uom_id, quantity_minor,
    to_warehouse_id, to_location_id, to_condition_value_id, line_checksum
) VALUES (5, 5, 1, 2, 2, 100, 1, 1, 1, zeroblob(32));

UPDATE balance_projection_rows
SET quantity_minor = quantity_minor + 100, last_applied_sequence = 5
WHERE projection_version_id = 3 AND catalog_item_id = 2 AND location_id = 1;
UPDATE balance_projection_versions
SET built_through_sequence = 5
WHERE projection_version_id = 3;
UPDATE app_state
SET last_ledger_sequence = 5, state_version = state_version + 1,
    updated_at_us = 260
WHERE singleton_id = 1;

INSERT INTO audit_events(
    audit_event_id, public_id, occurred_at_us, action_code, outcome,
    actor_user_id, actor_display_name, actor_role_code, permission_code,
    correlation_id, subject_type, subject_public_id, details_json, event_hash
) VALUES (
    100, '00000000-0000-7000-8000-000000003101', 260,
    'ADJUSTMENT_POSTED', 'SUCCESS', 1, 'Review Admin', 'admin',
    'WAREHOUSE_ADJUST', 'corr-adjustment-proof-0001', 'WAREHOUSE_TRANSACTION',
    '00000000-0000-7000-8000-000000003001',
    '{"reason":"post-rebaseline physical correction"}',
    X'ABABABABABABABABABABABABABABABABABABABABABABABABABABABABABABABAB'
);

COMMIT;

SELECT 'post_rebaseline_adjustment', ledger_sequence, kind, active_snapshot_id
FROM warehouse_transactions WHERE ledger_sequence = 5;
SELECT 'post_rebaseline_truth_projection_difference', count(*)
FROM (
    SELECT equipment_id, catalog_item_id, warehouse_id, location_id,
           condition_value_id, lot_key, uom_id, quantity_minor
    FROM v_balance_truth
    EXCEPT
    SELECT equipment_id, catalog_item_id, warehouse_id, location_id,
           condition_value_id, lot_key, uom_id, quantity_minor
    FROM v_active_balance
);
SELECT 'historical_original_and_current_correction', ledger_sequence, kind,
       active_snapshot_id
FROM warehouse_transactions
WHERE ledger_sequence IN (1, 5)
ORDER BY ledger_sequence;
