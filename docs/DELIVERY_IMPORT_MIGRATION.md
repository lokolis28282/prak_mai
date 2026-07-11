# Delivery Import Migration Map

Stage 0.12.15 moves only delivery document import, validation and matching to
`WarehouseFacade`. Physical acceptance remains legacy for Stage 0.12.16.

| Flow | User scenario | Endpoint/action | Legacy method | Target facade method | Tables | Balance change | Audit/event | Risk | Stage |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Template download | User downloads CSV template from Deliveries | `GET /import/delivery-template.csv` | `USER_CSV_TEMPLATES["delivery"]` | `get_delivery_import_template()` | none | no | none | low | 0.12.15 |
| CSV upload | User uploads a delivery CSV | `POST /api/import-csv?kind=delivery` | `preview_delivery_rows(..., auto_apply=True)` | `preview_delivery_import(rows, filename, source_metadata)` | read `stock_receipts`, `delivery_lines` | no | none | high: old path could auto-apply | 0.12.15 |
| Preview | UI shows parsed rows, unknown columns and summary | same upload response | `preview_delivery_rows` | `preview_delivery_import` | read only | no | none | medium | 0.12.15 |
| Confirm document | User confirms delivery document upload | `POST /api/action`, `CONFIRM_DELIVERY` | `confirm_delivery_preview` | `confirm_delivery_import(preview_id)` | `deliveries`, `delivery_lines`, `audit_log` | no | `DELIVERY_UPLOAD` / `DELIVERY_IMPORTED` | high: must not insert receipts | 0.12.15 |
| Deliveries list | User opens Deliveries | `GET /api/deliveries` | `deliveries(query)` | `list_deliveries(query, filters)` | read `deliveries`, `delivery_lines` | no | none | low | 0.12.15 |
| Delivery card | User opens delivery card | `GET /api/delivery?id=` | `delivery(id)` | `get_delivery(id)` | read `deliveries`, `delivery_lines` | no | none | low | 0.12.15 |
| Delivery lines | UI renders lines in card | `GET /api/delivery?id=` | `delivery(id)` | `get_delivery_lines(id, filters)` via `get_delivery` | read `delivery_lines` | no | none | low | 0.12.15 |
| Search deliveries | User searches by number, supplier, S/N, order/request | `GET /api/deliveries?query=` | `deliveries(query)` | `search_deliveries(query)` / `list_deliveries` | read only | no | none | low | 0.12.15 |
| Duplicate S/N in file | Preview marks repeated S/N | upload preview | `_delivery_serials` + local set | `DeliveryImportService.preview_delivery_import` | read only | no | none | medium | 0.12.15 |
| S/N already in stock | Preview marks existing warehouse S/N | upload preview | full read from `stock_receipts` | batched repository lookup | read `stock_receipts` | no | none | medium: avoid N+1 | 0.12.15 |
| Unknown columns | Preview warns about unmapped headers | upload preview | `unknown_csv_headers` | explicit mapping layer | none | no | none | medium | 0.12.15 |
| Ambiguous columns | Preview warns and does not silently choose | upload preview | not explicit | explicit mapping layer | none | no | none | medium | 0.12.15 |
| Edit lines | User bulk-fills line metadata | `POST /api/action`, `UPDATE_DELIVERY_LINES` | `update_delivery_lines` | optional `update_delivery_line_metadata` only for metadata | `delivery_lines`, `audit_log` | no | `DELIVERY_LINE_UPDATE` | medium: can affect acceptance data | 0.12.16 unless pure metadata needed |
| Acceptance scanner | User scans S/N into delivery | `POST /api/action`, `ACCEPT_DELIVERY_SERIAL` | `accept_delivery_serial` | not moved | `stock_receipts`, `delivery_lines`, refs, audit | yes | `DELIVERY_ACCEPT`, receipt event | high | 0.12.16 |
| Unplanned acceptance | User accepts S/N absent from document | same action with `unplanned` | `accept_delivery_serial(..., unplanned=True)` | not moved | `delivery_lines`, `stock_receipts`, audit | yes | `DELIVERY_ACCEPT` | high | 0.12.16 |
| Close delivery | User closes delivery | `POST /api/action`, `CLOSE_DELIVERY` | `close_delivery` | not moved | `deliveries`, audit | no direct balance | `DELIVERY_CLOSE` | medium | 0.12.16 |
| Export result | User exports delivery result CSV | `GET /export/delivery.csv?id=` | `delivery(id)` | `export_delivery_rows(id)` | read `delivery_lines` | no | none | low | 0.12.15 |
| Audit | Successful document upload is logged | confirm | `_audit("DELIVERY_UPLOAD")` | repository audit after commit input | `audit_log` | no | `DELIVERY_UPLOAD`, event type `DELIVERY_IMPORTED` | medium | 0.12.15 |
| Reports/events | Reports see loaded delivery separately from accepted receipt | internal `WarehouseEventReader` | reads `deliveries`, accepted lines via receipts | unchanged reader contract | read warehouse tables | no | `DELIVERY_IMPORTED` only for import | medium | 0.12.15 |

## Group A: Import and Delivery Document

Template download, CSV upload, column mapping, preview, duplicate matching, stock
matching, other-delivery matching, confirm document, list/card/lines/search/export,
and upload audit/event are part of Stage 0.12.15.

## Group B: Physical Warehouse Acceptance

Acceptance scanner, accepting planned or unplanned serials, creating receipts from
delivery lines, updating existing warehouse positions, closing deliveries, and any
balance-changing behavior stay in legacy code for Stage 0.12.16.
