# Архитектура ODE

Дата проверки: 2026-07-14. Текущий исходный код: Stage 0.13.2. Runtime-
метаданные и target package builder: `0.12.17.1 RC2`. Последний фактически
собранный Windows ZIP содержит `ODE 0.12.17 RC1`; ZIP RC2/Stage 0.13.2 не
создавался.

## Назначение системы

ODE — локальное браузерное приложение дежурной смены для складского учёта,
поставок, логов работ и отчётов. Runtime использует Python standard library и
один SQLite-файл; внешние сервисы для основных операций не требуются.

Главный бизнес-идентификатор сериализованного оборудования и компонентов —
S/N. Inventory Number является вторичным реквизитом и может быть назначен
позже. Кабели учитываются отдельно по количеству/метражу и не обязаны иметь
S/N.

## Компоненты

```text
app.py
 ├─ inventory/webapp.py        HTTP server, session/auth, HTML shell, API routes
 └─ inventory/cli.py           compatibility CLI
             │
             ▼
 inventory/
 ├─ core/                      ApplicationContext, feature flags, event contracts
 ├─ warehouse/                 receipts, issues, cables, deliveries, balance/history
 ├─ reports/                   work logs, daily/weekly reports
 ├─ administration/            users, audit read, backup/restore, diagnostics
 ├─ monitoring/                isolated placeholder/future module
 ├─ shared/                    SQLite/CSV/audit/validation adapters
 └─ db.py                      schema and idempotent migrations
             │
             ▼
 data/warehouse.db             working SQLite database
```

`ApplicationContext` является composition root. Web/API обращается к публичным
`WarehouseFacade`, `ReportsFacade`, `AdministrationFacade` и
`MonitoringFacade`. `WarehouseCore`/`WarehouseService` сохраняются как
compatibility layer для ещё не мигрированных сценариев, но новая доменная
логика не должна вызываться из webapp напрямую через core.

Модульные границы контролирует `scripts/audit_module_boundaries.py`. Владение
таблицами описано в [docs/DATABASE_OWNERSHIP.md](docs/DATABASE_OWNERSHIP.md),
полная карта стадий — в
[docs/MODULE_ARCHITECTURE.md](docs/MODULE_ARCHITECTURE.md).

## HTTP и frontend

`inventory/webapp.py` формирует итоговый HTML shell и HTTP handler. В конце
сборки `_externalized_html()` подключает фактические runtime assets из
`static/css/main.css` и `static/js/**`; большие legacy inline-константы не
следует считать единственным источником браузерного поведения.

Frontend разделён на `static/js/core`, `warehouse`, `reports`,
`administration`, `monitoring` и общие components. Контракт статических DOM id
проверяет `scripts/audit_frontend_contracts.py`, а реальное поведение —
`tests/headless_smoke.js` через `scripts/smoke_ui.py`.

Основные HTTP группы:

- read API и exports/templates — GET `/api/**`, `/export/**`, `/import/**`;
- write actions — POST `/api/action`;
- CSV preview — POST `/api/preview-csv?kind=...`;
- разрешённые direct imports — POST `/api/import-csv?kind=...`;
- authentication/session — `/api/login`, `/api/logout`.

Новые actions должны проходить через соответствующий facade, возвращать plain
JSON values, использовать текущий actor context и не раскрывать traceback,
секреты или абсолютные локальные пути.

## Данные и транзакции

Основные таблицы:

- Warehouse: `stock_receipts`, `stock_issues`,
  `stock_issue_allocations`, `deliveries`, `delivery_lines`, legacy
  `equipment`/`operations`;
- Reports: `work_logs`, `daily_report_uploads`, `daily_report_rows`;
- Administration/shared infrastructure: `users`, `audit_log`,
  `reference_values` до дальнейшего разделения.

Баланс вычисляется из receipts минус issue allocations; отдельная mutable
таблица баланса не ведётся. Reports получает warehouse facts через
`WarehouseEventReader`, а не прямой SQL к warehouse-owned таблицам.

Массовые write/import операции валидируют данные до записи и задают одну
caller-visible SQLite transaction boundary. Mutation-тесты выполняются только
на временных БД. Любая schema/data migration требует отдельного документа,
backup-процедуры и rollback-плана.

## Stage 0.13.1/0.13.2: Inventory Number

Одиночное и массовое назначение используют маршрут:

```text
UI/HTTP
 -> ApplicationContext.warehouse
 -> WarehouseFacade
 -> ReceiptWriteService
 -> ReceiptRepository
 -> SQLite
```

Stage 0.13.1 добавил заполнение пустого Inventory Number в существующей
Equipment Card. Stage 0.13.2 добавил CSV Preview/Confirm поверх того же
transaction-aware repository helper.

Критические инварианты:

- lookup только по case-insensitive `stock_receipts.serial_number`;
- новые карточки не создаются, заполненные другие номера не перезаписываются;
- preview читает БД и хранит план только в Warehouse preview store;
- confirm выполняет `BEGIN IMMEDIATE`, повторный анализ и сравнение с preview;
- все строки `SUCCESS`, legacy sync и audit применяются атомарно;
- direct import для `kind=inventory_numbers` запрещён;
- каждое реальное изменение публикует существующий audit action
  `EQUIPMENT_INVENTORY_NUMBER_ASSIGNED`, который читает Equipment Card
  Timeline; новый WarehouseEventReader event не вводился;
- схема БД не менялась, используются существующие unique constraints/indexes.

Полный API, CSV, status, sequence, security и failure contract находится в
[docs/INVENTORY_NUMBER_IMPORT_ARCHITECTURE.md](docs/INVENTORY_NUMBER_IMPORT_ARCHITECTURE.md).

## Безопасность и роли

- `admin` и `engineer` выполняют operational writes;
- `viewer` остаётся read-only и отклоняется backend, а не только скрытием UI;
- admin-only: пользователи, backup/restore, audit view, production DB upload и
  diagnostics;
- actor/audit author берётся из authenticated application context;
- session cookie — HttpOnly/SameSite, POST проверяет Origin/Host;
- CSV body ограничен 50 МБ, импорт — 40 000 непустых строк;
- preview имеет TTL/лимиты и owner binding согласно конкретному flow.

Подробности — [docs/SECURITY_BOUNDARIES.md](docs/SECURITY_BOUNDARIES.md).

## Известные архитектурные ограничения

- single-process SQLite не предназначен для активной многопользовательской
  записи и server deployment без отдельного решения;
- `inventory/webapp.py` остаётся крупным переходным composition/HTTP файлом;
- `WarehouseCore` и часть legacy service/API flows ещё существуют;
- Warehouse preview хранится в памяти и не переживает restart;
- нет persisted import jobs, progress/cancel и отдельного batch audit ID;
- Monitoring и внешние интеграции остаются вне текущего runtime;
- корректирующие/сторнирующие операции требуют отдельной модели событий.

Изменения этих ограничений нельзя выполнять массовым refactor: каждый доменный
flow мигрируется через facade с contract/API/headless тестами и синхронным
обновлением документации.
