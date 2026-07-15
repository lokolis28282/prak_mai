# Warehouse Ledger

Статус: **APPROVED — ODE 0.13 architecture baseline**

Ledger начинается только после active APPROVED snapshot. Legacy history и
reconciliation не создают ledger lines.

## Общие поля

Каждая команда содержит idempotency key, occurred_at, comment/source document,
actor principal и lines. На post сервер присваивает monotonic ledger_sequence,
posted_at, active_snapshot_id и correlation ID. sequence может иметь gaps после
rollback, но никогда не уменьшается и определяет cutoff ordering.

Lines используют положительное quantity_minor. Знак и location effect
определяются kind:

| Kind | From | To | Balance effect | Permission | Дополнительные проверки |
|---|---|---|---|---|---|
| RECEIPT | null | required | +Q at To | WAREHOUSE_RECEIPT | Supplier/source doc policy; subject identity valid |
| ISSUE | required | null | -Q at From | WAREHOUSE_ISSUE | Available Q >= requested; recipient/reason |
| TRANSFER | required | required, different | -Q From, +Q To; global net 0 | WAREHOUSE_TRANSFER | Same subject/UOM; both active |
| ADJUSTMENT_IN | null | required | +Q at To | WAREHOUSE_ADJUST | Reason/evidence required |
| ADJUSTMENT_OUT | required | null | -Q at From | WAREHOUSE_ADJUST | Available Q; reason/evidence |
| REVERSAL | Exact inverse | Exact inverse | Negates original transaction | WAREHOUSE_REVERSE | Target exists, not already reversed, same full line set |

Serialized Equipment имеет одну line, quantity=1 base unit и не может
одновременно находиться в двух locations. Bulk/cable допускает несколько lines.

## State

Ledger не хранит draft. Client draft находится в UI, а POST либо атомарно
создает POSTED transaction, либо ничего. Posted header/lines не UPDATE и не
DELETE. Исходная transaction не получает mutable REVERSED status: новая
REVERSAL ссылается на нее.

## Validations

Внутри write UoW:

1. app_state ACTIVE, external inventory freeze отсутствует;
2. permission и reauthentication policy;
3. idempotency key lookup;
4. active snapshot/fingerprint совпадает с request precondition;
5. equipment/catalog/UOM/location active;
6. identities не CONFLICT/MERGED;
7. line semantics соответствуют kind;
8. balance availability проверена на active projection;
9. occurred_at валиден и не используется вместо posted ordering;
10. duplicate subject lines canonicalизируются либо отклоняются;
11. projection delta не создает negative quantity;
12. audit payload построен до commit.

Request может передать expected_projection_version и expected_last_sequence.
Несовпадение возвращает STALE_STATE; server не пересчитывает намерение клиента.

## Reversal

REVERSAL всегда полный для одной original transaction. Она:

- копирует subject, quantity и conditions;
- меняет from/to местами;
- получает собственные actor, reason, time, idempotency key и sequence;
- имеет UNIQUE reverses_ledger_sequence;
- не может ссылаться на REVERSAL;
- не разрешается, если inverse приведет к negative balance или serialized
  equipment после исходной операции уже перемещено.

REVERSAL разрешен только для original transaction, записанной под тем же
`active_snapshot_id`, который активен в момент команды. После публикации нового
FULL baseline предыдущий ledger остается immutable history, но его строки уже
поглощены новым физическим snapshot и не входят в текущую balance formula.
Поэтому reversal старой transaction отклоняется стабильным API code
`REVERSAL_OUTSIDE_ACTIVE_BASELINE`; старый ledger и snapshot lineage не
пересчитываются и не переписываются.

Если exact reversal невозможен из-за последующих движений, admin создает
явные ADJUSTMENT_IN, ADJUSTMENT_OUT или TRANSFER с physical evidence и
объяснением. То же правило применяется после rebaseline: forward correction
описывает текущее физическое состояние, а не отменяет уже поглощенную delta.
История показывает original transaction, новый FULL snapshot и correction.

## Idempotency

Scope = permission code + principal public ID + endpoint. Повтор с тем же key и
тем же canonical request hash возвращает original 200/201. Тот же key с другим
hash возвращает IDEMPOTENCY_KEY_REUSED. Keys хранятся в transaction header
permanently.

## Transaction boundary

В одной SQLite write transaction:

    validate current state
    insert transaction header and lines
    apply projection delta
    update app_state.last_ledger_sequence
    append audit event
    commit

Любая ошибка откатывает все пять действий. Event
LedgerTransactionPosted публикуется синхронно внутри UoW; внешнее уведомление,
если появится, формируется после commit из outbox будущей версии.

## Cutoff

Ledger cutoff — последнее committed ledger_sequence при создании full inventory
freeze. Approval требует, чтобы current head равнялся cutoff. Новый snapshot
заменяет расчетную основу, а lines с sequence <= cutoff остаются immutable, но
не участвуют в балансе нового active snapshot.

Sequence diagrams:
[receipt](diagrams/receipt-sequence.md),
[issue](diagrams/issue-sequence.md),
[correction](diagrams/correction-sequence.md).
