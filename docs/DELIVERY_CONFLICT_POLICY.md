# Delivery Conflict Policy

When a delivery S/N already exists in `stock_receipts`, Stage 0.12.16 allows
only fill-empty updates.

Allowed empty fields:

- `inventory_number`
- `supplier`
- `vendor`
- `model`
- `project`
- `datacenter`
- `shelf`
- `order_number`
- `request_number`
- `plu`
- `item_name`

Filled fields are not overwritten automatically. If a filled field differs from
the delivery document, inspect returns it in `conflicting_fields` with current
and incoming values. Accept links the delivery line and fills empty fields only;
destructive override is a future explicit admin-correction stage.

Never auto-update historical `receipt_date` or `responsible`.
