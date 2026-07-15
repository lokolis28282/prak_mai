# Performance и масштабирование

Статус: **APPROVED — ODE 0.13 architecture baseline**

## Dataset

Acceptance dataset:

- 1 000 000 Equipment;
- 1 000 000 active snapshot items;
- 5 000 000 legacy events;
- 5 000 000 ledger lines;
- 100 warehouses/100 000 locations maximum model envelope;
- worst-case 10 000 history events for one repeated serial key;
- 1 000 000-row XLSX.

Данные включают leading zeros, ambiguous vendor-scoped S/N, bulk/cable,
corrupted dates, long comments и reference conflicts.

## Reference machine

Latency gates применяются на зафиксированном PERF_PROFILE_LOCAL_STANDARD:

- 8 logical CPU cores;
- 16 GiB RAM;
- local SSD/NVMe with at least 50k 4K random-read IOPS;
- no network filesystem, antivirus exception only if approved;
- release Python/runtime build;
- warm-cache и cold-start результаты записываются отдельно.

Если deployment слабее, acceptance report обязан указать hardware и новые
утвержденные SLO; нельзя публиковать неподтвержденные обещания.

## Measurable gates

| Scenario | Dataset/query | Gate on reference machine |
|---|---|---|
| Exact S/N | normalized exact key, warm | p95 <100 ms, p99 <250 ms |
| Inventory Number | global exact, warm | p95 <100 ms |
| Balance page | 100 rows keyset + filters | p95 <300 ms, p99 <750 ms |
| Equipment balance | one Equipment | p95 <100 ms |
| History first page | exact key, 100 rows | p95 <300 ms |
| Next history page | keyset | p95 <300 ms |
| Ledger post | <=100 lines incl projection/audit | p95 <500 ms excluding user network |
| Preview | 1m rows | completes <120 min; progress <=2 s interval |
| Preview memory | 1m rows | process RSS increase <=512 MiB |
| Cancel Preview | active parse | observed stop/checkpoint <=5 s |
| Projection rebuild | 1m snapshot +5m lines | <60 min, RSS increase <=1 GiB |
| Browser page | any list | <=200 rows and <=2 MiB JSON |

Cold exact lookup and startup are measured, reported and capped separately
after prototype; warm p95 gates выше являются release blockers.

## Key queries and indexes

| Query | Required access path |
|---|---|
| Exact identity | equipment_identities(kind,normalized_key,status), then namespace |
| Balance browse | active projection version + warehouse/location/keyset covering index |
| Equipment balance | projection(version,equipment_id) |
| Legacy timeline | legacy(serial_key,occurred_at,event_id) |
| Ledger tail | transaction sequence PK and lines FK |
| Snapshot stream | snapshot_id + stock key/row ID |
| Audit feed | occurred_at,event_id keyset |
| Reference resolve | domain/scope/normalized unique |

EXPLAIN QUERY PLAN gate запрещает SCAN крупной operational table для exact
lookup/page. Temporary sort >page working set является failure.

Legacy `serial_key` хранит canonical match key с BINARY collation. Exact query
использует `serial_key = ?`, тот же BINARY collation и полный
`ix_legacy_history_serial(serial_key, occurred_at_us, event_id)`; caller не
дублирует `serial_key <> ''` и не использует `INDEXED BY`. `COLLATE NOCASE`
является другим access contract и не допускается для этого normalized lookup.

## Search

Exact identifiers используют B-tree. FTS5 — отдельная derived index для
description/comment/general search. FTS result никогда не используется для
identity correction, match approval или balance command. FTS rebuildable.

## Import

Streaming OOXML, 2 000-row default batch, maximum two batches in memory.
Matching uses indexed IN/temp-key joins. Work is cancellable and resumable.
Source XML limits проверяются до allocation. Preview UI читает aggregates and
pages, не весь dataset.

## Projection

Runtime delta синхронный и O(lines log indexes). Rebuild shadow version
streaming. Active readers не блокируются долгим rebuild; final tail/swap имеет
короткий writer lock. Full aggregate на каждый balance request запрещен.

## Test method

- минимум 30 warm iterations after 5 warmups per query class;
- p50/p95/p99 и max;
- query plan captured;
- DB file/page/cache statistics;
- background load: 10 readers + single writer;
- WAL/checkpoint timings;
- no debug profiler during official run;
- reproducible seed and dataset manifest hash.

Performance report содержит machine, OS/filesystem, runtime/SQLite versions,
config PRAGMA, dataset hash and Git commit. Число без этих данных не является
доказательством.
