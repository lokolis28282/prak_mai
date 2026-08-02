# Current State

Дата проверки: 2026-08-02. Authoritative repository:
`~/Documents/prak_mai`.

## Два разных Stage-трека

Номера Stage в проекте использовались для двух разных программ работ. Их нельзя
смешивать.

### Warehouse source/runtime track

- Current source/runtime metadata: `0.20.0`.
- Последний фактически собранный ZIP: `0.12.17 RC1`.
- Рабочий runtime: `app.py` → общий application context + выбранный Warehouse
  site → `data/warehouse.db` (IXcellerate) или
  `data/warehouse_solar.db` (Solar).
- Главный продуктовый модуль: Warehouse.
- Reports предоставляет УВР, сменный и недельный отчёты; Monitoring — ручной
  hostname/DCIM flow и безопасную подготовку сообщения; Knowledge — статьи,
  теги и вложения. Все три контура изолированы от складских writes.
- Web routes/templates, Warehouse, Reports и Administration физически
  выделены из монолитов; compatibility adapters сохранены без второй
  реализации бизнес-логики.

Multi-Warehouse slice от 2026-07-26 добавляет session-scoped выбор склада.
Solar физически изолирован, стартует без operational rows и получает только
одноразовый снимок справочников IXcellerate. Авторизация, Reports, Monitoring
и Knowledge остаются общими. Контракт:
[`../MULTI_WAREHOUSE_ARCHITECTURE.md`](../MULTI_WAREHOUSE_ARCHITECTURE.md).

### ODE 0.17.0 Multi-Warehouse gate

IXcellerate и Solar используют физически разные SQLite-файлы и выбранный в
HTTP-сессии Warehouse runtime. Solar создаётся с нулевыми operational rows и
одноразовым снимком справочников; последующие операции и справочники двух
складов независимы. Полный gate: 598 тестов (`skipped=8`), headless Chrome,
Python/JavaScript syntax, module/frontend/data audits и clean-DB dry-run —
PASS. Рабочая IXcellerate DB осталась byte-identical. Подробности:
`../../RELEASE_REPORT_ODE_0_17_0.md`.

### Post-release UX regression

После релиза унифицирован словарь Warehouse: `Приход / принять` и
`Расход / списать`; пользовательские подписи `Выдать / Выдано` удалены.
Повторный полный gate содержит 599 тестов (`skipped=8`), headless Chrome и
все repository/module/frontend/data checks — PASS. Рабочие IXcellerate и
Solar DB остались byte-identical. Доказательства:
[`reviews/2026-07-26_FULL_PROJECT_UX_REGRESSION.md`](reviews/2026-07-26_FULL_PROJECT_UX_REGRESSION.md).

### Common Vacations slice

ODE 0.18.0 включает отдельный `inventory/vacations` bounded context:
общий календарь IXcellerate/Solar, ручные статусы Сферы, effective-dated
площадки/графики и очередь конфликтов. Правила покрывают цикл `1/3` от
26.07.2026, подменного, непересечение начальника/старших и минимум одного
дежурного в активной группе. Доступ не ограничен ролью, но каждая мутация
сохраняет actor/history/audit.

Свежая `vacations.db` создаётся без состава команды. Сотрудники и назначения
добавляются через UI/API, а рабочие ФИО остаются только в локальной ignored DB.

Обычный startup создаёт/открывает самостоятельную `data/vacations.db`.
`vacation_*` и `vacation_audit_log` отсутствуют в обеих Warehouse DB;
runtime migration Reports/Knowledge модуль отпусков не устанавливает.
Полный gate: 620 тестов (`skipped=8`), headless Chrome со всеми основными
разделами, Python/JavaScript syntax, module/frontend/data audits и clean-DB
dry-run — PASS. Рабочие IXcellerate/Solar DB остались byte-identical.
Контракт: [`../VACATIONS_ARCHITECTURE.md`](../VACATIONS_ARCHITECTURE.md).
Evidence:
[`reviews/2026-07-27_VACATIONS_MODULE_REVIEW.md`](reviews/2026-07-27_VACATIONS_MODULE_REVIEW.md).

### ODE 0.18.1 stabilization and multi-DB backup slice

Administration знает три независимые runtime-БД через описательный
`RuntimeDatabaseRegistry`: IXcellerate, Solar и Vacations. Read-only status
показывает точный target, размер, mtime, integrity/FK/schema и последнюю копию.
Создание копии доступно только admin и выполняется профильным
`MultiDatabaseBackupService`: общий write-lock, SQLite Backup API, внешний
storage, проверка результата, SHA-256 manifest, atomic rename и
`RUNTIME_DATABASE_BACKUP_CREATE` в общем Administration audit.

Restore в 0.18.1 не реализован и не отображается как действие. Legacy
`RESTORE_BACKUP` через HTTP fail-closed; обязательный design описан в
[`../decisions/ADR-013-multi-database-backup-restore.md`](../decisions/ADR-013-multi-database-backup-restore.md).
Отдельный будущий correction/reversal контур Warehouse описан в ADR-014 и не
смешан с этим изменением.

Стабилизация также скрывает внутренний SQLite constraint в Vacations HTTP 409
и делает code graph кроссплатформенно детерминированным (`static/...` на всех
ОС). Финальные gate/evidence зафиксированы в
`../../RELEASE_REPORT_ODE_0_18_1.md`.

### ODE 0.19.0 documentation alignment

Релиз без изменений runtime-кода: единственная правка вне документации —
`inventory.__version__`. Вся функциональность унаследована от 0.18.1, поэтому
поверхность API, схема SQLite, ownership таблиц и топология кода
(245 узлов / 502 связи) не менялись.

Причина релиза — расхождение между кодом и корневыми документами, накопленное
за 0.17.0–0.18.1. `CLAUDE.md` описывал контур 0.16.0 и утверждал, что
`data/warehouse.db` — «единственный активный продуктовый контур»;
`ARCHITECTURE.md` открывался разделом «ODE 0.14 initial-inventory boundary»;
`ITOG.md` был озаглавлен «ODE 0.16.0». Ни один из трёх не упоминал Solar,
Vacations и multi-DB backup. Все три приведены к фактическому контуру,
`AGENTS.md` синхронизирован с `CLAUDE.md`, число тестов приведено к
фактическим 628.

Gate 0.19.0 выполнен на Linux (Python 3.10.12): full discover
628 тестов `OK (skipped=8)` под `-W error::ResourceWarning`, Python compile,
49 JavaScript-файлов, module/frontend/repository-data audits, clean-DB
dry-run, `generate_code_graph.py --check` и `git diff --check` — PASS.
Headless Chrome smoke в этой среде не запускался и не заявляется как
выполненный: он остаётся частью macOS/Windows приёмки. Три рабочие БД
остались byte-identical, `integrity_check=ok`, FK violations и sidecars
отсутствуют. Evidence: `../../RELEASE_REPORT_ODE_0_19_0.md`.

### ODE 0.20.0 equipment composition projection

Карточка серийного оборудования показывает evidence-only проекцию компонентов,
списанных на его target S/N. `EquipmentCompositionService` читает существующие
`stock_issues` и `stock_issue_allocations` через Warehouse domain composition;
новых таблиц и production-миграции нет. Оператор видит группы, полный журнал,
hostname, задачу/ИЗМ и первичные реквизиты компонента. Заводской состав,
фактическое наличие и физические слоты явно остаются неподтверждёнными.

Текущий release gate: 639 тестов (`skipped=8` на macOS/Linux), включая отдельные
backend/API/UI contracts и headless Chrome сценарий карточки. Evidence:
`../../RELEASE_REPORT_ODE_0_20_0.md`.

### ODE 0.20.0 full documentation/system audit

Поверх release gate добавлены исполняемые living-doc и static-control
контракты. `scripts/audit_documentation.py` проверяет 201 Markdown-файл,
локальные ссылки, текущую версию и опасные Windows backup/restore утверждения;
frontend audit подтверждает 162 static ID, 317 JS references и 53 именованные
кнопки с обработчиками/формами. Полный warning-clean discover содержит 641
тест (`skipped=8`). Датированный итог:
`reviews/2026-08-02_ODE_0_20_0_FULL_SYSTEM_AUDIT.md`.

### ODE 0.19.1 local runtime stabilization

После операторской проверки 2026-08-02 устранены четыре runtime-регрессии:
fresh-process circular import в `app.py seed`, потеря остатка при переходе из
карточки оборудования в расход, незакрывающаяся мышью карточка и неверный
production contour Solar внутри demo runtime. Test launchers macOS/Windows
теперь создают и явно подключают отдельные IXcellerate, Solar и Vacations DB;
рабочая Vacations DB больше не может быть неявным target тестового запуска.

Повторный gate на macOS: 635 тестов `OK (skipped=8)` под
`-W error::ResourceWarning`, Python/JavaScript syntax,
module/frontend/repository-data audits, graph check, clean-DB builders и
headless Chrome — PASS. Исторический release gate выше сохранён без
ретроспективного изменения.

Точная default-команда `python3 app.py` проверена на трёх реальных runtime-БД:
IXcellerate overview/search/card, mouse close, переход в расход без Confirm,
Solar isolation и Vacations calendar — PASS. Production DB SHA совпали
до/после; детали — `../../RELEASE_REPORT_ODE_0_19_1.md`.

### ODE 0.16.0 modular extraction gate

Четыре upstream-коммита 0.16.0 проверены 2026-07-26 сначала в отдельном
worktree, затем на точной byte-copy рабочей БД. Схема SQLite и ownership
таблиц не менялись. Full discover: 593 upstream tests, `OK (skipped=8)`;
headless Chrome прошёл Warehouse, Reports, Monitoring, Knowledge и
Administration без console/window/unhandled/resource/HTTP/API500 ошибок.
После добавления контракта актуальности графа локальный gate содержит 594
теста. Рабочая `data/warehouse.db` во время обновления осталась byte-identical;
подробности — `../../RELEASE_REPORT_ODE_0_16_0.md`.

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

Scanner Operations 0.13.4 добавляет два расходных режима: несколько компонентов на
одно целевое оборудование и последовательные пары `компонент → оборудование`. Interactive scan теперь fail-closed:
неизвестный S/N не создаёт unmatched issue и блокирует проведение. Pair batch
имеет лимит 1000 строк и проводится одной транзакцией; disposable API test на
100 пар и полный browser smoke проходят. Это пока UX/runtime slice поверх
compatibility Warehouse и не утверждённый post-inventory ledger. Evidence —
`reviews/2026-07-15_SCANNER_OPERATIONS_0_13_4.md`.
Актуальный full discovery после slice: 397 tests, `OK (skipped=8)`, без
ResourceWarning.

### ODE 0.14 Full Inventory

Legacy receipts/issues/allocations образуют рабочий предварительный баланс.
Backend status до baseline — `READY`; balance имеет marker
`PROVISIONAL_HISTORICAL`, `authoritative=false`, `provisional=true`,
`baseline_timestamp=null`, а корректно настроенный production contour разрешает
реальные складские mutations. Unknown contour и demo, указывающий на рабочую
БД, остаются fail-closed.

External workspace поддерживает FULL session, строгий XLSX, source SHA,
Preview/findings, append-only manual resolutions и deterministic revalidation.
Скачиваемый операторский XLSX формируется read-only из активных справочников и
всей Warehouse history: основной лист начинается с S/N, отдельные листы содержат
инструкцию, а на момент gate — 34 точных типа по категориям, 24 активные полки
и 444 варианта номенклатуры. Исторический расчёт в подсказках помечен предварительным и не
выдаётся за результат инвентаризации.
Admin-only rehearsal создаёт отдельную ODE target-schema V001..V008 DB,
import commit, approved snapshot и active projection. Candidate проходит
schema/integrity/FK/domain invariants и reconciliation, не содержит legacy
history и не публикуется автоматически: `publish_available=false`. Preview не
меняет текущий баланс; approval/activation должна заменить его baseline-снимком
после backup и writer-stop gate.

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

Warehouse provisional-balance follow-up 2026-07-18: production posting снова
доступен, overview показывает текущий расчётный остаток, category `Другое`
согласована между SQL/API/UI. Полный gate: 507 tests PASS (`skipped=8`),
module/frontend audits, clean-DB dry-run и headless E2E PASS. Рабочая БД
сохранена byte-identical с SHA-256
`a4f48e21097b335b81f9b09a053dbb50f0276bd30cab488c74b67da9a2c957a6`.

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

Финальный технический presentation walkthrough 2026-07-19 завершён на
disposable byte-copy рабочей БД: desktop 1440x900 и mobile 390x844, основные
экраны Warehouse/Monitoring/Reports/Knowledge, scanner negative path,
server-side balance search и lazy rendering тяжёлых таблиц проверены в живом
браузере; Console/HTTP/API500 counters равны нулю. Полный gate: 539 tests PASS
(`skipped=8`), syntax/module/frontend audits, актуальный code graph
(203 узла / 364 связи), clean-DB dry-run и headless E2E PASS. Рабочая БД
не изменялась кодовыми проверками; после обычного audit-события `LOGIN`
пользователя финальный commit-gate baseline имеет SHA-256
`68f06d7a764ac8d2ccde1b59d99ad7977cb665808602d2980a3dfdc87c4a5314`,
`integrity_check=ok`, FK violations и sidecars отсутствуют.

Follow-up gate 2026-07-24 согласовал browser smoke и операторскую инструкцию с
текущим ленивым деревом остатков `категория → тип → вендор → модель`.
Frontend-contract audit учитывает динамически создаваемые controls группового
выбора поставки. Актуальный full discover содержит 566 tests (`skipped=8`),
headless E2E проходит весь Warehouse/Reports/Monitoring/Knowledge/Admin flow
без Console/HTTP/API500 ошибок, code graph актуализирован до 205 узлов /
368 связей. Проверки выполнялись на disposable byte-copy; рабочая БД осталась
byte-identical.

Warehouse stabilization 2026-07-25 добавила симметричные блоки последних
приходов/расходов и operation-level read-model расхода. Один расход теперь
занимает одну строку независимо от числа FIFO allocations; полная выгрузка
сохраняет несопоставленные problem rows и показывает целевую железку
(название, модель, инв. №, S/N, hostname). Навигационное имя `Остатки`
заменено на `Баланс`. Read-only проверка полного рабочего объёма сформировала
50 019 строк прихода и 18 798 строк расхода за 1,64 секунды. Full discover:
574 test (`skipped=8`), headless E2E и frontend/module/repository-data audits —
PASS; рабочая
БД не изменялась.

Git data boundary 2026-07-25: обязательный
`scripts/audit_repository_data.py` запрещает попадание runtime/company
artifacts в index, включая SQLite под замаскированным расширением. First-run
тест подтверждает, что clone без `data/warehouse.db` создаёт локальную схему с
нулём приходов, расходов, allocations и поставок. Перед очисткой старой GitHub
истории создан внешний backup `QWERTY`; переписывание истории не меняет
локальную рабочую БД.

Known bootstrap credentials новой пустой compatibility-БД больше не выводятся
в application/CI logs. Они по-прежнему являются открытым ограничением до
production bootstrap design, поэтому текущий verdict — local demo/pilot, а не
публичный или многопользовательский server deployment.

ODE 0.16.0 Stage 4 завершил декомпозицию web delivery: доменные HTTP-ветви
Administration, Reports, Warehouse, Monitoring и Knowledge вынесены в
`inventory/routes/`, HTML-сборка — в `inventory/templates/`.
`inventory/webapp.py` сокращён до общего HTTP/auth/session/security shell.
Полный upstream gate: 593 теста (`skipped=8`), Python/JS syntax,
module/frontend/data audits, clean-DB dry-run и headless Chrome smoke — PASS.
Текущий проверенный ODE 0.20.0 — 641 тест; code graph содержит 248 узлов /
506 связей. Актуальные значения и интерактивная карта находятся в
`docs/CODEBASE_GRAPH.md`, внешний Codebase Memory —
из `docs/CODEBASE_MEMORY_MCP.md`. Рабочая БД осталась byte-identical, SHA-256
`8681f3c34c52d12e665ddae9f9f818a7635c1108aee353baa9fc63830955305b`,
`integrity_check=ok`, FK violations и SQLite sidecars отсутствуют.

Следующий приоритет — пользовательская операторская приёмка и презентация
руководителю, затем target Equipment Query Port и отдельный controlled cutover
design. До него реальный initial-baseline publish запрещён. После cutover —
correction/reversal, backup/restore drill и server-readiness.

Ближайшие два кандидата уже имеют утверждённые контракты и не требуют нового
design-этапа: полный restore-vertical по
[`../decisions/ADR-013-multi-database-backup-restore.md`](../decisions/ADR-013-multi-database-backup-restore.md)
(закрывает пункт W1 «backup/restore drill») и сторнирующие складские операции
по
[`../decisions/ADR-014-warehouse-correction-reversal.md`](../decisions/ADR-014-warehouse-correction-reversal.md).
