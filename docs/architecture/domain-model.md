# Доменная модель ODE 0.13

Статус: **APPROVED — ODE 0.13 architecture baseline**

## Строгие термины

- **Serialized equipment** — индивидуально отслеживаемый физический объект с
  Equipment ID; quantity в snapshot/ledger всегда 1.
- **Bulk material** — взаимозаменяемый запас, учитываемый по CatalogItem,
  location, condition и при необходимости lot; отдельного Equipment нет.
- **Cable/consumable** — bulk material с UOM LENGTH/COUNT. Катушка с собственным
  S/N может быть Equipment, а кабель на ней — bulk stock.
- **CatalogItem** — каноническое описание типа товара; не физический объект.
- **Physical identity** — проверяемый внешний идентификатор Equipment:
  S/N или Inventory Number.
- **Stock balance position** — уникальная комбинация stock subject, warehouse,
  location, condition и lot в active projection.
- **Historical event** — неизменяемый факт legacy source; не ledger.
- **Current operational transaction** — posted WarehouseTransaction после
  active snapshot cutoff.
- Термины «карточка», «позиция» и «операция» без одного из этих уточнений в
  нормативных документах запрещены.

## Core entities

| Entity | Identity и обязательные поля | Mutable | Immutable | States / lifecycle | Инварианты | Owner |
|---|---|---|---|---|---|---|
| Equipment | equipment_id, public_id, subject_kind=SERIALIZED, catalog_item_id, lifecycle_status | catalog link через audited correction, lifecycle | IDs, created provenance | ACTIVE, QUARANTINED, RETIRED, MERGED | Не представляет bulk; merged имеет survivor | equipment |
| EquipmentIdentity | identity_id, equipment_id, kind, raw_value, normalized_key, scope_key, status, provenance | status/valid_to только новой correction | raw source, original key, created_at | ACTIVE, RETIRED, CONFLICT, UNVERIFIED | Active unique в namespace; raw не переписывается | equipment |
| CatalogItem | catalog_item_id, public_id, vendor, part_number, kind, UOM | display/active через versioned change | ID, creation provenance | ACTIVE, INACTIVE, MERGED | PN не угадывается; merge сохраняет raw history | references/catalog |
| Warehouse | warehouse_id, code, name | name, active | ID/code после использования | ACTIVE, INACTIVE | Code unique | references/catalog |
| WarehouseLocation | location_id, warehouse_id, code, parent, kind | display, active | ID, warehouse | ACTIVE, INACTIVE | Unique code within warehouse; acyclic parent | references/catalog |
| User | user_id, public_id, display name, login/email, active | profile, credential metadata, active | IDs, creation | INVITED, ACTIVE, LOCKED, DISABLED | Персональная identity; no shared write user | users |
| Role | role_id, code | display only | code, permission semantics | ACTIVE, INACTIVE | Initial codes operator/admin/auditor | users/security |
| InventorySession | session_id, public_id, committed import, source hash, parser/schema versions, scope, cutoff/effective time, approval actor | Только APPROVED→SUPERSEDED | Approval facts and source manifest | APPROVED, SUPERSEDED in operational DB | Только FULL может иметь Snapshot; PARTIAL имеет CycleCount | inventory/imports |
| InventoryPreview | preview_id, run ID, source hash, digest, counts | progress/status until finalized | finalized digest and parser versions | QUEUED, RUNNING, READY, FAILED, STALE, CANCELLED | Не пишет operational DB | imports |
| InventoryFinding | finding_id, run/row, code, severity, evidence | resolution link | detected evidence/code | OPEN, RESOLVED, WAIVED | ERROR нельзя waive без code policy | imports |
| InventoryResolution | resolution_id, finding, action, actor, reason | Нет; замена новой resolution | Все поля; finalized copy persists in import_resolutions | APPLIED, SUPERSEDED | Raw source не изменяет | imports |
| InventorySnapshot | snapshot_id, public_id, session, cutoff, approved_by/at, source/import hash | active flag меняется через supersede record | Items, cutoff, approval | APPROVED, SUPERSEDED | Approved immutable; ровно один active | inventory |
| InventorySnapshotItem | item_id, snapshot, row link, stock subject, location, condition, quantity_minor | Нет | Все | Immutable | Equipment xor catalog; serialized quantity=1 | inventory |
| InventoryCycleCount | cycle_count_id, approved PARTIAL session, scope, checksum | Нет | Все | Immutable approved result | Никогда не является baseline и не меняет projection | inventory |
| InventoryCycleCountItem | item_id, cycle count, row link, stock subject, location, quantity_minor | Нет | Все | Immutable | Только evidence/reconciliation в пределах scope | inventory |
| WarehouseTransaction | ledger_sequence, public_id, kind, idempotency key, actor, occurred/posted time | Только draft DTO до post | Posted header and sequence | POSTED; reversal — отдельная POSTED transaction kind=REVERSAL | Posted UPDATE/DELETE запрещен | warehouse |
| WarehouseTransactionLine | line_id, transaction, line_no, subject, quantity, from/to, condition | Нет после post | Все posted fields | Immutable | Positive quantity; kind-specific locations | warehouse |
| BalanceProjection | version_id + stock key rows, snapshot, applied sequence, checksum | Active rows sync update; version activation | Historical version manifest | BUILDING, READY, ACTIVE, FAILED, RETIRED | Derived; lag active version = 0 | balance |
| LegacyHistoryEvent | event_id, source row key, type, identity raw/key, actor raw/quality, date/quality, source coordinates, raw payload | Только optional equipment link via additive resolution | Source facts | IMPORTED, QUARANTINED, EXCLUDED | Не влияет на snapshot/ledger/projection | legacy history |
| ImportCommit | import_commit_id, source hash, manifest/digest, parser versions, approved actor/time | Нет | Все | COMMITTED | Один commit на approval idempotency key | imports |
| ImportRowLink | commit + source row key, target type/id, transform version | Нет | Все | Immutable | Source row linked at most once per commit | imports |
| AuditEvent | audit_event_id, action, actor snapshot, timestamp, correlation, subject, details | Нет | Все | Immutable | В той же UoW с critical write | audit |
| ReferenceDomain | domain_id, code, semantics | display/active | code | ACTIVE, INACTIVE | One owner and normalization rule | references |
| ReferenceValue | value_id, domain, code, display, scope, status, provenance | display/status via audited command | ID/code after use | PENDING, APPROVED, REJECTED, INACTIVE, MERGED | Read не создает value | references |
| ReferenceAlias | alias_id, domain, raw/key, target, provenance, status | review status | raw/provenance | PENDING, APPROVED, REJECTED, RETIRED | No semantic auto-merge | references |

## Value objects

| Value object | Состав и правило |
|---|---|
| PublicId | UUIDv7 text at API boundary; immutable |
| SerialRaw | Exact source text, including leading zeros and punctuation |
| SerialKey | Unicode NFKC, outer trim, locale-independent uppercase; internal spaces/hyphens retained |
| InventoryNumberKey | Same conservative normalization; globally scoped |
| PartNumber | Raw + conservative key, scoped by vendor |
| Quantity | quantity_minor INTEGER + Uom.scale; never binary float |
| LedgerSequence | Monotonic INTEGER assigned at post inside writer transaction |
| LedgerCutoff | Exact maximum posted sequence captured by inventory freeze |
| SourceCoordinate | source_file_id, sheet name, one-based row and optional cell |
| ContentHash | SHA-256 bytes; rendered lower-case hex |
| DateWithQuality | occurred_at_us nullable, raw, EXACT/MISSING/ESTIMATED/CORRUPTED, estimation_basis |
| ActorSnapshot | user_id nullable for legacy, display_name_raw, quality, role snapshot |
| StockSubject | Exactly one of equipment_id or catalog_item_id/lot |
| StockKey | subject + warehouse + location + condition + lot |
| CorrelationId | UUIDv7 common to API, domain, audit and filesystem operation |
| IdempotencyKey | Client scoped opaque string, unique with command scope/principal |

## Equipment identity rules

S/N не гарантирован глобально производителями. Active serial identity уникальна
в vendor scope. Inventory Number уникален глобально внутри ODE. Exact lookup по
одному S/N может вернуть несколько Equipment из разных vendor scopes; API
возвращает ambiguous result, а не выбирает.

Пустой S/N:

- допустим для bulk, потому что Equipment не создается;
- для serialized Equipment допустим только при непустом уникальном Inventory
  Number и явной resolution MISSING_SERIAL;
- если отсутствуют оба идентификатора, approval блокируется.

Case-only варианты дают одинаковый SerialKey и finding. Внутренние пробелы и
дефисы не удаляются; similarity key может использоваться только для Preview.
Leading zeros сохраняются. Numeric/scientific/formula Excel cells для identity
являются blocking finding: ODE не восстанавливает предполагаемый текст.

После baseline active identity не переписывается. Correction:

1. создает новую EquipmentIdentity;
2. переводит старую в RETIRED;
3. сохраняет reason, actor и source;
4. создает EquipmentIdentityChanged и AuditEvent;
5. не меняет legacy raw payload, snapshot или posted ledger.

Merge двух Equipment разрешен admin после preview последствий. Создается
EquipmentMerge, source получает lifecycle MERGED и redirect на survivor.
Исторические ссылки не переписываются. Если обе сущности имеют активный остаток,
коррекция оформляет связанные ADJUSTMENT_OUT/ADJUSTMENT_IN с нулевым net total.
Это application-enforced aggregate rule: use case проверяет active projection,
subjects, kinds и zero-net внутри одного UoW. DDL хранит обе sequence FK и
требует их совместную nullability, а verification gate обнаруживает остаток без
пары; schema сама не вычисляет business net эффекты merge.

Полное решение закреплено в
[ADR-006](../decisions/ADR-006-equipment-identity.md).

## Inventory authority handoff

До atomic publish authoritative aggregate хранится в Preview workspace.
После успешного replace authoritative APPROVED InventorySession и Snapshot
хранятся в operational DB; workspace становится immutable evidence и затем
удаляется по retention. Одновременно authoritative копий одного статуса нет.

## Aggregate boundaries

- Equipment aggregate: Equipment + active identities + merge state.
- Inventory approval aggregate: session + snapshot + items + reconciliation,
  публикуемый одним candidate transaction.
- Ledger aggregate: один transaction header + lines + projection delta + audit.
- Reference aggregate: domain/value/alias command.
- Security aggregate: session command.

Большие snapshot items не загружаются в память как object graph; application
use case обрабатывает их потоково через typed batch port, сохраняя aggregate
invariants на уровне команды и DDL.
