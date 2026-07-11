# Warehouse EventReader Migration ODE 0.12.10

Stage 0.12.10 формализует публичный контракт складских событий для Reports.
БД, схема, URL, JSON/CSV и бизнес-результаты отчетов не меняются.

## Карта текущих зависимостей

| Отчет | Текущий метод | Текущий источник | Таблицы | Поля Reports | Целевой event type | Риск |
| --- | --- | --- | --- | --- | --- | --- |
| Daily report | `WarehouseCore.daily_report()` | SQL внутри compatibility core | `work_logs` | `work_date`, `task_type`, `task_number`, `description`, `comment` | Не складское событие; остается Reports-owned data | Низкий: не переносится |
| Daily report | `WarehouseCore.daily_report()` | SQL внутри compatibility core | `stock_receipts` | `receipt_date`, `item_name`, `model`, `inventory_number`, `serial_number`, `quantity`, `unit`, `responsible`, `order_number`, `request_number` | `RECEIPT_CREATED` / `CABLE_RECEIVED` | Средний: сохранить порядок `receipt_date,id` и строку количества |
| Daily report | `WarehouseCore.daily_report()` | SQL join allocations | `stock_issues`, `stock_issue_allocations`, `stock_receipts` | `issue_date`, `task_type`, `task_number`, `source_item_name`, `source_serial_number`, `quantity`, `unit`, `responsible`, `comment` | `ISSUE_CREATED` / `CABLE_ISSUED` | Средний: сохранить агрегацию по `issue_id` |
| Daily report | `WarehouseCore.daily_report()` | `data_quality_problems()` | `stock_issues`, `stock_issue_allocations` | `date`, `serial_number`, `item_name`, `unmatched_quantity`, `responsible`, `comment` | `DATA_PROBLEM_FOUND` | Средний: не дублировать с обычным расходом |
| Daily report | `WarehouseCore.daily_report()` | SQL delivery union | `deliveries`, `delivery_lines`, `stock_receipts` | даты, номер поставки, supplier, source filename, serial_number, kind | `DELIVERY_IMPORTED`, `DELIVERY_ACCEPTED`, `DATA_PROBLEM_FOUND` | Средний: сохранить подписи блока `Поставки` |
| Weekly report summary | `WarehouseCore.weekly_report()` | SQL aggregate | `stock_receipts` | counts, sums, cable sums, projects, types | `RECEIPT_CREATED` / `CABLE_RECEIVED` | Средний: float/int values and grouping |
| Weekly report summary | `WarehouseCore.weekly_report()` | SQL aggregate | `stock_issues`, `stock_issue_allocations`, `stock_receipts` | counts, sums, cable sums, projects, types | `ISSUE_CREATED` / `CABLE_ISSUED` | Средний: allocations influence project/type/cable grouping |
| Weekly report summary | `WarehouseCore.weekly_report()` | `data_quality_problems()` | warehouse tables | problem row counts and details | `DATA_PROBLEM_FOUND` | Низкий: details are preserved as metadata |
| Weekly report summary | `WarehouseCore.weekly_report()` | SQL aggregate | `deliveries`, `delivery_lines`, `stock_receipts` | loaded, accepted, problem rows | `DELIVERY_IMPORTED`, `DELIVERY_ACCEPTED`, `DATA_PROBLEM_FOUND` | Средний: date sources differ (`uploaded_at`, receipt date, updated_at) |
| CSV exports | `ReportsFacade.export_daily_report_rows()`, `export_weekly_report_rows()` | same report methods | same as daily/weekly | same rows | same events | Низкий if report rows unchanged |

## Целевой переход

- `ReportsFacade` продолжает читать `work_logs` через Reports-owned service.
- Warehouse-owned facts are read through `WarehouseEventReader`.
- SQL over `stock_receipts`, `stock_issues`, `stock_issue_allocations`,
  `deliveries`, `delivery_lines` is allowed only inside `inventory/warehouse`.
- The EventReader implementation is compatibility code and may use the existing
  SQLite schema. Reports does not depend on that schema.

## Deduplication Strategy

- Business tables are primary for receipt/issue/delivery accepted events.
- `audit_log` is not used for events already represented by business tables.
- `audit_log` can be used later only for events with no business-table source.
- `event_id` is stable and source-prefixed, for example `receipt:123`,
  `issue:456`, `delivery:7`, `delivery-line-accepted:42`.
- If two sources produce the same `event_id`, the first business-table event wins.

## Legacy and Missing Data

EventReader does not invent missing actor, supplier, project, task or serial
data. Missing values are returned as empty strings. Presentation code can decide
whether to show `Не указано`.
