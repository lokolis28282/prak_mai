# DATA_MODEL_ODE_013

Дата актуализации: 2026-07-14. Current source: Stage 0.13.3A.5.

Статусы в документе: **FACT** — подтверждено production-кодом/схемой;
**IMPLEMENTED** — реализовано в текущем source; **PROPOSED** — целевая модель,
не production contract; **FUTURE STAGE** — следующий этап; **OPEN DECISION** —
нужно отдельное решение.

## Цель

Подготовить ODE 0.13 к загрузке реальной инвентаризации без постоянного
разделения production-данных на разные SQLite-файлы. Разделение runtime должно
быть логическим: одна БД, один сервисный слой, но разные правила для
оборудования, компонентов и кабелей. Одноразовая candidate DB Stage 0.13.3A —
изоляционный migration artifact, а не вторая production-БД.

## FACT — текущая production-модель

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

Stages 0.13.3A/0.13.3A.5 не меняют эту схему. Production-справочник остаётся плоской
таблицей `reference_values(kind, name, is_active, created_at)`; ни одна из
candidate-таблиц не добавлена в `inventory/db.py`.

## IMPLEMENTED — Reference Data Foundation Stage 0.13.3A

Offline-пакет `inventory/migration` формализует 16 controlled domains:

- `object_kind`, `equipment_category`, `equipment_role`, `equipment_type`;
- `component_type`, `cable_type`, `cable_category`;
- `vendor`, `model`, `catalog_item`, `supplier`;
- `datacenter`, `warehouse_location`, `unit_of_measure`;
- `operation_source`, `issue_reason`.

Reference/model/catalog values, aliases и решения review сохраняются только в
disposable candidate DB. Model identity vendor-scoped; canonical item name
пересчитывается из структурированных полей и не является идентификатором.
S/N остаётся исходным текстовым идентификатором; отдельный normalized match key
не подменяет source value.

Candidate создаётся под ignored
`migration_inputs/workspace/warehouse_migration_candidate.db` и добавляет
ровно девять offline-таблиц:

- `migration_batches`, `migration_source_files`;
- `reference_domains_v2`, `reference_values_v2`, `reference_aliases_v2`;
- `catalog_items_v2`;
- `migration_staging_rows`, `migration_serial_cells`;
- `migration_validation_results`.

Эти таблицы намеренно отсутствуют в production schema. Production operational
tables candidate остаются пустыми. Допускается только security snapshot
`users` с сохранёнными password hashes/ролями без вывода их значений.

## IMPLEMENTED / PILOT ONLY — Stage 0.13.3A.5

The pilot creates a second disposable DB, not a production schema migration.
It retains the nine Stage A tables and adds six `migration_pilot_*` tables for
marker, selection, identity, provenance, quarantine and performance.

Exactly 200 source receipt rows are represented. Only 130 safe `IMPORT`
primaries create `stock_receipts`; each has exact text S/N, quantity `1`, a
proven source date and `is_opening_balance=1`. All other decisions preserve
evidence without stock. One normalized match identity maps to at most one pilot
receipt. Shelf is not a key and alternate shelves remain provenance.

This does not assert that `normalized_match_value` is a production identity
column: it remains pilot/staging matching evidence. The production partial
unique S/N index still has `COLLATE NOCASE`, so case-distinct identities require
a separate ADR/schema decision. Candidate reference IDs and pilot target IDs do
not enter `data/warehouse.db`.

The source contains Vegman R220 but no R200; no model/source row is synthesized.
Huawei/xFusion and vendor-scoped models remain distinct candidate facts.

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

## PROPOSED — целевая production-модель

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
- `users`, `daily_report_*` - оставить без изменения.
- `work_logs` (УВР) - добавлены `section` («Раздел») и `needs_review` (флаг
  строк, мигрированных из legacy Excel и требующих ручной проверки раздела);
  миграция идемпотентна (`ALTER TABLE ADD COLUMN`).
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

### IMPLEMENTED без production schema migration в Stage 0.13.3A

- immutable XLSX читается напрямую из OOXML, включая raw token, тип ячейки и
  number format; numeric identifiers не проходят через `float`;
- numeric S/N сохраняет raw token, требует manual review и не получает
  match key автоматически; exponent display не подменяет source value;
- reference/alias/canonical proposals и полная provenance S/N загружаются
  только в disposable candidate;
- CLI `inspect-sources`, `build-candidate`, `validate-candidate`, `report`
  проверяет SHA источников и рабочей БД, candidate integrity/FK, пустоту
  operation tables и отсутствие staging-таблиц в production;
- исторические приходы, расходы и лист БАЛАНС не импортируются;
- `data/warehouse.db` не очищается, не заменяется и не мигрируется.

Следующий план — **PROPOSED/FUTURE STAGE**. Он относится к будущей
нормализации production-модели и не запускается автоматически Stage 0.13.3A:

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
- Candidate aliases со статусом `PENDING` и serial cells
  `SOURCE_CORRUPTED`/manual-review нельзя трактовать как утверждённые данные.
- Candidate DB не является production backup и не может быть установлена в
  `data` без отдельного reset workflow и явного подтверждения.
- The 200-row pilot is not evidence that all 51,003 receipt rows are importable;
  numeric/corrupted/quantity/unresolved and non-selected rows remain outside
  production.

## OPEN DECISIONS

- Какие approved reference values и aliases переносить в production и в какой
  схеме: расширять `reference_values` либо вводить новые runtime-таблицы.
- Какие строки исторического прихода/расхода разрешить после manual review.
- Какая case-sensitive production identity/index model заменит или дополнит
  текущий `COLLATE NOCASE` contract.
- Когда и как выполнить документированный backup/reset/install workflow.
- Нужны ли `stock_events`, `component_links` и явный `item_kind` в том же
  production migration или отдельными этапами.

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
