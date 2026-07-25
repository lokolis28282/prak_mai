-- Independent adversarial repro set for ODE 0.13 DDL review.
-- Run only against a temporary DB built fresh from V001..V008 in a scratch
-- directory. Never run against data/warehouse.db or any candidate DB.
--
-- Usage:
--   sqlite3 scratch.db "PRAGMA foreign_keys=ON;" ".read V001__system_and_security.sql"
--   ... (repeat for V002..V008 in order)
--   sqlite3 scratch.db "PRAGMA foreign_keys=ON;" ".read this_file.sql"

PRAGMA foreign_keys = ON;

----------------------------------------------------------------------------
-- FINDING A (CRITICAL): warehouse_locations.parent_location_id hierarchy
-- has no cycle guard. data-model.md claims "acyclic parent" but only same-
-- warehouse membership is checked (trg_location_parent_same_warehouse_*).
----------------------------------------------------------------------------
BEGIN IMMEDIATE;
INSERT INTO warehouses(warehouse_id, public_id, code, display_name, status, created_at_us, updated_at_us)
VALUES (1,'00000000-0000-7000-8000-000000000301','WH-1','WH','ACTIVE',10,10);
INSERT INTO warehouse_locations(location_id, public_id, warehouse_id, code, display_name, parent_location_id, location_kind, status, created_at_us, updated_at_us)
VALUES (1,'00000000-0000-7000-8000-000000000311',1,'ZONE-X','Zone X',NULL,'ZONE','ACTIVE',10,10);
INSERT INTO warehouse_locations(location_id, public_id, warehouse_id, code, display_name, parent_location_id, location_kind, status, created_at_us, updated_at_us)
VALUES (2,'00000000-0000-7000-8000-000000000312',1,'ZONE-Y','Zone Y',1,'ZONE','ACTIVE',10,10);
-- Close the cycle: X's parent becomes Y, while Y's parent is already X.
UPDATE warehouse_locations SET parent_location_id = 2 WHERE location_id = 1;
COMMIT;
SELECT 'FINDING_A_location_cycle_created' AS finding, location_id, parent_location_id
FROM warehouse_locations WHERE location_id IN (1,2);

----------------------------------------------------------------------------
-- FINDING A2 (CRITICAL, same root cause): reference_values.parent_value_id
-- hierarchy has the same gap. data-model.md: "Parent graph must be acyclic".
----------------------------------------------------------------------------
BEGIN IMMEDIATE;
INSERT INTO reference_domains(domain_id, code, display_name, normalization_policy, scope_policy, status, created_at_us, updated_at_us)
VALUES (1,'VENDOR','Vendor','CONSERVATIVE_TEXT','GLOBAL','ACTIVE',10,10);
INSERT INTO reference_values(value_id, public_id, domain_id, code, display_name, normalized_key, scope_key, parent_value_id, status, source_type, source_ref, created_at_us, updated_at_us)
VALUES (1,'00000000-0000-7000-8000-000000000101',1,'V1','V1','V1','GLOBAL',NULL,'APPROVED','TEST','test',10,10);
INSERT INTO reference_values(value_id, public_id, domain_id, code, display_name, normalized_key, scope_key, parent_value_id, status, source_type, source_ref, created_at_us, updated_at_us)
VALUES (2,'00000000-0000-7000-8000-000000000102',1,'V2','V2','V2','GLOBAL',1,'APPROVED','TEST','test',10,10);
UPDATE reference_values SET parent_value_id = 2 WHERE value_id = 1;
COMMIT;
SELECT 'FINDING_A2_reference_value_cycle_created' AS finding, value_id, parent_value_id
FROM reference_values WHERE value_id IN (1,2);

----------------------------------------------------------------------------
-- FINDING B (CRITICAL): partial index "WHERE col <> ''" is not matched by
-- SQLite's query planner for an ordinary equality lookup, causing SCAN
-- instead of SEARCH on legacy_history_events(serial_key). This reproduces
-- even on an EMPTY table (structural planner decision, not a stats/ANALYZE
-- artifact), and contradicts performance.md's "EXPLAIN QUERY PLAN gate
-- запрещает SCAN..." gate and REVIEW_RESULTS.md's claimed green result.
-- Reproduced on SQLite 3.51.0.
----------------------------------------------------------------------------
EXPLAIN QUERY PLAN
SELECT * FROM legacy_history_events WHERE serial_key = 'SN-0000001';
-- Expected (per docs): SEARCH ... USING INDEX ix_legacy_history_serial
-- Actual: SCAN legacy_history_events
-- Workaround that DOES use the index (must be duplicated by every caller;
-- undocumented anywhere in the DDL comments/data-model.md/performance.md):
EXPLAIN QUERY PLAN
SELECT * FROM legacy_history_events
WHERE serial_key = 'SN-0000001' AND serial_key <> '';

BEGIN IMMEDIATE;
INSERT INTO uoms(uom_id, code, display_name, dimension, scale, status, created_at_us)
VALUES (90,'EA90','Each',   'COUNT',0,'ACTIVE',10);
INSERT INTO catalog_items(catalog_item_id, public_id, item_kind, vendor_scope_key, part_number_raw, part_number_key, default_uom_id, display_name, status, source_ref, created_at_us, updated_at_us)
VALUES (90,'00000000-0000-7000-8000-000000090001','SERIALIZED','VENDOR:1','PN-1','PN-1',90,'Probe item','APPROVED','proof',10,10);
COMMIT;
-- Same defect, second confirmed instance: exact vendor+PN lookup as the
-- application would naturally write it.
EXPLAIN QUERY PLAN
SELECT * FROM catalog_items
WHERE vendor_scope_key = 'VENDOR:1' AND part_number_key = 'PN-1'
  AND status IN ('APPROVED','INACTIVE');
-- Expected: SEARCH ... USING INDEX ux_catalog_items_vendor_part
-- Actual: SCAN catalog_items

----------------------------------------------------------------------------
-- FINDING C (MEDIUM): trg_uom_scale_immutable_after_use does not check
-- inventory_reconciliation_items.uom_id, so a UOM referenced only by
-- reconciliation evidence can still have its scale mutated after use,
-- silently invalidating the immutable delta_quantity_minor interpretation
-- on that row. ADR-007 claims "UOM ... immutable scale" unconditionally.
----------------------------------------------------------------------------
BEGIN IMMEDIATE;
INSERT INTO uoms(uom_id, code, display_name, dimension, scale, status, created_at_us)
VALUES (91,'KG91','Kilogram','MASS',3,'ACTIVE',10);
INSERT INTO users(user_id, public_id, login_key, display_name, password_hash, status, must_change_password, credential_version, created_at_us, updated_at_us)
VALUES (1,'00000000-0000-7000-8000-000000000001','a','A','$argon2id$review-only-not-a-real-credential','ACTIVE',0,1,10,10);
INSERT INTO warehouses(warehouse_id, public_id, code, display_name, status, created_at_us, updated_at_us)
VALUES (2,'00000000-0000-7000-8000-000000000302','WH-2','WH2','ACTIVE',10,10);
INSERT INTO warehouse_locations(location_id, public_id, warehouse_id, code, display_name, location_kind, status, created_at_us, updated_at_us)
VALUES (3,'00000000-0000-7000-8000-000000000313',2,'S-C','C','SHELF','ACTIVE',10,10);
INSERT INTO reference_domains(domain_id, code, display_name, normalization_policy, scope_policy, status, created_at_us, updated_at_us)
VALUES (2,'STOCK_CONDITION','Stock condition','EXACT_CODE','GLOBAL','ACTIVE',10,10);
INSERT INTO reference_values(value_id, public_id, domain_id, code, display_name, normalized_key, scope_key, status, source_type, source_ref, created_at_us, updated_at_us)
VALUES (10,'00000000-0000-7000-8000-000000000110',2,'AVAILABLE','Available','AVAILABLE','GLOBAL','APPROVED','SYNTHETIC','proof',10,10);
INSERT INTO catalog_items(catalog_item_id, public_id, item_kind, vendor_scope_key, part_number_raw, part_number_key, default_uom_id, display_name, status, source_ref, created_at_us, updated_at_us)
VALUES (91,'00000000-0000-7000-8000-000000000291','BULK','UNSCOPED','','',90,'Bulk item','APPROVED','proof',10,10);
INSERT INTO import_commits(import_commit_id, public_id, import_kind, source_object_key, source_file_name, source_sha256, source_size_bytes, template_version, parser_version, schema_version, preview_digest, manifest_json, committed_by_user_id, actor_display_name, committed_at_us, idempotency_key, correlation_id)
VALUES (91,'00000000-0000-7000-8000-000000000591','FULL_INVENTORY','source-object-key-0091','p.xlsx',zeroblob(32),1,'1.0','inventory-xlsx/1','1',zeroblob(32),'{}',1,'A',10,'idempotency-key-0000091','corr-0091');
INSERT INTO inventory_sessions(session_id, public_id, import_commit_id, scope_type, scope_json, status, source_sha256, template_version, parser_version, schema_version, preview_digest, freeze_ledger_cutoff, freeze_started_at_us, effective_at_us, count_started_at_us, count_finished_at_us, approved_by_user_id, actor_display_name, approved_at_us, approval_idempotency_key, created_at_us, updated_at_us)
VALUES (91,'00000000-0000-7000-8000-000000000691',91,'FULL','{}','APPROVED',zeroblob(32),'1.0','inventory-xlsx/1','1',zeroblob(32),0,10,10,10,10,1,'A',10,'idempotency-key-0000091',10,10);
INSERT INTO inventory_snapshots(snapshot_id, public_id, session_id, ledger_cutoff, effective_at_us, status, is_active, item_count, totals_json, content_checksum, approved_by_user_id, actor_display_name, approved_at_us)
VALUES (91,'00000000-0000-7000-8000-000000000791',91,0,10,'APPROVED',1,0,'{}',zeroblob(32),1,'A',10);
INSERT INTO inventory_reconciliation_items(reconciliation_id, session_id, snapshot_id, catalog_item_id, warehouse_id, location_id, condition_value_id, lot_key, uom_id, expected_quantity_minor, counted_quantity_minor, delta_quantity_minor, classification, explanation_json)
VALUES (1, 91, 91, 91, 2, 3, 10, '', 91, 500, 500, 0, 'MATCH', '{}');
-- uom_id=91 is now referenced ONLY via inventory_reconciliation_items.
UPDATE uoms SET scale = 5 WHERE uom_id = 91;
COMMIT;
SELECT 'FINDING_C_uom_scale_mutated_despite_reconciliation_reference' AS finding,
       uom_id, scale FROM uoms WHERE uom_id = 91;

----------------------------------------------------------------------------
-- FINDING D (HIGH, documentation gap; the behavior itself is plausibly
-- correct by domain logic but is not documented anywhere): once a FULL
-- snapshot is superseded, no transaction posted under the old (now
-- inactive) snapshot can ever be reversed again, because
-- trg_reversal_header_target requires original.active_snapshot_id =
-- NEW.active_snapshot_id, and trg_ledger_requires_active_baseline requires
-- NEW.active_snapshot_id to be the CURRENTLY active snapshot.
----------------------------------------------------------------------------
BEGIN IMMEDIATE;
INSERT INTO balance_projection_versions(projection_version_id, public_id, snapshot_id, build_status, built_through_sequence, row_count, total_checksum, created_at_us, ready_at_us, activated_at_us)
VALUES (91, '00000000-0000-7000-8000-000000000891', 91, 'ACTIVE', 0, 0, zeroblob(32), 10, 10, 10);
UPDATE app_state SET balance_state='ACTIVE', active_snapshot_id=91, active_projection_version_id=91, state_version=state_version+1, updated_at_us=15 WHERE singleton_id=1;
INSERT INTO warehouse_transactions(ledger_sequence, public_id, kind, posting_status, active_snapshot_id, occurred_at_us, posted_at_us, actor_user_id, actor_display_name, actor_role_code, permission_code, idempotency_scope, idempotency_key, request_checksum, correlation_id)
VALUES (1, '00000000-0000-7000-8000-000000098001', 'RECEIPT', 'POSTED', 91, 20, 20, 1, 'A', 'admin', 'WAREHOUSE_RECEIPT', 'proof', 'idempotency-key-receipt-1', zeroblob(32), 'corr-receipt-1');
INSERT INTO warehouse_transaction_lines(line_id, ledger_sequence, line_no, catalog_item_id, uom_id, quantity_minor, to_warehouse_id, to_location_id, to_condition_value_id, line_checksum)
VALUES (1, 1, 1, 91, 90, 10, 2, 3, 10, zeroblob(32));
UPDATE app_state SET last_ledger_sequence=1, state_version=state_version+1, updated_at_us=20 WHERE singleton_id=1;
-- Now approve a successor FULL baseline (snapshot 92), superseding 91.
INSERT INTO import_commits(import_commit_id, public_id, import_kind, source_object_key, source_file_name, source_sha256, source_size_bytes, template_version, parser_version, schema_version, preview_digest, manifest_json, committed_by_user_id, actor_display_name, committed_at_us, idempotency_key, correlation_id)
VALUES (92,'00000000-0000-7000-8000-000000000592','FULL_INVENTORY','source-object-key-0092','q.xlsx',X'9292929292929292929292929292929292929292929292929292929292929292',1,'1.0','inventory-xlsx/1','1',X'9292929292929292929292929292929292929292929292929292929292929292','{}',1,'A',30,'idempotency-key-0000092','corr-0092');
INSERT INTO inventory_sessions(session_id, public_id, import_commit_id, scope_type, scope_json, status, source_sha256, template_version, parser_version, schema_version, preview_digest, observed_active_snapshot_id, freeze_ledger_cutoff, freeze_started_at_us, effective_at_us, count_started_at_us, count_finished_at_us, approved_by_user_id, actor_display_name, approved_at_us, approval_idempotency_key, created_at_us, updated_at_us)
VALUES (92,'00000000-0000-7000-8000-000000000692',92,'FULL','{}','APPROVED',zeroblob(32),'1.0','inventory-xlsx/1','1',zeroblob(32),91,1,30,30,30,30,1,'A',30,'idempotency-key-0000092',30,30);
UPDATE inventory_snapshots SET status='SUPERSEDED', is_active=0, superseded_by_snapshot_id=92 WHERE snapshot_id=91;
INSERT INTO inventory_snapshots(snapshot_id, public_id, session_id, previous_snapshot_id, ledger_cutoff, effective_at_us, status, is_active, item_count, totals_json, content_checksum, approved_by_user_id, actor_display_name, approved_at_us)
VALUES (92,'00000000-0000-7000-8000-000000000792',92,91,1,30,'APPROVED',1,0,'{}',zeroblob(32),1,'A',30);
UPDATE app_state SET active_snapshot_id=92, state_version=state_version+1, updated_at_us=30 WHERE singleton_id=1;
COMMIT;
-- Attempt (in a separate later transaction, as a real admin correction
-- would be) to reverse the RECEIPT posted under the now-superseded
-- snapshot 91.
BEGIN IMMEDIATE;
INSERT INTO warehouse_transactions(public_id, kind, posting_status, active_snapshot_id, occurred_at_us, posted_at_us, actor_user_id, actor_display_name, actor_role_code, permission_code, reason_code, reverses_ledger_sequence, idempotency_scope, idempotency_key, request_checksum, correlation_id)
VALUES ('00000000-0000-7000-8000-000000098002', 'REVERSAL', 'POSTED', 91, 40, 40, 1, 'A', 'admin', 'WAREHOUSE_REVERSE', 'late-mistake-fix', 1, 'proof', 'idempotency-key-reversal-1', zeroblob(32), 'corr-reversal-1');
COMMIT;
-- Expected error if this attempted transaction runs: the header insert is
-- rejected because active_snapshot_id=91 is no longer the active baseline
-- (trg_ledger_requires_active_baseline) -- REVERSAL of a pre-rebaseline
-- transaction is permanently impossible via this pathway. Nowhere in
-- transaction-model.md / warehouse-ledger.md / ADR-002 / ADR-010 is this
-- interaction documented; only ADJUSTMENT remains available, and even that
-- is not explicitly cross-referenced from the reversal docs.
