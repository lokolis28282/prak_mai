# Changelog ODE

## ODE 0.14.0 integrated presentation candidate (2026-07-18)

- добавлен рабочий ручной Monitoring flow: hostname/problem validation,
  опциональный Edge/Selenium DCIM collector, ping/classification, безопасная
  hostname routing, Rooms/email preview и локальная история без автоотправки;
- добавлена Knowledge Base с категориями, поиском, тегами, пагинацией,
  безопасным Markdown, create/edit/soft-delete, private attachments и
  server-side ролями `viewer`/`engineer`/`admin`;
- добавлены идемпотентные runtime-таблицы Knowledge и миграционный скрипт;
- восстановлены byte-exact LF для утверждённых DDL checksums и исправлен
  Windows `fsync` для candidate/test database публикации;
- добавлены конфигурация, документация, API/frontend/security/migration tests;
  локальные routing rules, Edge profile, cookies, БД и вложения не публикуются.
- интегрирован отдельный Reports changeset: УВР с CRUD/фильтрами, CSV/XLSX
  import/export, отчёты за смену и неделю; Reports читает складские события
  только через `WarehouseEventReader`;
- устранено дублирование Reports JavaScript в монолитном `ui.js`; рабочие
  сценарии вынесены в `static/js/reports/*`, а Reports subnavigation снова
  доступна оператору;
- normal startup promoted historical DB снова byte-stable: установка новых
  Reports/Knowledge таблиц выполняется только явным backup-guarded скриптом
  `scripts/migrate_runtime_modules.py`;
- headless Chrome проходит Warehouse receipt/issue/scanner/balance/history,
  Monitoring, Knowledge, УВР/сменный отчёт, Profile и Administration без
  browser/resource/HTTP/API500 ошибок;
- на Главную GitHub добавлена поддерживаемая SVG/Mermaid карта связей; локальный
  Codebase Memory index, internal JSON, runtime DB и вложения не коммитятся.

## ODE 0.14.0 — Full Inventory safety workflow and baseline rehearsal

- добавлен первый изолированный Monitoring capability: fail-closed
  Salt/Digital/X5Tech routing по hostname, безопасная подготовка To/CC/темы и
  публичный `MonitoringFacade`; UI, collectors и отправка писем не включены;
- offline генератор Tech/Digital rules переведён с отсутствующего `openpyxl`
  на standard-library OOXML reader ODE, исправлено повреждение завершающего
  дефиса в hostname pattern, JSON пишется атомарно;
- внутренние hostname/recipient JSON установлены только локально и исключены
  из публичного Git; GitHub получает код, тесты, контракты и Mermaid-карту
  архитектурных связей без company infrastructure data;

- рабочий Warehouse переведён в fail-closed состояние `NOT_INITIALIZED`:
  импортированные receipts/issues остаются доступной историей, но рассчитанный
  по ним остаток явно помечен как исторический и не считается физическим;
- реальные receipt/issue/scanner/delivery/inventory-number mutations блокируются
  на backend и CLI стабильной ошибкой `WAREHOUSE_NOT_INITIALIZED`; тестовые
  операции разрешены только в явно настроенном disposable demo contour;
- добавлен внешний FULL Inventory workspace: строгий text-only XLSX template,
  безопасный OOXML parser, provenance/source SHA, reference fingerprint,
  paginated Preview rows/findings и неизменяемая activity history;
- реализованы durable append-only manual resolutions, actor/reason/timestamp,
  explicit supersede для конфликтов и deterministic revalidation; raw Excel
  остаётся неизменным, corrected value хранится отдельно, старые Preview runs
  сохраняются, а digest учитывает effective resolution set;
- добавлен isolated `baseline_rehearsal/` contour: admin может собрать
  отдельную ODE target DB по approved V001..V008, создать import commit,
  approved snapshot и balance projection и доказать их равенство. Candidate
  никогда не заменяет рабочую БД, а `publish_available=false`;
- Catalog/Equipment automatic matching не выполняется: каждая включённая
  строка требует явного `CHOOSE_CATALOG_ITEM`, serialized row — отдельного
  equipment resolution; `LINK_EXISTING_EQUIPMENT` закрыт до Query Port;
- Preview performance: 1 000 строк — 0.13 s, 10 000 — 1.28 s, 50 000 —
  6.70 s на текущем MacBook; прогоны использовали temporary DB, исходная
  fixture DB осталась byte-identical;
- post-release hardening перевёл Inventory rows с materialized tuple на
  повторно открываемый streaming reader; независимый Preview worker теперь
  обрабатывает 50 000 строк за 6.45 s при peak RSS около 69 MiB;
- stale/double-submit операции защищены `BEGIN IMMEDIATE` и повторной проверкой
  active session/run; отмена во время Preview fail-closed, UI-кнопки работают
  single-flight;
- существующий source-vault object теперь повторно проверяется по SHA-256, а
  candidate path и cold import защищены от symlink/circular-import edge cases;
- runtime metadata синхронизирована на `0.14.0`; Windows builder больше не
  включает `data/warehouse.db`, runtime/candidate DB или credentials. Новый
  Windows ZIP этой работой не создавался.

## Warehouse Stabilization Reconciliation — 2026-07-15

- устранены `ResourceWarning: unclosed database` полного regression gate:
  семь raw SQLite test handles теперь используют явный `contextlib.closing`
  при сохранении прежней commit/rollback семантики;
- полный `unittest discover` вырос до 392 тестов и проходит под
  `-W error::ResourceWarning` без SQLite ResourceWarning;
- Python/JavaScript syntax, module/frontend audits и `git diff --check`
  проходят;
- ordinary headless Chrome smoke на временной byte-copy рабочей БД проходит
  receipt/issue/balance/history/search/profile/administration и Inventory
  Number workflow без console/window/resource/HTTP/API500 errors;
- создан `docs/project/` как единый current-state hub; Warehouse source Stage
  отделён от Target/Platform ODE delivery Stage без переписывания исторических
  review/DDL evidence;
- подготовлены отдельные focused prompts для независимого Warehouse review и
  двухфазного repository cleanup audit; массовое удаление/`git clean` без
  утверждённого hash manifest запрещено;
- независимый Warehouse review завершён со статусом `PASS`; Phase 1 cleanup
  audit не нашла кандидатов на удаление исходного кода и отделила безопасную
  локальную гигиену от evidence/archive решений владельца;
- выполнена минимальная безопасная Phase 2 cleanup: удалены только
  регенерируемые `__pycache__` вне защищённых artifact-контуров, а 20
  исторических корневых QA/release/review документов добавлены в единый
  documentation index;
- после прямого owner approval удалены byte-identical test ZIP, распакованный
  дубль canonical RC1, disposable migration workspace DB/output и Platform
  dev DB; локальная stabilization DB удалена только после `cmp` с целостным
  внешним SQLite backup. Raw/provenance/reports, canonical RC1 ZIP и активная
  рабочая БД сохранены; working tree уменьшен примерно с 2.2 GiB до 711 MiB;
- post-cleanup regression повторно проходит 392 tests с восемью ожидаемыми
  skip только для отсутствующих ignored full/pilot candidate DB; module/
  frontend audits и clean-test-DB dry-run проходят;
- `data/warehouse.db` не изменялась: финальный SHA-256
  `73568a1c3eecbd4476473f064620d7f0a196b336ce8ea6d834c5b99359d4b010`,
  `integrity_check=ok`, FK violations и sidecars отсутствуют.

## ODE Warehouse Final Stabilization Pass — 2026-07-14

- исправлен ложный «проблемы» KPI на Главной/Мониторинге: `incomplete_rows`
  считал опциональное поле `project` обязательным, из-за чего после промоушна
  исторических карточек счетчик показывал 50160 «проблем» из 50001 карточки
  (100% данных, не имеющих смысла); теперь считаются только реально
  обязательные для формы поля (`shelf`, `vendor`, `model`);
- удалён подтвержденно мёртвый код `inventory/webapp.py`: константы
  `UX_SCRIPT`, `WIZARD_SCRIPT`, `DELIVERY_JS` (149 строк) никогда не достигали
  браузера (`_externalized_html()` вырезает инлайновые `<script>`/`<style>`) и
  дублировали устаревшей версией то, что реально исполняет `static/js/ui.js`;
  среди прочего убрал видимость hardcoded vendor/model списков, которые на
  деле никогда не рендерились;
- удалены неиспользуемые `renderWizard`/`renderHeader`/`renderSidebar` из
  `static/js/components.js` (0 вызовов в кодовой базе);
- Главная: карточки `Monitoring`/`Reports` переименованы в `Мониторинг`/
  `Отчеты` для согласованности с остальным русскоязычным интерфейсом;
- Главная: добавлена полноценная карточка `Профиль` в `.portal-grid` (рядом с
  `Мониторинг`); top bar `.profile-actions` больше не дублирует вход в
  профиль/смену пароля отдельными кнопками — `openShiftProfile()` остаётся
  единственной role-aware точкой входа; `.portal-grid` переведена на 3 колонки,
  чтобы 5–6 карточек не оставляли одинокую карточку на отдельной строке;
- исправлена доказанная стороннняя regression этой же сессии: удаление
  `renderToast` затронуло `static/js/components/notifications.js`
  (`ReferenceError` на каждой загрузке страницы) — функция восстановлена,
  проверено headless smoke;
- исправлено устаревшее утверждение в `CLAUDE.md`/
  `docs/REFERENCE_DATA_ARCHITECTURE.md`, что production `reference_values`
  «остаётся плоским и неизменным»: после promotion полного historical
  candidate `reference_domains_v2`/`reference_values_v2`/`reference_aliases_v2`
  реально заполнены (20 доменов, 931 значение) и являются live источником
  `ReferenceDataService` для форм UI;
- найдено, но НЕ исправлено (требует отдельного data-correction этапа с
  byte-copy/backup/provenance protocol): 291 карточка (0.58% от 50000
  промоутнутых) имеет `item_name = '#N/A'` — Excel-артефакт из исходника
  исторической миграции, не код-баг.

## ODE Warehouse Stabilization — 2026-07-14

- заменён runtime-источник dropdown на canonical `reference_*_v2`; добавлен
  permission-gated редактор с pending/deactivate/rename/merge preview/audit;
- active ЦОД ограничен `Ixcellerate`; shelf/supplier garbage исключён из форм
  без изменения исторических raw значений;
- vendors/models больше не hardcoded, модели ограничены выбранным вендором;
- возвращена компактная module-card навигация; Monitoring и Reports показывают
  только «В разработке»;
- убран отдельный UX «режима администратора», backend role checks сохранены;
- черновики прихода/расхода получили schema v3, user/DB isolation, TTL 14 дней
  и явный Continue/Start over/Delete;
- draft rows можно удалять по одной, выбранными или полностью до confirm;
- global search получил cancellation/stale-response protection, canonical name/
  source name/Part Number и быстрый exact-identifier short circuit;
- доказанный ручной test receipt exact S/N `1` удалён атомарно после двух
  внешних backup; создан audit `TEST_DATA_REMOVED_AFTER_MANUAL_REVIEW`.

## Local Full Warehouse Promotion and Runtime Simplification

Дата: 2026-07-14

- `data/warehouse.db` стала единственной обычной локальной рабочей БД ODE;
  full candidate опубликована через проверенную sibling `.next` и атомарный
  `os.replace`, а старая тестовая БД сохранена byte-copy и SQLite `.backup`
  вне репозитория;
- ordinary `python3 app.py` принимает promoted marker DB как рабочую, печатает
  путь/версию/число карточек/integrity и не включает read-only candidate landing;
- повторный startup уже инициализированной full-marker БД не продвигает
  `sqlite_sequence` no-op вставками и сохраняет SHA рабочей БД;
- dashboard и карточки используют существующий `WarehouseFacade` и актуальные
  `stock_receipts`/`stock_issues`/allocations; legacy 23-card source больше не
  формирует KPI;
- normal Equipment Card/Timeline скрывает migration-only события и показывает
  opening state понятным термином «Начальный остаток»; migration review сохранён
  только как административная диагностика;
- scanner draft получил schema version, TTL и scope по пользователю и
  fingerprint рабочей БД; несовместимый ODE draft старой тестовой БД безопасно
  удаляется, ошибки localStorage не ломают UI;
- browser/unit/contract проверки выполняются на временных копиях; candidate и
  raw не редактируются, DB/backup/reports не готовятся к commit;
- финальный gate: 309 unit tests, Python/JavaScript syntax, module/frontend
  audits, ordinary и admin-review headless Chrome smoke; browser/HTTP/API500
  error counters равны нулю, SQLite integrity/FK чисты;
- серверный deployment, Kafka, release ZIP, commit и push не выполнялись.

Процедуры эксплуатации и rollback:
`docs/LOCAL_WORKING_DATABASE_RUNBOOK.md`.

## Full Historical Warehouse Candidate Build (historical pre-promotion stage)

Дата: 2026-07-14

- весь staging прихода (51 003) и расхода (20 357) получил one-row/one-status
  reconciliation в отдельной disposable `warehouse_full_candidate.db`;
- S/N identity разделяет `TEXT_EXACT`, Decimal-expanded provisional numeric и
  corrupted quarantine; полка не входит в identity, `БАЛАНС` не используется;
- issue-only S/N получают explicit migration opening state, а source/target S/N,
  conflicts, duplicates, warnings и provenance не теряются;
- candidate строится атомарно из operationally-empty Stage A DB, сохраняет
  только security/system/reference/staging contour и не копирует test operations
  из `data/warehouse.db`;
- добавлены full XLSX/Markdown migration и cleanliness reports, marker-guarded
  read-only API/UI, Equipment Card/Timeline, macOS/Windows launchers и backend
  запрет Inventory Number для provisional numeric identity;
- focused candidate/contract tests и headless Chrome smoke подтверждают marker,
  exact/leading-zero/numeric/opening behavior, clean contour, unchanged DB SHA,
  нулевые browser/API errors и отсутствие SQLite sidecars;
- production replacement, release ZIP, commit/push и server deployment не
  выполнялись. Подробности: `docs/FULL_WAREHOUSE_MIGRATION.md`.

## ODE 0.13, Stage 0.13.3A.5 — Preservation-Aware Pilot Migration Review

Дата: 2026-07-14

### Новые возможности

- добавлен отдельный pilot-only путь исторического прихода, который сохраняет
  `source_serial_value` символ в символ и использует
  `normalized_match_value` только для группировки/поиска;
- детерминированный selector с seed
  `ODE-0.13.3A.5-PILOT-v1` выбирает ровно 200 реальных receipt staging rows и
  сохраняет причину включения каждой строки;
- фиксированное распределение решений: 130 `IMPORT`, 10 `QUARANTINE`,
  7 `MANUAL_REVIEW`, 6 `EXACT_DUPLICATE`, 35
  `CONFLICT_HISTORY_ONLY`, 10 `QUANTITY_POSITION_DEFERRED` и 2
  `SOURCE_CORRUPTED_REJECTED`;
- source-safe exact duplicate ограничен шестью группами: только у них literal
  raw-equivalent row имеет primary с доказанной датой и безопасными
  reference/alias решениями; седьмая группа заблокирована pending supplier
  alias. Остальное duplicate coverage состоит из 26 identity-conflict groups и
  9 date/shelf/order history-variation groups;
- создаётся отдельная ignored DB
  `migration_inputs/workspace/warehouse_pilot_candidate.db`; исходная
  Stage 0.13.3A candidate и `data/warehouse.db` не перезаписываются;
- selection публикуется в локальных ignored
  `PILOT_RECEIPT_SELECTION.xlsx`/`.md`; identifier-поля XLSX сохраняются как
  text и проходят round-trip check.

### S/N, identity и canonical naming

- migration writer обходит опасный обычный `strip().upper()` validator, но
  переиспользует `ReceiptRepository`, caller-owned transaction, audit и
  Equipment Card Timeline;
- карточки создаются только для сохранных `TEXT_EXACT` rows с quantity `1`,
  доказанной source date и решением `IMPORT`; numeric/unproven и
  `SOURCE_CORRUPTED` никогда не создают карточку;
- одна normalized identity создаёт не более одной pilot card; exact duplicates
  и конфликтующие source rows сохраняются как provenance/history;
- shelf остаётся необязательным placement attribute, не входит в identity и не
  дробит serialized balance;
- Stage 0.13.3A references/aliases и canonical-name proposals переиспользуются
  без silent production reference creation; Huawei/xFusion и разные модели не
  объединяются;
- **FACT:** в фактическом source есть Vegman R220, но нет Vegman R200. Selector
  фиксирует `VEGMAN_R200_UNAVAILABLE_FROM_SOURCE` и не создаёт синтетическую
  source row; раздельность R200/R220 остаётся unit contract.

### Pilot DB, audit и Timeline

- pilot-only schema хранит marker, selection, одну identity на imported S/N,
  provenance, quarantine и performance metrics;
- pilot receipts помечаются `is_opening_balance=1`: они видны в pilot balance
  и Equipment Card, но не выдаются Reports как текущие receipt events;
- существующий `audit_log` используется для действий
  `MIGRATION_RECEIPT_IMPORTED`, `MIGRATION_SOURCE_ROW_LINKED`,
  `MIGRATION_CONFLICT_RECORDED`, `MIGRATION_EXACT_DUPLICATE_SKIPPED` и
  `MIGRATION_SERIAL_QUARANTINED`; второй event store не создаётся;
- Timeline отделяет исторический source date от времени миграции, показывает
  logical source file/sheet/row, source/canonical names и warnings; абсолютные
  локальные пути отфильтровываются.

### API, UI и безопасность

- marker-guarded review runtime требует `ODE_MIGRATION_PILOT=1`, точное имя DB,
  stage/status/read-only marker, обязательные таблицы, integrity/FK и отсутствие
  WAL/SHM/journal;
- после guard pilot startup отключает обычный schema initializer сервиса;
  production/default startup остаётся без изменений, а headless smoke проверяет
  неизменность SHA runtime-копии pilot DB;
- добавлены read-only `GET /api/migration-pilot` и pilot-вариант Equipment Card
  по `pilot_selection_id`; доступ разрешён только `admin`/`engineer`;
- pilot UI показывает permanent banner, selection, фильтры
  `IMPORT`/`QUARANTINE`/`CONFLICT`/`CORRUPTED` и migration section карточки;
  imported values рендерятся как text DOM nodes;
- все operational POST mutations в pilot mode запрещены backend; browser не
  получает raw XML, password hashes или абсолютные пути;
- безопасные macOS/Windows launcher'ы валидируют уже существующую pilot DB,
  ничего не пересобирают и никогда не подменяют production DB.

### БД и миграции

- production schema и `data/warehouse.db` не изменяются;
- Stage 0.13.3A candidate-only reference/staging schema сохраняется, а шесть
  `migration_pilot_*` tables существуют только в disposable pilot DB;
- лист `БАЛАНС`, исторический расход и оставшиеся receipt rows не импортируются;
- case-distinct S/N остаются несовместимы с текущим production
  `COLLATE NOCASE`; тяжёлая schema migration намеренно отложена до отдельного
  ADR/Stage.

### Тесты и документация

- добавлены selector/date/raw-source, exact writer/rollback, duplicate/conflict,
  marker/schema/security, read-only API/UI, launcher, identifier/XLSX round-trip
  и headless pilot scenarios;
- полный regression gate включает обычный UI smoke и отдельный pilot smoke на
  временной копии candidate DB; `unittest discover` проходит 292 теста с
  `-W error::ResourceWarning`;
- добавлены architecture, reviewer guide и manual QA; актуализированы S/N,
  reference, naming, staging, database ownership, security, API, events и
  Mermaid diagrams.

### Breaking changes

- для production runtime отсутствуют: обычный receipt/API/UI flow не меняет
  поведение, пока process не запущен с pilot flag и marker DB.

### Известные ограничения

- это 200-row review pilot, а не Stage 0.13.3B и не массовый import 51 003
  receipt rows;
- numeric S/N, corrupted values, quantity positions и unresolved references
  остаются вне складских карточек;
- реальный Vegman R200 отсутствует в источнике и не может быть проверен на
  source-driven pilot card;
- approval pilot review не разрешает production DB reset/replacement;
- окончательная case-sensitive production identity schema, reference approval
  authority и обработка исторического расхода остаются open decisions.

## ODE 0.13, Stage 0.13.3A — Reference Data Foundation, Canonical Naming and Migration Staging

Дата: 2026-07-14

### Новые возможности

- добавлен отдельный offline migration-слой для справочников,
  aliases, канонических наименований, точного извлечения S/N и
  migration staging;
- формализованы controlled domains для классификации объекта,
  оборудования, компонентов, кабелей, catalog data, поставщиков,
  локаций и операционных атрибутов;
- для aliases введены provenance, normalized source key, confidence,
  resolution status и поля ручного утверждения;
- каноническое имя строится детерминированно из типа, vendor,
  model/Part Number и основной характеристики; имя не является
  identity и может быть пересчитано;
- создаётся disposable candidate DB в ignored migration workspace с
  чистой актуальной production-схемой, candidate-справочниками и
  staging-таблицами только для review;
- проверенный candidate snapshot содержит 71 360 staging rows
  (51 003 receipt-source и 20 357 issue-source), 91 717 S/N-role cells,
  893 reference values, 916 aliases и 358 catalog proposals; все production
  operational tables пусты;
- добавлен validation/reporting CLI для проверки source SHA,
  identifier preservation, candidate schema, foreign keys и счётчиков.

### S/N preservation

- source S/N хранится отдельно от normalized match key; match key
  никогда не подменяет исходный identifier;
- XLSX extraction сохраняет файл/лист/строку/колонку, coordinate,
  cell type, number format, raw XML token, display/source value, warning,
  preservation status и source hash;
- numeric cells не проходят как безусловно безопасные: raw token
  анализируется без float, leading zeros могут быть восстановлены
  только при однозначном custom number format;
- все непустые numeric S/N требуют manual review и получают пустой
  match key; exponent token сохраняется буквально, а decimal display
  служит только подсказкой review;
- потерявшие точность длинные numeric identifiers отмечаются
  `SOURCE_CORRUPTED` и не допускаются к созданию ложной карточки;
- на фактическом warehouse source exact extractor нашёл четыре
  `SOURCE_CORRUPTED` cells: `ПРИХОД!L19513`, `ПРИХОД!L19580`,
  `РАСХОД!J4826`, `РАСХОД!J4866`; это два повторяющихся
  повреждённых значения, их match key пуст;
- CSV/XLSX preview пинит identifiers как text; round-trip тесты
  покрывают leading zeros, Unicode, internal spaces, long text, custom
  zero format и exponent notation.

### API, UI и безопасность

- HTTP endpoints, runtime UI и роли ODE не изменялись;
- будущий receipt UX с dependent references зафиксирован как
  `FUTURE STAGE`, а не как текущее поведение;
- candidate/staging tooling не принимает production DB как output,
  не печатает password hashes и не создаёт production references;
- команда `report` применяет тот же path/inode guard ко всем output,
  полностью регенерирует allowlisted JSON из candidate и никогда не
  доверяет/не объединяет содержимое старого report-файла;
- raw sources, reports, normalized previews, workspace DB и SQLite sidecars
  считаются local-only artifacts и не входят в commit/release ZIP.

### БД и миграция

- production schema `data/warehouse.db` не изменена; staging-таблицы
  не добавлены в `inventory/db.py`;
- текущая `reference_values(kind, name, is_active)` в runtime ODE не
  заменена; candidate-модель не считается production integration;
- исходный `БАЛАНС` не загружается и не считается источником
  операций;
- исторические receipt/issue rows не загружены ни в production,
  ни в операционные таблицы candidate DB;
- план будущего reset описывает byte-copy + SQLite backup,
  сохранение security identity, проверку candidate и отдельное
  явное подтверждение перед заменой рабочей БД; reset на этом Stage
  не выполнялся.

### Тесты и документация

- добавлены unit/integration тесты serial preservation, XLSX raw-cell
  extraction, identifier round-trip, reference normalization, alias safety,
  canonical naming, candidate DB, source/working-DB immutability и
  schema/security boundaries;
- focused migration suite содержит 39 тестов, включая regression cases для
  secret-bearing stale report и report path equal/hardlinked с source DB;
- актуализированы source review и основная архитектура; добавлены
  отдельные reference, naming, S/N, staging, reset и manual-testing
  contracts;
- полный gate после Stage проходит: 266 тестов (`OK` под
  `-W error::ResourceWarning`); baseline до Stage составлял 227 тестов.
- syntax и Node checks, module/frontend audits и clean-test-DB dry-run
  проходят; headless smoke посетил все маршруты, включая Inventory Number,
  и подтвердил ноль console/window/unhandled/resource/HTTP/API-500 errors;
- raw hashes и рабочая БД остались неизменными; рабочая SHA-256 —
  `eaab698c0bb8fd5de1ebd86a5999ee29d2a89e96b59e7fbaa171b0d38a26e8db`.

### Breaking changes

- отсутствуют: production API, UI, schema и warehouse behavior не
  изменены.

### Известные ограничения

- candidate package есть предложение для review, а не утверждённый
  production master-data set;
- semantic aliases, legal supplier/vendor variants, неоднозначные
  models и locations требуют ручного решения;
- повреждённые Excel numeric S/N нельзя восстановить без независимого
  authoritative источника;
- DCIM source остаётся пустым, Inventory Number source отсутствует;
- Stage 0.13.3B historical receipt migration требует отдельного
  review/approval и не запускается автоматически.

## ODE 0.13, Stage 0.13.3 — УВР (учет выполненных работ) и текстовые отчеты смены

Дата: 2026-07-14

- раздел `Отчеты` получил три рабочие вкладки: `УВР`, `Отчет за смену`,
  `Отчет за неделю`;
- в `work_logs` добавлена колонка `section` («Раздел») и служебный флаг
  `needs_review` для мигрированных строк, требующих проверки;
- вкладка `УВР` — реестр работ смены с сортировкой по столбцам, поиском по всем
  полям, фильтрами (период, статус, раздел), созданием, редактированием через
  модальное окно и удалением строк без перезагрузки страницы;
- «Имя задачи» вводится единым combobox с шаблонами (PNR-, Заказ, Outlook:,
  ROOMS, Zabbix и т.д.); шаблон без номера (ROOMS, Time, Zabbix) допустим,
  полностью анонимная запись отклоняется;
- `Отчет за смену` показывает таблицу выполненных работ за выбранную дату,
  `Отчет за неделю` — за период; обе вкладки используют те же столбцы, что и
  `УВР` (Дата, Имя задачи, Описание работ, Статус, Раздел, Тип, Комментарий),
  показывают инженера, под которым выполнен вход, и выгружают именно список
  работ за период в CSV (не складскую агрегацию);
- `Раздел` в форме новой записи и в модальном окне редактирования — строгий
  выпадающий список фиксированных разделов; свободный ввод недоступен, но
  унаследованные из Excel значения сохраняются и остаются редактируемыми;
- `work_log_section` добавлен в набор редактируемых справочников
  (`Администрирование → Справочники`).

### Импорт из Excel

- добавлен временный импорт истории работ из XLSX (кнопка `Импорт из Excel` на
  вкладке `УВР`) для миграции из старого файла «Баланс»;
- XLSX читается средствами стандартной библиотеки (`zipfile` + `xml.etree`),
  внешние зависимости не добавлены; поддержаны shared/inline strings и
  Excel-даты;
- заголовки сопоставляются существующим механизмом синонимов; читается только
  первый блок листа «Логи»/«Отчет», складские блоки игнорируются;
- значения `Раздел`, отсутствующие в справочнике, сохраняются как есть и
  помечаются `needs_review`; данные не теряются; импорт проходит через
  существующий preview → confirm с атомарной транзакцией.

### API и безопасность

- `POST /api/action` поддерживает `UPDATE_WORK_LOG` и `DELETE_WORK_LOG`
  (роли `engineer/admin`, `viewer` отклоняется сервером);
- `POST /api/preview-xlsx?sheet=<лист>` принимает XLSX и строит preview логов
  работ; прямой импорт без preview недоступен;
- отчеты за смену и за неделю используют существующий `GET /api/work-logs` с
  фильтром по дате и экспортируются через `GET /export/work-logs.csv`;
- каждое реальное изменение фиксируется audit-действиями `WORK_LOG_UPDATE` и
  `WORK_LOG_DELETE`.

### Тесты и документация

- добавлен `tests/test_uvr_workflow.py` (19 тестов): миграция схемы, CRUD и
  аудит, права `viewer`, standalone-задачи, narrative-отчеты, XLSX preview/
  confirm, fuzzy-сопоставление разделов, флаг проверки, пропуск строк-
  разделителей;
- обновлены README, CHANGELOG, `docs/REPORTS_ARCHITECTURE.md`,
  `docs/DATA_MODEL_ODE_013.md`, `docs/FRONTEND_CONTRACTS.md`.

### БД и миграции

- идемпотентная миграция добавляет `section` и `needs_review` в существующую
  `work_logs` (`ALTER TABLE ADD COLUMN`), данные не изменяются;
- добавлен справочник `work_log_section` и расширены `task_source`/`task_type`
  значениями из рабочего процесса смены.

## ODE 0.13, Stage 0.13.2 — Bulk Inventory Number Import

Дата: 2026-07-14

### Новые возможности

- добавлено массовое назначение Inventory Number существующему оборудованию из
  CSV через обязательные Preview и Confirm;
- поиск выполняется исключительно по S/N; отсутствующий S/N получает
  `NOT_FOUND`, новая карточка не создаётся;
- публичные построчные статусы:
  `SUCCESS`, `UNCHANGED`, `NOT_FOUND`, `ALREADY_ASSIGNED`,
  `DUPLICATE_INVENTORY_NUMBER`, `VALIDATION_ERROR`;
- повтор S/N внутри CSV является blocking validation error; остальные
  конфликты пропускаются, а допустимые строки могут быть применены;

### UI

- добавлены UTF-8 BOM template, выбор CSV, таблица Preview, status counters,
  Confirm и итоговый Result в разделе `Склад -> Инвентаризация`;
- Equipment Card Timeline показывает существующее audit-событие для каждой
  реально изменённой позиции.

### API и безопасность

- добавлен шаблон `GET /import/inventory-numbers-template.csv`;
- существующий `POST /api/preview-csv` поддерживает
  `kind=inventory_numbers`;
- существующий `POST /api/action` поддерживает
  `CONFIRM_IMPORT_PREVIEW` с `kind=inventory_numbers`;
- прямой `/api/import-csv?kind=inventory_numbers` запрещён: обойти preview и
  confirm нельзя;
- preview/confirm разрешены только `engineer/admin`; `viewer` отклоняется
  сервером; preview одноразовый, author-bound и ограничен TTL.

### Бизнес-логика, audit и Timeline

- preview выполняет только чтение и не меняет БД/audit;
- confirm начинает `BEGIN IMMEDIATE`, повторно анализирует весь план и
  отклоняет stale preview;
- все строки `SUCCESS`, legacy sync и audit применяются одной SQLite-
  транзакцией; при любой ошибке выполняется полный rollback;
- на каждую реально изменённую позицию создаётся существующее audit-действие
  `EQUIPMENT_INVENTORY_NUMBER_ASSIGNED`, которое отображается в Timeline
  карточки; отдельная event subsystem не создана;
- заполненный другой номер не перезаписывается, занятый номер не передаётся
  другой позиции, повторный импорт становится `UNCHANGED`.

### Импорт, тесты и документация

- обязательны столбцы Serial Number и Inventory Number; parser поддерживает
  UTF-8/UTF-8 BOM, compatibility fallback CP1251 и разделители `;`, `,`, tab;
- лимиты общих импортов сохранены: 50 МБ и 40 000 непустых строк; preview
  возвращает до 100 строк и 200 validation errors;
- добавлены 16 unittest (2 unit, 7 contract/integration, 3 API,
  4 frontend-contract) и headless сценарий; полный набор содержит 227 тестов;
- добавлены нормативный архитектурный/API-контракт и руководство ручной
  проверки Stage 0.13.2; актуализированы README, module/security/data/event и
  diagram-документы.

### БД и миграции

- схема и модель хранения не менялись; migration не требуется;
- используются существующие `stock_receipts.inventory_number`, связанная
  legacy `equipment.inventory_number`, unique constraints и `audit_log`;
- runtime-метаданные исходников и target package builder остаются
  `0.12.17.1 RC2`, тогда как последний фактически собранный Windows ZIP
  содержит `ODE 0.12.17 RC1`; ZIP RC2/Stage 0.13.2 не собирался;
- перед следующим Windows-релизом metadata, builder, embedded release notes и
  test count требуется синхронизировать отдельным release change.

### Исправления

- отдельных исправлений вне нового bulk workflow нет; бизнес-логика
  Stage 0.13.1 и существующих import/export сценариев не изменялась.

### Breaking changes

- отсутствуют: существующие API, CSV kinds и схема БД обратно совместимы.

### Известные ограничения

- preview хранится в памяти процесса, теряется при restart/TTL/eviction и
  после неуспешного confirm требует нового Preview;
- отдельного persisted batch ID, batch audit-event и фонового progress нет;
- сохраняются ограничения single-process SQLite и необходимость отдельной
  приемки на целевом Windows-хосте.

## ODE 0.13.1 — Equipment Card Inventory Workflow

Дата: 2026-07-13

- существующая карточка оборудования получила workflow присвоения Inventory
  Number после появления S/N: обновляется та же строка `stock_receipts`, новая
  карточка не создаётся;
- запись проходит через `ApplicationContext -> WarehouseFacade ->
  ReceiptWriteService -> ReceiptRepository -> SQLite`; отдельный endpoint,
  глобальный сервис и параллельная бизнес-логика не добавлены;
- заполненный Inventory Number нельзя перезаписать из карточки; повтор того же
  запроса идемпотентен, дубли блокируются существующими unique constraints и
  проверкой legacy `equipment`;
- связанная через `legacy_equipment_id` карточка синхронизируется в той же
  транзакции; viewer не может выполнить запись;
- реальное изменение фиксируется audit-действием
  `EQUIPMENT_INVENTORY_NUMBER_ASSIGNED` и автоматически попадает в текущую
  Timeline карточки;
- форма показывается внутри существующего `openPositionCard` только для S/N без
  Inventory Number и ролей `engineer/admin`; DOM строится безопасными
  компонентами без HTML-интерполяции пользовательского значения;
- добавлены contract/API/query-plan тесты и headless Chrome сценарий. Схема БД
  не менялась, рабочая `data/warehouse.db` не использовалась для mutation-тестов,
  release не собирался.

## ODE 0.12.17.1 RC2 — Compact Navigation, Search Modal, Test Circuit

Дата: 2026-07-12

- шапка стала компактной: убран постоянный ряд крупных разделов
  (`.product-nav`, дублировавший навигацию), фактическую разметку строит
  `warehouseLanding()` — экран «Добро пожаловать в ODE» с четырьмя карточками
  (Склад, Отчеты, Мониторинг, Профиль) теперь всегда виден на «Главной» вместо
  KPI-дашборда, который его раньше перезаписывал при каждой загрузке данных;
- глобальный поиск переведен с постоянного поля в шапке на кнопку-лупу и
  модальное окно; автофокус, debounce (180 мс), клавиатурная навигация
  (стрелки/Escape), поиск через существующий `/api/global-search` и открытие
  существующей карточки оборудования — без изменений в логике, изменена
  только разметка/презентация;
- добавлен `scripts/create_clean_test_db.py`: собирает одноразовую тестовую
  копию БД из рабочей базы, очищает только операционные (складские/отчетные)
  таблицы и сохраняет пользователей, хеши паролей, категории, полки и
  справочники; поддерживает `--dry-run`, `--profile empty`, `--profile demo`,
  требует `--overwrite` для существующего файла и никогда не разрешает
  `--source == --output`; рабочая база открывается только на чтение;
- добавлены `start_test_macos.command` и `start_test_windows.bat` —
  запускают ODE только на пересобираемой тестовой базе
  `data/warehouse_test_clean.db`; интерфейс показывает баннер
  «ТЕСТОВЫЙ КОНТУР» (флаг `ODE_TEST_MODE=1`), обычные launcher'ы его не
  устанавливают;
- временные scanner-списки прихода и расхода получили колонку «Действие»,
  одиночное/выбранное/полное удаление, счетчик, duplicate highlight и защиту
  от гонок scan/confirm; canonical JS state, localStorage, DOM и confirm payload
  обновляются одним путем, подтвержденные складские записи не удаляются;
- `create_clean_test_db.py` усилен SQLite read-only + Backup API snapshot,
  учетом WAL, FK-проверкой и атомарной публикацией; 15 тестов генератора
  проверяют также точное сохранение пользователей, password hashes и
  справочников, изоляцию launcher-окружения и запрет test-режима на рабочей БД;
- серверный поиск баланса сразу скрывает прежние кликабельные строки на время
  debounce/запроса, поэтому нельзя случайно открыть или списать чужую позицию;
- добавлены `CLAUDE.md` и developer-only настройка `codebase-memory-mcp`;
  MCP/cache не входят в runtime и release ZIP;
- схема БД не менялась; все автоматические mutation-проверки выполняются на
  временных/test DB. Контрольный SHA рабочей БД фиксируется до и после gate и
  должен совпадать;
- полный набор содержит 206 тестов; Windows package builder синхронизирован с
  именем RC2 и test-contour support-файлами, но release ZIP в рамках патча не
  пересобирался.

## ODE 0.12.17 RC1 — Product Hardening

Дата: 2026-07-11

- добавлены Dashboard, быстрые действия, постоянная навигация и глобальный поиск;
- расширена карточка оборудования и единая хронология связанных операций;
- `Проблемы` и `События` перенесены в `Склад`, Monitoring оставлен заглушкой;
- ограничены bootstrap, баланс, поставки, inventory DOM, история и preview storage;
- ускорены exact S/N/inventory paths, batch uniqueness и агрегирование категорий/проблем;
- добавлены delivery pagination и серверный поиск усеченного баланса;
- закрыты повторное связывание receipt с поставками и неконтролируемые JSON 500;
- добавлены session TTL/limits, admin login rate limit, Host/Origin checks и security headers;
- инженерный HTTP-контекст принудительно работает с service-role `engineer`;
- обязательная смена начального admin-пароля блокирует остальные admin operations;
- server/client CSV exports защищены от spreadsheet formulas, wizard DOM — от найденного XSS sink;
- UI smoke расширен глобальным поиском, Back/reload, mobile 390 px и реальной проверкой `/api/admin`;
- полный набор содержит 185 тестов; схема таблиц и существующие HTTP actions сохранены.

## ODE 0.12.16 RC1 — Release Candidate

Дата: 2026-07-11

- зафиксирована проверенная версия после Stage 0.12.16A acceptance поставок;
- полный сценарий поставок пройден в headless Chrome: preview, confirm,
  карточка, scanner acceptance, existing S/N, conflicts, unplanned acceptance,
  batch acceptance, balance, history and reports;
- 158 тестов проходят, UI smoke проходит, JS/runtime/resource/API500 ошибок
  нет;
- рабочая БД и схема не менялись; `integrity_check = ok`,
  `foreign_key_check` пуст;
- close delivery остается compatibility/legacy;
- destructive override конфликтующих данных не реализован;
- версия предназначена для тестовой эксплуатации, не для production.

## Stage 0.12.16 — Delivery Acceptance Migration

Дата: 2026-07-11

- planned and unplanned delivery acceptance migrated to
  `ApplicationContext -> WarehouseFacade`;
- added inspect before accept, acceptance summary, conflict read, batch accept
  and safe delivery line metadata update facade methods;
- new planned S/N creates a receipt through the Warehouse receipt repository
  transaction contract and links `delivery_lines.receipt_id`;
- existing S/N does not create a receipt; only empty allowed fields are filled,
  and filled-field conflicts are reported without overwrite;
- unplanned acceptance requires explicit metadata, creates an unplanned
  delivery line and then creates a receipt;
- delivery status refresh moved behind WarehouseFacade; close delivery remains
  legacy;
- balance/history/reports continue to read source warehouse rows through current
  contracts;
- no DB migration; release ZIP not rebuilt.

## Stage 0.12.15 — Delivery Document Import and Matching

Дата: 2026-07-11

- документ поставки отделён от фактического складского прихода;
- delivery CSV preview, column mapping, S/N parsing, duplicate matching,
  stock matching, confirm document, list/card/search/export/template routes
  переведены на `ApplicationContext -> WarehouseFacade`;
- добавлен Warehouse-owned delivery import layer:
  `delivery_imports`, `delivery_repository`, `delivery_mapping`,
  `delivery_validators`, `delivery_previews`, `delivery_models`;
- confirm создаёт только `deliveries`, `delivery_lines` и audit
  `DELIVERY_UPLOAD`; `DELIVERY_IMPORTED` остаётся warehouse event contract;
- `stock_receipts`, `stock_issues`, allocations and balance не меняются при
  delivery import;
- acceptance scanner, planned/unplanned accept, close delivery and receipt
  creation from delivery remain legacy for Stage 0.12.16;
- новый пользовательский шаблон поставки зафиксирован без legacy-only колонок;
- БД и схема не менялись; release ZIP не пересобирался.

## Stage 0.12.14 — Warehouse Equipment and Component Issue Migration

Дата: 2026-07-11

- serialized equipment/component issue write/import routes migrated to
  `ApplicationContext -> WarehouseFacade`;
- migrated manual issue, issue scanner validation, scanned S/N confirm, generic
  issue CSV preview/confirm/import, and strict bulk S/N issue preview/confirm;
- issue allocations and computed balance contracts preserved;
- soft problem-row behavior preserved for scanned/CSV issue flows;
- Warehouse-owned issue preview storage is used for issue and bulk issue
  previews;
- cable issue remains separate in the cable module;
- deliveries, inventory write, Administration write, backup/restore, auth,
  Monitoring and legacy equipment/operations remain compatibility-backed;
- БД и схема не менялись; release ZIP не пересобирался.

## Stage 0.12.13 — Cable Warehouse Module

Дата: 2026-07-11

- кабели отделены от S/N-оборудования и компонентов на уровне
  `WarehouseFacade`;
- manual cable receipt and manual cable issue routes now go through
  `ApplicationContext -> WarehouseFacade -> inventory/warehouse/cables.py`;
- добавлены cable validators, repository and models;
- кабели не требуют S/N, учитываются положительным целым количеством and do not
  use scanner/S/N receipt validation;
- cable balance/history/Reports contracts сохранены через текущие
  `stock_receipts`, `stock_issues`, `stock_issue_allocations` and
  `WarehouseEventReader`;
- audit actions для новых cable writes: `CABLE_RECEIPT_CREATE`,
  `CABLE_ISSUE_CREATE`, `CABLE_RECEIPT_BATCH`;
- общий issue оборудования/компонентов, поставки, inventory write,
  Administration write, backup/restore and Monitoring remain compatibility;
- БД и схема не менялись; release ZIP не пересобирался.

## Stage 0.12.12 — Warehouse Receipt Write Facade Migration

Дата: 2026-07-11

- equipment/component receipt write/import routes переведены на
  `ApplicationContext -> WarehouseFacade`;
- мигрированы manual receipt, scanned S/N batch confirm, receipt serial
  validation, receipt CSV preview/confirm and direct receipt CSV import;
- добавлена Warehouse-owned receipt preview storage;
- добавлено системное наименование через `build_item_name(...)`;
- batch/import операции валидируют все строки до записи и пишутся атомарно;
- balance/history/Reports event contracts сохранены: receipt rows видны в
  balance, WarehouseEventReader and daily/weekly reports;
- добавлены receipt write contract/API tests, включая rollback, duplicate S/N,
  actor/audit, preview/confirm, 100-row batch and delivery regression;
- issue, cable receipt, deliveries, inventory write, Administration write,
  backup/restore and Monitoring remain compatibility-backed;
- БД и схема не менялись; release ZIP не пересобирался.

## Stage 0.12.11 — Reports Write and Import Facade Migration

Дата: 2026-07-11

- Reports write/import routes переведены на `ApplicationContext -> ReportsFacade`;
- мигрированы single work log, batch work logs, work-log CSV import,
  work-log CSV preview/confirm and uploaded daily report import;
- preview для Reports хранится отдельно от warehouse previews в Reports-owned
  in-memory storage;
- массовые операции валидируют все строки до записи и сохраняются атомарно;
- audit сохраняется через shared audit adapter с автором, count, filename/id;
- добавлены Reports write contract/API tests, включая rollback, роли, preview,
  кириллицу, даты, audit и проверку складских таблиц;
- architecture audit запрещает legacy Reports write calls из webapp и доступ
  Reports к warehouse-owned tables;
- API/CSV URL, action names, response keys and headers сохранены;
- БД, схема, Warehouse writes, Administration writes, Monitoring, frontend
  component migration и release ZIP не менялись.

## Stage 0.12.10 — Warehouse EventReader Contract

Дата: 2026-07-11

- создан публичный контракт `WarehouseEvent` и `WarehouseEventReader`;
- `ReportsFacade` получает складские события через `ApplicationContext`;
- daily report, weekly report, weekly rows and report CSV exports построены через WarehouseEventReader;
- work logs остаются собственными данными Reports;
- результаты отчетов и CSV byte/text contract сохранены относительно legacy;
- добавлены EventReader и Reports event contract tests, включая 1000 warehouse events на временной БД;
- architecture audit запрещает SQL по warehouse-owned таблицам внутри `inventory/reports`;
- БД, схема, write/import flows, Monitoring, frontend и release ZIP не менялись;
- EventReader пока compatibility-backed внутри Warehouse и может читать текущую SQLite-схему.

## Stage 0.12.9 — Administration Read API Facade Migration

Дата: 2026-07-11

- read-only Administration API routes переведены на `AdministrationFacade`;
- `/api/data` продолжает отдавать текущего пользователя без раскрытия секретов;
- `/api/admin` собирает `backups`, `audit` и `users` через AdministrationFacade;
- `/export/audit.csv` читает audit через AdministrationFacade;
- URL, JSON/CSV контракты, роли и существующие ограничения доступа сохранены;
- добавлены Administration API contract/security tests;
- `password_hash`, session token и пароли не возвращаются в read API;
- write/admin actions, login/logout и auth flow пока legacy;
- БД, Monitoring, frontend Administration components и release ZIP не менялись.

## Stage 0.12.8 — Reports Read API Facade Migration

Дата: 2026-07-11

- read-only Reports API routes переведены на `ReportsFacade`;
- `/api/data` продолжает отдавать тот же JSON, но reports-owned поля читаются через ReportsFacade;
- внешние JSON/CSV контракты, URL, имена файлов, BOM, разделители и заголовки сохранены;
- добавлены Reports API contract tests и semantic comparison old service vs facade;
- module boundary audit теперь запрещает прямые read-only reports `service.*` вызовы из `_do_GET`;
- Warehouse events остаются read-only входом для отчетов через публичный контракт/compatibility layer;
- write/import логов работ и готовых отчетов пока legacy;
- БД, SQL, Monitoring, frontend Reports components и release ZIP не менялись.

## Stage 0.12.7 — Warehouse Read API Facade Migration

Дата: 2026-07-11

- read-only Warehouse API routes переведены на `WarehouseFacade`;
- `/api/data` внутри разделен: складские данные идут через WarehouseFacade, отчеты через ReportsFacade, пользователь через AdministrationFacade;
- внешние JSON/CSV контракты, URL и имена файлов сохранены;
- добавлены API contract tests и semantic comparison old service vs facade;
- module boundary audit теперь запрещает прямые read-only warehouse `service.*` вызовы из `_do_GET`;
- write API, импорты, confirm-flow, scanner validation и WarehouseCore остаются legacy;
- БД, SQL, бизнес-логика и release ZIP не менялись.

## Stage 0.12.6 — Product Module Boundaries

Дата: 2026-07-11

- создан переходный каркас модулей `core`, `warehouse`, `reports`, `monitoring`, `administration`;
- добавлены публичные фасады `WarehouseFacade`, `ReportsFacade`, `MonitoringFacade`, `AdministrationFacade`;
- добавлен `ApplicationContext` с централизованными feature flags;
- Monitoring изолирован как заглушка без зависимостей от Warehouse и Reports;
- добавлены frontend entrypoints для Core/Warehouse/Reports/Monitoring/Administration и компонентных подпакетов;
- добавлен `EventReader`/`EventPublisher` контракт, временно читающий складские события из существующей истории;
- добавлены документы по модульной архитектуре, владельцам таблиц, Reports, Monitoring и миграции;
- добавлен архитектурный аудит `scripts/audit_module_boundaries.py`;
- БД, бизнес-логика, реальные складские операции и release ZIP не менялись.

## Stage 0.12.5 — History Components

Дата: 2026-07-11

- рабочий экран `История` перенесен на компонентный DOM-рендер;
- старый `renderOperations()` оставлен только как compatibility alias к `renderWarehouseHistory()`;
- действия истории получают человекочитаемые названия через единый словарь;
- `details` и комментарии разбираются безопасно, ошибочный JSON не ломает экран;
- фильтры периода, инженера, действия и поиска работают на клиенте без изменения API;
- таблица истории ограничена первыми 200 строками текущей выборки;
- БД, API, сервисный слой, бизнес-логика и release ZIP не менялись.

## Stage 0.12.4 — Balance Components

Дата: 2026-07-10

- рабочий экран `Баланс` перенесен на `components.js`;
- KPI-карточки баланса `Серверы`, `Диски`, `Память`, `Сеть`, `Кабели`, `Прочее` строятся DOM-компонентами;
- фильтр по KPI-карточкам, активная подсветка и `Сбросить фильтр` работают без inline `onclick`;
- таблица баланса и кнопки строк `Открыть карточку` / `Списать` строятся DOM-узлами без `innerHTML`;
- поиск и select-фильтры баланса применяются вместе с KPI-фильтром;
- legacy `renderBalance()` оставлен только как fallback раннего render-прохода;
- бизнес-логика, сервисный слой, БД, приход, расход, поставки, отчеты и release ZIP не менялись.

## Stage 0.12.3 — Home and Navigation Components

Дата: 2026-07-10

- экран «Добро пожаловать в ODE» перенесен на `components.js`;
- карточки Главной `Склад`, `Отчеты`, `Мониторинг`, `Профиль` теперь строятся DOM-компонентами без `innerHTML`;
- клик по ODE в верхней панели переведен на component-кнопку и `goHome`;
- базовая навигация разделов строится в `router.js` через `renderButton`;
- legacy-экраны склада, отчетов, поставок и профиля не переписывались;
- бизнес-логика, сервисный слой и БД не менялись;
- release ZIP не пересобирался.

## Stage 0.12.2 — Architecture Stabilization

Дата: 2026-07-10

- зафиксирован backend facade: `inventory.service.WarehouseService` остается публичной точкой входа;
- `WarehouseCore` явно признан временным compatibility core;
- создан и задокументирован слой `inventory/services/*`;
- новые сервисы пока являются делегатами, перенос бизнес-методов будет идти постепенно;
- добавлен документ `docs/SERVICE_MIGRATION_PLAN.md`;
- добавлен UI component layer `static/js/components.js`;
- `static/js/ui.js` зафиксирован как legacy UI на переходный период;
- добавлены документы `docs/UI_COMPONENTS.md` и `docs/FRONTEND_MIGRATION_PLAN.md`;
- добавлен frontend contract audit `scripts/audit_frontend_contracts.py`;
- добавлен документ `docs/FRONTEND_CONTRACTS.md`;
- smoke UI теперь явно отчитывается об отсутствии console/runtime/window errors и прохождении ключевых разделов;
- миграция БД не выполнялась;
- бизнес-логика не менялась;
- release ZIP не пересобирался.

## ODE 0.12 — стабилизационный патч

- исправлен переход из параметров партии к временному списку S/N;
- наименование партии строится из типа, вендора и модели;
- упрощены приход, расход, навигация и шаблон поставки;
- добавлены кликабельный ODE и раздел «История».
- добавлены фильтруемые карточки баланса и localStorage-черновики скан-листов;
- поставки получили preview новых/обновляемых строк и атомарный confirm;
- добавлен самозавершающийся headless Chrome smoke-test.

История развития рабочего инструмента «ODE учет работ и склада». Учебные материалы ведутся отдельно и не определяют этот файл.

## Приемка сканером и поставки — 1 июля 2026

- добавлены атомарные приемка и списание списков S/N со сканера, работающего как клавиатура;
- неизвестные S/N расхода сохраняются как проблемные строки;
- добавлены загрузка и проверка документов поставки, поиск дублей и уже имеющихся позиций;
- реализованы карточка поставки, групповое заполнение реквизитов, приемка по S/N, внеплановые позиции, закрытие и CSV-выгрузка результата;
- добавлены таблицы `deliveries` и `delivery_lines`;
- ежедневные и недельные отчеты учитывают операции приемки поставок;
- актуальный автоматический набор содержит 72 теста.

## Финальный рабочий проход и пакет Windows — 28 июня 2026

### Интерфейс

- приведены к рабочему виду названия разделов, вкладок, кнопок загрузки, резервного копирования и проверки базы;
- установлен рабочий порядок вкладок склада, отчетов и мониторинга;
- баланс сделан главным рабочим экраном и ограничен первыми 500 строками без ограничения скачиваемой выборки;
- добавлены отдельный поиск карточек, последние 20 приходов, проблемные списания и раздел загруженных отчетов;
- карточка позиции получила связанные проблемные строки, переход к списанию и скачивание истории;
- технические формулировки скрыты от пользователя.

### CSV и надежность

- все пользовательские CSV-шаблоны и отчеты используют `;` и UTF-8 BOM для Excel с русской локалью;
- сохранены проверка файла, атомарное подтверждение и обработка файлов до 40 000 строк;
- перед работами создана резервная копия `warehouse_before_windows_final_20260628_123926.db`;
- добавлены проверки шаблонов, интерфейсных подписей и состава переносимого архива.

### Windows

- добавлены `README_WINDOWS.md` и понятный `start_windows.bat`;
- добавлен сборщик `build_windows_package.py`;
- переносимый архив содержит программу, рабочую базу и одну актуальную проверенную резервную копию без кэшей Python.

## Текущее состояние

- название: ODE;
- расшифровка: Отдел дежурных инженеров;
- режим: локальное приложение Python + SQLite;
- запуск: `python3 app.py`;
- основная база: `data/warehouse.db`;
- внешние зависимости: отсутствуют;
- автоматические тесты: 72.

## Stage 4.3 — отказ от Excel как основной логики

Завершен 28 июня 2026 года.

### Добавлено

- двухэтапный preview/confirm для CSV прихода и расхода без записи и аудита на этапе просмотра;
- статистика preview, первые 50 строк и ошибки с номером строки;
- серверные одноразовые preview-сессии и повторная проверка перед подтверждением;
- карточка позиции из баланса с текущим остатком, приходами, расходами, аллокациями и аудитом;
- общий поиск баланса и поиск позиции для расхода по складским реквизитам;
- автозаполнение формы расхода из найденной позиции;
- строгое массовое списание S/N оборудования и компонентов одной транзакцией;
- рабочие действия «Открыть» и «Списать» в балансе и экспорт текущей выборки;
- базовый еженедельный отчет, разбивки по проектам/типам и CSV-экспорт;
- тесты preview, подтверждения, карточек, поиска, атомарного массового расхода и недельного отчета.

### Совместимость и границы

- старые сервисные методы импорта сохранены для служебных сценариев;
- импорт логов работ и готовых ежедневных отчетов не изменен;
- схема рабочих таблиц не переписывалась, миграция БД не потребовалась;
- справочники продолжают работать в мягком режиме;
- DCIM, Kaiten, Solar и мониторинг не изменялись;
- backup до изменений: `data/backups/stage4_3_20260628_114208`.

## Stage 4.2.1 — свободный тестовый режим справочников и CSV

Завершен 28 июня 2026 года.

### Добавлено

- `strict_reference_validation = false` по умолчанию для прихода и расхода;
- свободный текст в ручных формах и CSV с подсказками из справочников;
- автоматический сбор фактических значений в `reference_values`;
- справочники наименований, моделей, стеллажей/полок и ЦОД;
- алфавитная сортировка значений с активными выше отключенных;
- баланс и его фильтры по фактически введенным значениям;
- тесты мягкого режима, автосбора, строгого режима и баланса.

### Миграция

- SQL-ограничение единиц учета `шт/м` снято без удаления строк прихода;
- существующие значения прихода перенесены в соответствующие справочники;
- backup до изменений: `data/backups/stage4_2_1_20260628_110306`.

## Stage 4.2 — пользователи и административный контур

Завершен 27 июня 2026 года.

### Добавлено

- локальные профили, роли `admin` / `engineer` / `viewer` и cookie-сессии;
- PBKDF2-SHA256-хеширование паролей стандартной библиотекой Python;
- дефолтный администратор `lokolis` только для пустой таблицы пользователей;
- смена пароля и признак рекомендации смены начального пароля;
- реальный email автора в аудите;
- ролевые проверки операций записи и admin-only функций;
- безопасная загрузка `.db` в прод со страховочным backup, миграцией, проверкой и откатом;
- таблицы `daily_report_uploads` и `daily_report_rows`;
- атомарный импорт, просмотр и экспорт готового ежедневного CSV-отчета;
- группировка и фильтр справочников;
- настройка текущего ЦОД `CURRENT_DATACENTER = "Ixcellerate"`;
- новые названия навигации и заглушка учета поставок-отправок.

### Миграция

- складские таблицы и существующие данные не переписываются;
- новые таблицы и индексы создаются идемпотентно;
- backup до миграции: `data/backups/warehouse_before_stage4_2_20260627.db`;
- интеграции с DCIM, Kaiten, Solar и мониторинг не изменялись.

## Stage 4.1 — эксплуатационная надежность без ролей

Завершен 27 июня 2026 года.

### Добавлено

- таблица единого аудита `audit_log`;
- автор аудита `local_user` без системы ролей;
- backup рабочей SQLite-базы через SQLite Backup API;
- проверка созданной копии перед подтверждением успеха;
- список backup-файлов в интерфейсе;
- `PRAGMA integrity_check` и проверка ключевых таблиц;
- восстановление только после явного подтверждения;
- страховочный backup текущей базы перед восстановлением;
- откат на страховочную копию при ошибке восстановления;
- аудит приходов, расходов, логов, справочников, backup, restore и проверок;
- вкладка «Администрирование»;
- сериализация веб-запросов на время административных операций;
- тесты backup, integrity check, restore и аудита.

### Миграция

- `audit_log` добавляется без изменения существующих складских таблиц;
- backup перед миграцией: `data/backups/warehouse_before_stage4_1_20260627.db`;
- роли, авторизация и корректирующие операции не добавлялись.

## Stage 3 — новый баланс и показатели

Завершен 27 июня 2026 года.

### Добавлено

- расчет баланса по `stock_receipts` и `stock_issue_allocations`;
- агрегация одинаковых позиций без зависимости от полки;
- справочное отображение всех полок позиции;
- фильтры по проекту, объекту, типам, единице учета и ЦОД;
- поле `datacenter` в новой модели прихода;
- API и CSV-экспорт нового баланса;
- показатели обзора по новой модели;
- ежедневный отчет только по новым приходам и расходам;
- тесты независимости от `equipment/operations`.

### Миграция

- в `stock_receipts` добавлено поле `datacenter`;
- перенесенные позиции получили ЦОД из старой карточки либо `Ixcellerate`;
- существующие строки сохранены;
- backup: `data/backups/warehouse_before_stage3_20260627.db`.

## Stage 2 — расширенный приход, расход и справочники

Завершен 27 июня 2026 года.

### Добавлено

- таблицы `stock_receipts`, `stock_issues`, `stock_issue_allocations`;
- таблица `reference_values`;
- расширенные реквизиты прихода;
- расход оборудования и компонентов по S/N;
- обязательная задача для оборудования и компонентов;
- проверка целевого оборудования и запрет самосписания;
- кабельный учет по наименованию и типу в метрах;
- FIFO-распределение кабелей по партиям;
- автоматическое получение проекта и реквизитов из прихода;
- управление справочниками из интерфейса;
- новые CSV-шаблоны и атомарный импорт;
- синхронизация совместимых CLI-операций с новой моделью.

### Миграция

- положительные остатки старой модели перенесены как начальные позиции;
- связь со старой карточкой хранится в `legacy_equipment_id`;
- старые таблицы и операции не удалялись;
- backup: `data/backups/warehouse_before_stage2_20260627.db`.

## Stage 1 — интерфейс, логи работ и ежедневные отчеты

Завершен 27 июня 2026 года.

### Добавлено

- разделы «Склад», «Отчеты» и «Мониторинг»;
- вложенные вкладки и адаптивная навигация;
- таблица `work_logs`;
- ручной ввод, фильтрация, CSV-импорт и экспорт логов;
- отдельное хранение источника, типа и номера задачи;
- полный номер задачи вида `ПНР-123`;
- ежедневный отчет из логов, прихода и расхода;
- заглушки Kaiten, еженедельного отчета и мониторинга.

### Миграция

- таблица логов добавлена без изменения складских таблиц;
- backup: `data/backups/warehouse_before_stage1_20260627.db`.

## Совместимость

- `equipment`, `operations`, `categories` и `locations` сохранены для старого CLI и истории;
- новые складские функции развиваются через таблицы `stock_*`;
- миграции в `inventory/db.py` идемпотентны и выполняются при запуске;
- перед обновлением обязательна отдельная резервная копия базы.

## Возможные следующие этапы

- корректирующие операции без удаления истории;
- диагностика и автоматическое расписание backup;
- печать этикеток и централизованное многопользовательское развертывание;
- интеграции с DCIM, Kaiten и мониторингом.
