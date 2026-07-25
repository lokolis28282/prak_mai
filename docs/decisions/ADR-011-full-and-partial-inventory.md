# ADR-011: Full и partial inventory

Статус: **APPROVED**

## Context

Partial cycle count полезен для проверки, но не доказывает global stock state.

## Decision

- Первый baseline: только scope_type=FULL.
- Последующие active baselines: только APPROVED FULL snapshot.
- FULL охватывает все active warehouses/locations, включенные в утвержденный
  inventory boundary; в 0.13 boundary глобальный для deployment.
- PARTIAL определяет warehouse/location/category filters и создает immutable
  cycle_count_result/items/reconciliation.
- PARTIAL никогда не создает InventorySnapshot, не меняет active_snapshot_id,
  cutoff или projection.
- Missing item в FULL — reconciliation MISSING и требует resolution.
- Missing вне PARTIAL scope не является finding; внутри scope — cycle-count
  discrepancy, но не balance delta.
- Partial approval требует INVENTORY_APPROVE; adjustment — отдельная admin
  command после review.

## Alternatives

Partial baseline; partial auto-adjustment; запрет partial counts.

## Consequences

Нельзя случайно заменить global baseline; partial дает evidence без скрытой
проводки.

## Rejected options

Partial baseline/auto-adjustment разрывают global formula; полный запрет лишает
операторов полезной проверки.

## Migration impact

Старые partial/number imports не становятся snapshots.

## Security impact

Scope/digest/actor immutable; adjustment требует отдельного permission/audit.

## Performance impact

Cycle count indexes scope/location; projection не rebuild.

## Rollback impact

Partial result additive и balance-neutral; удаление не нужно.

## Approval status

Утверждено как часть ODE 0.13 architecture baseline. DDL CHECK/trigger решение
закрыто.
