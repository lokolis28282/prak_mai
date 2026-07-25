# Транзакционная модель

Статус: **APPROVED — ODE 0.13 architecture baseline**

## Unit of Work

Application use case открывает один UnitOfWork:

    with uow.write(correlation_id) as tx:
        state = public query/repository reads through tx
        validate command and permission
        domain repositories stage writes
        synchronous handlers update projection
        audit repository appends event
        tx.commit()

Repository не вызывает commit/rollback, не открывает самостоятельное
соединение и не возвращает mutable DB row. Исключение из use case откатывает
domain write, projection и audit.

Read use case получает query_only connection и consistent snapshot transaction.
HTTP request не держит write transaction во время file upload/parsing.

## Общие правила

- Один command — одна DB transaction.
- Cross-context command координируется typed ports, не чужим repository.
- Permission проверяется до mutation и повторно при sensitive stale boundary.
- Critical success audit входит в transaction.
- Denied/failed attempts, где domain transaction не создавалась, пишутся
  отдельным security audit command без ложного SUCCESS.
- Correlation ID один для HTTP, workspace, candidate, DB и operations log.
- Network/file I/O не выполняется внутри долгой SQLite transaction.
- Post-commit callback не меняет доменную истину.

## Use-case transaction tables

### Upload inventory

| Phase | Action |
|---|---|
| Begin | Нет operational UoW; создать external upload lease |
| Read validation | Permission, file limits, freeze/session ownership |
| Writes | Temp file → SHA → immutable source; workspace session UPLOADED |
| Audit | External workspace security event |
| Commit | fsync source and workspace |
| Failure | Temp удаляется; operational DB byte-identical |

### Preview / resolution

| Phase | Action |
|---|---|
| Begin | Workspace batch transaction |
| Read validation | Source hash, run version, active freeze |
| Writes | Rows/findings/matches/statistics или additive resolution |
| Audit | Workspace actor/action |
| Commit | Каждая complete batch; final digest separately |
| Failure | Resume from last batch; operational DB byte-identical |

### Approve inventory

| Phase | Action |
|---|---|
| Begin | External publish lock; backup operational → candidate |
| Read validation | SHA, digest, versions, findings, refs, permission, active snapshot/head |
| Writes | Candidate transaction: equipment, import commit, session, snapshot/items, reconciliation, projection, supersession, app_state |
| Audit | INVENTORY_APPROVED in same candidate transaction |
| Commit | Candidate SQLite commit, full validation, close handles |
| Publish | Verified backup + atomic file replace |
| Failure | Discard candidate or restore pre-publish whole DB; no partial domain state |

Successor FULL baseline использует нормативный reserved-ID порядок внутри одной
`BEGIN IMMEDIATE` transaction в candidate DB:

1. Inventory approval service повторно проверяет active snapshot, ledger head,
   publish lock и approval idempotency key.
2. Этот service резервирует новый internal `snapshot_id` как следующий свободный
   INTEGER PK при уже удерживаемом single-writer lock. Public UUID генерируется
   отдельно и остается внешним идентификатором.
3. Старый snapshot переводится в SUPERSEDED со ссылкой на reserved successor ID.
4. Новый APPROVED snapshot вставляется с этим ID, затем потоково вставляются
   immutable items, reconciliation и projection.
5. `app_state`, audit и session supersession обновляются до COMMIT; FK/domain
   checks выполняются перед COMMIT и повторно перед publish candidate.

Partial UNIQUE active-snapshot constraint не позволяет вставить новый active row
первым. Поэтому post-insert AUTOINCREMENT flow здесь неприменим. Deferred FK
безопасен только внутри этой transaction: COMMIT отклоняется, если reserved ID
не был вставлен. `BEGIN IMMEDIATE`, external publish lock и stale-state check
исключают concurrent reservation/approval. Rollback освобождает незаписанный ID
и оставляет candidate в исходном состоянии; retry заново проверяет state и либо
возвращает уже committed idempotent result, либо резервирует ID повторно.

### Receipt / issue / transfer / adjustment / reversal

| Phase | Action |
|---|---|
| Begin | One operational write UoW |
| Read validation | ACTIVE baseline, no freeze, permission, idempotency, state version, identities, locations, availability; reversal target belongs to current baseline |
| Writes | Header + lines; synchronous projection delta; app_state sequence |
| Audit | Action-specific success event |
| Commit | All or none |
| Failure | No ledger, projection or success audit rows |

### Equipment identity correction / merge

| Phase | Action |
|---|---|
| Begin | One write UoW; active source balance requires linked adjustments |
| Read validation | Admin/permission, conflicts, impact preview digest |
| Writes | New identity/retire old or merge link; required paired adjustments when source has active balance; projection |
| Audit | IDENTITY_CORRECTED or EQUIPMENT_MERGED |
| Commit | Atomic aggregate and mathematical net check |
| Failure | Old identities and balances remain active |

Paired merge adjustment и zero-net mathematical check являются
application-enforced use-case invariant: DDL требует только одновременную
nullability двух sequence FK и не доказывает их stock subject/net effect.
`verify_domain_invariants.sql` дополнительно обнаруживает committed merge с
остатком без пары либо с неверными transaction kinds.

### Reference command

| Phase | Action |
|---|---|
| Begin | One write UoW |
| Read validation | Admin, scope/parent, uniqueness, impact digest |
| Writes | Additive status/value/alias change; reference version |
| Audit | REFERENCE_* |
| Commit | Atomic |
| Failure | Existing resolution unchanged |

### User/session command

| Phase | Action |
|---|---|
| Begin | One security UoW |
| Read validation | Admin/reauth where needed, credential/session version |
| Writes | User/role/session state |
| Audit | USER_*, LOGIN, LOGOUT, SESSION_REVOKED |
| Commit | Atomic |
| Failure | Denial audit in isolated security UoW when safe |

### Projection rebuild

| Phase | Action |
|---|---|
| Begin | Short manifest UoW then batched BUILDING version |
| Read validation | Stable snapshot/head read snapshot |
| Writes | Inactive shadow rows; no user-visible switch |
| Audit | REBUILD_STARTED/FAILED; activation event |
| Commit | Final short UoW applies tail and flips active pointer |
| Failure | Old active projection remains |

### Backup

| Phase | Action |
|---|---|
| Begin | Operations lock, read current DB metadata |
| Read validation | Admin+reauth, target local storage capacity |
| Writes | SQLite Backup API temp artifact + manifest + fsync |
| Audit | BACKUP_CREATED only after hash/restore-open verification |
| Commit | Atomic artifact rename; DB unchanged |
| Failure | Temp removed, failure audit |

### Restore

| Phase | Action |
|---|---|
| Begin | Maintenance lock; stop new requests |
| Read validation | Admin+reauth, manifest/hash, integrity/FK/application/schema compatibility |
| Writes | No in-place writes; prepare verified restore file |
| Audit | RESTORE_PREPARED in external operations log; RESTORE_COMPLETED already in restored candidate before publish |
| Commit | Close handles, atomic replace |
| Failure | Original DB filename restored/unchanged |

## Filesystem two-phase protocol

Prepare creates immutable temp/candidate on the same volume. Publish requires:

1. content hash and semantic validation;
2. fsync file;
3. fsync containing directory where supported;
4. closed SQLite handles and no WAL/SHM;
5. platform atomic replace;
6. reopen read-only verification;
7. release lock.

Filesystem operation и SQLite transaction не являются distributed transaction.
Correctness достигается candidate-as-complete-state и whole-file rollback, а не
компенсирующими row updates.
