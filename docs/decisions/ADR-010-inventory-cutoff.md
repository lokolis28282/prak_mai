# ADR-010: Inventory cutoff strategy

Статус: **APPROVED**

## Context

Физический XLSX count должен описывать один доказуемый stock state. Движение
между count и approval создает риск двойного учета.

## Alternatives

### A. Полный freeze

- Correctness: ledger head фиксируется до count; physical/software movements
  запрещены; snapshot effective_at = freeze_started_at.
- UX: склад временно недоступен, но правило понятно.
- Complexity: низкая.
- Double-count risk: минимальный.
- Excel: count interval и warehouse code.
- Operator: закрыть pending documents, начать freeze, завершить/approve.
- Rollback: abort session, release freeze, restart count.
- First baseline: полностью применимо; posting уже disabled.

### B. effective_at + movements during count

- Correctness: требует per-row counted_at и replay каждого movement.
- UX/Excel: сложный scan timestamp и reconciliation.
- Complexity/risk: высокие, late/missing timestamp вызывает double count.
- Rollback: сложный event replay.
- First baseline: неприменимо без существующего ledger.

### C. Freeze по zone/location

- Correctness: нужен scoped cutoff и запрет cross-zone transfer.
- UX: склад частично работает.
- Complexity/risk: высокие; one transaction пересекает scopes.
- Excel: точные zone windows.
- Rollback: per-zone state machine.
- First baseline: неоправданно.

## Decision

ODE 0.13 использует A для первого и всех FULL baselines. Freeze record внешний,
operational DB до approval не меняется. Cutoff = current ledger head at
freeze_started_at; effective_at_us = freeze_started_at_us. Head обязан остаться
неизменным до publish.

Physical emergency movement отменяет session и требует нового count. Late
operation с occurred_at <= effective_at не postится как обычная delta: она
сохраняется в late_operation_evidence; balance correction, если нужна,
оформляется отдельным adjustment после physical verification. Это исключает
двойной учет.

REVERSAL допустим только для transaction текущего active baseline. После
successor FULL snapshot прежние transactions остаются immutable evidence, но их
дельты уже поглощены новым physical count. Попытка reversal получает
`REVERSAL_OUTSIDE_ACTIVE_BASELINE`. Исправление текущего состояния оформляется
новой ADJUSTMENT_IN, ADJUSTMENT_OUT или TRANSFER под новым baseline с reason,
physical evidence и audit; старый ledger и snapshot lineage не переписываются.

## Consequences

Нужен operational owner freeze и процедура pending documents.

## Rejected options

B/C отклонены для 0.13 по complexity/correctness; могут получить новый ADR.

## Migration impact

Первый cutoff=0. Legacy operations не являются late new ledger.

## Security impact

Freeze start/release/abort и late evidence требуют actor/reason/audit.

## Performance impact

Нет temporal replay; approval/rebuild проще.

## Rollback impact

До publish session abort; после publish whole DB rollback policy.

## Approval status

Утверждено для ODE 0.13. Перед первой реальной инвентаризацией всё ещё требуется
operational owner freeze, но DDL/architecture решение закрыто.
