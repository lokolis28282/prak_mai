# Bugs - Stage 0.12.16A Delivery Acceptance

## BUG-DEL-16A-001

Severity: Medium

Area: frontend

Files:

- `static/js/ui.js`
- `inventory/webapp.py`

Steps:

1. Open Warehouse -> Deliveries in the browser.
2. Upload a delivery CSV with unknown columns, existing S/N, duplicate S/N, empty S/N and warnings.
3. Inspect the preview block.

Expected:

The preview shows source rows, parsed S/N count, new S/N, existing S/N, duplicates, rows without S/N, errors, warnings and unknown columns.

Actual:

The static frontend handler still rendered the older reduced preview counters, so important Stage 0.12.15/0.12.16 summary fields were not visible in the real UI.

Fix:

Synchronized delivery preview rendering with the facade response summary and kept unknown columns visible before confirm.

## BUG-DEL-16A-002

Severity: High

Area: frontend

Files:

- `static/js/ui.js`
- `inventory/webapp.py`

Steps:

1. Open a confirmed delivery card.
2. Scan planned, existing and unplanned S/N.
3. Try batch accept selected rows.

Expected:

Scanner runs inspect before accept, shows a result card, supports `accept_new`, `fill_empty_existing`, explicit unplanned acceptance and selected-row batch acceptance. Accepted rows are read-only in the table.

Actual:

The static UI still contained the older delivery scanner/card logic. The acceptance UX did not consistently use inspect-first decisions and the batch accept control was missing from the real browser path.

Fix:

Updated the static delivery card/scanner implementation to use facade-backed inspect/accept actions, added `deliveryScanResult`, selected-row batch accept and read-only accepted rows.

## Notes

No large architecture changes were made during 0.12.16A. The fixes were limited to making the existing Stage 0.12.16 backend acceptance contract reachable through the real browser UI.
