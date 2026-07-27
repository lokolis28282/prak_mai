# Release Report — ODE 0.18.1 stabilization and multi-DB backup

Дата: 2026-07-27.

## Verdict

ODE 0.18.1 стабилизирует ODE 0.18.0 и добавляет первый безопасный вертикальный
срез управления резервными копиями трёх независимых runtime-БД:
read-only status/list и создание проверенного snapshot. Restore не включён,
потому что полный preview/token/safety-backup/atomic-replace протокол ещё не
реализован.

Verdict: **READY FOR LOCAL DEMO / PILOT AND SOURCE DISTRIBUTION**.

Это не готовность к публичному многопользовательскому deployment. Release ZIP
не создавался; Git содержит только исходный код, тесты, документацию и
архитектурные схемы, без runtime-БД и данных компании.

## Исходная точка и Git

- upstream baseline: `898866d14441a9ab65cc144339dedfefca2509f3`
  (`ODE 0.18.0`);
- обновление: `fetch --prune` и fast-forward `main`;
- рабочая ветка: `codex/multidb-backup-0190`;
- baseline доказан предком итогового commit через
  `git merge-base --is-ancestor`.

## Реализовано

- `RuntimeDatabaseRegistry` с точными ID, путями, профилем и обязательными
  таблицами IXcellerate, Solar и Vacations;
- admin-only status: путь, размер, mtime, integrity/FK/schema, sidecars и
  последняя копия;
- создание snapshot через SQLite Backup API под общим runtime lock;
- внешнее хранилище, запрет repository-contained root, symlink и hardlink;
- sibling `.next`, fsync, права `0600`, проверка integrity/FK/schema, SHA-256
  manifest и атомарная публикация каждого файла;
- Administration audit без содержимого БД;
- UI с явным выбором одной runtime-БД и без частично работающего restore;
- понятный HTTP 409 для duplicate ФИО в Vacations без утечки SQLite
  constraint;
- одинаковая генерация code graph на Windows/POSIX и regression-тест;
- ADR полного restore и отдельный ADR будущих Warehouse correction/reversal.

## Не вошло

- restore preview, одноразовый token, safety backup и atomic replace;
- cross-profile restore и его UI;
- расписание, retention и шифрование backup;
- correction/reversal складских операций.

Эти функции не представлены как доступные. Обязательный следующий протокол
зафиксирован в
[`ADR-013`](docs/decisions/ADR-013-multi-database-backup-restore.md), а
компенсирующие складские события — отдельно в
[`ADR-014`](docs/decisions/ADR-014-warehouse-correction-reversal.md).

## Gate

| Проверка | Результат |
|---|---|
| Python compile | OK |
| JavaScript syntax | 47 файлов, OK |
| module-boundary audit | OK |
| frontend-contract audit | OK |
| repository-data audit | OK |
| clean-test-DB dry-run | OK |
| full `unittest discover` | 628 тестов, `OK (skipped=15)` |
| headless Chrome smoke | OK; browser/API errors — 0 |
| live disposable browser regression | OK |
| deterministic code graph | 245 узлов / 502 связи; current |
| `git diff --check` | OK |

Codebase Memory full reindex был запрошен с `persistence=false`, но в текущем
Windows-окружении отсутствуют binary и MCP tools. Поэтому последние
подтверждённые внешние метрики 0.18.0 — 7 067 узлов / 30 991 ребро /
550 файлов / 42 routes — не выдаются за метрики 0.18.1.
`artifact_present=false`; `.codebase-memory` в repository отсутствует.

## Сохранность рабочих БД

Перед любым запуском для каждой реально существующей runtime-БД созданы
byte-copy и SQLite Backup API copy во внешнем task-каталоге с manifest.

| Runtime DB | SHA-256 до и после | integrity | FK |
|---|---|---|---|
| IXcellerate | `7284c73a11771f4869bf6b198794fdc8787f789d7463a43f8f50e1a657db6450` | `ok` | 0 |
| Solar | `3370700fa811c73f61bbf22dd4835b08eb4489b518dcab521fe70361fc815cf3` | `ok` | 0 |
| Vacations | `19ce76def7bb63d60374d097c35bda537600b076f5be608d9c0b516b1e678543` | `ok` | 0 |

Во всех трёх случаях SHA совпал, sidecars отсутствуют. Warehouse DB не
содержат `vacation_*`; Vacations DB не содержит складских operational-таблиц.
Ни одна runtime-БД не отслеживается Git.

## Evidence

- ручная приёмка:
  [`docs/MANUAL_TESTING_0_18_1.md`](docs/MANUAL_TESTING_0_18_1.md);
- датированный review:
  [`docs/project/reviews/2026-07-27_ODE_0_18_1_MULTI_DB_BACKUP.md`](docs/project/reviews/2026-07-27_ODE_0_18_1_MULTI_DB_BACKUP.md);
- code graph:
  [`docs/CODEBASE_GRAPH.md`](docs/CODEBASE_GRAPH.md);
- backup runbook:
  [`docs/operations/backup-restore.md`](docs/operations/backup-restore.md).
