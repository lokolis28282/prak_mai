# ADR-006: Equipment identity

Статус: **APPROVED**

## Context

S/N не гарантирован глобально, Excel портит numeric identifiers, а correction и
merge не должны терять историю.

## Decision

- Equipment имеет INTEGER PK и public UUID.
- Active S/N unique по (kind=SERIAL_NUMBER, scope_key, normalized_key).
- scope_key = VENDOR:{reference_value_id}; неизвестный vendor = UNSCOPED.
- В UNSCOPED одновременно active может быть только один одинаковый serial;
  остальные остаются CONFLICT/UNVERIFIED до resolution.
- Inventory Number active unique в GLOBAL scope.
- Пустой S/N не создает identity row. Serialized Equipment требует хотя бы S/N
  или Inventory Number; cross-row invariant проверяется verification gate.
- SerialKey: NFKC, outer trim, invariant uppercase; internal spaces/hyphens и
  leading zeros сохраняются.
- Bulk/cable без individual identity представлены CatalogItem, не Equipment.
- Correction создает новую identity row, старую retires; immutable raw/key не
  UPDATE.
- Alias хранится отдельно; merge создает redirect и не переписывает history.

## Alternatives

Global S/N; vendor+S/N без unknown namespace; punctuation-stripped key; mutable
identity; automatic merge.

## Consequences

Exact lookup может быть AMBIGUOUS между vendors. Duplicate unknown serial
блокирует baseline.

## Rejected options

Global/stripped keys создают false merge; mutable/automatic merge теряет
provenance.

## Migration impact

Legacy identifiers не создают Equipment; physical inventory создает identities.
Old raw serial evidence сохраняется в history.

## Security impact

Correction/merge только admin+reauth, actor/reason/audit.

## Performance impact

Partial unique indexes exact lookup; aliases имеют отдельный index.

## Rollback impact

Correction is additive; DB rollback whole UoW. Merge rollback — explicit
reverse correction, не history rewrite.

## Approval status

Утверждено как часть ODE 0.13 architecture baseline. PK/UNIQUE/CHECK решение
закрыто; DDL blocker отсутствует.
