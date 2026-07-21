# Stage 0.12.16A - Delivery Acceptance E2E

Date: 2026-07-11
Commit: 739faf7
Decision: Passed

## Test Contour

- Working DB: `data/warehouse.db`
- Working DB SHA-256 before: `5eb98ea10824d92bc1ddbcbee2cdde92b630b7c9cc1c324af6ea40d5a66396f1`
- Working DB SHA-256 after browser E2E: `5eb98ea10824d92bc1ddbcbee2cdde92b630b7c9cc1c324af6ea40d5a66396f1`
- Browser E2E temp DB: `/var/folders/69/0blt65cn5v11xdxs75zyvcs40000gn/T/ode_delivery_acceptance_final_ub878z9a/warehouse_acceptance_e2e.db`
- Stress temp DB: `/var/folders/69/0blt65cn5v11xdxs75zyvcs40000gn/T/ode_delivery_stress_s1ekfqb5/warehouse_stress.db`
- API negative audit temp DB: `/var/folders/69/0blt65cn5v11xdxs75zyvcs40000gn/T/ode_delivery_api_audit_pq8_dy0b/warehouse_api_audit.db`

All mutation checks used temporary SQLite databases. The working DB hash was unchanged.

## Browser Scenario

Real headless Chrome covered:

- Home -> Warehouse -> Deliveries.
- Delivery CSV preview with canonical headers plus legacy alias `Request`.
- Unknown column display.
- Confirm delivery document.
- Delivery card open.
- Scanner inspect and accept for a new server S/N.
- Scanner inspect and accept for a new RAM component S/N.
- Existing S/N fill-empty handling.
- Existing S/N conflict display without destructive overwrite.
- Unplanned S/N skip, then explicit unplanned accept with mandatory values.
- Multi-S/N cell expansion and acceptance.
- Duplicate S/N in file.
- Balance search and position card.
- Daily and weekly reports.
- Batch delivery import and batch accept of 10 selected rows.

Browser error budget:

- `console.error`: 0
- `window.onerror` / runtime exceptions: 0
- `unhandledrejection`: 0
- resource errors: 0
- API 500: 0

## Expected vs Actual

Preview did not mutate persistent tables:

- `deliveries`: +0
- `delivery_lines`: +0
- `stock_receipts`: +0
- `stock_issues`: +0
- `allocations`: +0
- `DELIVERY_UPLOAD` audit: +0

Final main delivery summary:

- status: `Принята`
- total lines: 10
- accepted: 6
- existing: 2
- errors: 2
- waiting: 0
- processed: 8

Final E2E DB checks:

- `stock_issues`: 0
- `allocations`: 0
- duplicate receipt serials: 0
- bad delivery receipt links: 0
- error rows with receipt: 0
- `PRAGMA integrity_check`: `ok`
- `PRAGMA foreign_key_check`: empty

## API Audit

Direct API audit checked valid inspect, planned accept, repeat accept, unknown S/N, invalid delivery, invalid line batch, malformed JSON, empty body, oversized body, viewer denial, summary and conflicts.

Statuses:

- expected successful calls: 200
- expected denials/validation failures: 400
- HTTP 500 count: 0
- `PRAGMA integrity_check`: `ok`
- `PRAGMA foreign_key_check`: empty

## Stress

Stress used a separate temporary DB.

- preview 1000 rows: 0.008 sec
- confirm 1000 rows: 0.038 sec
- inspect 1000 S/N: 0.508 sec
- batch accept 1000 new S/N: 0.897 sec
- repeat accept attempts: 20/20 rejected in 0.011 sec
- existing-link 1000 S/N: 0.340 sec
- conflict detection 1000 S/N: 0.258 sec
- balance read: 0.011 sec, 2000 rows
- weekly report: 0.081 sec
- DB size: 2,969,600 bytes
- final counts: 3 deliveries, 3000 delivery_lines, 2000 stock_receipts, 0 stock_issues
- duplicate receipts: 0
- `PRAGMA integrity_check`: `ok`
- `PRAGMA foreign_key_check`: empty

## Bugs Found

Two frontend bugs were found during E2E and fixed before the final passing run. See `BUGS_DELIVERIES_0_12_16.md`.

Non-product runner issues were also corrected during acceptance:

- CDP file upload did not trigger the browser `change` handler, so the runner now calls the same UI handler with a browser `File`.
- The initial multi-S/N test row reused one inventory number for two S/N. The final scenario leaves inventory blank for that row, matching the unique inventory constraint.

## Result

Passed. Delivery document import, scanner acceptance, planned acceptance, existing-S/N fill-empty, conflict blocking, unplanned acceptance, batch acceptance, balance, history/report paths, audit/event effects and database consistency were verified on temporary databases. Close delivery and destructive override remain outside this stage.

## Final Regression Checks

- `python3 -m py_compile app.py inventory/**/*.py scripts/*.py tests/*.py`: passed
- `node --check static/js/**/*.js tests/headless_smoke.js`: passed
- `python3 scripts/audit_module_boundaries.py`: passed
- `python3 scripts/audit_frontend_contracts.py`: passed
- `python3 scripts/smoke_ui.py`: passed, no console/window/unhandled/resource/API500 errors
- `python3 -W error::ResourceWarning -m unittest discover -s tests -v`: 158 tests passed
- `sqlite3 data/warehouse.db "PRAGMA integrity_check;"`: `ok`
- `sqlite3 data/warehouse.db "PRAGMA foreign_key_check;"`: empty
- Final working DB SHA-256: `5eb98ea10824d92bc1ddbcbee2cdde92b630b7c9cc1c324af6ea40d5a66396f1`
