# BACKEND_ARCHITECTURE

Дата: 2026-07-10

## Цель refactoring

`inventory/service.py` больше не должен быть God Object. Внешний API должен остаться совместимым: весь существующий код продолжает импортировать `WarehouseService` и `WarehouseError` из `inventory.service`, но сам `WarehouseService` работает как facade над специализированными backend-сервисами.

## Новая структура

```text
inventory/
  service.py                    # Facade, совместимый публичный API
  services/
    warehouse_service.py         # Core implementation на переходном этапе
    receipt_service.py           # Приход
    issue_service.py             # Расход
    delivery_service.py          # Поставки
    balance_service.py           # Баланс и карточки
    history_service.py           # История и audit-read
    report_service.py            # Логи работ и отчеты
    profile_service.py           # Пользователи, профиль, auth
    reference_service.py         # Справочники
    monitoring_service.py        # Integrity и data-quality
    inventory_service.py         # Legacy inventory, backup, import/export
  shared/
    helpers.py                   # WarehouseError, общие флаги
    db.py                        # DB re-exports для сервисов
    audit.py                     # audit helper
  models/
    receipt.py
    issue.py
    delivery.py
    balance.py
    history.py
    references.py
```

## Facade

`inventory.service.WarehouseService` теперь:

- создает внутренний `WarehouseCore`;
- создает профильные сервисы;
- делегирует публичные методы в нужный сервис;
- сохраняет старые class constants;
- сохраняет свойства `db_path`, `lock`, `backup_dir`, `default_admin_created`;
- сохраняет совместимость для старых приватных helper-вызовов через `__getattr__`.

## Web/API Rule Since Stage 0.12.14

Новые Warehouse read endpoints и переносимые write/import endpoints должны идти через:

`ApplicationContext -> WarehouseFacade`

Прямой доступ `inventory/webapp.py` к `WarehouseCore` запрещен. Прямые
`service.*` вызовы допустимы только для неперенесенных legacy flows. Reports
write/import идут через `ReportsFacade`; equipment/component receipt
write/import, cable receipt/issue and serialized equipment/component issue
идут через `WarehouseFacade`. Поставки, inventory write, Administration write
и backup/restore остаются переходными compatibility flows.

## Сервисы

### `ProfileService`

Отвечает за:

- `authenticate`
- `user_by_email`
- `current_user`
- `user_context`
- `users`
- `create_user`
- `change_password`
- `update_profile`

### `ReferenceService`

Отвечает за:

- редактируемые справочники;
- legacy `categories/locations`;
- `reference_data`.

### `ReceiptService`

Отвечает за:

- delivery-owned receipt creation;
- список приходов;
- legacy `receipt`.

С Stage 0.12.12 целевая реализация прихода оборудования и компонентов
расположена в `inventory/warehouse/receipt_imports.py`,
`inventory/warehouse/receipt_repository.py`, `inventory/warehouse/validators.py`,
`inventory/warehouse/naming.py` и `inventory/warehouse/previews.py`, а публичный
доступ идет через `WarehouseFacade`.

С Stage 0.12.13 кабельный приход перенесен в
`inventory/warehouse/cables.py` и `cable_repository.py`.

### `IssueService`

Отвечает за:

- ручной расход;
- CSV preview/confirm расхода;
- bulk issue;
- сканирование расхода;
- проблемные/unmatched списания;
- legacy `issue`.

С Stage 0.12.13 кабельный расход перенесен в
`inventory/warehouse/cables.py` и `cable_repository.py`.

С Stage 0.12.14 общий расход оборудования и компонентов перенесен в
`inventory/warehouse/issue_imports.py`, `issue_repository.py`,
`issue_validators.py`, `issue_models.py` и `issue_previews.py`. Legacy
`ISSUE` через `equipment/operations` остается compatibility flow.

### `DeliveryService`

Отвечает за:

- preview поставок;
- confirm поставок;
- список поставок;
- карточку поставки;
- обновление строк;
- приемку S/N;
- закрытие поставки.

С Stage 0.12.15 импорт документа поставки отделён от фактической приёмки.
Preview, mapping, matching, confirm документа, list/card/lines/search/export и
template download идут через `WarehouseFacade` и
`inventory/warehouse/delivery_*.py`. Compatibility `DeliveryService` сохраняет
scanner acceptance, unplanned acceptance, создание receipt из delivery и
закрытие до Stage 0.12.16.

С Stage 0.12.16 фактическая приёмка перенесена в
`inventory/warehouse/delivery_acceptance.py`. Новый S/N создаёт receipt через
receipt repository transaction contract, существующий S/N только дополняет
пустые поля и связывает строку поставки. `close_delivery` остаётся legacy.

### `BalanceService`

Отвечает за:

- dashboard stats;
- баланс;
- категории склада;
- поиск позиции;
- карточку позиции.

### `HistoryService`

Отвечает за:

- единый журнал склада;
- чтение audit;
- legacy operation log.

### `ReportService`

Отвечает за:

- work logs;
- daily report;
- weekly report;
- uploaded daily reports;
- CSV export логов работ.

### `MonitoringService`

Отвечает за:

- SQLite integrity;
- data-quality problems.

### `InventoryService`

Отвечает за:

- backup/restore;
- replace production DB;
- legacy equipment cards;
- inventory compare;
- legacy imports;
- CSV export.

## Что осталось в `WarehouseCore`

`WarehouseCore` содержит старую реализацию на переходном этапе. Это временный compatibility core, а не целевая архитектура.

Текущее состояние Stage 0.12.2:

- `WarehouseCore` остается допустимым legacy-core;
- новые сервисы пока являются фасадами/делегатами над `WarehouseCore`;
- перенос методов будет идти постепенно, по одному доменному блоку;
- публичный Python API `WarehouseService` не менялся;
- HTTP API `/api/...` не менялся;
- схема SQLite и рабочая БД не менялись;
- бизнес-логика не переписывалась.

Причина такого состояния: первый безопасный разрез должен убрать внешний God Object и зафиксировать границы ответственности без риска потерять функциональность. Следующие переносы должны быть маленькими и покрываться существующими 80 regression-тестами, smoke UI и SQLite integrity-check.

## Зависимости

```text
webapp.py / cli.py / tests
        |
        v
inventory.service.WarehouseService
        |
        +--> ProfileService
        +--> ReceiptService
        +--> IssueService
        +--> DeliveryService
        +--> BalanceService
        +--> HistoryService
        +--> ReportService
        +--> ReferenceService
        +--> MonitoringService
        +--> InventoryService
                 |
                 v
           WarehouseCore
                 |
                 v
              SQLite
```

## Правила следующего этапа

1. Переносить методы из `WarehouseCore` в профильные сервисы группами.

2. После каждого переноса запускать:

```bash
python3 -m unittest -v tests.test_warehouse
python3 scripts/smoke_ui.py
sqlite3 data/warehouse.db 'PRAGMA integrity_check; PRAGMA foreign_key_check;'
python3 -m py_compile app.py inventory/*.py inventory/services/*.py inventory/shared/*.py inventory/models/*.py
node --check static/js/core.js static/js/api.js static/js/router.js static/js/ui.js tests/headless_smoke.js
```

3. Не менять рабочую БД при backend-refactoring.

4. Не менять API `/api/...` без отдельного migration plan.

5. Не менять схему БД в рамках сервисного переноса. Любая миграция данных должна иметь отдельный документ и backup-процедуру.

6. Не переносить несколько доменных блоков за один проход.
