# Delivery Acceptance Architecture

Stage 0.12.16 moves physical delivery acceptance to WarehouseFacade while
leaving delivery close/admin correction in compatibility code.

Public entry point:

`web/API -> ApplicationContext -> WarehouseFacade -> DeliveryAcceptanceService`

`DeliveryAcceptanceService` owns orchestration and transaction boundaries. It
uses `DeliveryRepository` for delivery SQL and the receipt write repository
transaction contract for actual receipt creation. It does not duplicate
`stock_receipts` insert SQL.

## Scenarios

- Planned new S/N: inspect finds a delivery line and no stock receipt; accept
  creates one `stock_receipts` row, links `delivery_lines.receipt_id`, sets the
  line to `Принято`, refreshes delivery status and writes audit.
- Existing S/N: inspect returns the existing receipt and conflicts. Accept does
  not create a receipt; it fills only empty allowed receipt fields, links the
  delivery line to the existing receipt and keeps conflicting filled values.
- Unplanned S/N: inspect returns `accept_unplanned`. Accept requires explicit
  values, creates an `is_unplanned=1` delivery line, creates a receipt, links
  the line and writes unplanned audit.
- Already accepted S/N: accept is blocked before mutation.

## Transactions

Single accept and batch accept run in one SQLite transaction:

1. re-read delivery and line;
2. re-check S/N and existing receipt;
3. create receipt or fill empty existing fields;
4. update delivery line;
5. refresh delivery status;
6. write audit;
7. commit.

Any error rolls back the receipt, line update, status update and success audit.

## Status Rule

`Принято` rows and `Уже на складе` rows with `receipt_id` are processed.
`Ожидается` rows keep the delivery partial. `Ошибка` and `Дубль в файле` remain
problem rows and do not block physical acceptance status. `Закрыта` is not set
by acceptance.

## Stress Snapshot

Temporary SQLite database, no production data mutation:

- inspect 1,000 planned S/N: 0.542 sec;
- batch accept 1,000 new S/N: 1.100 sec;
- existing-S/N link/fill-empty for 1,000 rows: 0.331 sec;
- conflict detection for 1,000 rows: 0.247 sec;
- balance read after acceptance: 0.011 sec;
- weekly report read after acceptance: 0.074 sec;
- open delivery card with 10,000 lines: 0.100 sec;
- DB size: 4.16 MB;
- final counts: 2,000 receipts, 3 deliveries, 12,000 delivery lines,
  zero stock issues and zero allocations;
- repeated accept attempt left receipt count unchanged;
- weekly report counted 1,000 newly accepted delivery items and did not count
  existing-S/N links as new receipts.
