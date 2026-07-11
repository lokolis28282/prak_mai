# WAREHOUSE_API_MIGRATION

Stage 0.12.7 migrates read-only Warehouse API calls from direct compatibility service calls to `WarehouseFacade`. URL routes, JSON/CSV formats, SQL, DB schema and write behavior are unchanged.

## Endpoint Map

| URL | Method | Current call | Target facade method | Tables | UI screen | Response format | Risk |
|---|---|---|---|---|---|---|---|
| `/api/data` | GET | mixed `service.*` | `warehouse.get_overview()`, Reports/Admin facades | many | all screens bootstrap | JSON object with existing keys | high: broad contract |
| `/api/balance` | GET | `service.stock_balance(**filters)` | `warehouse.get_balance(filters)` | `stock_receipts`, `stock_issues`, allocations | Balance | `{"rows": list}` | low |
| `/api/deliveries` | GET | `service.deliveries(query)` | `warehouse.list_deliveries(query)` | `deliveries`, `delivery_lines` | Deliveries | `{"deliveries": list}` | low |
| `/api/delivery` | GET | `service.delivery(id)` | `warehouse.get_delivery(id)` | `deliveries`, `delivery_lines` | Delivery card | delivery dict | medium: bad id handling |
| `/api/position-search` | GET | `service.search_stock_positions(query)` | `warehouse.search_warehouse(query)` | balance source tables | Issue/Card search | `{"rows": list}` | low |
| `/api/position-card` | GET | `service.position_card(...)` | `warehouse.get_position_card(filters)` | receipts, issues, balance | Position card modal | position/history/problem JSON | medium |
| `/api/scan-serial` | GET | `service.scan_receipt_serial/scan_issue_serial` | unchanged | stock/balance | Receipt/Issue scanner | JSON validation | write-flow adjacent, not migrated |
| `/export/balance.csv` | GET | `service.stock_balance(**filters)` | `warehouse.export_balance_rows(filters)` | balance source tables | Balance export | CSV, same filename/BOM/headers | low |
| `/export/delivery.csv` | GET | `service.delivery(id)["lines"]` | `warehouse.get_delivery(id)["lines"]` | delivery tables | Delivery export | CSV, same filename | low |
| `/export/stock.csv` | GET | `service.equipment()` | `warehouse.get_inventory_view()` | `equipment` | Legacy journal link | CSV | low legacy |
| `/export/log.csv` | GET | `service.operation_log(limit=None)` | `warehouse.get_warehouse_history_legacy()` | `operations` | Legacy journal link | CSV | low legacy |
| `/export/receipt.csv` | GET | `service.stock_receipts()` | `warehouse.receipts()` | `stock_receipts` | Receipt export | CSV localized | low read-only but write-domain data |
| `/export/issue.csv` | GET | `service.stock_issue_rows()` | `warehouse.issue_rows()` | `stock_issues` | Issue export | CSV localized | low read-only but write-domain data |
| `/export/problem-issues.csv` | GET | `service.data_quality_problems()` | `warehouse.get_problem_issues()` | issues/balance | Monitoring/problems | CSV localized | medium |

## Migrated In Stage 0.12.7

- `/api/balance`
- `/api/deliveries`
- `/api/delivery`
- `/api/position-search`
- `/api/position-card`
- `/api/data` warehouse-owned fields internally
- `/export/balance.csv`
- `/export/delivery.csv`
- `/export/stock.csv`
- `/export/log.csv`
- `/export/receipt.csv`
- `/export/issue.csv`
- `/export/problem-issues.csv`

## Not Migrated

- write endpoints under `/api/action`;
- CSV preview/import/confirm;
- scanner validation `/api/scan-serial`, because it sits directly in receipt/issue workflows;
- Reports exports and Admin exports except where `/api/data` reads their public facades.

## Contract Rule

The facade delegates to the compatibility service and returns plain `dict`/`list` values. Semantic comparison tests compare old service results to facade results without storing large snapshots.

## Verification

`tests/test_warehouse_api_contract.py` checks:

- semantic equality of legacy service reads and facade reads;
- JSON keys used by `static/js/ui.js`;
- plain JSON serializability;
- balance filters;
- balance CSV contract;
- deliveries empty state;
- unknown delivery id error behavior;
- position search/card payloads.
