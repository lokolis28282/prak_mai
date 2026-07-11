# ARCHITECTURE

Дата проверки: 2026-07-10

## Карта

`app.py`

Точка входа. Без аргументов или с `gui/web` запускает `inventory.webapp.main`; с CLI-командами передает управление `inventory.cli.main`.

`inventory/db.py`

SQLite-слой: путь БД, schema DDL, миграции/инициализация, `connect`, хеширование и проверка пароля.

`inventory/service.py`

Основная бизнес-логика. `WarehouseService` отвечает за пользователей, аудит, backup/restore, приход, расход, баланс, поставки, импорт, отчеты, справочники, инвентаризацию, integrity-check.

`inventory/webapp.py`

Локальный HTTP UI без внешних web-зависимостей. В одном файле формируются HTML, CSS, JS, CSV templates, HTTP handler, GET/POST API и экспорт CSV.

DB

Основная БД: `data/warehouse.db`. Ключевые таблицы: `stock_receipts`, `stock_issues`, `stock_issue_allocations`, `deliveries`, `delivery_lines`, `work_logs`, `daily_report_uploads`, `daily_report_rows`, `reference_values`, `audit_log`, `users`, legacy `equipment/operations/categories/locations`.

JS

Встроен в `inventory/webapp.py` внутри HTML-строк. Отвечает за навигацию, формы, fetch API, CSV preview/import, сканирование, карточки, отчеты, поставки, admin UI.

HTML/CSS

Генерируется строками в `inventory/webapp.py`. Итоговый HTML собирается базовой строкой `HTML` и серией `.replace(...)` плюс вставками `DELIVERY_JS`, `UX_SCRIPT`, `WIZARD_SCRIPT`.

API

Создается в `make_handler(service)`: GET `/api/data`, `/api/balance`, `/api/delivery`, `/api/deliveries`, `/api/work-logs`, `/api/daily-report`, `/api/weekly-report`, `/api/admin`, exports/templates. POST `/api/login`, `/api/logout`, `/api/action`, `/api/preview-csv`, `/api/import-csv`, `/api/upload-prod-db`.

Tests

`tests/test_warehouse.py` покрывает сервис, импорт, отчеты, backup/release, UI-текстовые контракты. `scripts/smoke_ui.py` + `tests/headless_smoke.js` выполняют headless Chrome E2E на временной копии БД.

## Основной поток

UI -> `fetch('/api/...')` -> `Handler` -> `WarehouseService` -> SQLite -> JSON/CSV response -> JS render.

## Архитектурный риск

`inventory/webapp.py` является монолитом: страницы, стили, JS, API и сборка UI находятся в одном файле. Итоговый DOM получается последовательными `.replace(...)`, поэтому изменение текста/разметки может сломать позднюю вставку. Это не текущий runtime-блокер, но главный источник будущих регрессий.
