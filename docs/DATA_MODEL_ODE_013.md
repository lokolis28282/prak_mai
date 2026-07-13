# DATA_MODEL_ODE_013

Дата: 2026-07-10

## Цель

Подготовить ODE 0.13 к загрузке реальной инвентаризации без разделения на разные SQLite-файлы. Разделение должно быть логическим: одна БД, один сервисный слой, но разные правила для оборудования, компонентов и кабелей.

## Текущая модель ODE 0.12

Основная рабочая модель склада уже находится не в legacy-таблицах `equipment` и `operations`, а в новых таблицах:

- `stock_receipts` - строки прихода и начального остатка.
- `stock_issues` - строки расхода.
- `stock_issue_allocations` - распределение расхода по строкам прихода.
- `deliveries` и `delivery_lines` - загруженные поставки и строки поставок.
- `reference_values` - справочники.
- `audit_log` - единый технический аудит действий.

Legacy-таблицы `equipment`, `operations`, `categories`, `locations` остаются для совместимости CLI и старых сценариев.

В `stock_receipts` логическое разделение сейчас задано тремя полями:

- `equipment_type`
- `component_type`
- `cable_type`

Сервис требует ровно один классификатор. Если заполнен `cable_type`, позиция считается кабелем. Если заполнен `component_type`, позиция считается компонентом. Иначе позиция считается оборудованием.

## Проблемы текущей модели

1. Разделение по трем nullable-text полям работает, но не является явным доменным типом.

   Правила зависят от комбинации `equipment_type/component_type/cable_type`, а не от одного поля `item_kind`. Это повышает риск неконсистентных строк.

2. Кабели и серийные позиции лежат в одной таблице с одинаковым набором полей.

   Для кабелей лишние `serial_number`, `inventory_number`, `model`. Для оборудования и компонентов лишняя кабельная логика по `item_name + cable_type`.

3. Компоненты пока не имеют отдельной связи с целевым сервером как состоянием.

   Расход компонента требует `target_serial_number`, но постоянной таблицы "компонент установлен в сервер" пока нет.

4. История есть, но она собирается из нескольких источников.

   `warehouse_history()` объединяет приходы, расходы и audit. Это работает для UI, но для 100k+ строк лучше иметь отдельный нормализованный журнал складских событий.

5. Индексы частично покрывают реальные запросы.

   Есть индексы по датам, serial, cable lookup и allocations, но для больших импортов нужны индексы по `item_kind`, `project`, `datacenter`, `item_name`, `model`, `vendor`, `delivery_id/state`.

## Целевая модель

### Общие принципы

Одна SQLite-БД. Один `ApplicationContext` с публичным `WarehouseFacade`;
`WarehouseService` сохраняется как compatibility layer. Логика разделяется
внутри Warehouse service/repository слоя и таблиц по типу позиции.

Ввести явный тип позиции:

- `equipment`
- `component`
- `cable`

На уровне сервиса все операции должны проходить через один слой валидации:

- `prepare_receipt()`
- `prepare_issue()`
- `validate_equipment()`
- `validate_component()`
- `validate_cable()`
- `append_stock_event()`

### Таблицы, которые оставить

- `stock_receipts` - оставить как основную таблицу лотов прихода на переходный период.
- `stock_issues` - оставить как таблицу расхода.
- `stock_issue_allocations` - оставить как FIFO/lot allocation.
- `deliveries`, `delivery_lines` - оставить.
- `reference_values` - оставить.
- `audit_log` - оставить для технического аудита.
- `users`, `work_logs`, `daily_report_*` - оставить без изменения.
- `equipment`, `operations`, `categories`, `locations` - оставить только как legacy-совместимость до отдельного решения.

### Поля, которые добавить позже

В `stock_receipts`:

- `item_kind TEXT CHECK(item_kind IN ('equipment','component','cable'))`
- `item_type TEXT`
- `normalized_key TEXT`
- `parent_equipment_serial TEXT DEFAULT ''`
- `lifecycle_status TEXT DEFAULT 'in_stock'`

В `stock_issues`:

- `item_kind TEXT CHECK(item_kind IN ('equipment','component','cable'))`
- `source_position_key TEXT`
- `target_equipment_serial TEXT DEFAULT ''`
- `issue_reason TEXT DEFAULT ''`

Новая таблица позже:

```sql
CREATE TABLE stock_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_date TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    event_type TEXT NOT NULL,
    item_kind TEXT NOT NULL CHECK (item_kind IN ('equipment', 'component', 'cable')),
    receipt_id INTEGER REFERENCES stock_receipts(id),
    issue_id INTEGER REFERENCES stock_issues(id),
    delivery_id INTEGER REFERENCES deliveries(id),
    serial_number TEXT NOT NULL DEFAULT '',
    inventory_number TEXT NOT NULL DEFAULT '',
    item_name TEXT NOT NULL DEFAULT '',
    item_type TEXT NOT NULL DEFAULT '',
    quantity REAL NOT NULL DEFAULT 0,
    unit TEXT NOT NULL DEFAULT '',
    project TEXT NOT NULL DEFAULT '',
    datacenter TEXT NOT NULL DEFAULT '',
    shelf TEXT NOT NULL DEFAULT '',
    target_equipment_serial TEXT NOT NULL DEFAULT '',
    responsible TEXT NOT NULL DEFAULT '',
    comment TEXT NOT NULL DEFAULT ''
);
```

Новая таблица позже для установленных компонентов:

```sql
CREATE TABLE component_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    component_receipt_id INTEGER NOT NULL REFERENCES stock_receipts(id),
    equipment_receipt_id INTEGER NOT NULL REFERENCES stock_receipts(id),
    linked_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    linked_by TEXT NOT NULL,
    unlinked_at TEXT NOT NULL DEFAULT '',
    unlinked_by TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT ''
);
```

## Общие поля

Для всех типов:

- `receipt_date` / `issue_date`
- `responsible`
- `item_kind`
- `item_name`
- `item_type`
- `project`
- `supplier`
- `vendor`
- `model`
- `shelf`
- `object_name`
- `datacenter`
- `unit`
- `quantity`
- `created_at`

## Специфика оборудования

Обязательные правила:

- `serial_number` обязателен.
- `inventory_number` является целевым обязательным реквизитом полной реальной
  инвентаризации, но может быть пуст при первом приходе.
- позднее назначение выполняется только по `serial_number`, не создаёт новую
  карточку и не перезаписывает другой заполненный номер.
- `quantity = 1`.
- `unit = 'шт'`.
- Расход только целым количеством.
- Карточка открывается по `serial_number`.
- История показывает приход, расход, поставку и audit.

Поля:

- `serial_number`
- `inventory_number`
- `equipment_type`
- `lifecycle_status`

## Специфика компонентов

Обязательные правила:

- `serial_number` обязателен.
- `quantity = 1`.
- `unit = 'шт'`.
- `inventory_number` опционален.
- Может быть привязан к серверу через `target_equipment_serial`.
- В будущем замена должна быть отдельным событием, а не просто расходом.

Поля:

- `serial_number`
- `component_type`
- `target_equipment_serial`
- `component_link_id`

## Специфика кабелей

Обязательные правила:

- `serial_number` обычно пустой.
- Учет по количеству или метражу.
- Ключ баланса: `item_name + cable_type + project + datacenter + unit`.
- Не проходит через мастер оборудования.
- Приход/расход кабеля должен быть отдельным упрощенным сценарием UI.

Поля:

- `cable_type`
- `quantity`
- `unit`
- `project`
- `datacenter`

## План безопасной миграции

### Реализовано без schema migration в Stage 0.13.1/0.13.2

- карточка и bulk CSV могут заполнить пустой `stock_receipts.inventory_number`
  существующей S/N-позиции;
- bulk Preview/Confirm использует существующий Warehouse receipt boundary,
  unique indexes и audit-backed Timeline;
- связанная пустая legacy `equipment.inventory_number` синхронизируется той же
  транзакцией;
- новые таблицы/столбцы, `stock_events` и data migration не добавлялись.

Следующий план относится к будущей нормализации модели и не запускается
автоматически Stage 0.13.2:

1. Только проектирование и тесты.

   На этом этапе БД не менять.

2. Добавить миграцию v013 в код, но включить ее только на копии БД.

   Сначала `ALTER TABLE ADD COLUMN item_kind`, `item_type`, `normalized_key`.

3. Backfill на копии.

   - `cable_type <> ''` -> `item_kind = 'cable'`
   - `component_type <> ''` -> `item_kind = 'component'`
   - иначе -> `item_kind = 'equipment'`

4. Добавить проверки консистентности.

   - equipment/component имеют `serial_number`.
   - cable не требует `serial_number`.
   - equipment/component имеют целое количество.
   - `item_kind` согласован с типовым полем.

5. Перевести сервис на `item_kind`.

   Сначала читать старые и новые поля одновременно. Запись делать в оба набора полей.

6. Перевести UI.

   Отдельные сценарии: equipment receipt, component receipt, cable receipt, equipment/component issue, cable issue.

7. Ввести `stock_events`.

   Первое время заполнять параллельно с `stock_receipts/stock_issues/audit_log`.

8. После acceptance убрать зависимость бизнес-логики от `equipment_type/component_type/cable_type` как от классификатора.

## Риски

- Ошибка backfill может неверно классифицировать реальные строки.
- Старые CSV могут не иметь достаточных полей для строгой модели.
- Компоненты без целевого сервера должны оставаться валидным складским остатком.
- Кабели с S/N являются исключением; модель должна либо явно поддержать serialized cable, либо блокировать такие строки.
- Будущие импорты 100k+ строк требуют отдельного job/streaming дизайна и
  индексов; текущий synchronous parser намеренно ограничен 40 000 строками.

## Нужные тесты

- Миграция на копии БД не меняет сумму баланса.
- `item_kind` корректно вычисляется из текущих строк.
- Оборудование без S/N отклоняется.
- Компонент без S/N отклоняется.
- Кабель без S/N принимается.
- Кабель списывается по `item_name + cable_type`.
- Оборудование и компоненты списываются только целыми штуками.
- Компонент требует целевое оборудование при списании/установке.
- Общая история содержит приход, расход, поставку, импорт и audit.
- Будущий импорт 100k строк укладывается в целевой лимит времени и памяти;
  текущий контракт должен безопасно отклонять файл свыше 40 000 строк.
