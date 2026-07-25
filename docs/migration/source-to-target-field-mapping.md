# ODE 0.12 → 0.13 field-level mapping

Статус: **APPROVED — ODE 0.13 architecture baseline**

Этот документ дополняет
[source-to-target-mapping.md](source-to-target-mapping.md). Frozen source DB
SHA является частью каждого idempotency key.

## Control columns for every source table

| Source table | Source row identity | Target/disposition | Provenance | Validation/quarantine | Idempotency/count/reconciliation |
|---|---|---|---|---|---|
| users | users.id | users/user_roles; KEEP_REVIEWED | DB SHA + source ID | shared/default/unsupported hash → quarantine/disabled | sha:users:id; target 0..source; reviewed decision report |
| reference_domains_v2 | id/domain_key | reference_domains; KEEP | DB SHA+ID+source | duplicate code/policy conflict | sha:domain:id; every row classified |
| reference_values_v2 | id | reference_values; KEEP/QUARANTINE/ARCHIVE | source/status/timestamps | candidate/rejected, scope collision | sha:refv2:id; approved target count |
| reference_aliases_v2 | id | reference_aliases; KEEP/REVIEW | source file/sheet/status | invalid target/scope, AUTO_APPROVED review | sha:alias:id; every row classified |
| reference_values | id | no direct target; ARCHIVE_MAPPING_EVIDENCE | flat kind/name | unresolved flat→v2 | sha:flatref:id; 894 decisions |
| catalog_items_v2 | id | catalog_items PENDING; KEEP_REVIEW | source/rule/confidence | all current 358 pending | sha:catalog:id; 358 decisions |
| migration_batches | id/batch_key | import_commits LEGACY_MIGRATION | manifest/stage/build | invalid manifest hash | sha:batch:id; expected 1 |
| migration_source_files | id | legacy_source_files | file name/SHA/size | missing/hash/size mismatch blocks | sha:sourcefile:id; expected 5 |
| migration_staging_rows | id; unique source coordinate | import_row_links/raw evidence | raw+normalized payload/hash | orphan source/coordinate/hash mismatch | sha:staging:id; expected 71,360 |
| migration_serial_cells | id; staging+role+coordinate | raw identifier evidence in row payload | raw XML/type/format/hash | orphan/contradictory preservation | sha:serialcell:id; expected 91,717 classified |
| migration_full_reconciliation | staging_row_id UNIQUE | legacy_history_events | source coordinate/hash/raw | corrupted/quarantined preserved | sha:reconciliation:staging_id; exactly 71,360 |
| migration_full_warnings | reconciliation+kind+code | legacy_history_warnings | exact severity/code/message | orphan warning | sha:warning:source unique key; source uniques |
| migration_full_identities | id | no Equipment; ARCHIVE_CROSSCHECK | grouping/preservation | mismatch becomes warning | sha:legacyidentity:id; 50,000 classified |
| migration_full_quarantine | source PK | event status QUARANTINED/warning | raw reason | always quarantine | sha:quarantine:id; expected 4 baseline |
| migration_full_marker | id=1 | legacy import manifest evidence | all hashes/build key | marker/file mismatch blocks | sha:marker:1; expected 1 |
| stock_receipts | id | DO_NOT_MIGRATE_TO_LEDGER; validation/enrichment | reconciliation.target_receipt_id | unlinked row → ODE_0_12_RUNTIME history quarantine/review | sha:receipt:id; 50,000 linked baseline |
| stock_issues | id | DO_NOT_MIGRATE_TO_LEDGER; validation/enrichment | reconciliation.target_issue_id | unlinked row rule as above | sha:issue:id; 18,798 linked baseline |
| stock_issue_allocations | id | DO_NOT_MIGRATE_TO_LEDGER; relationship evidence | issue/receipt/quantity raw | orphan/nonpositive/mismatch warning | sha:allocation:id; 18,798 classified |
| audit_log | id | selective audit_events or ARCHIVE | action/time/author/details | MIGRATION_* summarized, invalid actor/time archive | sha:audit:id; all 146,641 classified |
| equipment/operations | id | DROP_EMPTY_SCHEMA | frozen counts | nonzero count is blocker/new mapping | expected 0 |
| empty reports/deliveries/work tables | PK | DROP_EMPTY_SCHEMA | frozen counts | nonzero count is blocker | expected 0 baseline |

Executable source counts and orphan checks:
[source-mapping-baseline.sql](source-mapping-baseline.sql).

## Significant-field completeness

Every source column is either transformed, retained as provenance/evidence, or
explicitly excluded from authoritative data. Grouping below is exhaustive for
the frozen schema; detailed legacy target fields remain normative in
[legacy-history-mapping.md](legacy-history-mapping.md).

| Source table | Significant source columns | Target/use |
|---|---|---|
| users | id; first_name, last_name, position; email; password_hash; role; must_change_password, is_active; created_at | decision key; display/profile evidence; login/email keys; reviewed Argon2id or discard; user_roles; force change/status; timestamp evidence |
| reference_domains_v2 | id, domain_key, display_name, description, active, source, created_at, updated_at | reference_domains plus provenance; description remains mapping evidence if target has no field |
| reference_values_v2 | id, domain_id, canonical_value, display_name, normalized_key, scope_key, active, approval_status, source, created_at, updated_at | reference_values; key recomputed; source/times preserved |
| reference_aliases_v2 | id, domain_id, source_value, normalized_source_key, canonical_id, source_file, source_sheet, usage_count, confidence, resolution_status, approved_by, approved_at, notes | reference_aliases plus decision evidence; usage/confidence/notes remain provenance JSON/report, not authority |
| reference_values | id, kind, name, is_active, created_at | flat→v2 mapping evidence only; no canonical target row directly |
| catalog_items_v2 | id, reference_value_id, canonical_item_name; object/category/equipment/component IDs; vendor/model IDs; part_number; primary_characteristic; normalization_rule, confidence, requires_manual_review, resolution_status, source, timestamps | pending catalog item/reference FKs after review; display/PN; classification refs; rule/confidence/review/source/times as provenance |
| migration_batches | id, batch_key, stage, status, source_manifest_sha256, timestamps, notes | LEGACY_MIGRATION import commit manifest/evidence |
| migration_source_files | id, batch_id, source_path, file_name, sha256, size_bytes, immutable, created_at | source FK; path only resolves vault object and is not copied; name/hash/size; immutability/time evidence |
| migration_staging_rows | id, batch/source/coordinate/hash/kind; raw_payload, normalized_payload; source/normalized serial and preservation; all proposed object/catalog/reference fields; warnings/conflicts/resolution/decision; target_entity_id; created_at | import_row_links + raw/normalized legacy evidence; proposals/decisions are migration interpretation, never Equipment/balance authority |
| migration_serial_cells | id, staging_row_id, role and source coordinate; Excel type/format/XML/display/raw/key; preservation/warning/hash/rule/confidence/manual-review | identifier evidence JSON linked to one source row; all raw strings retained |
| migration_full_reconciliation | id, staging_row_id, operation/source coordinate/hash; serial/raw/XML/preservation/confidence/authority/review/status; target old IDs; item/inventory/classification/vendor/model/PN/quantity/date/location; target display evidence; warnings/conflicts/non-application reason; raw/normalized payload; created_at | exactly one LegacyHistoryEvent + warnings/provenance; old target IDs validate only; no ledger/snapshot/equipment creation |
| migration_full_warnings | id, reconciliation_id, identity_id, warning_kind, code, message, created_at | legacy_history_warnings; identity_id is old cross-check evidence, not Equipment FK |
| migration_full_identities | all identity/display/preservation/confidence/opening/target/count/item/classification/rule/warning/conflict/timestamp columns | archive cross-check report only; explicitly no Equipment or opening balance |
| migration_full_quarantine | id, reconciliation_id, reason_code, raw_token, source coordinate, affects_balance, resolution_status, notes, created_at | event QUARANTINED + warning; `affects_balance` retained only as rejected legacy claim |
| migration_full_marker | marker/stage/status/review flags; all source/production hashes; all count/status/hash summaries; build key/timestamps | immutable import manifest and verification report, never runtime app_state |
| stock_receipts | id; dates/responsible/order/request/PLU/item/project; S/N/inventory/supplier/vendor/model/location/object/DC/equipment/component/cable/UOM; quantity; legacy_equipment_id/opening flag/created_at | reconciliation validation and raw event enrichment only; REAL quantity preserved as text/evidence, no arithmetic |
| stock_issues | id; date/responsible/task; target/source identifiers/item/cable; quantity/comment/created_at | reconciliation validation and raw event enrichment only; no ledger |
| stock_issue_allocations | id, issue_id, receipt_id, quantity | old derivation evidence; FK/count/quantity report only |
| audit_log | id, event_date, action, entity_type, entity_id, details, author | allowlisted security/batch audit or immutable archive; author never auto-resolves User |

## users fields

| Source | Target | Transform |
|---|---|---|
| id | migration decision key, not target PK | New target ID/public UUID |
| first_name + last_name | users.display_name | Preserve exact components in mapping evidence; reviewed display |
| email | users.email_raw/email_key/login_key | Raw + conservative case-fold key; blank/duplicate blocks activation |
| password_hash | users.password_hash or discard | Copy only supported, non-default reviewed hash; otherwise INVITED/DISABLED |
| role | user_roles | admin→admin; viewer→auditor; engineer→operator only explicit review |
| must_change_password | users.must_change_password | Always 1 for migrated account |
| is_active | users.status | false→DISABLED; true→INVITED/ACTIVE after credential review |
| created_at | users.created_at_us | Exact only with timezone rule; otherwise migration timestamp + raw evidence |

No user row is created for arbitrary legacy performed_by text.

## references/catalog fields

| Source | Target | Transform |
|---|---|---|
| domain_key/display/description/active | reference_domains code/display/status | Policy assigned from approved domain registry |
| canonical_value/display_name/normalized_key | reference_values | Recompute key and compare; mismatch finding |
| scope_key | reference_values.scope_key | Empty→GLOBAL only for globally scoped domain |
| approval_status | status | APPROVED→APPROVED; CANDIDATE→PENDING; REJECTED→REJECTED |
| alias source_value/normalized_source_key | alias source_raw/source_key | Raw preserved, key recomputed |
| alias source_file/sheet | source hash/sheet evidence | Resolve file hash; missing source quarantine |
| alias resolution_status | alias status | AUTO_APPROVED requires re-review; never silently approved |
| catalog vendor/model/PN | catalog fields | Vendor-scoped PN; no Huawei/xFusion or HP/HPE semantic merge |
| normalization_rule/confidence/source | source_ref/mapping evidence | Preserved for review, not executable trust |

Flat reference_values never wins against approved v2 automatically.

## source/provenance fields

| Source | Target |
|---|---|
| migration_source_files.file_name | legacy_source_files.file_name |
| source_path | Never target path; resolve to immutable object and store opaque source_object_key |
| sha256/size_bytes | legacy_source_files.sha256/size_bytes |
| staging source_file/sheet/row | import_row_links coordinate |
| source_row_hash | import_row_links.source_row_sha256 and legacy event row hash |
| raw_payload | import_row_links.raw_payload_json and legacy event raw_payload_json |
| normalized_payload | legacy event normalized_payload_json as interpretation only |
| migration_serial_cells raw_xml/type/format/display/preservation | embedded versioned identifier evidence JSON; raw values unchanged |

## reconciliation → legacy event fields

Нормативная field mapping находится в
[legacy-history-mapping.md](legacy-history-mapping.md). Ключевые правила:

- operation_kind → event_type;
- raw_payload.responsible → performed_by_name_raw/personnel_code_raw/quality;
- source_operation_date_raw/status → date_raw/date_quality;
- source_serial_value → serial_raw;
- conservative recomputation → serial_key;
- source_file/sheet/row/hash → exact provenance;
- raw comments/vendor/model/PN/item/location/quantity preserved;
- QUARANTINED и SOURCE_CORRUPTED_REJECTED → record_status QUARANTINED;
- остальные source rows → IMPORTED, включая exact duplicate as historical fact.

## stock tables

| Source fields | Use |
|---|---|
| receipt id/date/responsible/item/SN/inventory/vendor/model/shelf/quantity | Cross-check linked reconciliation/raw payload; never target ledger |
| issue id/date/responsible/target/source/comment/quantity | Cross-check linked reconciliation; never target ledger |
| allocation issue_id/receipt_id/quantity | Evidence of old derivation only; never balance/projection |

Reconciliation query обязана доказать every receipt/issue linked or classify a
post-build runtime row separately. Target warehouse transaction count после
legacy migration = 0.

## audit fields

| Source action | Target |
|---|---|
| MIGRATION_* | One batch-level LEGACY_MIGRATION_COMPLETED audit + archive old rows |
| LOGIN | Optional security audit only if timestamp/actor reliable; no session recreation |
| cleanup/stabilization/test removal | Batch migration evidence or archive |
| unknown action | ARCHIVE pending explicit allowlist |

Old details/author не получают automatic personal user FK. Full log remains in
immutable old DB.

## Count equation

For each source table:

    source_count =
      migrated_count
      + quarantined_count
      + explicitly_excluded_count
      + archive_only_count

UNKNOWN must be zero. Re-run uses same deterministic keys and must produce the
same mapping checksum.
