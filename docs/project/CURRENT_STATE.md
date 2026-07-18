# Current State

Дата проверки: 2026-07-18. Authoritative repository:
`~/Documents/prak_mai`.

## Два разных Stage-трека

Номера Stage в проекте использовались для двух разных программ работ. Их нельзя
смешивать.

### Warehouse source/runtime track

- Current source/runtime metadata: `0.14.0`.
- Последний фактически собранный ZIP: `0.12.17 RC1`.
- Рабочий runtime: `app.py` → `inventory/` → `data/warehouse.db`.
- Главный продуктовый модуль: Warehouse.
- Reports предоставляет УВР, сменный и недельный отчёты; Monitoring — ручной
  hostname/DCIM flow и безопасную подготовку сообщения; Knowledge — статьи,
  теги и вложения. Все три контура изолированы от складских writes.

Обычная локальная рабочая БД содержит 50 000 receipts/cards, 18 798 issues и
18 798 allocations. Текущий SHA и правила работы с ней находятся в
`../LOCAL_WORKING_DATABASE_RUNBOOK.md`; SHA меняется после легитимных
операционных writes и не является константой версии.

### Target ODE 0.13 platform track

- Код находится в `ode/` и работает side-by-side с Warehouse runtime.
- Approved ADR-001..ADR-012 и DDL V001..V008 не применяются к
  `data/warehouse.db`.
- Platform Stage 0.13.1 реализован, NF-1/NF-2 исправлены, focused suite содержит
  60 tests.
- Формальный post-fix independent targeted PASS ещё не сохранён.
- Platform Stage 0.13.2 (security/audit/references) не начинался.
- Argon2id dependency/profile и production bootstrap policy не выбраны.

Warehouse Stage 0.13.2 (Bulk Inventory Number Import) уже реализован. Это не
Platform Stage 0.13.2.

## Проверенный regression baseline

На 2026-07-15 после закрытия test SQLite handles и до удаления disposable
candidate artifacts independent Warehouse review подтвердил:

- `python3 -W error::ResourceWarning -m unittest discover -s tests -q` —
  392/392 PASS, без ResourceWarning;
- focused `tests/ode013` — 60/60 PASS;
- module-boundary audit — PASS;
- frontend-contract audit — PASS;
- Python/JavaScript syntax — PASS;
- `scripts/create_clean_test_db.py --dry-run` — PASS, source SHA unchanged;
- ordinary headless Chrome smoke — PASS на временной byte-copy: receipt saved,
  issue/balance route, global search, Equipment Card, Inventory Number,
  profile/administration и placeholder modules; console/window/unhandled/
  resource/HTTP/API500 errors — 0;
- `git diff --check` — PASS.

После owner-approved repository cleanup полный discovery повторно запущен:
392 tests, `OK (skipped=8)`, без ResourceWarning. Восемь skip относятся только
к проверкам реальных ignored full/pilot candidate DB, которые теперь намеренно
отсутствуют; builders, временные candidate scenarios и остальной regression
suite продолжают выполняться. Для повторного artifact review candidate DB
сначала регенерируются штатными migration scripts.

После операторского stabilization pass закрыты три frontend-дефекта:

- CSS-компоненты больше не могут визуально переопределить HTML `hidden`;
- placeholders справочников не дублируются как selectable values;
- действие «Списать» отключено для позиции с нулевым остатком.

Повторный browser E2E прошёл полный локальный цикл Warehouse на disposable DB:
receipt, issue, balance, Equipment Card/Timeline, global search, drafts,
Inventory Number Preview/Confirm, engineer/admin permissions и references.
Console/window/unhandled/resource/HTTP/API500 errors — 0. Актуальный full discovery
после изменений: 394 tests, `OK (skipped=8)`, без ResourceWarning. Подробный
verdict — `reviews/2026-07-15_WAREHOUSE_OPERATIONAL_ACCEPTANCE.md`.

Scanner Operations 0.13.4 добавляет два расходных режима: один общий сервер и
последовательные пары `компонент → сервер`. Interactive scan теперь fail-closed:
неизвестный S/N не создаёт unmatched issue и блокирует проведение. Pair batch
имеет лимит 1000 строк и проводится одной транзакцией; disposable API test на
100 пар и полный browser smoke проходят. Это пока UX/runtime slice поверх
compatibility Warehouse и не утверждённый post-inventory ledger. Evidence —
`reviews/2026-07-15_SCANNER_OPERATIONS_0_13_4.md`.
Актуальный full discovery после slice: 397 tests, `OK (skipped=8)`, без
ResourceWarning.

### ODE 0.14 Full Inventory

Legacy receipts/issues/allocations теперь являются historical read model.
Backend status до baseline — `NOT_INITIALIZED`; balance имеет marker
`HISTORICAL_CALCULATION`, `authoritative=false`, `baseline_timestamp=null`, а
posting guard блокирует реальные складские mutations.

External workspace поддерживает FULL session, строгий XLSX, source SHA,
Preview/findings, append-only manual resolutions и deterministic revalidation.
Admin-only rehearsal создаёт отдельную ODE target-schema V001..V008 DB,
import commit, approved snapshot и active projection. Candidate проходит
schema/integrity/FK/domain invariants и reconciliation, не содержит legacy
history и не публикуется автоматически: `publish_available=false`.

Performance на disposable fixtures после streaming hardening: 1k — 0.13 s,
10k — 1.30 s, 50k — 6.45 s. Отдельный 50k Preview process использовал около
69 MiB peak RSS. Рабочая `data/warehouse.db` не изменялась.

Исторический automated gate 0.14: 444 tests PASS (`skipped=8` для отсутствующих
ignored migration artifacts), module/frontend audits и headless Chrome smoke
PASS, browser/HTTP/API500 error counters равны нулю.

Monitoring hostname-routing follow-up: 20 focused tests и полный gate
464 tests PASS (`skipped=8`). Локальные 33 Tech rules и 530 Digital hostname
валидны; внутренние JSON исключены из публичного Git, рабочая БД не менялась.

Интеграционный кандидат 2026-07-18 добавляет Monitoring UI/manual search,
Knowledge Base и Reports/УВР. Финальный gate: 503 tests PASS (`skipped=8`),
syntax/module/frontend audits, clean-DB dry-run, headless E2E и ручной in-app
browser walkthrough PASS. Подробные SHA/backup/evidence находятся в
`../../RELEASE_REPORT_ODE_0_14_INTEGRATION.md`.

Ручная операторская приёмка фиксируется отдельно по
`../MANUAL_TESTING_WAREHOUSE_STABILIZATION.md`.

## Git state

Точный Git status определяется командами `git status --short --branch` и
`git log --oneline origin/main..HEAD`. Runtime DB, Monitoring rules и candidate
artifacts остаются installation-owned local data и не публикуются вместе с
source commits.

Нельзя выполнять force reset или добавлять runtime/candidate DB. Следующий
commit допустим только после полного documentation/release gate и финального
подтверждения неизменности рабочей БД.

### Runtime data separation

Repository Data Separation prepared on 2026-07-16 establishes the canonical
policy: `data/warehouse.db` is installation-owned runtime data and must not be
tracked, staged, included in a source clone or copied into a code release. The
repository-wide rules live in `.gitignore`; `.git/info/exclude` is local
defence-in-depth only and is not a project policy.

Before removing the tracked index entry, the active DB was copied byte-for-byte
to an external `~/Documents/ODE_BACKUPS/repository-data-separation-<UTC>/`
directory and the source/backup size, SHA-256, SQLite integrity and foreign keys
were verified. The active local path remains `data/warehouse.db`; its content
was not changed.

A clone intentionally contains no runtime database. A new installation must
explicitly select and bootstrap its own local DB path. Compatibility runtime
initialization is not an approved production migration procedure: server
migrations require a separate backup/migrate/validate/rollback gate.

The old small DB remains in existing Git history. No history rewrite was
performed. A coordinated history cleanup, if ever required, is a separate
maintenance task for all collaborators and remotes.

Windows package builder 0.14 больше не включает `data/warehouse.db`: пакет
содержит только `data/README.md`. Новый физический Windows artifact ещё не
собран и требует отдельной Windows acceptance-процедуры.

## Repository cleanup

Owner-approved Phase 2 завершена 2026-07-15. Внутри repository из DB/ZIP
остались только активная `data/warehouse.db` и canonical
`release/ODE_0.12.17_RC1.zip`. Disposable migration workspace, Platform dev
DB, локальный дубль внешнего stabilization backup и дубли release удалены по
проверенному manifest. Raw/provenance/reports сохранены. Полное evidence — в
`reviews/2026-07-15_REPOSITORY_CLEANUP_EXECUTION.md`.

## Текущий приоритет

Следующий приоритет — презентационный walkthrough и ручная операторская приёмка
FULL Inventory 0.14, затем target Equipment Query Port и отдельный controlled
cutover design. До него реальный initial-baseline publish запрещён. После
cutover — correction/reversal, backup/restore drill и server-readiness.
