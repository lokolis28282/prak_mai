# Полная опись исполняемого кода ODE 0.15.0

Отчёт по каждому исполняемому файлу репозитория и итоговая архитектура.
Составлен по результатам полного предрелизного ревью (2026-07-19): назначение
каждого файла извлечено из его кода (docstring/структура), объёмы — фактические.

Сводные объёмы: **235 Python-файлов** (~55 400 строк вместе с тестами),
**41 JavaScript-файл** (~4 350 строк), 8 лаунчеров, 539 автоматических тестов.

## 1. Архитектура

ODE — модульный монолит на стандартной библиотеке Python + SQLite, с браузерным
UI и совместимым CLI. Никаких внешних runtime-зависимостей.

```
app.py                     ← единственная точка запуска
 ├─ inventory/webapp.py    HTTP-сервер: UI + JSON API (+ раздача static/)
 └─ inventory/cli.py       совместимый CLI
            │
            ▼
 inventory/core/ApplicationContext      ← собирает все модули
            │
   ┌────────┼──────────┬───────────┬────────────┬───────────┐
   ▼        ▼          ▼           ▼            ▼           ▼
 Warehouse  Reports  Monitoring  Knowledge  Administration  FullInventory
 Facade     Facade   Facade      Facade     Facade          (baseline)
   │           │  (события — только через WarehouseEventReader)
   ▼           ▼
 services / repositories / validators (внутри модуля)
            │
            ▼
 inventory/shared/  (connect, audit, CSV/XLSX, валидации)
 inventory/db.py    (схема SQLite + идемпотентные миграции)
            │
            ▼
 data/warehouse.db  (рабочая база; в git не входит)
```

Ключевые архитектурные правила (проверяются `scripts/audit_module_boundaries.py`):

- web/API обращается к модулям **только через публичные фасады**
  (`WarehouseFacade`, `ReportsFacade`, `MonitoringFacade`, `KnowledgeFacade`,
  `AdministrationFacade`), не через `WarehouseCore`/`WarehouseService` напрямую;
- Reports не читает и не пишет складские таблицы — только события через
  `WarehouseEventReader`; Warehouse не пишет отчётные таблицы;
- Monitoring полностью изолирован от Warehouse/Reports;
- `inventory/migration` — offline-инструментарий, не импортируется runtime'ом
  и не пишет в production; его выход — только disposable candidate-базы;
- `ode/` — параллельный foundation-контур целевой архитектуры 0.13 (CLI),
  не импортируется из `inventory/` и наоборот (проверяется тестом);
- S/N — identity карточки; полка — placement; canonical name — display;
- каждая мутация проходит транзакцией и пишет запись в `audit_log`.

Владение таблицами: Warehouse — `stock_receipts`, `stock_issues`,
`stock_issue_allocations`, `deliveries`, `delivery_lines`,
`reference_*_v2`; Reports — `work_logs`, `daily_report_uploads`,
`daily_report_rows`; Administration — `users`, `audit_log`, backup-файлы;
Knowledge — `knowledge_*`; legacy `equipment`/`operations` — только
совместимость CLI. Подробно: `docs/DATABASE_OWNERSHIP.md`.

Frontend — два сосуществующих слоя, оба загружаются через
`_externalized_html()` (инлайновые `<style>/<script>` из шаблона webapp.py
до браузера не доходят): string-template слой (`ui.js` и соседи) и
компонентный слой (`product.js` + `static/js/{core,components,…}`).
Соответствие DOM id ↔ JS проверяет `scripts/audit_frontend_contracts.py`.

## 2. Точки входа и лаунчеры

| Файл | Строк | Назначение |
|---|---|---|
| `app.py` | 16 | Единственная точка запуска: парсит args, зовёт `webapp.main()` (GUI) или `cli.main()`. |
| `build_windows_package.py` | 187 | Сборка переносимого source-ZIP для Windows; имена артефактов выводятся из `inventory.__version__`; рабочая БД в архив не попадает. |
| `start_macos.command` / `start_windows.bat` | — | Обычный запуск `python3 app.py` двойным щелчком. |
| `start_test_macos.command` / `start_test_windows.bat` | — | Запуск на отдельной чистой тестовой БД (`create_clean_test_db`), рабочая база не затрагивается. |
| `start_migration_pilot_macos.command` / `_windows.bat` | — | Marker-guarded read-only просмотр disposable pilot-БД; никогда не открывает `data/warehouse.db`. |
| `start_full_migration_candidate_macos.command` / `_windows.bat` | — | То же для full historical candidate; только существующий файл, без пересборки. |

## 3. `inventory/` — корневые файлы

| Файл | Строк | Назначение |
|---|---|---|
| `__init__.py` | 4 | Версия продукта — единственный источник (`__version__ = "0.15.0"`). |
| `db.py` | 725 | Схема SQLite и идемпотентные миграции; PBKDF2-хеши паролей; установка Knowledge/Reports-схем. |
| `webapp.py` | 2298 | HTTP-сервер (ThreadingHTTPServer): сессии (HttpOnly, SameSite=Strict), роутинг GET/POST, `/api/action` (все мутации под `service.lock`), валидация payload, CSV/XLSX download, раздача static с anti-traversal, security-заголовки. Известный монолит (HTML-шаблон внутри), разбирается постепенно. |
| `cli.py` | 246 | Совместимый CLI: таблицы, интерактивное меню, команды старой модели. |
| `service.py` | 318 | `WarehouseService` — compatibility-фасад над `WarehouseCore` для ещё не перенесённых сценариев; держит `RLock` и `user_context`. |
| `importing.py` | 200 | Толерантный разбор CSV: кодировки (UTF-8 BOM, CP1251), разделители `;`/`,`, синонимы заголовков. |
| `seed.py` | 73 | Демонаполнение пустой БД (только по явной команде `seed --reset`). |

## 4. `inventory/core/` — контекст приложения

| Файл | Строк | Назначение |
|---|---|---|
| `application.py` | 128 | `ApplicationContext`: связывает фасады всех модулей; `create_application_context`. |
| `context.py` | 27 | Runtime-конфигурация и feature-флаги. |
| `events.py` | 75 | Контракты межмодульных событий: `WarehouseEvent`, `EventReader`, `AuditLogEventReader`. |
| `exceptions.py` | 10 | Базовые исключения (`ODEError`). |

## 5. `inventory/warehouse/` — склад (главный контур)

| Файл | Строк | Назначение |
|---|---|---|
| `facade.py` | 725 | `WarehouseFacade` — единственная публичная точка входа склада: обзор/KPI, баланс, карточки, приход/расход, кабели, поставки, инвентаризация, data-quality операции; posting-guard всех мутаций. |
| `receipt_repository.py` | 628 | Персистентность прихода: вставка партий, назначение Inventory Number, fill-empty-only заполнение полей и даты, исправление/удаление дублей S/N (fail-closed, снимок в audit). |
| `receipt_imports.py` | 693 | `ReceiptWriteService`: одиночный приход, CSV preview/confirm, массовое назначение Inventory Number (Preview → Confirm одной транзакцией), data-quality врайтеры; `_require_write` — только admin/engineer. |
| `receipts.py` / `issues.py` | 6/8 | Публичные экспорты подмодулей. |
| `issue_repository.py` | 251 | Персистентность расхода: FIFO-аллокации, проверки повторного списания. |
| `issue_imports.py` | 425 | `IssueWriteService`: одиночное и массовое списание, CSV, компонент-на-оборудование. |
| `issue_validators.py` / `issue_models.py` / `issue_previews.py` | 69/26/9 | Валидация, модели, границы preview расхода. |
| `cables.py` | 214 | `CableService`: кабельный приход/расход по количеству/метражу. |
| `cable_repository.py` | 242 | Кабельные партии и FIFO-распределение. |
| `cable_validators.py` / `cable_models.py` | 143/39 | Определение кабельных строк, подготовка операций. |
| `balance.py` / `history.py` / `inventory.py` / `models.py` | 2 каждая | Плейсхолдеры границ будущей модульной миграции (намеренно пустые). |
| `deliveries.py` | 45 | Чтение/экспорт документов поставок. |
| `delivery_imports.py` | 258 | Preview/confirm импорта документа снабжения. |
| `delivery_acceptance.py` | 428 | Физическая приёмка поставки (скан, батч, внеплановые позиции). |
| `delivery_repository.py` | 323 | SQL-репозиторий поставок. |
| `delivery_mapping.py` / `delivery_validators.py` / `delivery_models.py` / `delivery_previews.py` | 107/56/71/146 | Маппинг колонок CSV, валидации, константы, хранилище preview. |
| `events.py` | 327 | `WarehouseEventReader` — read-only контракт событий для Reports. |
| `references.py` | 409 | `ReferenceDataService`: canonical справочники `reference_*_v2` (pending → approve, rename/deactivate/merge с preview), fallback на плоскую `reference_values`. |
| `classification.py` | 324 | Детерминированная классификация карточек и безопасная очистка display-полей. |
| `naming.py` | 20 | Правила canonical item name (display, не identity). |
| `previews.py` | 172 | Хранилище CSV-preview склада (в памяти, TTL). |
| `validators.py` | 178 | Валидация прихода: обязательные поля, даты, числа, ссылки. |
| `migration_pilot.py` | 359 | Preservation-aware записи для disposable pilot (только из offline-оркестрации). |
| `migration_pilot_review.py` | 681 | Marker-guarded read-only просмотр pilot-БД (fail-closed по env/marker/integrity). |
| `migration_full.py` | 277 | Записи для disposable full candidate. |
| `migration_full_review.py` | 537 | Marker-guarded read-only просмотр full candidate. |

### `inventory/warehouse/baseline/` — FULL-инвентаризация

| Файл | Строк | Назначение |
|---|---|---|
| `service.py` | 1883 | `FullInventoryService`: сессии FULL, потоковый Preview 50k строк вне рабочей БД, resolutions, готовность к approve и read-only подготовка операторских XLSX-подсказок. |
| `xlsx_parser.py` | 706 | Строгий OOXML-ридер и scan-first генератор шаблона ODE-FULL-INVENTORY v1 (text-only identifiers, dropdowns, инструкция и номенклатура). |
| `workspace.py` | 294 | Внешний версионированный SQLite-workspace для evidence Preview. |
| `models.py` | 97 | Публичный словарь состояний (`SystemState`, `SessionStatus`; StrEnum-shim для Python 3.10). |
| `posting_policy.py` | 79 | Policy: какие контуры склада разрешают posting (fail-closed). |

## 6. Остальные продуктовые модули

### `inventory/reports/` (отдельный контур; в 0.15.0 не изменялся)

| Файл | Строк | Назначение |
|---|---|---|
| `facade.py` | 402 | `ReportsFacade`: УВР, ежедневные/недельные отчёты, XLSX/CSV import/export. |
| `work_logs.py` | 264 | CRUD УВР одной транзакцией с аудитом. |
| `daily.py` | 114 | Импорт готового ежедневного отчёта (изолирован от `work_logs`). |
| `repository.py` | 249 | Персистентность отчётного контура. |
| `validators.py` | 188 | Правила валидации отчётных строк. |
| `imports.py` | 117 | Хранилище preview импорта. |
| `weekly.py` / `exports.py` / `models.py` | 2 каждая | Плейсхолдеры границ. |

### `inventory/monitoring/` (изолирован; в 0.15.0 не изменялся)

| Файл | Строк | Назначение |
|---|---|---|
| `facade.py` | 98 | `MonitoringFacade`: ручной hostname-поиск + маршрутизация адресатов. |
| `hostname_routing.py` | 436 | Маршрутизация по локальным JSON-правилам (файлы в git не входят). |
| `manual_search.py` | 623 | Ручное обогащение проблемы Zabbix; опциональный Selenium/Edge DCIM-collector. |
| `models.py` | 2 | Намеренно пустой контракт. |

### `inventory/knowledge/`

| Файл | Строк | Назначение |
|---|---|---|
| `facade.py` | 351 | Валидация, роли, безопасная работа с вложениями (resolve + containment). |
| `repository.py` | 258 | SQLite-репозиторий статей/тегов/вложений; soft-delete. |
| `markdown.py` | 124 | Безопасный Markdown-рендерер (без сырого HTML). |
| `models.py` | 100 | `KnowledgeArticle`, `KnowledgeAttachment`. |

### `inventory/administration/`

| Файл | Строк | Назначение |
|---|---|---|
| `facade.py` | 107 | `AdministrationFacade`: users/audit/backup/diagnostics (частично compatibility-layer, см. TECH_DEBT). |
| `audit.py`, `backup.py`, `diagnostics.py`, `users.py` | 2 каждая | Плейсхолдеры границ будущего переноса из `WarehouseCore`. |

### `inventory/services/` — backend-адаптеры (compatibility)

`warehouse_service.py` (3973 строки) — `WarehouseCore`: историческое ядро всех
операций, из которого код постепенно переносится в модули `warehouse/*`;
не удаляется одним изменением. Остальные 11 файлов (14–24 строки каждый) —
тонкие адаптеры (`BalanceService`, `ReceiptService`, `IssueService`,
`DeliveryService`, `ReferenceService`, `ReportService`, `ProfileService`,
`HistoryService`, `InventoryService`, `MonitoringService`, `_base.py`),
пробрасывающие вызовы фасадов в ядро.

### `inventory/shared/` — общие примитивы

| Файл | Строк | Назначение |
|---|---|---|
| `audit.py` | 76 | `write_audit_entry` — единая запись в `audit_log`. |
| `db.py` | 14 | `connect()`: контекст-менеджер SQLite, `PRAGMA foreign_keys=ON`, commit/rollback. |
| `xlsx.py` | 130 | Минимальный read-only XLSX-парсер на стандартной библиотеке. |
| `reference_normalization.py` | 23 | NFKC-нормализация справочных ключей (общая для runtime и offline). |
| `helpers.py` / `dates.py` / `csv_tools.py` / `validators.py` | 11/10/9/6 | `WarehouseError`, дата-хелперы, границы. |

### `inventory/models/` — типизированные плейсхолдеры

7 файлов по 13–14 строк: заготовки доменных моделей будущей целевой
архитектуры (balance, delivery, history, issue, receipt, references).

## 7. `inventory/migration/` — offline-инструментарий (не runtime)

| Файл | Строк | Назначение |
|---|---|---|
| `full_builder.py` | 2893 | Сборка и валидация полного исторического candidate (71 360 source rows → 50 000 карточек). |
| `candidate_db.py` | 1571 | Disposable reference/staging candidate Stage 0.13.3A. |
| `pilot_builder.py` | 1204 | Сборка/валидация 200-строчного pilot. |
| `pilot_selector.py` | 985 | Детерминированный selector с seed `ODE-0.13.3A.5-PILOT-v1`. |
| `xlsx_cells.py` | 809 | Read-only OOXML-ридер raw-ячеек + text-only XLSX/CSV writer (S/N-preservation). |
| `serial_preservation.py` | 527 | Lossless-извлечение S/N: Decimal-анализ numeric ячеек, match-key нормализация. |
| `reference_data.py` | 290 | Чистые правила доменов/алиасов (Huawei≠xFusion, HP≠HPE и т.д.). |
| `validation.py` | 275 | SHA-256, read-only подключения, health-проверки источников. |
| `staging_schema.py` / `full_schema.py` / `pilot_schema.py` | 246/271/170 | Candidate-only схемы. |
| `models.py` / `pilot_models.py` | 128/123 | Immutable-контракты. |
| `canonical_naming.py` | 70 | Canonical display names из структурных полей. |

## 8. `ode/` — foundation целевой архитектуры 0.13 (CLI-контур)

Параллельный side-by-side пакет (`python3 -m ode`), не связанный импортами с
`inventory/` (проверяется тестом архитектуры).

| Файл | Строк | Назначение |
|---|---|---|
| `cli.py` | 220 | CLI без зависимостей: create-db, diagnostics, JSON/human вывод, стабильные коды ошибок. |
| `__main__.py` | 7 | Запуск `python3 -m ode`. |
| `application/config.py` | 90 | Валидированная immutable конфигурация БД. |
| `application/context.py` | 35 | Composition root (никогда не создаёт схему сам). |
| `application/errors.py` | 85 | Стабильные коды ошибок CLI. |
| `infrastructure/database.py` | 596 | Политика подключений, SQLite-авторизатор (deny DDL/ATTACH/PRAGMA; permissive-снятие — совместимо с Python 3.10), детерминированный schema hash, Unit of Work. |
| `infrastructure/migrations.py` | 585 | Manifest-verified атомарное создание БД V001…V008. |
| `infrastructure/diagnostics.py` | 219 | Side-effect-free диагностика по approved-схеме. |
| `infrastructure/paths.py` | 102 | Канонические пути, fail-closed dev-политика БД. |
| `system/models.py` | 187 | Immutable health/diagnostics контракты. |
| `system/service.py` / `system/queries.py` | 52/16 | Health-policy и read-only порты. |

## 9. `scripts/` — операционные и релизные инструменты

| Файл | Строк | Назначение |
|---|---|---|
| `audit_module_boundaries.py` | 596 | Gate: проверка границ модулей без импорта приложения. |
| `audit_frontend_contracts.py` | 178 | Gate: соответствие DOM id ↔ ссылки из JS. |
| `create_clean_test_db.py` | 466 | Чистая тестовая копия рабочей БД (read-only источник, SHA-доказательства). |
| `smoke_ui.py` | 112 | Headless Chrome E2E основного маршрута на временной копии БД. |
| `smoke_migration_pilot_ui.py` / `smoke_migration_full_ui.py` | 155/196 | Headless smoke pilot/full review с SHA-proof неизменности БД. |
| `migration_reference_data.py` / `migration_pilot.py` / `migration_full_candidate.py` | 149/146/141 | CLI-оркестраторы offline-миграций (единственное разрешённое место импорта `inventory.migration`). |
| `audit_warehouse_database.py` | 610 | Воспроизводимый аудит и безопасная очистка рабочей БД (byte-copy + backup + план). |
| `reclassify_warehouse_cards.py` | 443 | Безопасная коррекция type-полей по описательным признакам (план → apply). |
| `stabilize_reference_data.py` | 389 | Идемпотентная стабилизация canonical Reference Data. |
| `generate_hostname_rules.py` | 454 | Генерация monitoring JSON-правил из утверждённых Excel (выход в git не входит). |
| `restore_legacy_patchcord_balance.py` | 229 | Восстановление однозначных опенинг-балансов патч-кордов из legacy. |
| `remove_test_serial.py` | 232 | Удаление одного доказанного тестового S/N из рабочей БД (backup + proof). |
| `migrate_runtime_modules.py` / `migrate_knowledge_base.py` | 165/47 | Аддитивная установка Reports/Knowledge схем в существующую БД. |
| `benchmark_full_inventory.py` | 218 | Disposable benchmark Preview 1k/10k/50k. |
| `generate_code_graph.py` | 377 | Генерация интерактивного офлайн-графа связей кодовой базы → `docs/assets/code_graph.html` (AST-импорты Python + webapp→static); `--check` ловит stale HTML. |

## 10. `baseline_rehearsal/`

| Файл | Строк | Назначение |
|---|---|---|
| `candidate.py` | 577 | Сборка и верификация rehearsal-БД initial baseline на target-схеме (snapshot, schema hash, integrity, FK, domain invariants; публикация в рабочую БД отключена). |

## 11. `static/js/` — frontend

Слой A — string-template (исторический, живой):

| Файл | Строк | Назначение |
|---|---|---|
| `core.js` | 14 | `esc()`, `option()`, `request()` — базовые примитивы и экранирование. |
| `ui.js` | 854 | Баланс, справочники, «Контроль качества данных», сценарии прихода/расхода, lazy rendering тяжёлых таблиц, сканер-списки, поставки (частично), загрузка данных `loadAll()`, Timeline-подписи. |
| `product.js` | 1013 | Компонентный рендер: главная, карточки модулей, обзор склада (KPI + лента), Equipment Card, серверная догрузка баланса, поиск и миграционные review-экраны. |
| `components.js` / `router.js` / `api.js` | 73/64/1 | Диалоги/нотификации, роутер разделов, заготовка API-слоя. |

Слой B — модульный (по разделам):

| Группа | Файлы (строк) | Назначение |
|---|---|---|
| `core/` | context (13), router (10), app (8), api (4), errors (4) | Каркас будущего модульного фронта. |
| `warehouse/` | full_inventory (332), migration_pilot (261), inventory (197), balance (9), history (7), index (7), deliveries/issue/receipt (1) | FULL-инвентаризация, pilot review, массовое назначение Inventory Number; однострочные — плейсхолдеры границ. |
| `reports/` | work_logs (261), daily (65), weekly (56), index (38) | УВР CRUD/XLSX, отчёты за смену/неделю. |
| `administration/` | references (168), остальные (1) | Редактор canonical справочников; плейсхолдеры. |
| `knowledge/` | index (250) | База знаний: список, статья, редактор, вложения. |
| `monitoring/` | index (181) | Ручной hostname-поиск и результаты. |
| `components/` | 6 файлов (1) | Плейсхолдеры компонентной библиотеки. |

`tests/headless_smoke.js` (247), `headless_migration_pilot_smoke.js` (94),
`headless_migration_full_smoke.js` (109) — сценарии headless Chrome E2E.

Однострочные JS-файлы — намеренные плейсхолдеры границ модульной миграции
фронтенда (см. `docs/FRONTEND_MIGRATION_PLAN.md`); они входят в
`_externalized_html()`-список и зарезервированы под перенос кода из монолита.

## 12. `tests/` — 68 Python test-файлов, 539 тестов

| Группа | Файлы | Что покрывают |
|---|---|---|
| Склад: ядро | `test_warehouse` (1119), `test_warehouse_api_contract`, `test_warehouse_stabilization`, `test_warehouse_system_state`, `test_warehouse_posting_guard` | Приход/расход/баланс, Windows-пакет, состояния системы, posting-guard. |
| Склад: запись | `test_warehouse_receipt_write_*`, `test_warehouse_issue_write_*`, `test_warehouse_cable_*` | Write-сервисы прихода/расхода/кабелей: API + контракты. |
| Качество данных | `test_warehouse_data_quality_fix` (327) | Fill-empty, дата, дубли S/N, удаление (fail-closed), роли. |
| Карточка | `test_equipment_card_inventory_workflow` (373), `test_warehouse_overview_frontend`, `test_warehouse_classification`, `test_warehouse_reclassification` | Inventory Number, редактор карточки, обзор, классификация. |
| Поставки | `test_delivery_*` (4 файла) | Импорт/приёмка: API + контракты. |
| FULL-инвентаризация | `test_full_inventory_*` (7 файлов) | XLSX, workspace, Preview, resolutions, candidate, API, frontend-контракт. |
| Inventory Number импорт | `test_inventory_number_import_*` (4 файла) | Preview/Confirm, уникальность, идемпотентность. |
| Миграция | `test_migration_*` (7 файлов), `test_serial_preservation` (331), `test_reference_data_foundation`, `test_legacy_patchcord_balance` | Candidate/pilot/full builders, S/N-preservation, маркеры/runtime-guard. |
| Reports | `test_reports_*` (4), `test_uvr_workflow` | УВР, события только через reader, изоляция контура. |
| Monitoring | `test_monitoring_*` (4) | Routing, manual search, API, изоляция (8 skip без Selenium). |
| Knowledge | `test_knowledge_*` (4) | CRUD, роли, Markdown, миграция схемы. |
| Безопасность и платформа | `test_webapp_security` (226), `test_administration_api_contract`, `test_architecture`, `test_ui_navigation_architecture`, `test_stage_0_12_17`, `test_scanner_draft_frontend_contract`, `test_preview_limits`, `test_create_clean_test_db`, `test_runtime_module_migration`, `test_warehouse_event_reader` | Сессии/роли/утечки traceback, границы модулей, навигация, лимиты preview, тестовая БД. |
| `ode013/` | 4 файла (630+294+221+194) | CLI-контур 0.13: авторизатор/UoW, манифест миграций, диагностика, архитектурные запреты. |

Вспомогательные: `full_inventory_support.py` (156), `ode013/support.py` (40).

## 13. Трассировка от main: где вход и выход Monitoring и Reports

Main один: `app.py`. Без аргументов (или `gui`/`web`) он вызывает
`inventory/webapp.py::main()`; любой другой аргумент — `inventory/cli.py::main()`
(legacy CLI-модель). `webapp.main()` делает строго по порядку: валидация
test-mode БД → `PostingPolicy` (production/demo контур) → marker-проверки
migration full/pilot (до инициализации БД) → `WarehouseService` →
`create_application_context()` → печать контура/версии/integrity → HTTP-сервер.

Все модули собираются в одном месте — `inventory/core/application.py`:

```
ApplicationContext.from_service(service)
 ├─ WarehouseFacade(service, posting_policy, full_inventory)
 ├─ ReportsFacade(service, warehouse_events=WarehouseEventReader(service))
 ├─ MonitoringFacade()          ← БЕЗ service и БЕЗ db_path
 ├─ KnowledgeFacade(service)
 └─ AdministrationFacade(service)
```

**Monitoring — вход/выход.** Вход: экран «Мониторинг» → GET
`/api/monitoring/status` (webapp.py:832) и POST `/api/monitoring/manual-search`
(webapp.py:1178). Выход: JSON с routing-решением и подготовленным текстом
письма; ошибки — `MonitoringError` → HTTP 400. Внутри: `MonitoringFacade`
(конфиг только из env) → `hostname_routing.py` (локальные JSON-правила,
`data/monitoring/`, в git не входят) и `manual_search.py` (опциональный
Selenium/Edge DCIM). Модуль по построению не имеет доступа к
`data/warehouse.db` — фасад создаётся без сервиса и пути к БД. История
поисков хранится в браузере (`localStorage`, ключ
`ode_monitoring_manual_search_history`, максимум 50 записей), не в БД.
Особенность (намеренная, не противоречие): `/api/monitoring/manual-search` —
единственный POST, выполняющийся **вне** `service.lock` (webapp.py:1154),
потому что это долгий сетевой/Selenium-вызов, а общий БД-лок ему не нужен.

**Reports — вход/выход.** Вход: GET `/api/worklogs`, отчёты за
смену/неделю/загруженные, CSV-экспорты; POST-действия `WORK_LOG_*`,
preview/confirm импортов CSV/XLSX — все под `service.lock`. Выход: JSON/CSV.
Запись — только в собственные таблицы (проверено по всем INSERT/UPDATE/DELETE
модуля): `work_logs`, `daily_report_uploads`, `daily_report_rows`. Складские
данные Reports видит единственным способом — через инжектированный
`WarehouseEventReader` (`inventory/warehouse/events.py`): это warehouse-owned
read-only контракт (только SELECT по `stock_receipts`/`stock_issues`/
`stock_issue_allocations`), сам Reports SQL к складским таблицам не пишет ни
одного. Направление зависимости одностороннее: Warehouse не знает о Reports.

Противоречий в связке не найдено: единственная точка сборки, у Monitoring
нет пути к рабочей БД, у Reports нет прямого SQL к складу, все мутации — под
одним RLock, обход лока — только у двух безопасных read/external endpoint'ов
(monitoring manual-search и full-inventory workspace-контур).

## 14. Выводы ревью 0.15.0

1. Границы модулей соблюдены и защищены автоматическим gate'ом.
2. Все мутации: фасад → write-service (`_require_write`) → репозиторий →
   транзакция + `audit_log`; `/api/action` дополнительно под `RLock`.
3. Динамический SQL существует только с allowlist-полями/таблицами;
   пользовательские значения — исключительно через параметры.
4. Файловые endpoint'ы защищены от path traversal; сессии — server-side,
   HttpOnly, SameSite=Strict.
5. Плейсхолдеры (файлы в 1–2 строки) — намеренные границы миграции, не мусор.
6. Главный технический долг прежний: монолит `webapp.py` и compatibility-ядро
   `WarehouseCore` (см. `TECH_DEBT.md`); разбирать постепенно, через фасады.
