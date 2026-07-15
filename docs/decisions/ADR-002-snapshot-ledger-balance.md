# ADR-002: Snapshot + ledger как источник баланса

Статус: **APPROVED**

## Context

Legacy movements не доказывают opening balance. Физическая инвентаризация
создает достоверное состояние, а последующие движения — дельты.

## Decision

До active APPROVED FULL snapshot баланс NOT_INITIALIZED и posting запрещен.
Истина: active snapshot + POSTED ledger с sequence > cutoff. Новый FULL
snapshot supersedes предыдущий; reconciliation объясняет, но не проводит delta.

### Atomic successor contract

Successor FULL snapshot публикуется только в candidate DB под external publish
lock и `BEGIN IMMEDIATE`. Inventory approval service владеет выделением
internal ID: после повторной проверки active snapshot/ledger head он резервирует
следующий свободный `snapshot_id`, supersedes старый snapshot со ссылкой на этот
ID, вставляет successor с зарезервированным ID, items, projection, `app_state` и
audit, выполняет FK/domain checks и только затем COMMIT.

`snapshot_id` — internal INTEGER PK; independently generated public UUID остается
API/audit identity. Вставка нового active snapshot первой невозможна из-за
partial UNIQUE active constraint, поэтому post-insert AUTOINCREMENT allocation
не является допустимым flow. `superseded_by_snapshot_id` является deferred FK:
промежуточная ссылка на reserved ID допустима только внутри transaction, а
COMMIT без successor отклоняется.

Concurrent approval исключается external publish lock, SQLite single writer и
stale snapshot/head validation. Rollback отменяет reservation и все mutations;
retry повторяет stale/idempotency checks. Уже committed approval с тем же key
возвращает исходный result, а stale concurrent request отклоняется.

## Alternatives

Legacy opening state; нулевой баланс; вечный первый snapshot с adjustments;
partial baseline.

## Consequences

Баланс воспроизводим; хранится несколько immutable snapshots; ровно один active.
Ledger старого baseline после supersession остается immutable history, но не
участвует в truth нового baseline.

## Rejected options

Legacy/zero/partial отклонены как недоказуемые. Hidden adjustment отклонен как
утрата объяснимости.

## Migration impact

stock_receipts/issues не мигрируют в ledger. Первый baseline только из нового
approved XLSX.

## Security impact

Approval требует permission, actor snapshot, audit и candidate validation.

## Performance impact

Projection обязателен для чтения; truth rebuild потоковый.

## Rollback impact

До writes — whole DB rollback; после writes требуется freeze и business decision.

## Approval status

Утверждено как часть ODE 0.13 architecture baseline. DDL blocker: нет.
