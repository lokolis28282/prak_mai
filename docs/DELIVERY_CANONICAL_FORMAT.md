# Delivery Canonical Format

The internal canonical delivery import row uses these fields:

Required for a useful document line:

- `serial_number` or a known no-S/N state
- `quantity`

Recommended document fields:

- `delivery_date`
- `supplier`
- `delivery_number`
- `request_number`
- `order_number`
- `plu`
- `serial_number`
- `inventory_number`
- `vendor`
- `model`
- `item_type`
- `project`
- `datacenter`
- `shelf`
- `quantity`
- `comment`

Compatibility-only fields may still be stored when old files provide them:
`request_position`, `order_position`, `accounting_object`, `asset_number`,
`equipment_unit`, `receipt_statement`, `planned_date`, `contract_number`.
The database schema is not changed in Stage 0.12.15.

## Synonyms

- S/N: `S/N`, `SN`, `Серийный номер`, `Серийник`, `Серийные номера`,
  `Serial`, `Serial Number`
- Inventory number: `Инв.№`, `Инв. №`, `Инвентарный номер`, `Inventory`,
  `Asset Number`, `Номер ОС`
- Order: `Заказ`, `Заказ №`, `Заказ№`, `Номер заказа`, `Order`
- Request: `Заявка`, `Заявка №`, `Заявка№`, `Request`
- Delivery: `Поставка`, `Номер поставки`, `Delivery`, `Delivery Number`
- Supplier: `Поставщик`, `Supplier`, `Vendor Supplier`
- Vendor: `Вендор`, `Производитель`, `Vendor`, `Manufacturer`
- Model: `Модель`, `Model`
- Type: `Тип`, `Тип оборудования`, `Тип компонента`, `Категория`, `Item Type`
- Quantity: `Количество`, `Кол-во`, `шт`, `Qty`, `Quantity`

Header matching is case-insensitive. BOM, repeated whitespace and dots are
normalized. Unknown columns are shown in preview and preserved in preview metadata
until confirm. Ambiguous headers are reported as warnings and are not chosen
silently.

## Dates

Accepted date formats follow the warehouse date parser where possible:
`YYYY-MM-DD`, `DD.MM.YYYY`, and common CSV date strings. Unparseable dates stay as
source text in the document metadata/presentation layer; they do not create
receipts in this stage.

## Quantity

Quantity must be numeric and greater than zero for a valid line. A row with one
S/N and quantity greater than 1 is marked as requiring review. A row with multiple
S/N values and quantity 1 or a quantity different from the S/N count is marked as
a quantity error/review depending on the exact mismatch. No serial numbers are
invented.

## Serial Numbers

`serial_number` may contain one or more values separated by comma, semicolon,
line break, tab, or repeated whitespace. Values are trimmed, empty values are
removed, comparisons are case-insensitive, and the source cell is retained in
preview metadata when it differs from the expanded S/N. One S/N becomes one
`delivery_lines` row.
