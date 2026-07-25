# ODE 0.13 — response to independent DDL review

Статус: **FINAL RESPONSE — approval gate 2026-07-15**

Этот документ отвечает на findings, но не заменяет и не изменяет immutable
evidence [INDEPENDENT_REVIEW.md](INDEPENDENT_REVIEW.md) и
`independent-review-repro.sql`.

## Baseline и метод

- branch/HEAD/origin/main: `main` /
  `76afadd5355f4d379b19dcabf1f28850986d5300` /
  `76afadd5355f4d379b19dcabf1f28850986d5300`;
- production DB открывалась только как `mode=ro&immutable=1`;
- production SHA-256 до gate:
  `73568a1c3eecbd4476473f064620d7f0a196b336ce8ea6d834c5b99359d4b010`;
- review SHA-256: `INDEPENDENT_REVIEW.md` =
  `e7dd86cbc180139ae170c7ff2c432b14a94c83d69b23063f60bcdc8f0e4b4715`,
  repro =
  `b1652d2bdc98a457be3f0d5041657f03ce005a90fc54544f09c86e2356db95f6`;
- каждый repro повторен на независимых временных SQLite DB;
- V001–V008 дважды собраны с registry, затем выполнены schema, negative,
  domain, rebaseline, hierarchy и query-plan gates.

## Verdict summary

| Finding | Verdict | Root cause | Решение | Remaining risk |
|---|---|---|---|---|
| 1, legacy/catalog partial indexes | CONFIRMED | `col = ?` не доказывает `col <> ''` | Полный legacy lookup index; отдельный полный catalog lookup index | Нестандартный `NOCASE` не соответствует BINARY key contract |
| 2, parent cycles | CONFIRMED | Self-FK и same-scope FK не доказывают acyclic graph | DB triggers для domain/warehouse и bounded ancestor traversal | Restore обязан валидировать source graph до publish |
| 3, UOM reconciliation | CONFIRMED | Один authoritative consumer отсутствовал в trigger | Добавлен шестой `EXISTS` | Новые UOM consumers должны добавляться в explicit coverage |
| 4, reversal after rebaseline | CONFIRMED | Корректное DDL-поведение не было API/UX contract | Отдельный code и forward-correction contract | Runtime ещё не реализован |
| 4b, successor PK | CONFIRMED | Reserved-ID ordering был только в proof comment | Normative reserved-ID flow в ADR/transaction model | Runtime ещё не реализован |
| 5, merge adjustments | CONFIRMED | Cross-aggregate invariant намеренно не выражен DDL | Явный application contract + invariant detector | Runtime command test обязателен в Stage 0.13.1 |
| 6, Argon2id wording | CONFIRMED | Format CHECK был сформулирован шире реальной гарантии | DB/application/operations guarantees разделены | Library/profile выбираются при implementation |
| 7, `PARTIAL_INVENTORY` | CONFIRMED | Prose enum отстал от DDL | Enum синхронизирован | Нет |
| 8, verification coverage | CONFIRMED | Count threshold не доказывал набор triggers | Explicit trigger lists и hierarchy invariant queries | Lists обновляются вместе с schema |

`PARTIALLY_CONFIRMED`: нет. `NOT_REPRODUCED`: нет. `REJECTED`: нет.

## Finding 1 — exact legacy S/N и catalog lookup

### Собственный repro

Исходный индекс имел `WHERE serial_key <> ''`. Обычный parameterized
`WHERE serial_key = ?1` не доказывал partial predicate и давал table `SCAN`.
После исправления V004 содержит:

```sql
CREATE INDEX ix_legacy_history_serial
ON legacy_history_events(serial_key, occurred_at_us, event_id);
```

На `100001` synthetic legacy rows до и после `ANALYZE`:

```text
SEARCH legacy_history_events USING INDEX ix_legacy_history_serial (serial_key=?)
```

План одинаков для parameter, literal и explicit `COLLATE BINARY`. Ordering
`occurred_at_us, event_id` удовлетворяется индексом: `USE TEMP B-TREE FOR
ORDER BY` отсутствует. `LIMIT` не меняет access path. Явный `COLLATE NOCASE`
намеренно не green: он даёт index scan и temp sort, потому что canonical keys и
DDL используют BINARY collation. API не разрешает подменять collation query.

Catalog partial UNIQUE сохранён как integrity constraint. Для production
vendor/part lookup добавлен:

```sql
CREATE INDEX ix_catalog_items_vendor_part_lookup
ON catalog_items(vendor_scope_key, part_number_key, status, catalog_item_id);
```

План: `SEARCH ... USING COVERING INDEX
ix_catalog_items_vendor_part_lookup`.

### Изменения и proof

- DDL: V002, V004;
- proof: `explain_query_plans.sql`;
- regression: parameter/literal/BINARY, ordering/LIMIT, before/after ANALYZE,
  100001 rows;
- архитектура/совместимость: domain model не меняется; миграция создаёт два
  lookup indexes; write/storage cost немного возрастает, exact read перестаёт
  быть O(N).

## Полный аудит partial indexes

Ни один green plan не использует `INDEXED BY`. `SEARCH` на маленькой таблице
после `ANALYZE` не является обязательным: planner вправе выбрать малый scan;
ни один exact production lookup не зависит от такого случая.

| Index | Production predicate/use | Implication и plan | Решение |
|---|---|---|---|
| `ux_users_email_key` | uniqueness; login uses `login_key` | `email_key=?` не доказывает `length>0` | Constraint-only, без изменения |
| `ux_user_roles_active` | grant conflict, `revoked_at_us IS NULL` | Predicate exact | Оставлен |
| `ix_user_roles_role_active` | active members by role + `IS NULL` | Predicate exact; SEARCH on representative rows | Оставлен |
| `ix_sessions_user_active` | live sessions + `revoked_at_us IS NULL` | Predicate exact; SEARCH | Оставлен |
| `ix_reference_values_parent` | `parent_value_id=?` | Equality implies `IS NOT NULL`; SEARCH | Оставлен |
| `ux_catalog_items_vendor_part` | approved/inactive uniqueness | Natural lookup does not imply `<> ''` | Constraint retained; full lookup index added |
| `ux_equipment_serial_active` | active serial uniqueness | Kind/status predicates exact | Constraint retained; reads use full exact index |
| `ux_equipment_inventory_active` | active inventory-number uniqueness | Kind/status exact | Constraint retained; reads use full exact index |
| `ux_equipment_identity_alias_active` | active alias uniqueness/resolve | Status exact | Оставлен |
| `ux_inventory_snapshot_active` | current snapshot, `is_active=1` | Predicate exact; SEARCH | Оставлен |
| `ux_snapshot_item_equipment` | serialized item equality | Equality implies non-null | Constraint retained |
| `ux_snapshot_item_bulk_key` | bulk item equality | Equality implies non-null | Constraint retained |
| `ux_reconciliation_equipment` | serialized reconciliation equality | Equality implies non-null | Constraint retained |
| `ux_reconciliation_bulk` | bulk reconciliation equality | Equality implies non-null | Constraint retained |
| `ix_ledger_lines_equipment` | ledger by equipment | Equality implies non-null; SEARCH | Оставлен |
| `ix_ledger_lines_catalog` | ledger by catalog | Equality implies non-null; SEARCH | Оставлен |
| `ix_ledger_lines_from_location` | outbound/location stream | Equality/range excludes null; SEARCH | Оставлен |
| `ix_ledger_lines_to_location` | inbound/location stream | Equality/range excludes null; SEARCH | Оставлен |
| `ux_projection_active` | active projection, `build_status='ACTIVE'` | Predicate exact | Оставлен |
| `ux_projection_equipment_key` | equipment projection key | Equality implies non-null | Constraint retained |
| `ux_projection_bulk_key` | bulk projection key | Equality implies non-null | Constraint retained |
| `ix_projection_equipment` | projection by equipment | Equality implies non-null; SEARCH | Оставлен |
| `ix_projection_catalog_location` | catalog/location projection | Equality implies non-null; SEARCH | Оставлен |

## Finding 2 — hierarchy anti-cycle

V002 добавляет `BEFORE INSERT/UPDATE` triggers:

- `trg_location_parent_acyclic_insert/update`;
- `trg_reference_parent_acyclic_insert/update`;
- `trg_reference_parent_domain_insert/update`;
- существующая same-warehouse защита расширена: смена warehouse у parent с
  детьми также отклоняется.

Ancestor CTE использует `UNION`, поэтому множество ограничено числом distinct
rows и завершается даже на уже corrupted cycle. Trigger отклоняет candidate ID
в ancestor set и ancestor component без root. Он не изменяет rows, не вызывает
recursive trigger loop, пропускает `NULL` parent и допускает bulk load
parent-before-child.

Negative suite на обеих сборках: `9/9` rejection — self, 2-node, 3-node и
cross-scope для обеих иерархий плюс смена warehouse у parent с детьми. После
каждого: `integrity_check=ok`, FK=`0`, roots не изменены. Отдельный corrupted
ancestor probe отклонил нового location/value, указывающего внутрь заранее
созданного cycle. Rename/deactivate/alias scenario прошёл и был rolled back.

`verify_domain_invariants.sql` содержит bounded recursive cycle queries и
cross-domain/cross-warehouse queries. Restore/migration сначала выполняет эти
queries и не публикует invalid candidate; runtime protection не отключается.

Влияние: DB invariant усиливается; V002 требует schema migration; обычный
parent write получает bounded ancestor lookup, read/API compatibility не
меняется.

## Finding 3 — UOM immutability

`trg_uom_scale_immutable_after_use` теперь учитывает
`inventory_reconciliation_items`. На обеих DB UOM, использованный только там
(`0` uses в остальных пяти consumers), не позволил изменить scale:
`used UOM dimension and scale are immutable`; scale остался `3`, integrity/FK
— `ok/0`. Влияние ограничено V008 и корректным отклонением ранее опасного
update.

## Finding 4 — reversal после rebaseline

DDL не изменён. Normative contract: REVERSAL разрешён только для transaction
текущего active baseline. После FULL rebaseline старые snapshot и ledger
immutable; исправление фактического состояния — новая `ADJUSTMENT_IN`,
`ADJUSTMENT_OUT` или `TRANSFER` под новым baseline. Ledger и lineage не
пересчитываются.

Stable application/API code: `REVERSAL_OUTSIDE_ACTIVE_BASELINE`.
`REVERSAL_UNSAFE` сохранён для иной причины — exact inverse нельзя доказать в
том же baseline.

Proof: receipt sequence 1 под snapshot 1; FULL snapshot 2; обе попытки старого
reversal отклонены; adjustment sequence 5 под snapshot 2 разрешён; truth и
projection совпадают (`difference=0`), history показывает оба факта.

Изменены ledger/transaction/API/UI contracts, ADR-010 и correction sequence.
Миграция/производительность/DDL не меняются; runtime должен отобразить stable
code и explanatory correction choices.

## Finding 4b — reserved successor snapshot ID

Normative owner — inventory approval service. Под external publish lock:

1. `BEGIN IMMEDIATE` в candidate;
2. recheck active snapshot, ledger head и idempotency;
3. reserve следующий internal INTEGER `snapshot_id`;
4. supersede старый snapshot со ссылкой на reserved ID;
5. insert successor с этим ID, затем immutable items/reconciliation/projection;
6. update `app_state`, audit и session facts;
7. domain/FK checks и `COMMIT`.

Public UUID генерируется отдельно. Новый active row нельзя вставить первым из-за
partial UNIQUE; post-insert AUTOINCREMENT flow поэтому непригоден. Deferred FK
безопасен: missing successor отклоняется на COMMIT. SQLite single writer,
publish lock и stale recheck исключают concurrent reservation. Rollback
отменяет reservation; retry снова выполняет stale/idempotency checks.

Proof: active-first и missing-successor rejected; reserved sequence succeeded;
intermediate rollback восстановил old active и не оставил successor; duplicate
key и stale observed snapshot rejected; все clone DB остались `ok/0`.

## Findings 5–8

| Finding | Changed files | Regression proof | Remaining risk |
|---|---|---|---|
| 5 | `domain-model.md`, `transaction-model.md`, `verify_domain_invariants.sql` | Invalid merge detected as `1`; transaction rollback leaves `0` merge rows | Stage 0.13.1 command implementation/test |
| 6 | `security.md`, `data-model.md` | Plaintext negative remains rejected; wording audit separates three guarantee levels | Approved runtime library/profile selection |
| 7 | `data-model.md` | Prose enum contains the four V005 values | None |
| 8 | `verify_schema.sql`, `verify_domain_invariants.sql` | Both fresh builds pass explicit 9-index, 43-immutability-trigger and 8-hierarchy-trigger lists; hierarchy invariants return zero | Lists must change atomically with future schema |

### Merge и paired adjustments

Repro подтвердил, что DDL допускает merge source с active balance и `NULL`
adjustment references; invariant query обнаружил `1` violation, rollback
оставил `0` merge rows. Решение не добавляет дорогой cross-aggregate trigger:
merge command обязан в одном UoW создать paired `ADJUSTMENT_OUT/IN` с zero net,
записать обе sequences и audit. Это явно application-level guarantee;
verification query выявляет invalid committed candidate. Remaining risk —
runtime implementation и command regression test Stage 0.13.1.

### Argon2id

SQLite гарантирует только non-empty/no-default и `$argon2id$...` format.
Application library гарантирует реальную verification, versioned
memory/time/parallelism profile, rehash policy и constant-time API.
Operations отвечают за bootstrap/rotation, backup и secret handling.

### Enum и verification coverage

`PARTIAL_INVENTORY` добавлен в prose import enum. Count-based trigger gate
заменён explicit required-name list; добавлены hierarchy trigger coverage и
cycle/scope invariants.

## Changed artifacts и regression proof

DDL: V002, V004, V008. Status header/checksum изменился во всех V001–V008.
Proof SQL: `explain_query_plans.sql`, `verify_schema.sql`,
`verify_domain_invariants.sql`, `synthetic_rebaseline_correction_proof.sql`.
Architecture/ADR/API/UI/migration docs перечислены в final review result.

Две clean schema имеют `41` tables, `73` indexes, `73` triggers, `3` views и
одинаковый `.schema` SHA-256
`143bb0ae16c68c1fcd653ecc94adc62464746fed738ebfa47749057380f7f0cb`.
Оставшихся CRITICAL/HIGH findings нет; runtime implementation этим gate не
начат.
