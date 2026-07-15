-- REVIEW-ONLY successor FULL baseline proof. Run after synthetic_inventory_proof.sql.
PRAGMA foreign_keys = ON;
BEGIN IMMEDIATE;

INSERT INTO import_commits(
    import_commit_id, public_id, import_kind, source_object_key, source_file_name,
    source_sha256, source_size_bytes, template_version, parser_version,
    schema_version, preview_digest, manifest_json, committed_by_user_id,
    actor_display_name, committed_at_us, idempotency_key, correlation_id
) VALUES (
    2, '00000000-0000-7000-8000-000000002001', 'FULL_INVENTORY',
    'source-proof-0002', 'proof-2.xlsx',
    X'1212121212121212121212121212121212121212121212121212121212121212',
    200, '1.0', 'inventory-xlsx/1', '1',
    X'1313131313131313131313131313131313131313131313131313131313131313',
    '{"proof":"successor"}', 1, 'Review Admin', 250,
    'approve-proof-0002', 'corr-approve-proof-0002'
);

INSERT INTO import_row_links(
    row_link_id, import_commit_id, source_sheet, source_row_number,
    source_row_key, source_row_sha256, raw_payload_json,
    target_type, target_public_id, transform_version
) VALUES
    (3, 2, 'Inventory', 2, 'ROW-1',
     X'2121212121212121212121212121212121212121212121212121212121212121',
     '{"serial":"SN-0001"}', 'EQUIPMENT',
     '00000000-0000-7000-8000-000000000401', 'proof/1'),
    (4, 2, 'Inventory', 3, 'ROW-2',
     X'2222222222222222222222222222222222222222222222222222222222222222',
     '{"part_number":"PN-C-1","quantity":"1.200"}', 'CATALOG_ITEM',
     '00000000-0000-7000-8000-000000000202', 'proof/1'),
    (5, 2, 'Inventory', 4, 'ROW-3',
     X'2323232323232323232323232323232323232323232323232323232323232323',
     '{"part_number":"PN-C-1","quantity":"0.300"}', 'CATALOG_ITEM',
     '00000000-0000-7000-8000-000000000202', 'proof/1');

INSERT INTO inventory_sessions(
    session_id, public_id, import_commit_id, scope_type, scope_json, status,
    source_sha256, template_version, parser_version, schema_version,
    preview_digest, observed_active_snapshot_id, freeze_ledger_cutoff,
    freeze_started_at_us, effective_at_us, count_started_at_us,
    count_finished_at_us, approved_by_user_id, actor_display_name,
    approved_at_us, approval_idempotency_key, created_at_us, updated_at_us
) VALUES (
    2, '00000000-0000-7000-8000-000000002101', 2, 'FULL',
    '{"boundary":"GLOBAL"}', 'APPROVED',
    X'1212121212121212121212121212121212121212121212121212121212121212',
    '1.0', 'inventory-xlsx/1', '1',
    X'1313131313131313131313131313131313131313131313131313131313131313',
    1, 4, 200, 200, 200, 240, 1, 'Review Admin', 250,
    'approve-proof-0002', 190, 250
);

-- Deferred superseded_by FK permits this order while the partial UNIQUE
-- active-snapshot constraint remains true after every statement.
UPDATE inventory_snapshots
SET status = 'SUPERSEDED', is_active = 0, superseded_by_snapshot_id = 2
WHERE snapshot_id = 1;
UPDATE inventory_sessions SET status = 'SUPERSEDED', updated_at_us = 250
WHERE session_id = 1;

INSERT INTO inventory_snapshots(
    snapshot_id, public_id, session_id, previous_snapshot_id, ledger_cutoff,
    effective_at_us, status, is_active, item_count, totals_json,
    content_checksum, approved_by_user_id, actor_display_name, approved_at_us
) VALUES (
    2, '00000000-0000-7000-8000-000000002201', 2, 1, 4, 200,
    'APPROVED', 1, 3, '{"EA":1,"M":1500}',
    X'2424242424242424242424242424242424242424242424242424242424242424',
    1, 'Review Admin', 250
);

INSERT INTO inventory_snapshot_items(
    snapshot_item_id, snapshot_id, row_link_id, equipment_id, warehouse_id,
    location_id, condition_value_id, uom_id, quantity_minor,
    identity_evidence_json, row_checksum
) VALUES (
    3, 2, 3, 1, 1, 1, 1, 1, 1, '{"serial_raw":"SN-0001"}',
    X'2525252525252525252525252525252525252525252525252525252525252525'
);
INSERT INTO inventory_snapshot_items(
    snapshot_item_id, snapshot_id, row_link_id, catalog_item_id, warehouse_id,
    location_id, condition_value_id, uom_id, quantity_minor,
    identity_evidence_json, row_checksum
) VALUES
    (4, 2, 4, 2, 1, 1, 1, 2, 1200, '{"part_number_raw":"PN-C-1"}',
     X'2626262626262626262626262626262626262626262626262626262626262626'),
    (5, 2, 5, 2, 1, 2, 1, 2, 300, '{"part_number_raw":"PN-C-1"}',
     X'2727272727272727272727272727272727272727272727272727272727272727');

UPDATE balance_projection_versions SET build_status = 'RETIRED'
WHERE projection_version_id = 2;
INSERT INTO balance_projection_versions(
    projection_version_id, public_id, snapshot_id, build_status,
    built_through_sequence, row_count, total_checksum, created_at_us,
    ready_at_us, activated_at_us
) VALUES (
    3, '00000000-0000-7000-8000-000000002301', 2, 'ACTIVE', 4, 3,
    X'2828282828282828282828282828282828282828282828282828282828282828',
    250, 250, 250
);
INSERT INTO balance_projection_rows(
    projection_row_id, projection_version_id, equipment_id, catalog_item_id,
    warehouse_id, location_id, condition_value_id, lot_key, uom_id,
    quantity_minor, last_applied_sequence, row_checksum
)
SELECT 300 + snapshot_item_id, 3, equipment_id, catalog_item_id, warehouse_id,
       location_id, condition_value_id, lot_key, uom_id, quantity_minor, 4,
       zeroblob(32)
FROM inventory_snapshot_items WHERE snapshot_id = 2;

UPDATE app_state
SET active_snapshot_id = 2, active_projection_version_id = 3,
    state_version = state_version + 1, updated_at_us = 250
WHERE singleton_id = 1;

INSERT INTO audit_events(
    audit_event_id, public_id, occurred_at_us, action_code, outcome,
    actor_user_id, actor_display_name, actor_role_code, permission_code,
    correlation_id, subject_type, subject_public_id, details_json, event_hash
) VALUES (
    99, '00000000-0000-7000-8000-000000002401', 250,
    'INVENTORY_APPROVED', 'SUCCESS', 1, 'Review Admin', 'admin',
    'INVENTORY_APPROVE', 'corr-approve-proof-0002', 'INVENTORY_SNAPSHOT',
    '00000000-0000-7000-8000-000000002201', '{"proof":"successor"}',
    X'2929292929292929292929292929292929292929292929292929292929292929'
);

COMMIT;

SELECT 'successor_baseline', balance_state, active_snapshot_id,
       active_projection_version_id, last_ledger_sequence
FROM app_state WHERE singleton_id = 1;
SELECT 'snapshot_chain', snapshot_id, previous_snapshot_id,
       superseded_by_snapshot_id, status, is_active
FROM inventory_snapshots ORDER BY snapshot_id;
