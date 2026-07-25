# Balance Projection

Статус: **APPROVED — ODE 0.13 architecture baseline**

## Математический источник истины

Пусть S — active approved snapshot, c — его ledger cutoff, K — stock key,
qS(K) — quantity snapshot item, а Δ(T,K) — signed effect posted transaction.

    Truth(K, n) = qS(K) + Σ Δ(T, K), для c < T.sequence <= n

LegacyHistoryEvent, old stock_receipts/stock_issues, audit и Preview не входят
в сумму. Нулевые Truth rows отсутствуют. Отрицательный результат запрещен
transaction validator.

Для transfer:

    Δ(from key) = -Q
    Δ(to key)   = +Q

Global subject total не меняется. Reversal имеет точный противоположный Δ.

## Схема

Projection состоит из version manifest и rows, описанных в
[data-model.md](data-model.md#balance-projection). Stock key:

    equipment_id XOR catalog_item_id
    + warehouse_id
    + location_id
    + condition_value_id
    + lot_key
    + uom_id

Active version указывает snapshot_id, built_through_sequence, row_count и
total_checksum. app_state ссылается на ту же version.

## Штатное обновление

Решение: синхронно в той же Unit of Work с ledger post. Максимальный допустимый
видимый lag — 0 transactions.

- projector получает typed InventoryApproved или LedgerTransactionPosted;
- выполняет deterministic UPSERT/DELETE zero row;
- обновляет row checksum и manifest sequence;
- ошибка projector откатывает ledger и audit;
- user получает success только после commit.

Kafka не нужна и не участвует в correctness.

## Checksum

Row checksum:

    SHA256(versioned canonical stock key || quantity_minor || last_sequence)

Total checksum:

    SHA256(snapshot content checksum ||
           built_through_sequence ||
           ordered(row_checksum by binary stock key))

Checksum доказывает детерминированное совпадение двух rebuild при одинаковом
input; он не заменяет независимую арифметическую verification query.

## Consistency check

Проверка пересчитывает truth batched SQL/streaming и сравнивает:

- все stock keys;
- quantities;
- row count;
- total by warehouse/UOM/condition;
- built-through sequence;
- total checksum.

Mismatch atomically переводит app_state в INCONSISTENT отдельной technical UoW,
блокирует warehouse writes и возвращает BALANCE_PROJECTION_INCONSISTENT.
Пользователь видит последний проверенный balance с явным stale banner только в
режиме auditor; operator write screens недоступны.

## Shadow rebuild без остановки чтения

1. зафиксировать active snapshot и head n read transaction;
2. создать version BUILDING;
3. потоково построить rows из snapshot + ledger (c,n);
4. проверить row count/checksum, status READY;
5. в короткой writer UoW заблокировать post, применить tail n+1..current head;
6. повторить consistency check;
7. atomically переключить active version/app_state;
8. старую version оставить read-only 30 days, затем удалить rows.

Readers до шага 7 используют старую ACTIVE version. BUILDING lag не является
user-visible lag. Если rebuild упал, active version не меняется.

Для initial snapshot approval projection строится в candidate DB и становится
active вместе с atomic publish.

## Failure recovery

- Ledger/projector failure: whole UoW rollback.
- Startup обнаружил head mismatch: write lock + consistency check; не
  auto-исправлять скрыто.
- Corrupt active projection: rebuild shadow или restore, с audit.
- Projection rows можно потерять без потери truth; snapshots/ledger нельзя.

## Query rules

Balance page читает только ACTIVE version и использует keyset pagination.
Exact Equipment balance — index by version/equipment. API всегда возвращает
projection_version, snapshot_id, built_through_sequence и consistency status.
