# Жизненный цикл полной инвентаризации

Статус: **APPROVED — ODE 0.13 architecture baseline**

## Scope

ODE 0.13 поддерживает только FULL inventory как источник baseline. PARTIAL
cycle count разрешен после первого baseline как scoped reconciliation evidence:
он создает approved InventoryCycleCount, но никогда не создает Snapshot,
не меняет active baseline и не обновляет projection.

Pre-approval aggregate и posting-freeze находятся во внешнем workspace/state
storage. До atomic publish operational DB не изменяется.

## Статусы

| Status | Кто/условие входа | Разрешено | Запрещено | Создаваемые данные и audit | Recovery |
|---|---|---|---|---|---|
| DRAFT | Operator создает session и durable freeze token | Заполнить manifest, отменить | Upload без freeze, warehouse posting | Workspace session; external security log | Resume по session ID; admin release abandoned freeze |
| UPLOADED | Source сохранен, SHA/size проверены | Начать Preview, reject | Изменить source in-place, approve | Source vault object + manifest | Повторный upload создает новый source version/session |
| PREVIEWING | Worker получил immutable run | Смотреть progress, cancel | Resolutions, approve | Batched rows/findings/statistics | Resume с checkpoint; invalid batch rebuild |
| REVIEW_REQUIRED | Preview complete, есть open findings | Resolve, rerun matching, reject | Approve при blocking findings | Immutable finding + additive resolutions | Повторный расчет создает новый preview run/digest |
| READY_FOR_APPROVAL | Нет unresolved blocking findings | Approve, reject, refresh | Менять raw source | Final preview digest, readiness record | Stale fingerprint → PREVIEWING |
| APPROVING | Permission и stale checks пройдены | Только наблюдать progress | Любые конкурирующие команды; posting | Candidate + publish attempt log | Failure discards candidate, session → FAILED |
| APPROVED | Candidate validated и atomically active | Read snapshot/reconciliation | Изменять items/cutoff/source | Operational session, snapshot, import commit, audit | Только whole-DB rollback по runbook |
| REJECTED | Operator/admin до publish | Read evidence до retention | Resume/approve этой session | Rejection actor/reason in workspace | Новый session для того же source |
| FAILED | Parser/publish/system failure | Inspect, retry allowed phase, reject | Approve без revalidation | Failure phase/code/correlation | Retry PREVIEWING либо READY after clean candidate |
| SUPERSEDED | Новый snapshot atomically активирован | Read historical snapshot | Reactivate через UPDATE | Supersession link/audit | Rollback только whole release/candidate procedure |

APPROVING не может быть отменен пользовательским запросом после начала file
replace. До replace cancellation безопасно удаляет candidate.

## Posting-freeze

Для новой полной инвентаризации operator сначала создает external freeze:

1. read-only считываются active_snapshot_id и ledger head;
2. создается защищенный freeze record с session ID и случайным token hash;
3. все warehouse write-use-cases проверяют freeze record и возвращают
   INVENTORY_FREEZE_ACTIVE;
4. физические движения склада организационно прекращаются;
5. Excel фиксирует counted interval;
6. approval требует того же active snapshot и ledger head.

Для первого baseline active snapshot отсутствует, cutoff=0 и posting уже
запрещен состоянием NOT_INITIALIZED.

Freeze не пишет operational DB и потому соблюдает правило «до подтверждения
рабочая база не меняется». Освобождение abandoned freeze требует admin,
reauthentication, reason и external operations audit.

## Переходы

~~~mermaid
stateDiagram-v2
    [*] --> DRAFT
    DRAFT --> UPLOADED: immutable source + SHA
    DRAFT --> REJECTED: cancel
    UPLOADED --> PREVIEWING: start preview
    UPLOADED --> REJECTED: reject
    PREVIEWING --> REVIEW_REQUIRED: findings
    PREVIEWING --> READY_FOR_APPROVAL: no blocking findings
    PREVIEWING --> FAILED: parser/system failure
    PREVIEWING --> REJECTED: cancel
    REVIEW_REQUIRED --> REVIEW_REQUIRED: additive resolutions
    REVIEW_REQUIRED --> PREVIEWING: rerun / stale
    REVIEW_REQUIRED --> READY_FOR_APPROVAL: all blocking resolved
    REVIEW_REQUIRED --> REJECTED: reject
    READY_FOR_APPROVAL --> PREVIEWING: fingerprint stale
    READY_FOR_APPROVAL --> APPROVING: approve command
    READY_FOR_APPROVAL --> REJECTED: reject
    APPROVING --> APPROVED: candidate validated + atomic replace
    APPROVING --> FAILED: candidate/publish failure
    FAILED --> PREVIEWING: retry parse
    FAILED --> READY_FOR_APPROVAL: retry publish after full revalidation
    FAILED --> REJECTED: abandon
    APPROVED --> SUPERSEDED: newer approved snapshot
    SUPERSEDED --> [*]
    REJECTED --> [*]
~~~

## Approval preconditions

Approve MUST fail before candidate mutation if:

- source SHA-256/size/object key changed;
- template, parser or schema version differs from finalized Preview;
- recalculated preview digest differs;
- open blocking finding exists;
- resolution signature/digest differs;
- observed active snapshot differs;
- current ledger head differs from freeze cutoff;
- freeze token/session does not match;
- source references are no longer APPROVED or reference fingerprint changed;
- requester lacks INVENTORY_APPROVE;
- session is not READY_FOR_APPROVAL;
- an idempotency key points to a different request.

Candidate validation is also a precondition of publish, not of entering
APPROVING.

## Snapshot и session

InventorySession — workflow, actors, source versions, freeze and approval
decision. InventorySnapshot — immutable stock fact at cutoff. Session может
существовать без snapshot; snapshot не существует без approved session.

Перечисленные DRAFT..APPROVING статусы принадлежат Preview workspace.
Operational `inventory_sessions` содержит только опубликованный результат со
статусом APPROVED или SUPERSEDED. Для scope FULL результатом является Snapshot;
для PARTIAL — InventoryCycleCount. Это исключает pre-approval operational rows.

Несколько APPROVED snapshots сохраняются. Ровно один snapshot active. При
publish нового baseline старый получает SUPERSEDED в той же candidate
transaction, но его items не меняются.

## Reconciliation

Перед новым baseline expected state пересобирается из текущего active snapshot
и ledger до freeze cutoff. Для каждого stock key сохраняются counted,
expected, delta и classification. Новый snapshot не генерирует скрытые
adjustments. UI объясняет:

- новое физическое оборудование;
- отсутствующее оборудование;
- изменение location/condition;
- расхождение bulk quantity;
- identity conflict;
- полное совпадение.

Reconciliation влияет на approval findings, но после ручного утверждения новый
snapshot сам становится baseline.

Для PARTIAL expected state считается только внутри утвержденного scope.
Missing вне scope игнорируется, внутри scope сохраняется как cycle-count
finding/reconciliation. Результат не порождает adjustment автоматически; если
оператор решает исправить остаток, он отдельно проводит ADJUSTMENT с permission
и audit. PARTIAL session не может стать global active baseline ни через API, ни
через DDL trigger.

## Unknown items

Unknown serialized item может создать Equipment только если:

- есть S/N либо Inventory Number по правилам identity;
- CatalogItem и location разрешены;
- duplicate/conflict findings разрешены;
- raw source и operator resolution сохранены.

Unknown catalog/reference без approved mapping блокирует approval. ODE не
создает canonical values автоматически.

## Failure guarantees

- Parser failure не меняет source и operational DB.
- Candidate failure удаляет candidate, operational DB byte-identical.
- Replace failure восстанавливает pre-publish filename under lock.
- После successful replace session APPROVED уже присутствует в новой DB.
- Повтор того же approval idempotency key возвращает существующий result.

Sequence: [inventory-sequence.md](diagrams/inventory-sequence.md).
