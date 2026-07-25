# ADR-012: Balance projection update model

Статус: **APPROVED**

## Context

Projection ускоряет чтение, но asynchronous lag усложняет локальный single-DB
correctness.

## Decision

Active projection обновляется синхронно в той же UoW, что ledger/snapshot
activation/audit. Видимый lag=0. Rebuild создает BUILDING shadow version,
проверяет canonical checksum, догоняет tail под writer lock и атомарно
переключает app_state. Projection rows разрешено очищать/rebuild; truth rows
immutable.

## Alternatives

Async worker/Kafka; calculate balance on every read; in-place rebuild.

## Consequences

Write latency включает indexed projection delta; failure откатывает ledger.

## Rejected options

Async допускает stale balance; read aggregation не масштабируется; in-place
rebuild лишает verified active version.

## Migration impact

Initial projection строится только из approved physical snapshot; legacy
tables не input.

## Security impact

Inconsistent projection blocks writes; rebuild/activation audited.

## Performance impact

O(lines) runtime updates, indexed reads, streaming shadow rebuild.

## Rollback impact

UoW rollback сохраняет old projection; failed rebuild не активируется.

## Approval status

Утверждено как часть ODE 0.13 architecture baseline. DDL blocker: нет.
