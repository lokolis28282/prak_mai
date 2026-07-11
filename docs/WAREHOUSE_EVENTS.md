# Warehouse Events

`WarehouseEvent` is the public read-only contract used by Reports to consume
warehouse facts without knowing internal warehouse tables or `WarehouseCore`.

## Model

Fields:

- `event_id`
- `event_type`
- `event_date`
- `event_time`
- `actor`
- `entity_type`
- `entity_id`
- `serial_number`
- `item_name`
- `quantity`
- `unit`
- `project`
- `supplier`
- `task_number`
- `comment`
- `source`
- `metadata`

The contract is returned as plain dataclasses or dicts. It must not expose
`sqlite3.Row`, raw SQL objects, passwords, session tokens or secret metadata.

## Event Types

- `RECEIPT_CREATED`
- `RECEIPT_IMPORTED`
- `ISSUE_CREATED`
- `ISSUE_IMPORTED`
- `DELIVERY_IMPORTED`
- `DELIVERY_ACCEPTED`
- `DELIVERY_UPDATED`
- `DELIVERY_CLOSED`

Stage 0.12.15: delivery document confirm emits/audits only the import fact
(`DELIVERY_UPLOAD` in audit, `DELIVERY_IMPORTED` in warehouse event contract).
It must not emit `DELIVERY_ACCEPTED` or receipt-created events because no
physical stock receipt is created during document import.

Stage 0.12.16: new delivery acceptance creates a receipt source row and links a
delivery line, so readers may expose both receipt and delivery accepted facts
according to the existing report contract. Existing-S/N linking does not create
a new receipt and must not produce a false receipt-created fact.
- `CABLE_RECEIVED`
- `CABLE_ISSUED`
- `INVENTORY_CHECKED`
- `DATA_PROBLEM_FOUND`

## Reader

`WarehouseEventReader` belongs to Warehouse and exposes:

- `list_events(date_from, date_to, event_types=None, limit=None)`
- `list_report_events(date_from, date_to)`
- `list_problem_events(date_from, date_to)`
- `get_event(event_id)`

Stage 0.12.10 implementation is compatibility-backed and reads the current
SQLite schema inside `inventory/warehouse`. Reports receives only events.

Stage 0.12.12 keeps the event contract stable while equipment/component receipt
writes move behind `WarehouseFacade`. New receipt rows still appear as
`RECEIPT_CREATED`; no duplicate receipt summary event is emitted for Reports.

Stage 0.12.13 keeps cable event names stable while cable write logic moves to
the cable module. Cable receipt rows still emit `CABLE_RECEIVED`; cable issue
allocations still emit `CABLE_ISSUED`. No separate audit-derived duplicate event
is emitted for Reports.

Stage 0.12.14 keeps issue event names stable while serialized issue writes move
to the issue module. Matched issue rows still emit `ISSUE_CREATED`; unmatched
problem rows continue to emit `DATA_PROBLEM_FOUND` through the problem event
reader. Reports must not consume issue audit rows as duplicate business events.

## Ordering

Events are ordered by date/time and stable source priority. For reports, the
existing report block order is preserved by Reports presentation logic:

1. `Логи работ`
2. `Приход`
3. `Расход`
4. `Проблемные строки`
5. `Поставки`

## Deduplication

Business table events have priority over audit events. Event IDs include source
and primary key to prevent duplicate receipt/issue/delivery rows.
