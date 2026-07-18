# ODE 0.14 — Integration and Presentation Readiness

Дата: 2026-07-18. Статус: **PRESENTATION CANDIDATE PASS**.

## Scope

Интеграционный кандидат объединяет безопасный Warehouse 0.14, ручной
Monitoring flow, Knowledge Base и Reports/УВР в одном `ApplicationContext`.
Изменения коллег перенесены отдельными commits, конфликты разрешены без прямой
связи Monitoring/Reports с Warehouse writes.

## Warehouse verdict

- 50 000 карточек и historical movements доступны для поиска и Timeline, но
  не считаются фактическим остатком.
- Production status до физической инвентаризации — `NOT_INITIALIZED`,
  `authoritative=false`, `baseline_timestamp=null`.
- Production receipt/issue/scanner/transfer posting блокируется server-side.
- Disposable demo contour поддерживает полный scanner E2E без риска рабочей БД.
- FULL Inventory поддерживает strict XLSX, Preview, findings, resolutions,
  revalidation и target-schema candidate rehearsal.
- Реальный approval/atomic cutover намеренно отсутствует. Candidate нельзя
  выдавать за рабочий baseline; следующий controlled change требует остановки
  writers, backup, Equipment/catalog decisions и отдельной приёмки.

## Integrated modules

- Monitoring: validated hostname/problem, optional DCIM collection, local
  hostname routing, message preview and browser-local history. Auto-send off.
- Knowledge: role-checked articles/tags/search/safe Markdown/private
  attachments. Owns only `knowledge_*` tables and attachment path.
- Reports: УВР CRUD/filter/import/export, shift/week views. Warehouse facts are
  read only through `WarehouseEventReader`.

Existing promoted databases require the explicit backup-guarded
`scripts/migrate_runtime_modules.py`; ordinary startup does not mutate schema.

## Security and repository data

- `data/warehouse.db`, Monitoring JSON rules, browser profiles, cookies,
  Knowledge attachments, candidate DB and release archives are ignored.
- No internal hostname/recipient JSON is tracked.
- Runtime module migration creates external byte-copy + SQLite backup and a
  manifest before applying additive schema.

## Verification evidence

- full Python suite: 503 tests PASS, 8 expected skips for absent ignored
  migration artifacts, `ResourceWarning` treated as error;
- Python/JavaScript syntax: PASS;
- module/frontend audits: PASS (`153` HTML ids, `444` static references);
- clean-test DB dry-run: PASS; production source byte-identical during check;
- headless Chrome E2E: PASS on disposable copy, all declared modules and
  Warehouse scanner flows visited, console/window/resource/HTTP/API500 = 0;
- manual in-app browser walkthrough: PASS for Home, historical Warehouse
  overview, FULL session creation, Reports navigation, Monitoring manual form
  and Knowledge landing; browser error/warning log empty;
- `git diff --check` and local Markdown link audit: PASS;
- Codebase Memory was rebuilt with `persistence=false`: 6 184 nodes,
  26 241 edges, 470 files and 26 detected HTTP routes.

The additive runtime module migration was applied after stopping writers:

- before SHA-256: `73568a1c3eecbd4476473f064620d7f0a196b336ce8ea6d834c5b99359d4b010`;
- after SHA-256: `a1da7dc52813fecabee8ec192e8d7d627b2b41071e993a28b8ca4c4d5ae7949c`;
- external rollback directory:
  `~/Documents/ODE_BACKUPS/runtime-modules-20260718T-integration/`;
- before/after integrity `ok`, FK violations `0`, sidecars none;
- Warehouse row counts unchanged: receipts `50 000`, issues `18 798`,
  allocations `18 798`; new work logs/articles start at `0`.

## Release boundary

Source candidate готовится для презентации и дальнейшей операторской оценки.
Новый Windows artifact этой работой не собирается. Серверный multi-user
deployment, automatic email/Rooms delivery и real initial-baseline cutover не
заявляются готовыми.
