# ODE 0.13 DDL final review results

Статус: **APPROVED_FOR_IMPLEMENTATION — evidence 2026-07-15**

Это approval evidence для ODE 0.13 architecture baseline. DDL применялся
только к временным DB в `/tmp`; `data/warehouse.db` не изменялась. Runtime
implementation и Stage 0.13.1 не начинались.

## Baseline

| Fact | Value |
|---|---|
| branch | `main` |
| HEAD / origin/main | `76afadd5355f4d379b19dcabf1f28850986d5300` / same |
| production DB SHA-256 before | `73568a1c3eecbd4476473f064620d7f0a196b336ce8ea6d834c5b99359d4b010` |
| production size | `579461120` bytes |
| production mtime | `2026-07-15T11:45:53+0300` |
| production integrity/FK | `ok / 0` through `mode=ro&immutable=1` |
| WAL/SHM/journal | absent |

Worktree до gate уже был dirty и содержал unrelated product/data artifacts.
Изменения этого этапа ограничены разрешёнными DDL/proof/architecture/ADR/API/
UI/migration documents. Product Python, JavaScript/CSS и runtime layout не
редактировались.

## Clean schema builds

V001–V008 независимо применены к `/tmp/ode013-final-build1.db` и
`/tmp/ode013-final-build2.db`. Registry содержит exact final checksums.

| Gate | Build 1 | Build 2 |
|---|---|---|
| `.schema` SHA-256 | `143bb0ae16c68c1fcd653ecc94adc62464746fed738ebfa47749057380f7f0cb` | same |
| application_id | `1329874225` (`0x4F444531`) | same |
| user_version / registry | `8 / 8` | `8 / 8` |
| tables / indexes / triggers / views | `41 / 73 / 73 / 3` | same |
| integrity_check | `ok` | `ok` |
| foreign_key_check | `0` | `0` |
| REAL quantity columns | `0` | `0` |
| default credentials | `0` | `0` |
| exact-index/trigger coverage | PASS | PASS |

Final V001–V008 hashes опубликованы в [README.md](README.md). Любое изменение
байтов требует нового review/checksum.

Preview workspace также дважды собран отдельно: `7` tables, `7` indexes,
application_id `1329877079` (`0x4F445057`), user_version `1`, integrity/FK
`ok/0`. Unresolved finding query использует `SEARCH preview_findings USING
INDEX ix_preview_findings_page`.

## Independent findings

| Finding | Verdict | Resolution |
|---|---|---|
| CRITICAL partial exact lookup | CONFIRMED | legacy full ordered index + catalog full lookup index |
| CRITICAL hierarchy cycles | CONFIRMED | DB same-scope and bounded anti-cycle triggers |
| MEDIUM UOM reconciliation | CONFIRMED | reconciliation added to immutability trigger |
| HIGH reversal after rebaseline | CONFIRMED contract gap | stable API/UI/ADR forward-correction contract |
| HIGH successor snapshot PK | CONFIRMED implementation contract | normative reserved-ID sequence |
| MEDIUM merge adjustments | CONFIRMED application-contract gap | explicit one-UoW paired adjustment rule + invariant query |
| LOW Argon2id wording | CONFIRMED | DB/application/operations guarantees separated |
| LOW `PARTIAL_INVENTORY` mismatch | CONFIRMED | prose synchronized |
| LOW verification coverage | CONFIRMED | explicit trigger lists + hierarchy invariants |

`PARTIALLY_CONFIRMED`, `NOT_REPRODUCED` и `REJECTED`: нет.
Полный technical response находится в
[RESPONSE_TO_INDEPENDENT_REVIEW.md](RESPONSE_TO_INDEPENDENT_REVIEW.md).

## Constraint and hierarchy negatives

На каждой clean build выполнено:

- `26/26` general constraint rejections: authoritative immutability, FK,
  password format, identity/catalog rules, projection non-negative, serialized
  quantity, idempotency, storage key и UOM-after-use;
- `9/9` hierarchy rejections: location/reference self, 2-node, 3-node,
  cross-scope и смена warehouse у parent с детьми;
- `2/2` old-baseline reversal rejections.

Дополнительно на isolated clones: `4/4` successor negatives (active-first,
missing successor, repeated key, stale approval) и `2/2` references into a
pre-existing corrupted ancestor cycle. Итого `80/80` expected rejection
observations. После каждого hierarchy rejection root edges сохранились,
transaction была rolled back, integrity/FK = `ok/0`. Rename/deactivate/alias
не меняют hierarchy и прошли positive rollback scenario.

Reserved-ID intermediate rollback оставил snapshot 2 `APPROVED/active`, без
snapshot 3. Successful reserved-ID replacement доказан synthetic rebaseline.

## Synthetic domain and rebaseline proof

Обе DB дали одинаковый результат:

1. до первого FULL baseline — `NOT_INITIALIZED`;
2. snapshot 1 approved; receipt `+500`, issue `-200`, reversal `+200`, transfer;
3. truth/projection cable total `1500`, rebuild difference `0`;
4. legacy insert не изменил balance (`1501/1501` с serialized unit);
5. reserved-ID flow заменил snapshot 1 на snapshot 2 при ledger cutoff `4`;
6. reversal receipt старого baseline отклонён для old и active snapshot IDs;
7. `ADJUSTMENT_IN +100` под snapshot 2 разрешён;
8. truth/projection difference `0`; history содержит receipt под snapshot 1 и
   adjustment под snapshot 2;
9. все `verify_domain_invariants.sql` queries вернули `0`;
10. final integrity/FK = `ok/0`.

Merge probe отдельно подтвердил application boundary: DDL допускает merge с
active source balance без adjustment IDs, invariant query возвращает `1`, а
rollback не оставляет merge. Stage 0.13.1 обязан реализовать paired
`ADJUSTMENT_OUT/ADJUSTMENT_IN` и command test.

## Query-plan gate

Legacy gate использовал `100001` synthetic rows. До и после `ANALYZE`:

```text
SEARCH legacy_history_events USING INDEX ix_legacy_history_serial (serial_key=?)
```

Parameterized, literal и `COLLATE BINARY` exact lookup не имеют table `SCAN` и
`USE TEMP B-TREE FOR ORDER BY`. Explicit `NOCASE` не соответствует canonical
BINARY key contract и закономерно не green.

| Query | Plan/result |
|---|---|
| exact S/N / Inventory Number | covering `ix_equipment_identity_exact` SEARCH |
| equipment keyset page | `ix_equipment_lifecycle_page` SEARCH |
| legacy exact/history ordering | `ix_legacy_history_serial` SEARCH |
| catalog vendor/part | covering `ix_catalog_items_vendor_part_lookup` SEARCH |
| balance page | `ix_projection_balance_page` SEARCH |
| ledger by equipment | covering `ix_ledger_lines_equipment` SEARCH + PK |
| snapshot items | session/snapshot exact indexes + `ix_snapshot_items_page` on un-analyzed build |
| unresolved Preview findings | `ix_preview_findings_page` SEARCH |
| projection equipment page | `ix_projection_equipment` SEARCH |
| projection rebuild | intentional truth stream scan/GROUP BY |

Planner may scan a two-row table after `ANALYZE`; это не exact-lookup failure.
p95 не заявляется: reference machine и representative multi-million dataset не
утверждены.

## Security and documentation consistency

- SQLite проверяет только non-empty/no-default и Argon2id encoded prefix;
- real Argon2id verification/profile/rehash/constant-time library — application;
- rotation, backup protection и secret handling — operations;
- reversal code в API/UI/ledger/ADR: `REVERSAL_OUTSIDE_ACTIVE_BASELINE`;
- reserved successor order одинаков в transaction model и ADR-002;
- same-domain/same-warehouse acyclic guarantees одинаковы в DDL/data model;
- `PARTIAL_INVENTORY`, quantity/UOM, statuses и equipment identity enum
  согласованы.

## Formal conclusion

Оставшихся CRITICAL/HIGH findings нет. ADR-001–ADR-012 имеют статус
`APPROVED`; DDL — `APPROVED_FOR_IMPLEMENTATION`; комплект — ODE 0.13
architecture baseline. Runtime version не повышалась. Stage 0.13.1 может быть
начат только после отдельного пользовательского подтверждения.

## Production safety

Final `mode=ro&immutable=1` verification подтвердил SHA-256
`73568a1c3eecbd4476473f064620d7f0a196b336ce8ea6d834c5b99359d4b010`,
size `579461120`, mtime `2026-07-15T11:45:53+0300`,
`integrity_check=ok`, FK=`0` и отсутствие WAL/SHM/journal. Значения полностью
совпадают с baseline. Commit, push, migration, release и deployment не
выполнялись.
