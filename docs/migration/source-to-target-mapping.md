# Source-to-target mapping

Статус: **APPROVED — ODE 0.13 architecture baseline**
Source: frozen ODE 0.12 DB. Counts ниже — audit baseline 2026-07-15; freeze
manifest authoritative.

Field-level mapping, quarantine and idempotency rules:
[source-to-target-field-mapping.md](source-to-target-field-mapping.md).
Executable read-only count proof:
[legacy-history-count-proof.sql](legacy-history-count-proof.sql).
All-source baseline/orphan proof:
[source-mapping-baseline.sql](source-mapping-baseline.sql).

| Source / current rows | Target | Transform | Disposition/reason | Validation | Expected / idempotency |
|---|---|---|---|---|---|
| users / 1 | users + user_roles | Normalize login/email/display; map admin→admin, viewer→auditor, engineer→operator only manual; known default hash not copied | KEEP selected; no shared write account | Unique login/email, role decision, forced activation/change | 0..1 active identities; source DB SHA+user ID |
| reference_domains_v2 / 20 | reference_domains | Map domain_key/code and policy | KEEP | All referenced domain IDs resolve | 20 reviewed; source SHA+domain ID |
| reference_values_v2 / 939 | reference_values | APPROVED 499 eligible; CANDIDATE 433 review; REJECTED 7 retained in mapping evidence only | KEEP approved, QUARANTINE candidate, ARCHIVE rejected | Scope/key uniqueness; provenance | Approved target count = accepted mapping rows; source SHA+value ID |
| reference_aliases_v2 / 927 | reference_aliases | APPROVED 2 and AUTO_APPROVED 517 require rule review; PENDING 408 stays pending | KEEP/REVIEW; never implicit canonical | Alias target/domain/scope; source coordinates | One target per accepted source ID |
| reference_values / 894 | mapping evidence only | Compare flat value to approved v2; no direct canonical creation | ARCHIVE, because second source of truth | Coverage report flat→v2/unresolved | 894 classified; source SHA+flat ID |
| catalog_items_v2 / 358 PENDING | catalog_items pending/quarantine | Preserve raw canonical name, vendor/model/PN and provenance; admin approval required | KEEP as PENDING, none automatically APPROVED | Vendor-scoped PN conflicts, UOM/kind | 358 classified; source SHA+catalog ID |
| migration_batches / 1 | import_commits(LEGACY_MIGRATION) | Manifest hashes/build metadata | KEEP batch-level provenance | Source manifest hash | 1 committed migration import |
| migration_source_files / 5 | legacy_source_files | Copy immutable file metadata; verify vault object hash | KEEP | File exists, size/SHA match | 5 or blocking missing source; source SHA+file ID |
| migration_staging_rows / 71 360 | import_row_links / legacy evidence | Link coordinate/hash/raw payload to event; reconciliation authoritative for transform | KEEP provenance, not operational stock | Unique source coordinate and row hash | 71 360 linked exactly once |
| migration_full_reconciliation / 71 360 | legacy_history_events | Field mapping in legacy-history-mapping | KEEP archive only | One row→one event, quality checks | Exactly 71 360 including quarantine; source row hash |
| migration_serial_cells / 91 717 | legacy event raw evidence / import_row_links | Preserve identity cell metadata in raw payload or evidence object | KEEP unique evidence | staging/coordinate/hash coverage | All rows linked to event or explicit orphan quarantine |
| migration_full_warnings / 129 813 | legacy_history_warnings | Map severity/code/message by reconciliation ID | KEEP | FK event, unique event/severity/code | Count after exact duplicate collapse equals source unique key |
| migration_full_identities / 50 000 | migration cross-check only | Validate identity group and serial preservation; do not create Equipment | ARCHIVE: derived from legacy, not physical baseline | Every target identity reference resolved | 50 000 classified |
| stock_receipts / 50 000 | none directly; legacy event enrichment only | Cross-check target_receipt_id and raw payload fields | DO NOT COPY as ledger/snapshot | All 50 000 referenced by reconciliation; no unlinked rows | 0 warehouse_transactions |
| stock_issues / 18 798 | none directly; legacy event enrichment only | Cross-check target_issue_id | DO NOT COPY as ledger/snapshot | All 18 798 referenced; no unlinked rows | 0 warehouse_transactions |
| stock_issue_allocations / 18 798 | warning/evidence only if relationship adds unique fact | Validate issue→receipt relation and quantity, preserve in raw evidence | DO NOT COPY as ledger/projection | 1 allocation per current issue baseline; quantities report | 0 warehouse_transaction_lines |
| audit_log / 146 641 | selective audit_events or archive only | MIGRATION_* summarized batch-level; LOGIN/security rows may map if actor/time valid; full old log remains old DB | NO bulk copy; avoids duplicated provenance | Action classification totals =146 641 | Target count = explicit allowlist; source SHA+audit ID |
| migration_full_marker / 1 | import commit manifest | Preserve build keys/hashes/status as source fact, not runtime state | KEEP evidence | Marker hashes vs files/DB | 1 manifest object |
| migration_full_cleanliness / 64 | migration verification report | Preserve report artifact, not tables | ARCHIVE | Re-run equivalent gates | 64 accounted |
| migration_full_performance / 10 | old benchmark artifact | Preserve report with machine unknown; no target rows | ARCHIVE | Report hash | 10 accounted |
| migration_full_quarantine / 4 | legacy events status QUARANTINED + warnings | Preserve raw/source reason | KEEP archive quarantine | All 4 tied to source rows | 4 classified; no drop |
| migration_validation_results / 973 | migration evidence artifact | Map blocking results to new verification report | ARCHIVE | Result classification | 973 accounted |
| equipment / 0; operations / 0 | none | No data | DROP empty schema after cutover | Count remains zero in freeze | 0 |
| reports/deliveries/work logs / 0 baseline | none unless freeze delta | Recount at freeze; any nonzero becomes explicit mapping decision | DROP empty schema | Freeze count | 0 expected, otherwise BLOCKER |

## Row-count accounting

Каждая source table получает итоговую category:

    target authoritative rows
    + target quarantine/evidence rows
    + archive-only rows
    = frozen source rows

Ни одна row не может иметь category UNKNOWN. Mapping runner пишет per-row
decision code и deterministic idempotency key.

## Runtime delta rule

На audit baseline unlinked receipts/issues = 0. Freeze снова проверяет. Если
появятся unlinked rows после historical build, они не становятся new ledger.
Они получают LegacyHistoryEvent source_type=ODE_0_12_RUNTIME с source_file
виртуальным DB snapshot manifest, raw DB row payload и date/actor quality.

## Forbidden mappings

- stock_receipts → warehouse RECEIPT;
- stock_issues → warehouse ISSUE;
- allocation sums → opening balance;
- migration identity → Equipment without physical inventory;
- pending reference/catalog → APPROVED;
- audit migration row → duplicate source provenance;
- local-time text → exact UTC without timezone proof.
