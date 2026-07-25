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

## Equipment Card Timeline — Stage 0.13.1/0.13.2

Inventory Number assignment writes the existing audit action
`EQUIPMENT_INVENTORY_NUMBER_ASSIGNED` with entity type `stock_receipt`, receipt
ID, current actor and details containing S/N/Inventory Number. Bulk import
creates one audit row for every actually changed `SUCCESS` position in the same
transaction as the update.

Equipment Card Timeline renders this as
`Запись журнала: EQUIPMENT_INVENTORY_NUMBER_ASSIGNED`. Preview,
`UNCHANGED`, `NOT_FOUND` and conflict statuses produce no audit/Timeline row.

This action is deliberately not added to the `WarehouseEventReader` Event
Types list above and is not a Reports business event. No second event publisher
or event table is introduced; Timeline reuses the existing audit reader.

## Migration Pilot Timeline — Stage 0.13.3A.5

**PILOT ONLY / NOT PRODUCTION:** historical pilot receipts reuse existing
`audit_log` and Equipment Card Timeline. They do not add a parallel event store
or a new Reports `WarehouseEvent` type.

The migration actions are:

- `MIGRATION_RECEIPT_IMPORTED` — one preserved primary created a pilot receipt;
- `MIGRATION_SOURCE_ROW_LINKED` — source provenance linked to the card;
- `MIGRATION_CONFLICT_RECORDED` — conflicting vendor/model/item/shelf history
  retained without a second receipt;
- `MIGRATION_EXACT_DUPLICATE_SKIPPED` — duplicate source row linked/skipped;
- `MIGRATION_SERIAL_QUARANTINED` — non-importable identity retained outside
  stock.

Actions linked to a receipt use `entity_type=stock_receipt` and its pilot
receipt ID. Quarantine uses `entity_type=migration_staging_row`. Details are a
closed projection of logical source filename, sheet/row, source/canonical item
names and warnings; absolute paths are redacted.

Pilot receipts are stored with `is_opening_balance=1`. The current
`WarehouseEventReader` excludes them, so daily/weekly Reports do not announce a
historical reconstruction as `RECEIPT_CREATED`. Equipment Card still reads the
receipt plus related audit entries and relabels the card history as
`Исторический приход (миграция)`.

The source historical receipt date is displayed from migration provenance. The
audit timestamp is the actual pilot build/migration time; one must not be
rewritten to impersonate the other. A duplicate/conflict source row may add
provenance/audit history but never another business receipt or balance unit.

**FUTURE 0.13.3B / OPEN DECISION:** a production historical-event vocabulary
and report policy require a separate contract. Pilot actions must not be
promoted to production event semantics automatically.

## Full Historical Candidate and Promoted Timeline

The full build reuses `audit_log`; it does not add an event table or publisher.
The exact candidate exposes the closed action set below only in read-only
review. The promoted local working DB preserves the same provenance, but normal
Equipment Card filters `MIGRATION_%` audit rows from the user Timeline and
derives understandable receipt/issue history through the existing Warehouse
facade. Its closed migration action set is:

- `MIGRATION_RECEIPT_IMPORTED`;
- `MIGRATION_SOURCE_ROW_LINKED`;
- `MIGRATION_EXACT_DUPLICATE_SKIPPED`;
- `MIGRATION_CONFLICT_RECORDED`;
- `MIGRATION_NUMERIC_IDENTITY_PROVISIONAL`;
- `MIGRATION_OPENING_STATE_CREATED`;
- `MIGRATION_ISSUE_IMPORTED`;
- `MIGRATION_SERIAL_QUARANTINED`.

A proven historical operation date is passed through the existing optional
audit `event_date`; an unproven date falls back to the deterministic Stage A
candidate timestamp and retains `SOURCE_DATE_UNPROVEN`. Logical filename,
sheet/row/hash, source/canonical names, preservation status, final status,
warnings and conflicts remain details. Absolute local paths are redacted.

Opening state is relabelled `Начальный остаток` in ordinary Equipment Card and
never presented as a supplier receipt. Its user explanation is: «Восстановлено
начальное состояние до доступной истории операций». Detailed source/status
wording remains available only in admin migration review. Candidate audit may
form a future outbox source only after a separate production design; this build
adds neither outbox nor Kafka.

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
