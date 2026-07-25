-- REVIEW-ONLY positive domain prototype. Apply only to a temporary DB after V001-V008.
PRAGMA foreign_keys = ON;

SELECT 'before_baseline_state', balance_state, active_snapshot_id
FROM app_state WHERE singleton_id = 1;

BEGIN IMMEDIATE;

INSERT INTO roles(role_id, code, display_name, active, created_at_us)
VALUES (1, 'admin', 'Administrator', 1, 10),
       (2, 'operator', 'Operator', 1, 10),
       (3, 'auditor', 'Auditor', 1, 10);

INSERT INTO permissions(permission_code, display_name, risk_level, active, created_at_us)
VALUES ('INVENTORY_APPROVE', 'Approve inventory', 'SENSITIVE', 1, 10),
       ('WAREHOUSE_RECEIPT', 'Post receipt', 'STANDARD', 1, 10),
       ('WAREHOUSE_ISSUE', 'Post issue', 'STANDARD', 1, 10),
       ('WAREHOUSE_TRANSFER', 'Post transfer', 'STANDARD', 1, 10),
       ('WAREHOUSE_REVERSE', 'Reverse transaction', 'SENSITIVE', 1, 10);

INSERT INTO users(
    user_id, public_id, login_key, email_raw, email_key, display_name,
    password_hash, status, must_change_password, credential_version,
    created_at_us, updated_at_us
) VALUES (
    1, '00000000-0000-7000-8000-000000000001', 'review.admin',
    'review@example.invalid', 'review@example.invalid', 'Review Admin',
    '$argon2id$review-only-not-a-real-credential', 'ACTIVE', 0, 1, 10, 10
);

INSERT INTO user_roles(
    user_role_id, user_id, role_id, assigned_by_user_id, assigned_at_us
) VALUES (1, 1, 1, 1, 10);

INSERT INTO role_permissions(role_id, permission_code, granted_at_us, granted_by_user_id)
SELECT 1, permission_code, 10, 1 FROM permissions;

INSERT INTO reference_domains(
    domain_id, code, display_name, normalization_policy, scope_policy,
    status, created_at_us, updated_at_us
) VALUES
    (1, 'STOCK_CONDITION', 'Stock condition', 'EXACT_CODE', 'GLOBAL', 'ACTIVE', 10, 10),
    (2, 'VENDOR', 'Vendor', 'CONSERVATIVE_TEXT', 'GLOBAL', 'ACTIVE', 10, 10);

INSERT INTO reference_values(
    value_id, public_id, domain_id, code, display_name, normalized_key,
    scope_key, status, source_type, source_ref, created_by_user_id,
    created_at_us, updated_at_us
) VALUES
    (1, '00000000-0000-7000-8000-000000000101', 1, 'AVAILABLE',
     'Available', 'AVAILABLE', 'GLOBAL', 'APPROVED', 'SYNTHETIC', 'proof', 1, 10, 10),
    (2, '00000000-0000-7000-8000-000000000102', 2, 'VENDOR_A',
     'Vendor A', 'VENDOR A', 'GLOBAL', 'APPROVED', 'SYNTHETIC', 'proof', 1, 10, 10);

INSERT INTO uoms(uom_id, code, display_name, dimension, scale, status, created_at_us)
VALUES (1, 'EA', 'Each', 'COUNT', 0, 'ACTIVE', 10),
       (2, 'M', 'Metre', 'LENGTH', 3, 'ACTIVE', 10);

INSERT INTO catalog_items(
    catalog_item_id, public_id, item_kind, vendor_value_id, vendor_scope_key,
    part_number_raw, part_number_key, default_uom_id, display_name, status,
    source_ref, created_at_us, updated_at_us
) VALUES
    (1, '00000000-0000-7000-8000-000000000201', 'SERIALIZED', 2, 'VENDOR:2',
     'PN-S-1', 'PN-S-1', 1, 'Synthetic server', 'APPROVED', 'proof', 10, 10),
    (2, '00000000-0000-7000-8000-000000000202', 'CABLE', 2, 'VENDOR:2',
     'PN-C-1', 'PN-C-1', 2, 'Synthetic cable', 'APPROVED', 'proof', 10, 10);

INSERT INTO warehouses(
    warehouse_id, public_id, code, display_name, status, created_at_us, updated_at_us
) VALUES (1, '00000000-0000-7000-8000-000000000301',
          'WH-1', 'Synthetic warehouse', 'ACTIVE', 10, 10);

INSERT INTO warehouse_locations(
    location_id, public_id, warehouse_id, code, display_name,
    location_kind, status, created_at_us, updated_at_us
) VALUES
    (1, '00000000-0000-7000-8000-000000000311', 1, 'SHELF-A',
     'Shelf A', 'SHELF', 'ACTIVE', 10, 10),
    (2, '00000000-0000-7000-8000-000000000312', 1, 'SHELF-B',
     'Shelf B', 'SHELF', 'ACTIVE', 10, 10);

INSERT INTO equipment(
    equipment_id, public_id, catalog_item_id, lifecycle_status,
    identity_status, created_at_us, updated_at_us
) VALUES (1, '00000000-0000-7000-8000-000000000401',
          1, 'ACTIVE', 'VERIFIED', 10, 10);

INSERT INTO equipment_identities(
    identity_id, equipment_id, kind, raw_value, normalized_key, scope_key,
    status, valid_from_us, source_type, source_ref, changed_by_user_id, reason
) VALUES (1, 1, 'SERIAL_NUMBER', 'SN-0001', 'SN-0001', 'VENDOR:2',
          'ACTIVE', 10, 'SYNTHETIC', 'proof', 1, 'initial proof identity');

INSERT INTO import_commits(
    import_commit_id, public_id, import_kind, source_object_key, source_file_name,
    source_sha256, source_size_bytes, template_version, parser_version,
    schema_version, preview_digest, manifest_json, committed_by_user_id,
    actor_display_name, committed_at_us, idempotency_key, correlation_id
) VALUES (
    1, '00000000-0000-7000-8000-000000000501', 'FULL_INVENTORY',
    'source-proof-0001', 'proof.xlsx', zeroblob(32), 100,
    '1.0', 'inventory-xlsx/1', '1', zeroblob(32), '{"proof":true}',
    1, 'Review Admin', 100, 'approve-proof-0001', 'corr-approve-proof-0001'
);

INSERT INTO import_row_links(
    row_link_id, import_commit_id, source_sheet, source_row_number,
    source_row_key, source_row_sha256, raw_payload_json,
    target_type, target_public_id, transform_version
) VALUES
    (1, 1, 'Inventory', 2, 'ROW-1', zeroblob(32), '{"serial":"SN-0001"}',
     'EQUIPMENT', '00000000-0000-7000-8000-000000000401', 'proof/1'),
    (2, 1, 'Inventory', 3, 'ROW-2', X'0101010101010101010101010101010101010101010101010101010101010101',
     '{"part_number":"PN-C-1","quantity":"1.000"}',
     'CATALOG_ITEM', '00000000-0000-7000-8000-000000000202', 'proof/1');

INSERT INTO inventory_sessions(
    session_id, public_id, import_commit_id, scope_type, scope_json, status,
    source_sha256, template_version, parser_version, schema_version,
    preview_digest, freeze_ledger_cutoff, freeze_started_at_us, effective_at_us,
    count_started_at_us, count_finished_at_us, approved_by_user_id,
    actor_display_name, approved_at_us, approval_idempotency_key,
    created_at_us, updated_at_us
) VALUES (
    1, '00000000-0000-7000-8000-000000000601', 1, 'FULL',
    '{"boundary":"GLOBAL"}', 'APPROVED', zeroblob(32), '1.0',
    'inventory-xlsx/1', '1', zeroblob(32), 0, 20, 20, 20, 80,
    1, 'Review Admin', 100, 'approve-proof-0001', 10, 100
);

INSERT INTO inventory_snapshots(
    snapshot_id, public_id, session_id, ledger_cutoff, effective_at_us,
    status, is_active, item_count, totals_json, content_checksum,
    approved_by_user_id, actor_display_name, approved_at_us
) VALUES (
    1, '00000000-0000-7000-8000-000000000701', 1, 0, 20,
    'APPROVED', 1, 2, '{"EA":1,"M":1000}', zeroblob(32),
    1, 'Review Admin', 100
);

INSERT INTO inventory_snapshot_items(
    snapshot_item_id, snapshot_id, row_link_id, equipment_id,
    warehouse_id, location_id, condition_value_id, uom_id, quantity_minor,
    identity_evidence_json, row_checksum
) VALUES (
    1, 1, 1, 1, 1, 1, 1, 1, 1,
    '{"serial_raw":"SN-0001"}', zeroblob(32)
);

INSERT INTO inventory_snapshot_items(
    snapshot_item_id, snapshot_id, row_link_id, catalog_item_id,
    warehouse_id, location_id, condition_value_id, uom_id, quantity_minor,
    identity_evidence_json, row_checksum
) VALUES (
    2, 1, 2, 2, 1, 1, 1, 2, 1000,
    '{"part_number_raw":"PN-C-1"}',
    X'0202020202020202020202020202020202020202020202020202020202020202'
);

INSERT INTO balance_projection_versions(
    projection_version_id, public_id, snapshot_id, build_status,
    built_through_sequence, row_count, total_checksum, created_at_us,
    ready_at_us, activated_at_us
) VALUES (
    1, '00000000-0000-7000-8000-000000000801', 1, 'ACTIVE',
    0, 2, zeroblob(32), 100, 100, 100
);

INSERT INTO balance_projection_rows(
    projection_row_id, projection_version_id, equipment_id,
    warehouse_id, location_id, condition_value_id, uom_id,
    quantity_minor, last_applied_sequence, row_checksum
) VALUES (1, 1, 1, 1, 1, 1, 1, 1, 0, zeroblob(32));

INSERT INTO balance_projection_rows(
    projection_row_id, projection_version_id, catalog_item_id,
    warehouse_id, location_id, condition_value_id, uom_id,
    quantity_minor, last_applied_sequence, row_checksum
) VALUES (
    2, 1, 2, 1, 1, 1, 2, 1000, 0,
    X'0202020202020202020202020202020202020202020202020202020202020202'
);

UPDATE app_state
SET balance_state = 'ACTIVE',
    active_snapshot_id = 1,
    active_projection_version_id = 1,
    state_version = state_version + 1,
    updated_at_us = 100
WHERE singleton_id = 1;

INSERT INTO audit_events(
    audit_event_id, public_id, occurred_at_us, action_code, outcome,
    actor_user_id, actor_display_name, actor_role_code, permission_code,
    correlation_id, subject_type, subject_public_id, details_json, event_hash
) VALUES (
    1, '00000000-0000-7000-8000-000000000901', 100,
    'INVENTORY_APPROVED', 'SUCCESS', 1, 'Review Admin', 'admin',
    'INVENTORY_APPROVE', 'corr-approve-proof-0001', 'INVENTORY_SNAPSHOT',
    '00000000-0000-7000-8000-000000000701', '{"proof":true}', zeroblob(32)
);

COMMIT;

SELECT 'after_approve_state', balance_state, active_snapshot_id,
       active_projection_version_id
FROM app_state WHERE singleton_id = 1;

-- Receipt +500 cable minor units.
BEGIN IMMEDIATE;
INSERT INTO warehouse_transactions(
    public_id, kind, posting_status, active_snapshot_id, occurred_at_us,
    posted_at_us, actor_user_id, actor_display_name, actor_role_code,
    permission_code, idempotency_scope, idempotency_key, request_checksum,
    correlation_id
) VALUES (
    '00000000-0000-7000-8000-000000001001', 'RECEIPT', 'POSTED', 1,
    110, 110, 1, 'Review Admin', 'admin', 'WAREHOUSE_RECEIPT',
    'proof:receipt', 'receipt-proof-0001', zeroblob(32), 'corr-receipt-proof-0001'
);
INSERT INTO warehouse_transaction_lines(
    line_id, ledger_sequence, line_no, catalog_item_id, uom_id, quantity_minor,
    to_warehouse_id, to_location_id, to_condition_value_id, line_checksum
) VALUES (1, 1, 1, 2, 2, 500, 1, 1, 1, zeroblob(32));
UPDATE balance_projection_rows
SET quantity_minor = quantity_minor + 500, last_applied_sequence = 1
WHERE projection_version_id = 1 AND catalog_item_id = 2 AND location_id = 1;
UPDATE balance_projection_versions SET built_through_sequence = 1
WHERE projection_version_id = 1;
UPDATE app_state SET last_ledger_sequence = 1, state_version = state_version + 1,
    updated_at_us = 110 WHERE singleton_id = 1;
INSERT INTO audit_events(
    audit_event_id, public_id, occurred_at_us, action_code, outcome,
    actor_user_id, actor_display_name, actor_role_code, permission_code,
    correlation_id, subject_type, subject_public_id, details_json, event_hash
) VALUES (2, '00000000-0000-7000-8000-000000000902', 110,
    'RECEIPT_POSTED', 'SUCCESS', 1, 'Review Admin', 'admin',
    'WAREHOUSE_RECEIPT', 'corr-receipt-proof-0001', 'WAREHOUSE_TRANSACTION',
    '00000000-0000-7000-8000-000000001001', '{}',
    X'0202020202020202020202020202020202020202020202020202020202020202');
COMMIT;

-- Issue -200.
BEGIN IMMEDIATE;
INSERT INTO warehouse_transactions(
    public_id, kind, posting_status, active_snapshot_id, occurred_at_us,
    posted_at_us, actor_user_id, actor_display_name, actor_role_code,
    permission_code, idempotency_scope, idempotency_key, request_checksum,
    correlation_id
) VALUES (
    '00000000-0000-7000-8000-000000001002', 'ISSUE', 'POSTED', 1,
    120, 120, 1, 'Review Admin', 'admin', 'WAREHOUSE_ISSUE',
    'proof:issue', 'issue-proof-00001', zeroblob(32), 'corr-issue-proof-0001'
);
INSERT INTO warehouse_transaction_lines(
    line_id, ledger_sequence, line_no, catalog_item_id, uom_id, quantity_minor,
    from_warehouse_id, from_location_id, from_condition_value_id, line_checksum
) VALUES (2, 2, 1, 2, 2, 200, 1, 1, 1, zeroblob(32));
UPDATE balance_projection_rows
SET quantity_minor = quantity_minor - 200, last_applied_sequence = 2
WHERE projection_version_id = 1 AND catalog_item_id = 2 AND location_id = 1;
UPDATE balance_projection_versions SET built_through_sequence = 2
WHERE projection_version_id = 1;
UPDATE app_state SET last_ledger_sequence = 2, state_version = state_version + 1,
    updated_at_us = 120 WHERE singleton_id = 1;
INSERT INTO audit_events(
    audit_event_id, public_id, occurred_at_us, action_code, outcome,
    actor_user_id, actor_display_name, actor_role_code, permission_code,
    correlation_id, subject_type, subject_public_id, details_json, event_hash
) VALUES (3, '00000000-0000-7000-8000-000000000903', 120,
    'ISSUE_POSTED', 'SUCCESS', 1, 'Review Admin', 'admin',
    'WAREHOUSE_ISSUE', 'corr-issue-proof-0001', 'WAREHOUSE_TRANSACTION',
    '00000000-0000-7000-8000-000000001002', '{}',
    X'0303030303030303030303030303030303030303030303030303030303030303');
COMMIT;

-- Exact reversal of issue +200.
BEGIN IMMEDIATE;
INSERT INTO warehouse_transactions(
    public_id, kind, posting_status, active_snapshot_id, occurred_at_us,
    posted_at_us, actor_user_id, actor_display_name, actor_role_code,
    permission_code, reason_code, reverses_ledger_sequence, idempotency_scope,
    idempotency_key, request_checksum, correlation_id
) VALUES (
    '00000000-0000-7000-8000-000000001003', 'REVERSAL', 'POSTED', 1,
    130, 130, 1, 'Review Admin', 'admin', 'WAREHOUSE_REVERSE',
    'PROOF_REVERSAL', 2, 'proof:reversal', 'reversal-proof-01',
    zeroblob(32), 'corr-reversal-proof-0001'
);
INSERT INTO warehouse_transaction_lines(
    line_id, ledger_sequence, line_no, catalog_item_id, uom_id, quantity_minor,
    to_warehouse_id, to_location_id, to_condition_value_id, line_checksum
) VALUES (3, 3, 1, 2, 2, 200, 1, 1, 1, zeroblob(32));
UPDATE balance_projection_rows
SET quantity_minor = quantity_minor + 200, last_applied_sequence = 3
WHERE projection_version_id = 1 AND catalog_item_id = 2 AND location_id = 1;
UPDATE balance_projection_versions SET built_through_sequence = 3
WHERE projection_version_id = 1;
UPDATE app_state SET last_ledger_sequence = 3, state_version = state_version + 1,
    updated_at_us = 130 WHERE singleton_id = 1;
INSERT INTO audit_events(
    audit_event_id, public_id, occurred_at_us, action_code, outcome,
    actor_user_id, actor_display_name, actor_role_code, permission_code,
    correlation_id, subject_type, subject_public_id, details_json, event_hash
) VALUES (4, '00000000-0000-7000-8000-000000000904', 130,
    'REVERSAL_POSTED', 'SUCCESS', 1, 'Review Admin', 'admin',
    'WAREHOUSE_REVERSE', 'corr-reversal-proof-0001', 'WAREHOUSE_TRANSACTION',
    '00000000-0000-7000-8000-000000001003', '{}',
    X'0404040404040404040404040404040404040404040404040404040404040404');
COMMIT;

-- Transfer 300: location changes, global total does not.
BEGIN IMMEDIATE;
INSERT INTO warehouse_transactions(
    public_id, kind, posting_status, active_snapshot_id, occurred_at_us,
    posted_at_us, actor_user_id, actor_display_name, actor_role_code,
    permission_code, idempotency_scope, idempotency_key, request_checksum,
    correlation_id
) VALUES (
    '00000000-0000-7000-8000-000000001004', 'TRANSFER', 'POSTED', 1,
    140, 140, 1, 'Review Admin', 'admin', 'WAREHOUSE_TRANSFER',
    'proof:transfer', 'transfer-proof-001', zeroblob(32), 'corr-transfer-proof-0001'
);
INSERT INTO warehouse_transaction_lines(
    line_id, ledger_sequence, line_no, catalog_item_id, uom_id, quantity_minor,
    from_warehouse_id, from_location_id, from_condition_value_id,
    to_warehouse_id, to_location_id, to_condition_value_id, line_checksum
) VALUES (4, 4, 1, 2, 2, 300, 1, 1, 1, 1, 2, 1, zeroblob(32));
UPDATE balance_projection_rows
SET quantity_minor = quantity_minor - 300, last_applied_sequence = 4
WHERE projection_version_id = 1 AND catalog_item_id = 2 AND location_id = 1;
INSERT INTO balance_projection_rows(
    projection_row_id, projection_version_id, catalog_item_id,
    warehouse_id, location_id, condition_value_id, uom_id,
    quantity_minor, last_applied_sequence, row_checksum
) VALUES (3, 1, 2, 1, 2, 1, 2, 300, 4, zeroblob(32));
UPDATE balance_projection_versions
SET built_through_sequence = 4, row_count = 3
WHERE projection_version_id = 1;
UPDATE app_state SET last_ledger_sequence = 4, state_version = state_version + 1,
    updated_at_us = 140 WHERE singleton_id = 1;
INSERT INTO audit_events(
    audit_event_id, public_id, occurred_at_us, action_code, outcome,
    actor_user_id, actor_display_name, actor_role_code, permission_code,
    correlation_id, subject_type, subject_public_id, details_json, event_hash
) VALUES (5, '00000000-0000-7000-8000-000000000905', 140,
    'TRANSFER_POSTED', 'SUCCESS', 1, 'Review Admin', 'admin',
    'WAREHOUSE_TRANSFER', 'corr-transfer-proof-0001', 'WAREHOUSE_TRANSACTION',
    '00000000-0000-7000-8000-000000001004', '{}',
    X'0505050505050505050505050505050505050505050505050505050505050505');
COMMIT;

SELECT 'after_ledger_truth_total_M', sum(quantity_minor)
FROM v_balance_truth WHERE catalog_item_id = 2;
SELECT 'after_ledger_projection_total_M', sum(quantity_minor)
FROM v_active_balance WHERE catalog_item_id = 2;

-- Shadow rebuild and atomic active pointer switch.
BEGIN IMMEDIATE;
INSERT INTO balance_projection_versions(
    projection_version_id, public_id, snapshot_id, build_status,
    built_through_sequence, row_count, total_checksum, created_at_us, ready_at_us
) VALUES (
    2, '00000000-0000-7000-8000-000000000802', 1, 'READY',
    4, 3, zeroblob(32), 150, 150
);
INSERT INTO balance_projection_rows(
    projection_row_id, projection_version_id, equipment_id, catalog_item_id,
    warehouse_id, location_id, condition_value_id, lot_key, uom_id,
    quantity_minor, last_applied_sequence, row_checksum
)
SELECT 100 + row_number() OVER (
           ORDER BY ifnull(equipment_id, 0), ifnull(catalog_item_id, 0),
                    warehouse_id, location_id
       ),
       2, equipment_id, catalog_item_id, warehouse_id, location_id,
       condition_value_id, lot_key, uom_id, quantity_minor,
       last_applied_sequence, zeroblob(32)
FROM v_balance_truth;
UPDATE balance_projection_versions
SET build_status = 'RETIRED'
WHERE projection_version_id = 1;
UPDATE balance_projection_versions
SET build_status = 'ACTIVE', activated_at_us = 150
WHERE projection_version_id = 2;
UPDATE app_state
SET active_projection_version_id = 2,
    state_version = state_version + 1,
    updated_at_us = 150
WHERE singleton_id = 1;
COMMIT;

SELECT 'projection_rebuild_difference', count(*)
FROM (
    SELECT equipment_id, catalog_item_id, warehouse_id, location_id,
           condition_value_id, lot_key, uom_id, quantity_minor
    FROM balance_projection_rows WHERE projection_version_id = 1
    EXCEPT
    SELECT equipment_id, catalog_item_id, warehouse_id, location_id,
           condition_value_id, lot_key, uom_id, quantity_minor
    FROM balance_projection_rows WHERE projection_version_id = 2
);

SELECT 'before_legacy_total', sum(quantity_minor)
FROM v_active_balance;

BEGIN IMMEDIATE;
INSERT INTO legacy_source_files(
    source_file_id, public_id, file_name, source_object_key, sha256,
    size_bytes, media_type, workbook_metadata_json, imported_at_us,
    import_batch_key
) VALUES (
    1, '00000000-0000-7000-8000-000000001101', 'legacy-proof.xlsx',
    'legacy-source-0001', zeroblob(32), 100, 'application/vnd.openxmlformats',
    '{"proof":true}', 160, 'legacy-proof-batch'
);
INSERT INTO legacy_history_events(
    event_id, public_id, source_file_id, source_sheet, source_row_number,
    source_row_key, source_row_sha256, record_status, event_type,
    serial_raw, serial_key, performed_by_name_raw, performed_by_quality,
    occurred_at_us, date_raw, date_quality, raw_payload_json,
    normalized_payload_json, imported_at_us
) VALUES (
    1, '00000000-0000-7000-8000-000000001102', 1, 'Receipt', 2,
    'RECEIPT:2', zeroblob(32), 'IMPORTED', 'RECEIPT',
    'SN-0001', 'SN-0001', 'Legacy Person', 'EXACT',
    1, '1', 'EXACT', '{"legacy":true}', '{"legacy":true}', 160
);
COMMIT;

SELECT 'after_legacy_total', sum(quantity_minor)
FROM v_active_balance;

SELECT 'truth_projection_difference', count(*)
FROM (
    SELECT equipment_id, catalog_item_id, warehouse_id, location_id,
           condition_value_id, lot_key, uom_id, quantity_minor
    FROM v_balance_truth
    EXCEPT
    SELECT equipment_id, catalog_item_id, warehouse_id, location_id,
           condition_value_id, lot_key, uom_id, quantity_minor
    FROM v_active_balance
);
