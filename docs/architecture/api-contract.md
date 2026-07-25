# API Contract v1

Статус: **APPROVED CONTRACT — runtime не реализован**
Base path: /api/v1. Универсальный /api/action запрещен.

## Protocol

JSON UTF-8, timestamps RFC 3339 UTC, IDs UUID strings, quantities:

    {"minor": 1250, "uom": "M", "scale": 3}

Success:

    {"data": {...}, "meta": {"correlation_id": "...", "etag": "..."}}

Error:

    {
      "error": {
        "code": "STALE_STATE",
        "message": "Безопасное сообщение",
        "field_errors": [{"field": "...", "code": "..."}],
        "details": {},
        "retryable": false
      },
      "meta": {"correlation_id": "..."}
    }

message не является machine contract. Stable contract — code. Неожиданная
ошибка возвращает INTERNAL_ERROR без stack trace.

## Concurrency, idempotency и pagination

- Все create/post commands требуют Idempotency-Key (16–128 safe chars).
- Mutation существующего draft/workspace resource требует If-Match ETag.
- Ledger commands содержат expected snapshot/projection/head fingerprint.
- List endpoints: limit default 50, max 200, opaque signed cursor; OFFSET нет.
- Response возвращает next_cursor и has_more.
- 409 — conflict/idempotency; 412 — stale ETag/fingerprint; 422 — domain
  validation; 423 — freeze/maintenance; 403 — permission.

## DTO

- SessionCreate: warehouse_code, inventory_external_id, count plan.
- UploadResult: session_id, source_sha256, size, template manifest.
- PreviewRun: run_id, status, progress, digest, statistics, fingerprints.
- ResolutionCreate: finding_id/row_id, action_code, target_id/value_id, reason.
- ApproveCommand: preview_digest, source_sha256, freeze_token, fingerprints,
  explicit confirmation totals.
- TransactionCreate: kind, occurred_at, comment/reason/source_document, lines,
  expected_state.
- TransactionLine: stock subject ID, quantity, from/to location/condition, lot.
- Page<T>: items, next_cursor, has_more, source fingerprint.

## Endpoints

| Method / route | Permission | Request → response | Errors/stale/idempotency | Audit |
|---|---|---|---|---|
| POST /auth/login | Public rate-limited | Login → Principal | AUTH_FAILED, ACCOUNT_LOCKED; idempotency no | LOGIN/FAILED |
| POST /auth/logout | Authenticated | empty → 204 | SESSION_EXPIRED | LOGOUT |
| GET /auth/me | Authenticated | — → Principal | SESSION_EXPIRED | — |
| GET /inventory-sessions | INVENTORY_READ | cursor/filter → Page<Session> | INVALID_CURSOR | — |
| POST /inventory-sessions | INVENTORY_UPLOAD | SessionCreate → Session(DRAFT)+freeze | FREEZE_ACTIVE; idempotent | external SESSION_CREATED |
| GET /inventory-sessions/{id} | INVENTORY_READ | — → Session | NOT_FOUND | — |
| POST /inventory-sessions/{id}/upload | INVENTORY_UPLOAD | multipart XLSX + If-Match → UploadResult | FILE_*, STALE_ETAG; idempotent by hash | external SOURCE_UPLOADED |
| POST /inventory-sessions/{id}/preview-runs | INVENTORY_PREVIEW | If-Match → PreviewRun | SOURCE_NOT_READY, RUN_EXISTS; idempotent | external PREVIEW_STARTED |
| GET /inventory-sessions/{id}/preview-runs/{run} | INVENTORY_READ | — → PreviewRun | NOT_FOUND | — |
| POST /preview-runs/{run}/cancel | INVENTORY_PREVIEW | If-Match → status | NOT_CANCELLABLE | external PREVIEW_CANCELLED |
| GET /preview-runs/{run}/findings | INVENTORY_READ | cursor,severity,status → Page<Finding> | INVALID_FILTER/CURSOR | — |
| GET /preview-runs/{run}/matches | INVENTORY_READ | cursor,row → Page<Match> | INVALID_CURSOR | — |
| GET /preview-runs/{run}/statistics | INVENTORY_READ | — → Statistics | RUN_NOT_READY | — |
| POST /preview-runs/{run}/resolutions | INVENTORY_RESOLVE | ResolutionCreate+If-Match → Resolution | FINDING_NOT_RESOLVABLE, STALE_ETAG; idempotent | external FINDING_RESOLVED |
| POST /inventory-sessions/{id}/approve | INVENTORY_APPROVE | ApproveCommand → PublishJob/ApprovedSnapshot | PREVIEW_STALE, BLOCKING_FINDINGS, LEDGER_HEAD_CHANGED, CANDIDATE_INVALID; idempotent | INVENTORY_APPROVED in candidate |
| POST /inventory-sessions/{id}/reject | INVENTORY_APPROVE | reason+If-Match → REJECTED | NOT_REJECTABLE | external INVENTORY_REJECTED |
| GET /inventory-snapshots | INVENTORY_READ | cursor → Page<Snapshot> | INVALID_CURSOR | — |
| GET /inventory-snapshots/{id} | INVENTORY_READ | — → Snapshot summary | NOT_FOUND | — |
| GET /inventory-snapshots/{id}/reconciliation | INVENTORY_READ | cursor,class → Page<Delta> | INVALID_FILTER | — |
| GET /equipment | EQUIPMENT_READ | cursor,filters → Page<Equipment> | FILTER_TOO_BROAD | — |
| GET /equipment/{id} | EQUIPMENT_READ | — → Equipment | NOT_FOUND, MERGED_REDIRECT | — |
| GET /equipment:lookup | EQUIPMENT_READ | kind,value,vendor? → ExactLookup | IDENTITY_AMBIGUOUS/NOT_FOUND | — |
| GET /equipment/{id}/timeline | HISTORY_READ | cursor,source_type → Page<TimelineEvent> | INVALID_CURSOR | — |
| POST /equipment/{id}/identity-corrections | IDENTITY_CORRECT | Correction+impact_digest → Equipment | IDENTITY_CONFLICT, IMPACT_STALE; idempotent | IDENTITY_CORRECTED |
| POST /equipment-merges | EQUIPMENT_MERGE | source,survivor,impact_digest,reason → Merge | BALANCE_CONFLICT, IMPACT_STALE; idempotent | EQUIPMENT_MERGED |
| GET /legacy-history:lookup | HISTORY_READ | serial,vendor?,cursor → Page<LegacyEventGroup> | QUERY_TOO_BROAD | — |
| GET /warehouse-transactions | WAREHOUSE_READ | cursor,kind,subject,time → Page<Transaction> | INVALID_CURSOR | — |
| GET /warehouse-transactions/{id} | WAREHOUSE_READ | — → Transaction | NOT_FOUND | — |
| POST /warehouse-transactions | kind-specific | TransactionCreate → Transaction | NOT_INITIALIZED, FREEZE_ACTIVE, INSUFFICIENT_STOCK, STALE_STATE; idempotent | *_POSTED |
| POST /warehouse-transactions/{id}/reversal | WAREHOUSE_REVERSE | reason, expected_state → Reversal | ALREADY_REVERSED, REVERSAL_UNSAFE, REVERSAL_OUTSIDE_ACTIVE_BASELINE; idempotent | REVERSAL_POSTED |
| GET /balance | BALANCE_READ | cursor,warehouse,location,condition,subject → Page<BalanceRow> | NOT_INITIALIZED, PROJECTION_INCONSISTENT | — |
| GET /balance/{equipment_id} | BALANCE_READ | — → EquipmentBalance | NOT_FOUND/NOT_INITIALIZED | — |
| GET /references/domains | REFERENCE_READ | — → domains+version | — | — |
| GET /references/{domain}/values | REFERENCE_READ | cursor,status,scope → Page<Value> | INVALID_DOMAIN | — |
| POST /references/{domain}/values | REFERENCE_EDIT | ValueCreate → Value | DUPLICATE_KEY; idempotent | REFERENCE_CREATED |
| POST /reference-aliases/{id}/decision | REFERENCE_EDIT | approve/reject,target,reason+ETag → Alias | STALE_ETAG/SCOPE_MISMATCH | ALIAS_DECIDED |
| POST /reference-values/{id}/merge | REFERENCE_EDIT | target,impact_digest,reason → Merge | IMPACT_STALE/CYCLE | REFERENCE_MERGED |
| GET /audit-events | AUDIT_READ | cursor,actor,action,subject,time → Page<AuditEvent> | FILTER_TOO_BROAD | — |
| POST /report-jobs | REPORT_CREATE | type,params → Job | UNSUPPORTED_REPORT; idempotent | REPORT_REQUESTED |
| GET /report-jobs/{id} | REPORT_READ | — → Job/artifact metadata | NOT_FOUND/EXPIRED | — |
| GET /backups | BACKUP_READ | cursor → Page<BackupManifest> | STORAGE_UNAVAILABLE | — |
| POST /backups | BACKUP_CREATE+reauth | reason → BackupJob | BACKUP_IN_PROGRESS; idempotent | BACKUP_CREATED/FAILED |
| POST /restores/validate | RESTORE+reauth | backup_id → RestorePlan | HASH/SCHEMA/INTEGRITY failure | RESTORE_VALIDATED |
| POST /restores | RESTORE+reauth | plan_digest,confirmation → PublishJob | PLAN_STALE/MAINTENANCE_REQUIRED; idempotent | RESTORE_PREPARED/COMPLETED |
| GET /diagnostics | DIAGNOSTICS_READ | — → redacted health | — | DIAGNOSTICS_READ |

Uploads use multipart only for file part plus JSON manifest; file bytes never
base64 JSON.

## Exact lookup response

ExactLookup имеет status FOUND, AMBIGUOUS или NOT_FOUND и candidates. API не
выбирает vendor при одинаковом S/N. Similar search — отдельный UI assistance
endpoint будущей версии и не участвует в commands.

## Reversal errors

`REVERSAL_OUTSIDE_ACTIVE_BASELINE` — стабильный non-retryable domain code: target
transaction относится к superseded FULL baseline. `details` содержит только
target transaction public ID и public IDs old/current snapshots. UI объясняет,
что historical ledger immutable, и предлагает отдельную ADJUSTMENT_IN,
ADJUSTMENT_OUT или TRANSFER command по фактическому состоянию.

`REVERSAL_UNSAFE` сохраняется для target текущего baseline, если exact inverse
нарушит availability/serialized placement или после target были несовместимые
движения. Эти коды не взаимозаменяемы.

## Audit visibility

GET endpoints не пишут audit для каждого row. Экспорт audit/history, sensitive
diagnostics, backup download и permission denial логируются.

## Compatibility

API v1 не обязан сохранять текущий /api/action. Legacy route выключается вместе
с old UI после cutover; adapter не входит в новую domain architecture.
