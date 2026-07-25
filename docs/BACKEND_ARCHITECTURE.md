# BACKEND_ARCHITECTURE

## FULL Inventory 0.14

Backend является единственным источником system state. До baseline он
возвращает `NOT_INITIALIZED`/`INVENTORY_*`, `authoritative=false`,
`balance_kind=HISTORICAL_CALCULATION`, `baseline_timestamp=null` и блокирует
posting через `PostingPolicy`. Preview evidence живёт во внешнем versioned
SQLite workspace; operational DB открывается только read-only. Resolutions
append-only и применяются при новом deterministic Preview run. Admin-only
rehearsal создаёт отдельную target DB; реального publish endpoint нет.

Дата актуализации: 2026-07-16. Current source/runtime: `0.14.0`.

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
  migration/                    # Offline-only reference/staging contour
    models.py                   # Immutable reference/alias contracts
    reference_data.py           # 16 controlled domains и alias safety
    canonical_naming.py         # Пересчитываемые display names
    xlsx_cells.py               # Read-only OOXML и text-only XLSX writer
    serial_preservation.py      # S/N provenance без float/coercion
    staging_schema.py           # 9 candidate-only SQLite tables
    candidate_db.py             # Safe disposable bundle builder/exports
    validation.py               # Source/candidate invariants
    pilot_models.py             # Fixed pilot decisions/marker/selection contracts
    pilot_selector.py           # Deterministic 200-row source selector
    pilot_schema.py             # 6 pilot-only SQLite tables
```

Тонкий entry point offline-контура —
`scripts/migration_reference_data.py`. Его команды `inspect-sources`,
`build-candidate`, `validate-candidate` и `report` не подключены к Web/API,
`ApplicationContext` или runtime CLI `inventory/cli.py`.
`report` повторяет полный source/output inode guard и регенерирует только
allowlisted JSON; существующий report никогда не читается и не merge-ится.

Stage 0.13.3A.5 adds a second thin offline entry point,
`scripts/migration_pilot.py`, which may orchestrate `inventory/migration` and
inject `inventory/warehouse/migration_pilot.py`. Runtime Warehouse does not
import the offline package. Marker-guarded review is implemented by
`inventory/warehouse/migration_pilot_review.py` behind `WarehouseFacade`.

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
идут через `WarehouseFacade`. Delivery document/acceptance flows также
Warehouse-owned с отдельно отмеченными legacy-операциями. Inventory Number
assignment в карточке и bulk Preview/Confirm с Stage 0.13.1/0.13.2 идут через
receipt boundary `WarehouseFacade`; старое физическое inventory compare,
прочие legacy inventory operations, Administration write и backup/restore
остаются переходными compatibility flows.

**IMPLEMENTED (Stage 0.13.3A):** offline `inventory/migration` не является
новым Warehouse endpoint и не обходит facade для production writes: модуль
вообще не пишет в production. Он читает immutable migration sources, проверяет
`data/warehouse.db` через read-only SQLite и строит только disposable
candidate в ignored `migration_inputs/workspace`.

**IMPLEMENTED / PILOT ONLY (Stage 0.13.3A.5):** a deterministic selector
classifies exactly 200 receipt rows and the dedicated migration writer sends
only 130 preserved primaries directly to the existing transaction-aware
`ReceiptRepository`. It bypasses ordinary `strip().upper()` validators but
does not duplicate repository/audit/card infrastructure. The resulting DB is a
separate marker-guarded disposable artifact; review GET routes and card reads go
through `ApplicationContext -> WarehouseFacade`. Operational POST routes are
denied in pilot mode. After the marker/integrity guard, the web entry point
constructs `WarehouseService(..., initialize_database=False)` so ordinary
startup schema initialization cannot rewrite the pilot; the default remains
`True` for every production/test call site.

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

С Stage 0.13.1/0.13.2 receipt boundary также владеет одиночным и массовым
назначением Inventory Number существующим S/N-позициям:

`WarehouseFacade -> ReceiptWriteService -> ReceiptRepository`.

Bulk flow использует Warehouse-owned preview store, повторный анализ под
`BEGIN IMMEDIATE` и transaction-aware repository helper. Новые карточки не
создаются. Полный контракт —
[INVENTORY_NUMBER_IMPORT_ARCHITECTURE.md](INVENTORY_NUMBER_IMPORT_ARCHITECTURE.md).

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

Эта compatibility-зона не включает новый Inventory Number write-flow: несмотря
на историческое имя `InventoryService`, назначение вторичного реквизита
существующему receipt является Warehouse receipt responsibility.

## Что осталось в `WarehouseCore`

`WarehouseCore` содержит старую реализацию на переходном этапе. Это временный compatibility core, а не целевая архитектура.

Текущее состояние Stage 0.13.3A:

- `WarehouseCore` остается допустимым legacy-core;
- часть сервисов остаётся фасадами/делегатами над `WarehouseCore`, а receipt,
  issue, cable, delivery и Inventory Number flows имеют Warehouse-owned
  реализации;
- дальнейший перенос идёт постепенно, по одному доменному блоку;
- публичный Python API `WarehouseService` не менялся;
- существующие generic HTTP API расширяются только через документированные
  kind/action contracts;
- production-схема SQLite, плоский runtime `reference_values` и рабочая БД не
  менялись;
- бизнес-логика не переписывалась.

**IMPLEMENTED:** отдельный offline-контур формализует 16 reference domains,
безопасные aliases, canonical naming и точное извлечение S/N. Девять таблиц
`migration_*`/`*_v2` создаются только в disposable candidate DB. Candidate
может содержать security snapshot (`users`, роли, password hashes без вывода),
но production operational tables остаются пустыми; исторические приходы и
расходы не импортируются.

**PROPOSED/FUTURE STAGE:** перенос утверждённых справочников в runtime,
исторических операций и замена рабочей БД требуют отдельного решения,
backup/reset gate и явного подтверждения. Candidate DB Stage 0.13.3A не
является production replacement.

Причина такого состояния: безопасные доменные разрезы должны фиксировать
границы ответственности без массового rewrite. Следующие переносы должны быть
маленькими и покрываться полным обнаруженным набором regression/contract/API
тестов, smoke UI, module/frontend audits и SQLite integrity-check.

## Зависимости

```text
webapp.py / tests
        |
        v
  ApplicationContext
        |
        +--> WarehouseFacade --> warehouse services/repositories --+
        +--> ReportsFacade -----------------------------------------+--> SQLite
        +--> AdministrationFacade ---------------------------------+
        +--> MonitoringFacade
        |
        +--> compat WarehouseService --> specialized services/WarehouseCore

cli.py --> compatibility WarehouseService --> SQLite

scripts/migration_reference_data.py
        --> inventory/migration (offline only)
        --> immutable migration_inputs/raw
        --> ignored migration_inputs/workspace/candidate DB
        -X-> data/warehouse.db writes / Web/API / WarehouseFacade

scripts/migration_pilot.py
        --> inventory/migration selector/builder
        --> injected inventory/warehouse migration writer
        --> ignored warehouse_pilot_candidate.db

pilot Web GET --> ApplicationContext --> WarehouseFacade
        --> migration_pilot_review --> marker-validated pilot DB read
        -X-> operational POST / data/warehouse.db
```

## Правила следующего этапа

1. Переносить методы из `WarehouseCore` в профильные сервисы группами.

2. После каждого переноса запускать:

```bash
python3 -m py_compile app.py inventory/**/*.py scripts/*.py tests/*.py
for file in static/js/*.js static/js/**/*.js tests/headless_smoke.js; do
  node --check "$file" || exit 1
done
python3 scripts/audit_module_boundaries.py
python3 scripts/audit_frontend_contracts.py
python3 -W error::ResourceWarning -m unittest discover -s tests -v
python3 scripts/create_clean_test_db.py --dry-run
python3 scripts/smoke_ui.py
sqlite3 -readonly data/warehouse.db 'PRAGMA integrity_check; PRAGMA foreign_key_check;'
git diff --check
```

3. Не менять рабочую БД при backend-refactoring.

4. Не менять API `/api/...` без отдельного migration plan.

5. Не менять схему БД в рамках сервисного переноса. Любая миграция данных должна иметь отдельный документ и backup-процедуру.

6. Не переносить несколько доменных блоков за один проход.
