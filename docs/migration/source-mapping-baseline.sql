-- READ-ONLY baseline and referential proof for significant ODE 0.12 sources.
PRAGMA query_only = ON;

SELECT 'users' AS source_table, count(*) AS source_rows FROM users
UNION ALL SELECT 'reference_domains_v2', count(*) FROM reference_domains_v2
UNION ALL SELECT 'reference_values_v2', count(*) FROM reference_values_v2
UNION ALL SELECT 'reference_aliases_v2', count(*) FROM reference_aliases_v2
UNION ALL SELECT 'reference_values', count(*) FROM reference_values
UNION ALL SELECT 'catalog_items_v2', count(*) FROM catalog_items_v2
UNION ALL SELECT 'migration_batches', count(*) FROM migration_batches
UNION ALL SELECT 'migration_source_files', count(*) FROM migration_source_files
UNION ALL SELECT 'migration_staging_rows', count(*) FROM migration_staging_rows
UNION ALL SELECT 'migration_serial_cells', count(*) FROM migration_serial_cells
UNION ALL SELECT 'migration_full_reconciliation', count(*) FROM migration_full_reconciliation
UNION ALL SELECT 'migration_full_warnings', count(*) FROM migration_full_warnings
UNION ALL SELECT 'migration_full_identities', count(*) FROM migration_full_identities
UNION ALL SELECT 'migration_full_quarantine', count(*) FROM migration_full_quarantine
UNION ALL SELECT 'migration_full_marker', count(*) FROM migration_full_marker
UNION ALL SELECT 'stock_receipts', count(*) FROM stock_receipts
UNION ALL SELECT 'stock_issues', count(*) FROM stock_issues
UNION ALL SELECT 'stock_issue_allocations', count(*) FROM stock_issue_allocations
UNION ALL SELECT 'audit_log', count(*) FROM audit_log
ORDER BY source_table;

-- All results below must be zero unless a query explicitly returns a status
-- distribution for approval.
SELECT 'orphan_reference_value_domain' AS check_name, count(*) AS violations
FROM reference_values_v2 v
LEFT JOIN reference_domains_v2 d ON d.id = v.domain_id
WHERE d.id IS NULL
UNION ALL
SELECT 'orphan_alias_domain', count(*)
FROM reference_aliases_v2 a
LEFT JOIN reference_domains_v2 d ON d.id = a.domain_id
WHERE d.id IS NULL
UNION ALL
SELECT 'orphan_alias_canonical', count(*)
FROM reference_aliases_v2 a
LEFT JOIN reference_values_v2 v ON v.id = a.canonical_id
WHERE a.canonical_id IS NOT NULL AND v.id IS NULL
UNION ALL
SELECT 'orphan_catalog_reference', count(*)
FROM catalog_items_v2 c
LEFT JOIN reference_values_v2 v ON v.id = c.reference_value_id
WHERE c.reference_value_id IS NOT NULL AND v.id IS NULL
UNION ALL
SELECT 'orphan_staging_source', count(*)
FROM migration_staging_rows s
LEFT JOIN migration_source_files f ON f.id = s.source_file_id
WHERE f.id IS NULL
UNION ALL
SELECT 'orphan_serial_cell', count(*)
FROM migration_serial_cells c
LEFT JOIN migration_staging_rows s ON s.id = c.staging_row_id
WHERE s.id IS NULL
UNION ALL
SELECT 'orphan_reconciliation', count(*)
FROM migration_full_reconciliation r
LEFT JOIN migration_staging_rows s ON s.id = r.staging_row_id
WHERE s.id IS NULL
UNION ALL
SELECT 'duplicate_reconciliation_source', count(*)
FROM (
    SELECT staging_row_id FROM migration_full_reconciliation
    GROUP BY staging_row_id HAVING count(*) > 1
)
UNION ALL
SELECT 'orphan_warning', count(*)
FROM migration_full_warnings w
LEFT JOIN migration_full_reconciliation r ON r.id = w.reconciliation_id
WHERE r.id IS NULL
UNION ALL
SELECT 'orphan_quarantine', count(*)
FROM migration_full_quarantine q
LEFT JOIN migration_full_reconciliation r ON r.id = q.reconciliation_id
WHERE r.id IS NULL
UNION ALL
SELECT 'orphan_issue_allocation_issue', count(*)
FROM stock_issue_allocations a
LEFT JOIN stock_issues i ON i.id = a.issue_id
WHERE i.id IS NULL
UNION ALL
SELECT 'orphan_issue_allocation_receipt', count(*)
FROM stock_issue_allocations a
LEFT JOIN stock_receipts r ON r.id = a.receipt_id
WHERE r.id IS NULL;

SELECT 'reference_values_v2' AS source, approval_status AS status, count(*) AS rows
FROM reference_values_v2 GROUP BY approval_status
UNION ALL
SELECT 'reference_aliases_v2', resolution_status, count(*)
FROM reference_aliases_v2 GROUP BY resolution_status
UNION ALL
SELECT 'catalog_items_v2', resolution_status, count(*)
FROM catalog_items_v2 GROUP BY resolution_status
ORDER BY source, status;
