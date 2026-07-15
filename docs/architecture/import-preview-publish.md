# XLSX Import, Preview Workspace и Atomic Publish

Статус: **APPROVED — ODE 0.13 architecture baseline**
Этот документ одновременно является Excel contract, Preview storage contract
и publish protocol; разделение на три файла создало бы повторение одного
content-addressed workflow.

## Утвержденный XLSX contract

Template ID: ODE-FULL-INVENTORY
Template version: 1.0
Parser contract: inventory-xlsx/1
Максимум: 1 000 000 data rows, 512 MiB compressed, 4 GiB expanded XML.

Обязательные листы:

1. Manifest — key/value metadata, одна inventory session.
2. Inventory — header в строке 1 и data со строки 2.

Опциональные Instructions и Lookups игнорируются как data. Неизвестный лист
дает WARNING; executable macros запрещены.

### Manifest

| Key | Type | Rule |
|---|---|---|
| TemplateId | text | exactly ODE-FULL-INVENTORY |
| TemplateVersion | text | exactly supported version |
| InventoryExternalId | text | required, unique in source organization |
| WarehouseCode | text | required active warehouse |
| CountStartedAt | RFC 3339 | required with timezone |
| CountFinishedAt | RFC 3339 | required, >= start |
| CountedBy | text | required raw team/person label |
| TimeZone | IANA name | required |
| ReferenceVersion | hash/version | required |
| Comment | text | optional, max 2000 chars |

### Inventory columns

| Column | Type | Required / validation |
|---|---|---|
| RowId | text max 100 | Required, unique, stable across correction file |
| ItemKind | enum | SERIALIZED, BULK, CABLE, CONSUMABLE |
| WarehouseCode | text | Required; equals manifest unless multi-warehouse template is separately versioned |
| LocationCode | text | Required active location in warehouse |
| SerialNumber | text | Conditional; never numeric/formula |
| InventoryNumber | text | Optional text; never numeric/formula |
| PartNumber | text | Required for new CatalogItem match; no guessed conversion |
| Vendor | text | Required for scoped S/N unless approved UNSCOPED resolution |
| Model | text | Optional raw text; exact alias only |
| Description | text | Required raw source item name |
| Quantity | decimal text | Serialized exactly 1; bulk >0 and representable by UOM scale |
| UOM | reference code | Required active UOM |
| Condition | reference code | AVAILABLE, QUARANTINED, DAMAGED or approved domain value |
| Lot | text | Optional for bulk; forbidden for serialized unless catalog policy requires |
| CountedBy | text | Required; raw value preserved |
| CountedAt | RFC 3339 | Optional per-row; must be within manifest interval |
| Comment | text max 4000 | Optional |

Blank whitespace-only is blank. Required blanks are ERROR. Extra columns are
preserved in raw payload and produce WARNING. Unknown enum/reference is ERROR.

### Cell and row rules

- Identity cells MUST be Excel text cells. Leading zeros are preserved.
- Scientific notation, numeric or formula identity cell is blocking ERROR.
- Formula cells in Manifest/Inventory are blocking ERROR even with cached value.
- Merged cells intersecting data area are blocking ERROR.
- Hidden Inventory rows are parsed and marked blocking HIDDEN_DATA_ROW.
- Filtered rows are parsed normally.
- Duplicate RowId is ERROR.
- Duplicate serialized identity is ERROR until operator resolution.
- Duplicate bulk stock key is ERROR; no implicit sum. Resolution may explicitly
  aggregate selected rows and records the arithmetic.
- Completely blank trailing rows are ignored; blank row inside data yields
  WARNING with source coordinate.
- Quantity conversion is decimal-string → quantity_minor; rounding forbidden.
- Workbook date system, shared strings and raw XML cell representation are
  recorded.
- External links, macros, embedded objects and DDE are rejected.
- ZIP path traversal, decompression ratio and XML entity expansion are blocked.

Physical scan occurs in Excel. ODE never modifies the source workbook.

## Source vault

Upload streams to a temporary same-volume file while computing SHA-256 and
size. После validation файл fsync и content-addressed rename в source vault.
Existing same hash is reused read-only. Permissions allow only ODE service and
operations admin. File name is metadata, never a path. Malware/type validation
precedes parsing.

## Workspace schema

Workspace is a separate SQLite DB per session under protected runtime state.
It uses application_id 0x4F445057, foreign_keys=ON, WAL during processing and
single writer. Retention: APPROVED/REJECTED 30 days after verified publish or
rejection; FAILED 90 days; source vault follows backup policy.

### preview_runs

run_id TEXT PK UUIDv7, session_id TEXT, attempt INTEGER, session_status CHECK
DRAFT/UPLOADED/PREVIEWING/REVIEW_REQUIRED/READY_FOR_APPROVAL/APPROVING/
APPROVED/REJECTED/FAILED/SUPERSEDED, run_status CHECK
QUEUED/RUNNING/READY/FAILED/STALE/CANCELLED, source_sha256 BLOB, source_size,
template/parser/schema/reference versions, observed_snapshot_id nullable,
observed_ledger_head INTEGER, freeze_token_hash BLOB, started/completed times,
last_checkpoint_row INTEGER, row_count, finding_count, preview_digest BLOB,
failure_code/message. UNIQUE(session_id, attempt), UNIQUE(session_id,
preview_digest) when READY. Первый run row создается вместе с DRAFT workflow
session и до parser start имеет run_status QUEUED.

### preview_rows

row_id INTEGER PK, run_id FK, source_sheet, source_row_number, source_row_id,
row_sha256 BLOB, raw_payload_json, normalized_payload_json, row_status CHECK
VALID/WARNING/BLOCKED, stock_subject_kind, proposed_match_key,
processed_at_us. UNIQUE(run_id, source_sheet, source_row_number);
UNIQUE(run_id, source_row_id). Index status and match key.

### preview_cells

cell_id INTEGER PK, row_id FK, column_code, coordinate, excel_cell_type,
number_format, raw_xml_value, display_value, preservation_status, cell_sha256.
UNIQUE(row_id,column_code). Identity/date cells and anomalous cells are stored;
ordinary values may remain only in raw payload to bound size.

### preview_findings

finding_id INTEGER PK, run_id FK, row_id nullable FK, code, severity CHECK
INFO/WARNING/ERROR, blocking boolean, field_code nullable, message,
evidence_json, finding_checksum BLOB, status CHECK OPEN/RESOLVED/WAIVED.
UNIQUE(run_id,row_id,code,finding_checksum). Index blocking/status/code.

### preview_matches

match_id INTEGER PK, run_id FK, row_id FK, candidate_type, candidate_public_id,
match_kind CHECK EXACT/ALIAS/SIMILAR/CONFLICT/NONE, score_basis_json,
is_selected boolean, match_checksum. UNIQUE(run_id,row_id,candidate_type,
candidate_public_id). Similar match никогда не выбирается автоматически для
identity.

### preview_resolutions

resolution_id INTEGER PK, run_id FK, finding_id nullable FK, row_id nullable FK,
action_code, target_public_id nullable, replacement_value_id nullable,
reason TEXT, actor_user_public_id, actor_display_name, created_at_us,
supersedes_resolution_id nullable FK, resolution_checksum BLOB. Rows immutable;
активной считается последняя chain member. UNIQUE(run_id,resolution_checksum).

### preview_statistics

run_id FK, metric_code, dimension_key, value_integer, value_json,
statistics_checksum. PK(run_id,metric_code,dimension_key).

### Workspace checksum

Preview digest вычисляется по versioned canonical encoding:

    SHA256(
      source_sha256 ||
      template/parser/schema/reference versions ||
      observed snapshot/ledger head ||
      ordered row_sha256 ||
      ordered finding_checksum ||
      ordered active resolution_checksum
    )

Порядок всегда source sheet ordinal, row number, stable IDs. JSON
canonicalизируется UTF-8, sorted keys, no insignificant whitespace.

## Почему не другие хранилища

- Memory: теряется при crash, ограничивает 1 млн rows, не дает durable review.
- Operational DB: нарушает правило byte-identical до approval и смешивает
  недоверенные данные с authoritative.
- Browser localStorage: не является серверной provenance, имеет малый лимит,
  доступно XSS и конкретному browser profile.

## Bounded-memory processing

- SAX/raw OOXML streaming, без загрузки workbook DOM;
- batch 2 000 rows по умолчанию, configurable 500–10 000;
- commit checkpoint каждой batch в workspace;
- не более двух batch в памяти;
- progress = parsed rows/known worksheet dimension, dimension считается hint;
- cancel проверяется между batch;
- exact matching выполняется batched indexed query до 2 000 keys;
- statistics обновляются incrementally;
- final digest выполняется streaming ordered scan.

## Crash, resume и stale

- RUNNING с просроченным worker lease становится FAILED/RESUMABLE.
- Resume продолжает после последней полностью committed batch.
- Partial batch удаляется по batch marker.
- Новый parser/schema/reference fingerprint создает новый attempt; старый
  immutable.
- Изменение source hash требует нового session.
- Изменение active baseline/ledger head переводит READY run в STALE.
- Один session может иметь много runs, но publish ссылается ровно на один
  finalized digest.
- Cleanup никогда не удаляет source/candidate, упомянутый активным publish
  attempt или backup manifest.

## Prepare publish

Approve command повторно вычисляет digest и fingerprints, проверяет permission
и freeze. Затем:

1. ставит external publish lock;
2. SQLite Backup API копирует operational DB в same-volume candidate;
3. candidate открывается с foreign_keys=ON и exclusive writer;
4. одним transaction создаются import commit, approved session, snapshot/items,
   reconciliation, equipment/identities, projection и audit;
5. candidate проходит all verification gates;
6. candidate переводится в single-file state: WAL checkpoint TRUNCATE, handles
   закрыты;
7. создается verified pre-publish backup;
8. candidate file и parent directory fsync;
9. все runtime handles закрываются;
10. POSIX os.replace или Windows ReplaceFileW atomically заменяет DB;
11. новая DB read-only открывается и проверяется;
12. runtime открывает WAL и снимает freeze;
13. workspace получает PUBLISHED receipt.

Candidate никогда не строится на network filesystem и не переносится между
volumes. См. [publish sequence](diagrams/publish-sequence.md) и
[database lifecycle](../operations/database-lifecycle.md).

## Failure

До replace operational DB byte-identical. После failed replace удерживается
maintenance lock и запускается platform-specific restore filename procedure.
После replace, но до reopen, rollback использует pre-publish backup. Нельзя
«докатывать» непроверенный candidate.
