# CLAUDE.md — ODE

## Current Warehouse stabilization boundary

- Единственный активный продуктовый контур — Warehouse на `data/warehouse.db`.
- Monitoring и Reports принадлежат отдельным направлениям и не связываются со
  складом. Monitoring предоставляет изолированный manual hostname/DCIM flow и
  routing по локальным ignored JSON rules; Reports — УВР и сменные отчёты.
- Reference Data runtime: `UI → existing API → ApplicationContext →
  WarehouseFacade → ReferenceDataService → reference_*_v2`.
- Нельзя hardcode справочники в JS и нельзя переписывать operational raw/S/N
  при rename/deactivate/merge canonical значения.
- Админские права определяются session user/role, не ФИО. UI не имеет
  отдельного «режима администратора».
- Черновик никогда не перехватывает навигацию; восстановление только по явному
  выбору пользователя.
- Коррекции production data требуют внешнего byte-copy + SQLite `.backup`,
  доказательства provenance, транзакции, audit и post-check integrity/FK.

Инструкции для Claude при работе в этом репозитории. Компактно и по фактам;
подробности — в `docs/README.md` (индекс архитектурной документации) и в
`README.md` (пользовательская инструкция).

Current source/runtime metadata: ODE `0.14.0`; последний фактический ZIP
остаётся `0.12.17 RC1`. Новый Windows artifact не собран.

## Текущий локальный контур (2026-07-14)

- `data/warehouse.db` — единственная обычная локальная рабочая БД; `python3
  app.py` обязан выбирать её без migration env/launcher.
- Это проверенная promotion полного historical candidate: 50 000 карточек,
  50 000 receipt states, 18 798 issues и 18 798 allocations. Legacy
  `equipment/operations` не являются read-path карточек, KPI или баланса.
- Обычный склад читает через существующий `WarehouseFacade`; прямой новый
  параллельный SQL/runtime для мигрированных карточек запрещён.
- `migration_inputs/workspace/warehouse_full_candidate.db`, pilot, raw и
  generated reports — immutable/воспроизводимые артефакты, не рабочая БД и не
  объекты ручного редактирования.
- Mutation/smoke выполняются только на временной byte-copy рабочей БД. Перед
  заменой — внешний backup, проверки и sibling `.next`; публикация — только
  после остановки writers атомарным `os.replace`.
- Серверный production deployment не реализован. Test DB никогда не включается
  в обычный code release и не копируется на production вместе с кодом.

Практический runbook: `docs/LOCAL_WORKING_DATABASE_RUNBOOK.md`.

## Что такое ODE

ODE («Отдел дежурных инженеров») — локальный рабочий инструмент дежурной смены
ЦОД: складской учет оборудования и кабеля, приход/расход, поставки,
инвентаризация, баланс, история позиций, логи работ и отчеты. Работает на
Python (стандартная библиотека, без внешних зависимостей) и SQLite, интерфейс —
браузерный (`app.py` → `inventory/webapp.py`), плюс совместимый CLI
(`inventory/cli.py`).

ODE — не просто складская таблица, а операционная платформа смены. Через
несколько версий она должна стать основным рабочим инструментом всей смены, а
не одного инженера. Любое архитектурное решение стоит проверять не только на
«работает ли сейчас», но и на «выдержит ли это следующий этап»:

```
MacBook (разработка) → рабочий ноутбук инженера (пилот)
  → несколько инженеров → сервер → API → интеграции (после 1.0)
```

До сервера и API — обычный локальный однопользовательский SQLite-инструмент.
Не стоит городить многопользовательские/клиент-серверные механизмы заранее, но
стоит избегать решений, которые эту модель прямо заблокируют (жесткие
допущения «один процесс на одной машине» в новом коде, обход фасадов и т.п.).

## S/N-first принцип

Главный бизнес-идентификатор оборудования и компонентов — серийный номер
(S/N), а не внутренний database ID и не инвентарный номер:

- позиция появляется в ODE по факту прихода S/N;
- инвентарный номер может отсутствовать при первом приходе и добавляется позже;
- получение инвентарного номера не создает новую позицию — дополняет
  существующую карточку по S/N;
- заполненные конфликтующие поля не перезаписываются автоматически (см.
  `docs/DELIVERY_CONFLICT_POLICY.md`);
- повторный приход того же S/N и повторный расход уже выданного S/N запрещены,
  проверка выполняется на сервере внутри транзакции;
- кабели — исключение: обычно без S/N, учитываются по количеству/метражу,
  расход распределяется FIFO по партиям прихода.

Для массового назначения Inventory Number действуют дополнительные инварианты:

- lookup только по S/N; Inventory Number никогда не используется как fallback
  идентификатор карточки;
- обязательны Preview и Confirm, direct import запрещён;
- Preview не меняет БД/audit, повтор S/N внутри CSV блокирует Confirm;
- Confirm повторно анализирует план под write-lock и применяет все `SUCCESS`
  одной транзакцией либо откатывает всё;
- конфликтные/не найденные строки не создают карточки и не перезаписывают
  данные;
- каждое реальное изменение использует существующий
  `EQUIPMENT_INVENTORY_NUMBER_ASSIGNED` audit/Timeline contract.

Нормативное описание —
`docs/INVENTORY_NUMBER_IMPORT_ARCHITECTURE.md`.

Для migration sources действует более строгий preservation contract:

- `source_serial_value` никогда не заменяется match key и не проходит через
  `int`, `float` или guessed repair;
- numeric XLSX cell читается из raw OOXML token с типом/number format и
  анализируется через `Decimal`; точность свыше Excel 15-digit guarantee не
  считается доказанной;
- numeric S/N никогда не получает match key автоматически: exponent token
  сохраняется буквально, custom-zero display остаётся предложением для review;
- допустимый match key: NFKC, удаление только внешних whitespace/невидимых
  format controls и casefold; внутренние пробелы, дефисы, script и ведущие
  нули сохраняются;
- `SOURCE_CORRUPTED` не получает match key и не может породить карточку;
- S/N, Inventory Number, Part Number, Request/Order/PLU в generated XLSX/CSV
  записываются только как text (`@` для XLSX).

Нормативное описание — `docs/SERIAL_NUMBER_PRESERVATION.md`.

Для Stage 0.13.3A.5 pilot дополнительно:

- выбирать ровно 200 source rows только детерминированным selector с seed
  `ODE-0.13.3A.5-PILOT-v1`; не подменять отсутствующее source покрытие
  synthetic rows;
- карточку создавать только для decision `IMPORT`, preservation
  `TEXT_EXACT`, quantity `1` и доказанной source date;
- exact duplicate/conflict rows связывать provenance с одной карточкой;
  quarantine/corrupted/quantity rows не должны создавать receipt;
- source S/N передавать migration writer без `strip`/`upper`; обычный receipt
  validator для исторического pilot import запрещён;
- shelf — placement/history, не identity и не причина второй карточки;
- фактический source содержит R220, но не R200; это документированный gap, а
  не разрешение генерировать R200;
- pilot receipts/audit существуют только в marker-guarded disposable DB и не
  являются Reports business receipt events;
- marker guard должен завершиться до `ApplicationContext`; только после него
  pilot web startup передаёт `initialize_database=False`. Default production
  startup остаётся `True`, а browser smoke обязан подтвердить неизменный SHA
  pilot DB copy.

Полный контракт — `docs/MIGRATION_PILOT_ARCHITECTURE.md`.

## Архитектура

```
app.py
 ├─ inventory/webapp.py   HTTP UI + API (частично монолит, см. ниже)
 └─ inventory/cli.py      совместимый CLI
            │
            ▼
   inventory/core/            ApplicationContext, маршрутизация, контракт событий
   inventory/warehouse/       склад: приход, расход, кабели, поставки, баланс, история
   inventory/reports/         work logs, ежедневные/недельные отчеты
   inventory/administration/  users, роли, аудит, backup/restore, diagnostics
   inventory/monitoring/      manual hostname/DCIM search, изолирован от остальных
   inventory/knowledge/       статьи, теги, private attachments
            │
            ▼
   inventory/shared/       общие адаптеры SQLite/CSV/валидации
   inventory/db.py         схема и идемпотентные миграции
            │
            ▼
   data/warehouse.db       рабочая SQLite-база

scripts/migration_reference_data.py
            │ offline only
            ▼
   inventory/migration/    reference/alias/naming/S/N/staging
      │ read-only                    │ generated + ignored
      ▼                              ▼
migration_inputs/raw      migration_inputs/workspace/candidate DB

scripts/migration_pilot.py
            │ offline selection/build; injected Warehouse writer
            ▼
warehouse_pilot_candidate.db
            │ marker-guarded, read-only review only
            ▼
WarehouseFacade -> migration pilot UI / Equipment Card
```

Публичные фасады: `WarehouseFacade`, `ReportsFacade`, `MonitoringFacade`,
`AdministrationFacade`. Новый код в `web/API` обращается к модулям только через
фасад, не через `WarehouseCore`/`WarehouseService` напрямую. Полная карта
миграции по стадиям — `docs/MODULE_ARCHITECTURE.md`.

Владение таблицами (кто пишет что) — `docs/DATABASE_OWNERSHIP.md`. Коротко:
Warehouse владеет `stock_receipts`, `stock_issues`, `stock_issue_allocations`,
`deliveries`, `delivery_lines`; Reports — `work_logs`,
`daily_report_uploads`, `daily_report_rows`; Administration — `users`,
`audit_log`, backup-файлами. Reports не пишет складские таблицы, Warehouse не
пишет отчетные — только через `WarehouseEventReader`.

Stage 0.13.3A migration package не является runtime-модулем и не владеет
production tables — offline `migration_*` tables существуют только в
disposable candidate. Это не относится к `reference_domains_v2` /
`reference_values_v2` / `reference_aliases_v2`: после promotion полного
historical candidate (см. «Текущий локальный контур») они реально
присутствуют и заполнены в `data/warehouse.db`, и `ReferenceDataService`
(`inventory/warehouse/references.py`, `has_v2()`) читает вендоров, модели,
поставщиков, полки и ЦОД именно из них для всех форм UI. Плоская
`reference_values` остаётся только fallback для доменов без v2-аналога
(`task_type`, `work_log_status`) и для установок без v2-таблиц.

`inventory/webapp.py` — известный архитектурный долг: HTML/CSS/JS/HTTP handler
в одном файле, DOM собирается цепочкой `.replace(...)`. Не переписывать его
одним большим изменением; выносить логику в модули постепенно, через фасады.
Рядом существует модульный frontend `static/js/{core,warehouse,reports,
administration,monitoring,components}` — уточняй перед правкой, какой слой
реально рендерит нужный экран.

Важная деталь: в конце сборки `HTML` вызывается `_externalized_html()`
(`inventory/webapp.py`), которая regex'ом вырезает ВЕСЬ инлайновый
`<style>...</style>` и `<script>...</script>` из накопленного шаблона и
заменяет их на `<link rel="stylesheet" href="/static/css/main.css">` и
`<script src="...">` для файлов из `static/js/`. Любой код внутри инлайновых
`<style>`/`<script>`, добавленный до вызова `_externalized_html()`, до
браузера НЕ доходит; фактическая логика и стили живут в `static/js/*.js` и
`static/css/main.css`. Проверяй поведение через сам `webapp.HTML` (или живой
сервер), а не только чтением исходника.

Stage 0.13.3A.5 stabilization удалила три больших подтвержденно мёртвых
константы (`UX_SCRIPT`, `WIZARD_SCRIPT`, `DELIVERY_JS`), которые почти год
дублировали (устаревшей версией) логику `static/js/ui.js` и содержали
hardcoded vendor/model списки, никогда не доходившие до браузера. Остальная
HTML-разметка в этом файле (вне `<style>`/`<script>`) — реальная, обычные
`.replace()`-вставки в неё меняют то, что видит пользователь.

## Правила зависимостей

- Reports не читает/не пишет складские таблицы напрямую — только через
  `WarehouseEventReader`.
- Warehouse не пишет отчетные таблицы.
- Monitoring не импортирует Warehouse/Reports/`WarehouseService`/
  `WarehouseCore`; будущие таблицы — с префиксом `monitoring_`.
- `WarehouseCore` — compatibility core, не удалять одним изменением; новая
  логика подключается через фасады, вторая параллельная реализация экрана не
  создается.
- `inventory/migration` не импортируется из Web/API/runtime services и не
  пишет в production; source path только read-only, output только ignored
  `migration_inputs/workspace`.
- Stage 0.13.3A.5 orchestration may import both offline migration modules and
  `inventory.warehouse.migration_pilot` only from the dedicated script. The
  Warehouse runtime must not import `inventory.migration`; it reads strict
  `migration_pilot_*` projections through its own review adapter.
- Pilot review must fail closed unless env flag, exact marker/name/stage/status,
  mode, integrity/FK and no-sidecar conditions all pass. Never bypass this with
  ordinary launchers or an arbitrary `--db`.
- Автоматически approve alias можно только для NFKC/case/безопасных whitespace
  вариантов. Не сливать Huawei/xFusion, HP/HPE, Hunix/Hynix, legal supplier
  names или разные vendor-scoped models без ручного решения.
- Canonical item name — display, который пересчитывается из type/vendor/model
  или component fields; он не identity. S/N — identity, shelf — placement.
- Не добавлять внешние зависимости без явного обоснования (`requirements.txt`
  сейчас пуст, проект работает на стандартной библиотеке).

## Работа с базой (обязательно)

- **Запрещено** без прямого указания: очищать/перезаписывать
  `data/warehouse.db`, сбрасывать пароль `lokolis`, гонять stress/нагрузочные
  тесты на рабочей базе, копировать тестовую базу поверх рабочей.
- Перед любой mutation-операцией — зафиксировать путь к БД и SHA-256, сделать
  backup. Тестовые/деструктивные операции — только на временной копии.
- После работы сравнить SHA-256 рабочей базы до/после (должен совпасть, если
  задача не про саму БД) и прогнать `PRAGMA integrity_check` /
  `PRAGMA foreign_key_check`.
- Для тестового контура без риска для рабочих данных — `scripts/
  create_clean_test_db.py` (см. `docs/TEST_DATABASE_GUIDE.md`, если создан).
- Candidate builder обязан открыть working DB `mode=ro` + `query_only`,
  проверить SHA/integrity/FK/отсутствие staging и сохранить только security
  snapshot без вывода password hashes. Operational/audit rows не переносятся.
- Candidate DB, raw sources, reports/normalized/workspace artifacts не
  коммитить и не устанавливать вместо `data/warehouse.db`.
- `warehouse_pilot_candidate.db` is a separate disposable output. Never build
  over the Stage A candidate, start it without marker guard, or use a pilot
  launcher against `data/warehouse.db`. Pilot UI is read-only; do not add
  operational mutation exceptions.

## Команды тестов и проверок

```bash
python3 -m py_compile app.py inventory/**/*.py scripts/*.py tests/*.py
for file in static/js/**/*.js tests/headless_smoke.js; do
  node --check "$file" || exit 1
done
python3 scripts/audit_module_boundaries.py
python3 scripts/audit_frontend_contracts.py
python3 -W error::ResourceWarning -m unittest discover -s tests -v
python3 scripts/create_clean_test_db.py --dry-run
python3 scripts/smoke_ui.py            # headless Chrome E2E, нужен Node+Chrome
git diff --check
```

Для Stage 0.13.3A дополнительно:

```bash
python3 scripts/migration_reference_data.py inspect-sources
python3 scripts/migration_reference_data.py build-candidate --overwrite
python3 scripts/migration_reference_data.py validate-candidate
python3 scripts/migration_reference_data.py report
```

`report` обязан применять полный output/source inode guard и регенерировать
только allowlisted JSON; merge существующего report запрещён.

Для Stage 0.13.3A.5 дополнительно:

```bash
python3 scripts/migration_pilot.py --help
python3 scripts/migration_pilot.py select
python3 scripts/migration_pilot.py build
python3 scripts/migration_pilot.py validate
./start_migration_pilot_macos.command   # manual review; existing DB only
```

Pilot gate also verifies raw/normalized/production hashes, marker/counts,
identifier text round-trip, pilot integrity/FK/no sidecars, role/mutation
boundaries, unchanged runtime-copy SHA and a separate headless pilot scenario.
Current full discover result is 464 tests under
`-W error::ResourceWarning`. Never run a 51,003-row
operational import as a performance test.

## Codebase memory (только developer tooling)

- Для структурного поиска сначала можно использовать MCP
  `codebase-memory-mcp`, но важные связи обязательно сверять с `rg` и чтением
  актуального кода.
- Разрешенный корень индекса — только этот репозиторий. Не индексировать
  `data/*.db*`, секреты, release/backup/cache и не включать `persistence=true`.
- Индекс и cache не коммитятся; при `auto_index=false`/`auto_watch=false`
  после существенного diff нужна явная переиндексация. Подробности —
  `docs/CODEBASE_MEMORY_MCP.md`.

## Git safety

- Не делать force push и force reset. До push локальный непушенный commit можно
  amend только по прямому разрешению пользователя и только для объединения
  кода и документации одной логической задачи; после push история не
  переписывается.
- Не откатывать чужие/пользовательские изменения без прямого запроса.
- Не коммитить: `data/backups/`, `release/`, `exports/`, `screenshots/`,
  `migration_inputs/{raw,normalized,reports,workspace}/`, `__pycache__/`,
  `*.pyc`, test/candidate DB, секреты (см. `.gitignore` и local exclude).
- Перед коммитом — показать `git status`, `git diff --stat`, список файлов,
  результаты тестов, SHA-256 рабочей БД до/после. Коммитить только с явным
  подтверждением пользователя, если не оговорено иное в задаче.

## Release workflow

### Documentation Gate

Перед созданием любого release commit обязательно просканировать весь
репозиторий и подтвердить, что обновлены все затронутые текущей Stage разделы:

- `CHANGELOG.md` и README/пользовательские инструкции;
- архитектурная документация, diagrams и схемы;
- API/CSV contracts и описание workflow;
- Timeline/Audit/events и security/permissions;
- Manual QA, Release Notes, количество тестов и результаты gate.

Commit запрещён, если хотя бы один из этих разделов требует обновления.
Исторические version-specific отчёты не переписываются задним числом; для новой
Stage создаётся датированный report/appendix.

После успешного Documentation Gate:

1. Прогнать полный набор проверок из раздела «Команды тестов» выше.
2. Создать один commit для кода, тестов и документации логической задачи.
3. Выполнить `git show --stat HEAD` и убедиться, что документация входит в этот
   же commit. Если commit ещё не pushed и документация пропущена, amend допустим
   только после прямого разрешения пользователя; после push история не
   переписывается.
4. Если scope явно требует Windows artifact, собрать его отдельной release-
   процедурой через `build_windows_package.py`, см. `WINDOWS_RELEASE.md`.
5. Актуальные release-заметки хранить в `RELEASE_REPORT_ODE_*.md`; release-
   архивы находятся в `release/` и не коммитятся.

## Известные ограничения (source/runtime 0.14.0; ZIP 0.12.17 RC1)

- SQLite не рассчитана на активную многопользовательскую запись — актуально
  для этапов «несколько инженеров» и «сервер», требует отдельного решения.
- Нет корректирующих/сторнирующих операций для ошибочно проведенного
  прихода/расхода.
- Monitoring manual UI и optional DCIM collector реализованы; email/Rooms
  transport и Kaiten отсутствуют, недельный отчёт — базовая агрегация.
- Нет автоматического расписания/ротации backup.
- `inventory/webapp.py` — монолит (см. «Архитектура» выше) — главный источник
  риска регрессий при правке разметки/JS.
- Stage 0.13.3A.5 создаёт только 200-row review pilot (130 imported cards in a
  disposable DB): массовые receipts, issues, production reference migration и
  reset рабочей БД относятся к будущему Stage и требуют отдельного
  подтверждения.
- Production S/N uniqueness remains `COLLATE NOCASE`; case-distinct identity
  requires an ADR/schema decision. Numeric/corrupted source values remain
  quarantined, and real-source Vegman R200 coverage is unavailable.
- Полный перечень технического долга — `TECH_DEBT.md`.
