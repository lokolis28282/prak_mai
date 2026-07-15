# References и Catalog

Статус: **APPROVED — ODE 0.13 architecture baseline**

Этот документ дополняет ownership и DDL точными lifecycle-правилами.

## Единственные источники истины

| Domain | Scope |
|---|---|
| VENDOR | global |
| MODEL | vendor-scoped |
| EQUIPMENT_TYPE | global or parent component taxonomy |
| COMPONENT_TYPE | equipment-type scoped |
| CABLE_TYPE | global |
| SUPPLIER | global |
| STOCK_CONDITION | global |
| UOM | global, separate uoms table |
| WAREHOUSE | warehouses table |
| LOCATION | warehouse-scoped locations table |
| CATALOG_ITEM | vendor + Part Number where known |

UI не содержит hardcoded labels/values, кроме protocol enum codes. API
возвращает active reference options.

## Value lifecycle

    PENDING -> APPROVED -> INACTIVE
       |          |
       v          v
    REJECTED     MERGED

Create canonical — admin command с provenance. Read/resolve никогда не создает
value. Rename меняет display_name, но стабильный code/ID не меняется. Если
семантика изменилась, создается новый value и старый inactive/merged.

## Alias lifecycle

- PENDING: обнаружен Preview, target отсутствует или не подтвержден.
- APPROVED: explicit admin decision, exact scope and target.
- REJECTED: не должен разрешаться.
- RETIRED: ранее действовал, больше не применяется новым imports.

Raw historical values не меняются. Alias применяется только будущим Preview и
может отображаться в provenance старых imports.

## Merge

Перед merge admin получает impact preview:

- affected aliases;
- catalog items;
- equipment;
- snapshot items and ledger references;
- reports/search labels.

Merge не UPDATE foreign keys authoritative history. Old value хранит
merged_into; queries resolve canonical redirect, а historical DTO показывает
raw и current canonical отдельно.

Запрещены автоматические Huawei/xFusion, HP/HPE и любые semantic merges.
String similarity создает PENDING finding, не decision.

## Vendor-scoped model и Part Number

Model normalized key уникален в vendor scope. Одинаковое display name у разных
vendors допустимо. Part Number сохраняет raw и conservative key; vendor+PN —
кандидат уникальности CatalogItem, но пустой PN не объединяет items.

## Parent-child

`parent_value_id` всегда указывает value того же domain и не создает cycle.
Cross-domain scoping выражается `scope_value_id` согласно `scope_policy`, а не
parent link. Эти два правила enforce DB triggers; restore/migration обязан
выполнить hierarchy invariant queries до publish. Rename и INACTIVE не меняют
parent edge, alias никогда не участвует в parent hierarchy.
Удаление запрещено; используется INACTIVE. Деактивация reference с active
Equipment/Location не меняет историю, но запрещает новые imports/transactions.

## Preview impact

Reference fingerprint включает approved values, aliases, UOM scales,
warehouses/locations и catalog items. Любое изменение после Preview делает run
STALE. Operator resolution не может сам создать canonical; он выбирает
существующий approved target либо передает finding admin.
