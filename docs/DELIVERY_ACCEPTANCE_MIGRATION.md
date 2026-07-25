# Delivery Acceptance Migration Map

Stage 0.12.16 migrates physical delivery acceptance to `WarehouseFacade`.
Delivery close/admin correction remain compatibility flows.

| Scenario | UI flow | Endpoint/action | Legacy method | Target facade method | Tables | Transaction | Creates receipt | Updates existing receipt | Audit/event | Risk | Stage |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Inspect scanner S/N | Delivery card scanner, Enter before accept | `POST /api/action`, `INSPECT_DELIVERY_SERIAL` new action | none; frontend directly asked confirm | `inspect_delivery_serial(delivery_id, serial_number)` | read `deliveries`, `delivery_lines`, `stock_receipts` | read-only | no | no | none | medium: frontend must not guess allowed action | 0.12.16 |
| Planned new S/N accept | Scan S/N from document, confirm accept | `POST /api/action`, `ACCEPT_DELIVERY_SERIAL` | `accept_delivery_serial` | `accept_delivery_serial(delivery_id, serial_number, values=None)` | `deliveries`, `delivery_lines`, `stock_receipts`, `reference_values`, `audit_log` | one transaction: recheck delivery/line/SN, create receipt, update line/status, audit | yes | no | `DELIVERY_ACCEPT`, `DELIVERY_ACCEPTED`; receipt row also visible as receipt event | high: must use receipt contract and rollback atomically | 0.12.16 |
| Existing S/N inspect | Scan S/N already in stock | inspect action | legacy raises `Этот S/N уже есть на складе` | `inspect_delivery_serial` | read `stock_receipts`, `delivery_lines` | read-only | no | no | optional conflict info only | medium | 0.12.16 |
| Existing S/N fill-empty | User confirms filling empty warehouse fields | `ACCEPT_DELIVERY_SERIAL` with existing S/N | legacy blocks existing S/N | `accept_delivery_serial` | `stock_receipts`, `delivery_lines`, `deliveries`, `audit_log` | one transaction: recheck, fill empty allowed fields, link line, refresh status, audit | no | fills empty fields only | `DELIVERY_ACCEPT_EXISTING`, `DELIVERY_ACCEPTED` existing-link metadata; no `RECEIPT_CREATED` | high: avoid overwriting filled data | 0.12.16 |
| Conflict detection | Existing S/N has different filled values | inspect action and accept response | none | `get_delivery_conflicts`, `inspect_delivery_serial` | read only unless fill-empty accepted | read-only for inspect | no | no automatic overwrite | optional `DELIVERY_CONFLICT_FOUND` not required | medium | 0.12.16 |
| Already accepted S/N | Re-scan accepted line | `ACCEPT_DELIVERY_SERIAL` | legacy raises after line state check | `inspect_delivery_serial`, `accept_delivery_serial` | read only on failure | rollback/no write | no | no | none on failure | low | 0.12.16 |
| Unplanned inspect | Scan S/N absent from document | inspect action | legacy returns `{found:false}` | `inspect_delivery_serial` | read delivery/stock | read-only | no | no | none | medium | 0.12.16 |
| Unplanned accept | Explicit confirm and mandatory values | `ACCEPT_DELIVERY_SERIAL` with `unplanned:true` and values | `accept_delivery_serial(..., unplanned=True)` | `accept_unplanned_delivery_serial(delivery_id, serial_number, values)` | `delivery_lines`, `stock_receipts`, `deliveries`, refs, audit | one transaction: create line, create receipt, link, status, audit | yes | no | `DELIVERY_ACCEPT_UNPLANNED`, `DELIVERY_ACCEPTED`, receipt event from receipt row | high: cannot accept empty metadata | 0.12.16 |
| Batch accept | Select lines, apply common values, accept | `POST /api/action`, `ACCEPT_DELIVERY_BATCH` new action | none | `accept_delivery_batch(delivery_id, line_ids, common_values=None)` | same as planned/existing | one transaction for all selected lines | yes for new serials | fill-empty for existing | `DELIVERY_ACCEPT_BATCH` plus line-level details summary | high: rollback whole batch on strict error | 0.12.16 |
| Safe line edit | Select rows or editable cells before acceptance | `UPDATE_DELIVERY_LINES` | `update_delivery_lines` | `update_delivery_line_metadata` | `delivery_lines`, `audit_log` | transaction over selected rows | no | no | `DELIVERY_LINE_UPDATE` | medium: must keep accepted rows read-only | 0.12.16 |
| Refresh status | After accept/edit | internal | `_refresh_delivery_status` | `refresh_delivery_status(delivery_id)` | `deliveries`, `delivery_lines` | inside acceptance transaction or standalone | no | no | none | medium: rule for existing rows must be explicit | 0.12.16 |
| Acceptance summary | Delivery card progress | `GET /api/delivery` or new action | implicit counts in `deliveries` list | `get_delivery_acceptance_summary(delivery_id)` | read `delivery_lines` | read-only | no | no | none | low | 0.12.16 |
| Conflicts read | Delivery card conflict panel | new action | none | `get_delivery_conflicts(delivery_id)` | read `delivery_lines`, `stock_receipts` | read-only | no | no | none | low | 0.12.16 |
| Close delivery | Button in delivery card | `CLOSE_DELIVERY` | `close_delivery` | not migrated | `deliveries`, `audit_log` | legacy transaction | no | no | `DELIVERY_CLOSE` | medium | future/admin stage |
| Reports/events | Daily/weekly reports show accepted positions | internal `WarehouseEventReader` | reads `delivery_lines.receipt_id` joined to `stock_receipts` | unchanged event reader contract | read warehouse tables | read-only | no | no | `DELIVERY_ACCEPTED`; receipt row remains source fact | medium: avoid duplicate report rows | 0.12.16 |
| Balance/history | Accepted new S/N appears in balance/history | `/api/balance`, `/api/data` history | stock rows and audit history | existing facade readers | read stock/audit | read-only | no | no | receipt/audit rows | low | 0.12.16 |

## Status Rule

For Stage 0.12.16, rows with `state='Принято'` are accepted. Rows with
`state='Уже на складе'` and a linked `receipt_id` are treated as processed for
delivery-level status because the document row has been reconciled with an
existing warehouse position. Error and duplicate rows are not blocking physical
acceptance status; they remain problem rows for review.

Delivery status:

- zero processed rows -> `Ожидается`;
- some processed rows and some waiting rows -> `Частично принята`;
- no waiting rows and at least one processed row -> `Принята`;
- `Закрыта` is only an explicit close action and is not set by acceptance.
