# ADR-007: Fixed-point quantity

Статус: **APPROVED**

## Context

REAL не дает точной арифметики для кабеля и bulk.

## Decision

quantity_minor INTEGER >0; UOM имеет dimension и immutable scale 0..6.
Serialized Equipment требует quantity_minor=1, UOM dimension COUNT, scale=0.
Bulk/cable используют CatalogItem и один UOM; rounding запрещен.

## Alternatives

REAL; decimal TEXT; per-row arbitrary scale.

## Consequences

Детерминированные sums/checksums; conversion overflow/scale validation required.

## Rejected options

REAL drift; TEXT медленнее и допускает неоднозначность; arbitrary scale ломает
aggregation.

## Migration impact

Legacy quantity сохраняется raw и не конвертируется в balance. Новый XLSX
должен точно представляться declared UOM scale.

## Security impact

Limits предотвращают integer overflow/abusive input.

## Performance impact

INTEGER indexes/sums эффективны.

## Rollback impact

Quantity write откатывается общей UoW; UOM scale после использования immutable.

## Approval status

Утверждено как часть ODE 0.13 architecture baseline. DDL blocker: нет.
