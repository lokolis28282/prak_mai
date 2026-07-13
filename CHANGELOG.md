# Changelog ODE

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
