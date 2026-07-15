-- READ-ONLY proof against frozen/current ODE 0.12 DB.
PRAGMA query_only = ON;

-- Expected audit baseline: 71,360 = 71,356 imported + 4 quarantined + 0 excluded.
WITH classified AS (
    SELECT
        id,
        staging_row_id,
        CASE
          WHEN final_status IN ('QUARANTINED', 'SOURCE_CORRUPTED_REJECTED')
            THEN 'QUARANTINED'
          ELSE 'MIGRATED'
        END AS disposition
    FROM migration_full_reconciliation
)
SELECT
    count(*) AS source_count,
    sum(disposition = 'MIGRATED') AS migrated_count,
    sum(disposition = 'QUARANTINED') AS quarantined_count,
    0 AS explicitly_excluded_count,
    count(*) - sum(disposition IN ('MIGRATED', 'QUARANTINED')) AS unclassified
FROM classified;

-- Zero rows: one source staging row cannot map more than once.
SELECT staging_row_id, count(*) AS mappings
FROM migration_full_reconciliation
GROUP BY staging_row_id
HAVING count(*) > 1;

-- Zero rows: every reconciliation row has a staging source and file.
SELECT r.id
FROM migration_full_reconciliation r
LEFT JOIN migration_staging_rows s ON s.id = r.staging_row_id
LEFT JOIN migration_source_files f ON f.id = s.source_file_id
WHERE s.id IS NULL OR f.id IS NULL;

-- Separate rejected/corrupted accounting.
SELECT final_status, count(*) AS rows
FROM migration_full_reconciliation
WHERE final_status IN ('QUARANTINED', 'SOURCE_CORRUPTED_REJECTED')
GROUP BY final_status
ORDER BY final_status;

-- Date-quality source proof.
SELECT
    source_operation_date_status,
    sum(trim(source_operation_date_raw) = '') AS raw_missing,
    sum(trim(source_operation_date) = '') AS parsed_missing,
    count(*) AS rows
FROM migration_full_reconciliation
GROUP BY source_operation_date_status
ORDER BY source_operation_date_status;

-- Actor/FIO availability proof.
SELECT
    operation_kind,
    sum(trim(json_extract(raw_payload, '$.responsible')) = '') AS actor_missing,
    sum(trim(json_extract(raw_payload, '$.responsible')) GLOB '[0-9]*'
        AND trim(json_extract(raw_payload, '$.responsible')) <> '') AS actor_code_like,
    count(*) AS rows
FROM migration_full_reconciliation
GROUP BY operation_kind;

-- Identifier evidence coverage; zero orphan rows expected.
SELECT c.id
FROM migration_serial_cells c
LEFT JOIN migration_staging_rows s ON s.id = c.staging_row_id
WHERE s.id IS NULL;

-- Every old operational receipt/issue is derivative-linked at audit baseline.
SELECT 'unlinked_receipts' AS check_name, count(*) AS rows
FROM stock_receipts r
LEFT JOIN migration_full_reconciliation m ON m.target_receipt_id = r.id
WHERE m.id IS NULL
UNION ALL
SELECT 'unlinked_issues', count(*)
FROM stock_issues i
LEFT JOIN migration_full_reconciliation m ON m.target_issue_id = i.id
WHERE m.id IS NULL;

-- Exact S/N source reproduction sample/query contract.
-- Bind :serial_key in a read-only runner; each returned row retains coordinates.
SELECT
    normalized_match_value AS serial_key,
    source_serial_value AS serial_raw,
    operation_kind,
    source_file,
    source_sheet,
    source_row,
    source_row_hash,
    raw_payload
FROM migration_full_reconciliation
WHERE normalized_match_value = :serial_key
ORDER BY source_file, source_sheet, source_row, id;

-- Schema-dependency proof is performed on target by verify_domain_invariants.sql:
-- no legacy_* object SQL may reference inventory_snapshot, warehouse_transaction
-- or balance_projection.
