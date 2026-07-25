-- Run read-only after V001-V008 and registry insertion.
PRAGMA query_only = ON;

SELECT 'integrity_check' AS check_name, integrity_check AS result
FROM pragma_integrity_check;

SELECT 'foreign_key_violations' AS check_name, count(*) AS result
FROM pragma_foreign_key_check;

SELECT 'application_id' AS check_name,
       CASE WHEN application_id = 0x4F444531 THEN 'PASS' ELSE 'FAIL' END AS result
FROM pragma_application_id;

SELECT 'user_version' AS check_name,
       CASE WHEN user_version = 8 THEN 'PASS' ELSE 'FAIL' END AS result
FROM pragma_user_version;

SELECT 'migration_registry' AS check_name,
       CASE WHEN count(*) = 8
             AND min(version) = 1 AND max(version) = 8
            THEN 'PASS' ELSE 'FAIL' END AS result
FROM schema_migrations;

SELECT 'schema_counts' AS check_name,
       json_object(
           'tables', sum(type = 'table' AND name NOT LIKE 'sqlite_%'),
           'indexes', sum(type = 'index' AND sql IS NOT NULL),
           'triggers', sum(type = 'trigger'),
           'views', sum(type = 'view')
       ) AS result
FROM sqlite_master;

SELECT 'real_quantity_columns' AS check_name,
       CASE WHEN count(*) = 0 THEN 'PASS' ELSE 'FAIL:' || group_concat(name) END
FROM (
    SELECT m.name || '.' || p.name AS name
    FROM sqlite_master m, pragma_table_info(m.name) p
    WHERE m.type = 'table'
      AND (p.name LIKE '%quantity%' OR p.name LIKE '%scale%')
      AND upper(p.type) = 'REAL'
);

SELECT 'default_credentials' AS check_name,
       CASE WHEN count(*) = 0 THEN 'PASS' ELSE 'FAIL' END AS result
FROM users;

SELECT 'required_exact_indexes' AS check_name,
       CASE WHEN count(*) = 9 THEN 'PASS' ELSE 'FAIL:' || count(*) END AS result
FROM sqlite_master
WHERE type = 'index'
  AND name IN (
      'ix_equipment_identity_exact',
      'ux_equipment_inventory_active',
      'ix_catalog_items_vendor_part_lookup',
      'ix_legacy_history_serial',
      'ix_ledger_lines_equipment',
      'ix_snapshot_items_page',
      'ix_projection_balance_page',
      'ix_projection_equipment',
      'ix_audit_events_page'
  );

WITH required(name) AS (
    VALUES
      ('trg_audit_events_no_delete'),
      ('trg_audit_events_no_update'),
      ('trg_equipment_identity_immutable_fields'),
      ('trg_equipment_identity_no_delete'),
      ('trg_equipment_alias_immutable_fields'),
      ('trg_equipment_alias_no_delete'),
      ('trg_equipment_merges_no_delete'),
      ('trg_equipment_merges_no_update'),
      ('trg_import_commits_immutable_delete'),
      ('trg_import_commits_immutable_update'),
      ('trg_import_findings_immutable_delete'),
      ('trg_import_findings_immutable_update'),
      ('trg_import_resolutions_immutable_delete'),
      ('trg_import_resolutions_immutable_update'),
      ('trg_import_rows_immutable_delete'),
      ('trg_import_rows_immutable_update'),
      ('trg_cycle_count_items_no_delete'),
      ('trg_cycle_count_items_no_update'),
      ('trg_cycle_count_no_delete'),
      ('trg_cycle_count_no_update'),
      ('trg_reconciliation_no_delete'),
      ('trg_reconciliation_no_update'),
      ('trg_inventory_session_immutable_fields'),
      ('trg_inventory_session_no_delete'),
      ('trg_snapshot_items_immutable_delete'),
      ('trg_snapshot_items_immutable_update'),
      ('trg_snapshot_immutable_fields'),
      ('trg_snapshot_no_delete'),
      ('trg_legacy_links_immutable_delete'),
      ('trg_legacy_links_immutable_update'),
      ('trg_legacy_events_immutable_delete'),
      ('trg_legacy_events_immutable_update'),
      ('trg_legacy_warnings_immutable_delete'),
      ('trg_legacy_warnings_immutable_update'),
      ('trg_legacy_source_files_immutable_delete'),
      ('trg_legacy_source_files_immutable_update'),
      ('trg_users_no_delete'),
      ('trg_late_evidence_no_delete'),
      ('trg_late_evidence_no_update'),
      ('trg_ledger_line_no_delete'),
      ('trg_ledger_line_no_update'),
      ('trg_ledger_transaction_no_delete'),
      ('trg_ledger_transaction_no_update')
), missing(name) AS (
    SELECT required.name
    FROM required
    LEFT JOIN sqlite_master m
      ON m.type = 'trigger' AND m.name = required.name
    WHERE m.name IS NULL
)
SELECT 'immutability_trigger_coverage' AS check_name,
       CASE WHEN count(*) = 0 THEN 'PASS'
            ELSE 'FAIL:' || group_concat(name)
       END AS result
FROM missing;

WITH required(name) AS (
    VALUES
      ('trg_reference_parent_domain_insert'),
      ('trg_reference_parent_domain_update'),
      ('trg_reference_parent_acyclic_insert'),
      ('trg_reference_parent_acyclic_update'),
      ('trg_location_parent_same_warehouse_insert'),
      ('trg_location_parent_same_warehouse_update'),
      ('trg_location_parent_acyclic_insert'),
      ('trg_location_parent_acyclic_update')
), missing(name) AS (
    SELECT required.name
    FROM required
    LEFT JOIN sqlite_master m
      ON m.type = 'trigger' AND m.name = required.name
    WHERE m.name IS NULL
)
SELECT 'hierarchy_trigger_coverage' AS check_name,
       CASE WHEN count(*) = 0 THEN 'PASS'
            ELSE 'FAIL:' || group_concat(name)
       END AS result
FROM missing;
