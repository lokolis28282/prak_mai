# Логическая модель данных ODE 0.13

Статус: **APPROVED — DDL не применять напрямую к production DB**

## Общие соглашения

| Соглашение | Решение |
|---|---|
| Internal key | INTEGER PRIMARY KEY; authoritative rows не удаляются и ID не переиспользуются |
| Public key | public_id TEXT UNIQUE, canonical UUIDv7 |
| Timestamp | INTEGER UTC microseconds since Unix epoch; API возвращает RFC 3339 |
| Date quality | EXACT, MISSING, ESTIMATED, CORRUPTED |
| Hash | BLOB длиной 32 bytes SHA-256; API/manifest — lower-case hex |
| Boolean | INTEGER NOT NULL CHECK value IN (0,1) |
| JSON | TEXT NOT NULL CHECK json_valid(value) |
| Quantity | INTEGER quantity_minor + UOM scale |
| Delete rule | RESTRICT; CASCADE только для ephemeral session/security children |
| Text | Raw и normalized поля разделены; raw никогда не нормализуется in-place |
| Retention | PERMANENT означает срок жизни системы и migration archive |

Все FK индексируются со стороны child, если они участвуют в join. Все
authoritative timestamps, actor snapshots и hashes immutable.
Любая operational stock row с парой warehouse/location обязана ссылаться на
location того же warehouse; это проверяют именованные cross-table triggers во
всех snapshot/cycle/reconciliation/ledger/projection paths.

Для компактных объявлений ниже действует строгая нотация: все поля NOT NULL и
без DEFAULT, если прямо не написано NULL/nullable/default. Суффиксы имеют
фиксированный тип: внутренние *_id — INTEGER; public/session/correlation/object
keys — TEXT; *_at_us, *_sequence, *_count, *_bytes, scale и quantity — INTEGER;
*_sha256, *_checksum и token/hash fields — BLOB; *_json — TEXT с json_valid;
boolean/is_*/active flags — INTEGER CHECK IN (0,1); enum/code/raw/key/name/path/
reason/status fields — TEXT. Любое исключение указывается рядом.

## System

### schema_migrations — owner infrastructure, retention PERMANENT

| Column | Type/null/default | Key/constraint |
|---|---|---|
| version | INTEGER NOT NULL | PK; values 1..8 for this review set |
| name | TEXT NOT NULL | UNIQUE |
| checksum | BLOB NOT NULL | length=32 |
| applied_at_us | INTEGER NOT NULL | >0 |
| applied_by | TEXT NOT NULL | non-empty personal/release actor |
| application_version | TEXT NOT NULL | non-empty invoking build version |

Индекс: unique(name). Миграция применяется только explicit CLI/release step.

### app_state — owner bootstrap/application, retention singleton

| Column | Type/null/default | Key/constraint |
|---|---|---|
| singleton_id | INTEGER NOT NULL DEFAULT 1 | PK, CHECK=1 |
| balance_state | TEXT NOT NULL | NOT_INITIALIZED, ACTIVE, INCONSISTENT |
| active_snapshot_id | INTEGER NULL | FK inventory_snapshots |
| active_projection_version_id | INTEGER NULL | FK balance_projection_versions |
| last_ledger_sequence | INTEGER NOT NULL DEFAULT 0 | >=0 |
| state_version | INTEGER NOT NULL DEFAULT 1 | optimistic concurrency |
| updated_at_us | INTEGER NOT NULL | >0 |

Checks: NOT_INITIALIZED требует null snapshot/projection; ACTIVE требует оба ID.

## Users and security

### users — owner users, retention PERMANENT

| Column | Type/null/default | Key/constraint |
|---|---|---|
| user_id | INTEGER NOT NULL | PK |
| public_id | TEXT NOT NULL | UNIQUE UUIDv7 |
| login_key | TEXT NOT NULL | UNIQUE, normalized |
| email_raw | TEXT NULL | |
| email_key | TEXT NULL | partial UNIQUE |
| display_name | TEXT NOT NULL | non-empty |
| password_hash | TEXT NOT NULL | Argon2id encoded-prefix format only; cryptographic verification is application-level |
| status | TEXT NOT NULL | INVITED, ACTIVE, LOCKED, DISABLED |
| must_change_password | INTEGER NOT NULL DEFAULT 1 | boolean |
| credential_version | INTEGER NOT NULL DEFAULT 1 | >=1 |
| created_at_us | INTEGER NOT NULL | immutable |
| updated_at_us | INTEGER NOT NULL | |

Пароль и login не переносятся автоматически из известной default identity.

### roles — owner users/security, retention PERMANENT

role_id PK, code TEXT UNIQUE NOT NULL, display_name TEXT NOT NULL, active boolean,
created_at_us. Initial immutable codes: operator, admin, auditor.

### permissions — owner security, retention PERMANENT

permission_code TEXT PK, display_name TEXT, risk_level TEXT CHECK
READ/STANDARD/SENSITIVE, active boolean, created_at_us. Permission codes
versioned application contract; удаление после использования запрещено.

### role_permissions — owner security, retention PERMANENT

role_id FK roles, permission_code TEXT FK permissions, granted_at_us,
granted_by_user_id nullable FK users. PK(role_id, permission_code). Initial rows
точно совпадают с permission matrix security.md.

### user_roles — owner users, retention PERMANENT

user_role_id PK, user_id FK users, role_id FK roles,
assigned_by_user_id nullable FK users, assigned_at_us, revoked_at_us NULL.
Partial unique active assignment on (user_id, role_id) WHERE revoked_at_us IS
NULL.

### sessions — owner security, retention 90 days after expiry/revocation

session_id TEXT PK UUIDv7, token_hash BLOB UNIQUE length=32, user_id FK users,
credential_version INTEGER, csrf_secret_hash BLOB, created_at_us,
last_seen_at_us, idle_expires_at_us, absolute_expires_at_us,
revoked_at_us NULL, revoke_reason TEXT NULL, ip_hash BLOB NULL,
user_agent_family TEXT NULL. Indexes: user_id/revoked_at, expiry.

## References and catalog

### reference_domains — owner references, retention PERMANENT

domain_id PK, code TEXT UNIQUE, display_name, normalization_policy TEXT,
scope_policy TEXT, status CHECK ACTIVE/INACTIVE, created/updated timestamps.

### reference_values — owner references, retention PERMANENT

value_id PK, public_id UNIQUE, domain_id FK, code TEXT, display_name TEXT,
normalized_key TEXT, scope_key TEXT, scope_value_id nullable self-FK,
parent_value_id nullable
self-FK, status CHECK PENDING/APPROVED/REJECTED/INACTIVE/MERGED,
merged_into_value_id nullable self-FK, source_type, source_ref, created_by_user_id
nullable FK, created_at_us, updated_at_us. UNIQUE(domain_id, scope_key,
normalized_key). Indexes: parent, status, merged target.

Parent graph must be acyclic; parent must share domain. Cross-domain scope uses
scope_value_id, not parent_value_id. Both parent invariants are DB-enforced.
Merged target must share domain and cannot be merged/rejected.

### reference_aliases — owner references, retention PERMANENT

alias_id PK, domain_id FK, source_raw TEXT, source_key TEXT, scope_key TEXT,
canonical_value_id nullable FK, status CHECK
PENDING/APPROVED/REJECTED/RETIRED, source_file_hash nullable BLOB,
source_sheet nullable TEXT, first_source_row nullable INTEGER,
decision_by_user_id nullable FK, decision_at_us nullable, reason nullable,
created_at_us. UNIQUE(domain_id, scope_key, source_key, source_file_hash).
Pending/rejected alias may have null canonical; approved requires it.

### uoms — owner references/catalog, retention PERMANENT

uom_id PK, code TEXT UNIQUE, display_name, dimension CHECK COUNT/LENGTH/MASS,
scale INTEGER CHECK 0..6, status ACTIVE/INACTIVE. Scale is immutable after use.

### catalog_items — owner references/catalog, retention PERMANENT

catalog_item_id PK, public_id UNIQUE, item_kind CHECK
SERIALIZED/BULK/CABLE/CONSUMABLE, vendor_value_id nullable FK,
vendor_scope_key TEXT, model_value_id
nullable FK, part_number_raw TEXT, part_number_key TEXT, equipment_type_value_id
nullable FK, component_type_value_id nullable FK, default_uom_id FK uoms,
display_name TEXT, status CHECK PENDING/APPROVED/INACTIVE/MERGED,
merged_into_catalog_item_id nullable self-FK, source_ref, created/updated
timestamps. Partial UNIQUE(vendor_scope_key, part_number_key) WHERE
part_number_key is non-empty and status in APPROVED/INACTIVE.

### warehouses — owner references/catalog, retention PERMANENT

warehouse_id PK, public_id UNIQUE, code TEXT UNIQUE, display_name, status
ACTIVE/INACTIVE, created/updated timestamps.

### warehouse_locations — owner references/catalog, retention PERMANENT

location_id PK, public_id UNIQUE, warehouse_id FK, code TEXT, display_name,
parent_location_id nullable self-FK, location_kind CHECK
ZONE/AISLE/RACK/SHELF/BIN/VIRTUAL, status ACTIVE/INACTIVE, created/updated
timestamps. UNIQUE(warehouse_id, code). Index(parent_location_id). Parent must
belong to same warehouse and hierarchy must be acyclic.

## Equipment

### equipment — owner equipment, retention PERMANENT

| Column | Type/null/default | Key/constraint |
|---|---|---|
| equipment_id | INTEGER NOT NULL | PK |
| public_id | TEXT NOT NULL | UNIQUE UUIDv7 |
| catalog_item_id | INTEGER NOT NULL | FK catalog_items |
| lifecycle_status | TEXT NOT NULL | ACTIVE, QUARANTINED, RETIRED, MERGED |
| identity_status | TEXT NOT NULL | VERIFIED, MISSING_SERIAL, CONFLICT, UNVERIFIED |
| merged_into_equipment_id | INTEGER NULL | self-FK |
| created_at_us | INTEGER NOT NULL | immutable |
| updated_at_us | INTEGER NOT NULL | |

MERGED требует survivor и не может быть survivor самого себя.

### equipment_identities — owner equipment, retention PERMANENT

identity_id PK, equipment_id FK, kind CHECK SERIAL_NUMBER/INVENTORY_NUMBER,
raw_value TEXT, normalized_key TEXT, scope_key TEXT, status CHECK
ACTIVE/RETIRED/CONFLICT/UNVERIFIED, valid_from_us, valid_to_us nullable,
source_type, source_ref, changed_by_user_id nullable FK, reason TEXT.

Indexes:

- exact lookup(kind, normalized_key, status);
- UNIQUE(kind, scope_key, normalized_key) WHERE status=ACTIVE;
- equipment_id/status.

Inventory Number uses scope_key=GLOBAL. Serial uses VENDOR:{value_id} or
UNSCOPED. Empty raw/key rows are not created.

### equipment_identity_aliases — owner equipment, retention PERMANENT

identity_alias_id PK, identity_id FK, alias_raw, alias_key, scope_key,
status CHECK ACTIVE/RETIRED, source_type, source_ref, created_at_us,
retired_at_us nullable. Partial UNIQUE(scope_key, alias_key) WHERE ACTIVE.
Alias lookup never replaces the canonical identity row and preserves every
previously observed raw spelling.

### equipment_merges — owner equipment, retention PERMANENT

merge_id PK, source_equipment_id FK, survivor_equipment_id FK,
effective_at_us, actor_user_id FK, actor_display_name, reason,
out_adjustment_sequence nullable FK warehouse_transactions,
in_adjustment_sequence nullable FK warehouse_transactions, correlation_id
TEXT UNIQUE. UNIQUE(source_equipment_id). Source != survivor. Исторические FK
не переписываются.

## Committed imports and inventory

### import_commits — owner imports, retention PERMANENT

import_commit_id PK, public_id UNIQUE, import_kind CHECK
FULL_INVENTORY/PARTIAL_INVENTORY/LEGACY_MIGRATION/REFERENCE_IMPORT,
source_object_key TEXT,
source_file_name TEXT, source_sha256 BLOB length=32, source_size_bytes INTEGER,
template_version, parser_version, schema_version, preview_digest BLOB,
manifest_json valid JSON, committed_by_user_id FK, actor_display_name,
committed_at_us, idempotency_key TEXT UNIQUE, correlation_id TEXT UNIQUE.

### import_row_links — owner imports, retention PERMANENT

row_link_id PK, import_commit_id FK, source_sheet TEXT, source_row_number
INTEGER >0, source_row_key TEXT, source_row_sha256 BLOB, raw_payload_json,
target_type TEXT, target_public_id TEXT, transform_version TEXT.
UNIQUE(import_commit_id, source_sheet, source_row_number, source_row_key).
Indexes: target_type/target_public_id, row hash.

### import_findings — owner imports, retention PERMANENT

import_finding_id PK, import_commit_id FK, row_link_id nullable FK, code TEXT,
severity TEXT CHECK INFO/WARNING/ERROR, was_blocking boolean, evidence_json,
finding_checksum BLOB. UNIQUE(import_commit_id, finding_checksum). Это
immutable копия finalized Preview findings, а не новая проверка.

### import_resolutions — owner imports, retention PERMANENT

import_resolution_id PK, import_commit_id FK, import_finding_id nullable FK,
row_link_id nullable FK, action_code TEXT, target_type nullable TEXT,
target_public_id nullable TEXT, replacement_reference_value_id nullable FK,
reason TEXT, actor_user_id FK, actor_display_name TEXT, resolved_at_us,
resolution_checksum BLOB. UNIQUE(import_commit_id, resolution_checksum).
Operator decision отделено от raw source и остается после cleanup workspace.

### inventory_sessions — owner inventory, retention PERMANENT after publish

session_id PK, public_id UNIQUE, import_commit_id UNIQUE FK,
scope_type CHECK FULL/PARTIAL, scope_json valid JSON,
status CHECK APPROVED/SUPERSEDED, source_sha256 BLOB, template_version,
parser_version, schema_version, preview_digest BLOB,
observed_active_snapshot_id nullable FK, freeze_ledger_cutoff INTEGER >=0,
freeze_started_at_us, effective_at_us equal freeze_started_at_us,
count_started_at_us, count_finished_at_us, approved_by_user_id FK,
actor_display_name, approved_at_us, approval_idempotency_key UNIQUE,
created_at_us, updated_at_us.

DRAFT..APPROVING/REJECTED/FAILED существуют только во внешнем Preview
workspace. В operational DB атомарный publish создает только APPROVED session;
позднее допустим единственный переход в SUPERSEDED. Все факты approval
immutable.

### inventory_snapshots — owner inventory, retention PERMANENT

snapshot_id PK, public_id UNIQUE, session_id UNIQUE FK, previous_snapshot_id
nullable FK, ledger_cutoff INTEGER >=0, status CHECK APPROVED/SUPERSEDED,
is_active boolean, item_count INTEGER, totals_json grouped by UOM,
content_checksum BLOB length=32, approved_by_user_id FK, actor_display_name,
approved_at_us. Partial UNIQUE(is_active) WHERE is_active=1. Active requires
APPROVED.

### inventory_snapshot_items — owner inventory, retention PERMANENT

snapshot_item_id PK, snapshot_id FK, row_link_id FK, equipment_id nullable FK,
catalog_item_id nullable FK, warehouse_id FK, location_id FK,
condition_value_id FK, lot_key TEXT default empty, uom_id FK,
quantity_minor INTEGER >0, identity_evidence_json valid JSON,
row_checksum BLOB length=32.

CHECK exactly one of equipment_id/catalog_item_id. UNIQUE(snapshot_id,
row_link_id). Partial UNIQUE indexes enforce stock key separately for non-null
equipment_id and non-null catalog_item_id. Serialized Equipment quantity
equals one minor unit with UOM dimension COUNT and scale=0; enforced by SQL
trigger, application validator and verification query.

### inventory_cycle_counts / inventory_cycle_count_items — owner inventory, retention PERMANENT

Approved PARTIAL session создает ровно один immutable cycle count и его items.
Scope сохраняется как JSON; item содержит source row link, stock subject,
warehouse/location/condition/lot/UOM/quantity и checksum. Эти таблицы дают
reconciliation evidence, но не имеют пути к active snapshot или projection.

### inventory_reconciliation_items — owner inventory, retention PERMANENT

reconciliation_id PK, session_id FK, snapshot_id nullable FK,
cycle_count_id nullable FK,
equipment_id nullable FK, catalog_item_id nullable FK, warehouse_id, location_id,
condition_value_id, lot_key, uom_id, expected_quantity_minor, counted_quantity_minor,
delta_quantity_minor, classification CHECK MATCH/NEW/MISSING/LOCATION_CHANGED/
CONDITION_CHANGED/QUANTITY_CHANGED/IDENTITY_CONFLICT, explanation_json,
import_resolution_id nullable FK import_resolutions. UNIQUE(session_id,
stock key, classification) реализуется двумя partial UNIQUE indexes для
equipment/catalog; CHECK требует ровно один subject и ровно один result owner:
snapshot XOR cycle_count. Delta = counted - expected.

## Warehouse ledger

### warehouse_transactions — owner warehouse, retention PERMANENT

ledger_sequence INTEGER PRIMARY KEY AUTOINCREMENT, public_id TEXT UNIQUE,
kind CHECK RECEIPT/ISSUE/TRANSFER/ADJUSTMENT_IN/ADJUSTMENT_OUT/REVERSAL,
posting_status TEXT CHECK value=POSTED, active_snapshot_id FK,
occurred_at_us, posted_at_us, actor_user_id FK, actor_display_name,
actor_role_code, permission_code, comment TEXT, reason_code nullable,
source_document_ref nullable, reverses_ledger_sequence nullable UNIQUE FK,
idempotency_scope TEXT, idempotency_key TEXT, correlation_id TEXT UNIQUE.
UNIQUE(idempotency_scope, idempotency_key). Indexes: posted time, kind,
reverses sequence, active snapshot.

Header и lines никогда не UPDATE/DELETE. Факт reversal определяется новой
REVERSAL row, а не сменой статуса исходной row.

### warehouse_transaction_lines — owner warehouse, retention PERMANENT

line_id PK, ledger_sequence FK, line_no INTEGER >0, equipment_id nullable FK,
catalog_item_id nullable FK, lot_key TEXT default empty, uom_id FK,
quantity_minor INTEGER >0, from_warehouse_id/location_id/condition_id nullable
FK, to_warehouse_id/location_id/condition_id nullable FK, line_comment TEXT,
line_checksum BLOB. UNIQUE(ledger_sequence, line_no). CHECK exactly one stock
subject. Kind-specific nullability проверяется SQL trigger, application
validator и verification query. Indexes по equipment, catalog/location,
from-location, to-location.

### warehouse_late_operation_evidence — owner warehouse, retention PERMANENT

late_evidence_id PK, operation_kind, occurred/discovered timestamps,
cutoff_snapshot_id FK, source_document_ref, raw_payload_json, resolution CHECK
NO_BALANCE_EFFECT/ADJUSTMENT_POSTED, optional adjustment ledger FK, personal
actor snapshot, reason and correlation ID. Late evidence само не является
ledger и не влияет на balance; эффект возможен только через отдельный posted
adjustment.

## Balance projection

### balance_projection_versions — owner balance, retention active + previous

projection_version_id PK, public_id UNIQUE, snapshot_id FK, build_status CHECK
BUILDING/READY/ACTIVE/FAILED/RETIRED, built_through_sequence INTEGER,
row_count INTEGER, total_checksum BLOB, created_at_us, ready_at_us nullable,
activated_at_us nullable, failure_code nullable. Partial UNIQUE(build_status)
WHERE ACTIVE. Старые RETIRED versions удаляются после verified backup и
retention 30 days; manifests остаются в audit.

### balance_projection_rows — owner balance, retention with version

projection_row_id PK, projection_version_id FK, equipment_id nullable FK,
catalog_item_id nullable FK,
warehouse_id FK, location_id FK, condition_value_id FK, lot_key TEXT,
uom_id FK, quantity_minor INTEGER CHECK >0, last_applied_sequence INTEGER,
row_checksum BLOB. CHECK exactly one subject. Two partial UNIQUE indexes enforce
(version, subject, warehouse, location, condition, lot, uom) separately for
equipment and catalog. Additional indexes support exact equipment,
catalog/location and keyset browse. Zero rows are removed.

## Legacy archive

### legacy_source_files — owner legacy history, retention PERMANENT

source_file_id PK, public_id UNIQUE, file_name, source_object_key,
sha256 BLOB UNIQUE length=32, size_bytes, media_type, workbook_metadata_json,
imported_at_us, import_commit_id FK. Stored source is immutable.

### legacy_history_events — owner legacy history, retention PERMANENT

event_id PK, public_id UNIQUE, source_file_id FK, source_sheet,
source_row_number >0, source_row_key, source_row_sha256 BLOB,
record_status CHECK IMPORTED/QUARANTINED/EXCLUDED, event_type CHECK
RECEIPT/ISSUE/UNKNOWN, serial_raw TEXT, serial_key TEXT,
inventory_number_raw TEXT, part_number_raw TEXT, vendor_raw TEXT,
model_raw TEXT, source_item_name_raw TEXT, performed_by_name_raw TEXT NOT NULL,
performed_by_quality CHECK EXACT/MISSING/CODE_ONLY/CORRUPTED,
accepted_by_name_raw TEXT NULL, occurred_at_us nullable,
date_raw TEXT NOT NULL, date_quality CHECK EXACT/MISSING/ESTIMATED/CORRUPTED,
estimation_basis TEXT NULL, comment_raw TEXT, quantity_raw TEXT,
location_raw TEXT, raw_payload_json valid JSON,
normalized_payload_json valid JSON, imported_at_us.

UNIQUE(source_file_id, source_sheet, source_row_number, source_row_key).
Indexes: (serial_key, occurred_at_us, event_id), source coordinate, date
quality, record status. ESTIMATED требует occurred_at и estimation_basis;
MISSING/CORRUPTED не имеют synthesized occurred_at.

### legacy_history_warnings — owner legacy history, retention PERMANENT

warning_id PK, event_id FK, severity CHECK WARNING/CONFLICT, code, message,
source_raw nullable. UNIQUE(event_id, severity, code). Index code.

### legacy_history_equipment_links — owner legacy history, retention PERMANENT

link_id PK, event_id FK, equipment_id FK, confidence CHECK EXACT/REVIEWED,
reason TEXT, decided_by_user_id FK, actor_display_name TEXT, decided_at_us,
supersedes_link_id nullable UNIQUE FK. Active link is the immutable chain tail:
the row not referenced by a newer link. SQL trigger requires the first row to
have no predecessor and every correction to extend the current tail for the
same event; legacy event itself не UPDATE.

## Audit and reports

### audit_events — owner audit, retention PERMANENT

audit_event_id INTEGER PRIMARY KEY, public_id TEXT UNIQUE, occurred_at_us,
action_code, outcome CHECK SUCCESS/DENIED/FAILED, actor_user_id nullable FK,
actor_display_name NOT NULL, actor_role_code nullable, session_id nullable,
permission_code nullable, correlation_id TEXT, subject_type, subject_public_id
nullable, ip_hash nullable BLOB, user_agent_family nullable, details_json,
previous_event_hash nullable BLOB, event_hash BLOB.

Indexes: occurred_at/event ID for keyset, actor, action, subject, correlation.
System events require actor_display_name=SYSTEM. Audit hash chain detects
accidental alteration but не заявляется криптографически tamper-proof без
внешнего anchor.

### report_jobs — owner reports, metadata retention 1 year, artifact 30 days

report_job_id PK, public_id UNIQUE, report_type, parameters_json, requested_by
FK users, status CHECK QUEUED/RUNNING/COMPLETED/FAILED/CANCELLED,
source_fingerprint_json, artifact_object_key nullable, artifact_sha256 nullable,
created/started/completed timestamps, failure_code nullable. Index requester,
status/time. Reports не становятся источником баланса.

### backup_records — owner infrastructure/operations, metadata PERMANENT

backup_record_id PK, public_id, opaque storage_object_key, database/manifest
SHA-256, size, schema version, optional snapshot, ledger sequence, status CHECK
VERIFIED/EXPIRED/RESTORED/FAILED, personal actor snapshot and retention dates.
DB bytes and backup bytes are never stored in this table.

## Workspace schema

Preview workspace имеет отдельную схему и lifecycle. Она определена в
[import-preview-publish.md](import-preview-publish.md#workspace-schema) и не
является частью operational DB.

## SQLite profile

- application_id = 0x4F444531;
- schema_migrations — authoritative; user_version дублирует последний numeric
  migration ID для быстрой диагностики;
- review set использует registry versions 1..8 и user_version=8;
- page_size 4096 для новой DB; изменение только после benchmark/ADR;
- foreign_keys=ON на каждом handle;
- runtime journal_mode=WAL, synchronous=FULL, busy_timeout=10000 ms;
- wal_autocheckpoint=1000 pages;
- query_only=ON для read pools;
- trusted_schema=OFF, extension loading disabled;
- DB только на local filesystem;
- schema/data migration на startup запрещена;
- online backup выполняется SQLite Backup API;
- file replace выполняется только после checkpoint, закрытия handles и fsync.

Review-only фактический DDL находится в [ddl/](ddl/README.md) и не является
разрешением применить его к рабочей или candidate DB. Cross-table invariants
выражаются именованными SQL triggers только там, где это необходимо для
защиты истины, и дополнительно проверяются application validator и explicit
verification gate.
