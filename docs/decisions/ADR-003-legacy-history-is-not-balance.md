# ADR-003: Legacy history не является балансом

Статус: **APPROVED**

## Context

ODE 0.12 преобразовала старые Excel rows в receipts/issues, но новая модель
использует их только для расследования.

## Decision

Каждая source row становится immutable LegacyHistoryEvent с source coordinates,
raw payload, actor/date quality и warnings. У legacy tables нет FK, trigger или
query path к snapshot, ledger и projection. Equipment link отдельный и
поисковый.

## Alternatives

Перенести old movements в ledger; вычислить opening state; оставить только
исходные файлы без query model.

## Consequences

Поиск быстрый и provenance полный; старое количество не влияет на stock.

## Rejected options

Ledger/opening state нарушают утвержденный инвариант; file-only archive не
обеспечивает поиск по S/N.

## Migration impact

71 360 reconciliation rows классифицируются как migrated/quarantined/excluded;
stock tables служат только cross-check.

## Security impact

Legacy PII минимальна: raw actor/code, без password/user binding.

## Performance impact

Индекс serial_key/date/event; archive масштабируется независимо от balance.

## Rollback impact

Old DB/source files остаются immutable evidence.

## Approval status

Утверждено как часть ODE 0.13 architecture baseline. DDL blocker: нет.
