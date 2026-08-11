# Repository Map — ODE 0.21.0

Authoritative checkout: `/Users/lokolis/Documents/prak_mai`. Другие копии не
являются источником истины и используются только read-only после явного
сравнения.

## Runtime code

- `app.py` — обычный entry point для трёх runtime-БД;
- `inventory/webapp.py` — HTTP/session/security shell и dispatch;
- `inventory/routes/` — domain HTTP handlers без business SQL;
- `inventory/templates/` — сборка итогового HTML;
- `static/css`, `static/js` — реально загружаемый frontend;
- `inventory/core/` — `ApplicationContext`, routing и contracts;
- `inventory/warehouse/` — Warehouse facade/services, включая
  `equipment_composition.py`;
- `inventory/reports/`, `monitoring/`, `knowledge/`, `vacations/`,
  `administration/` — отдельные bounded contexts с публичными facade;
- `inventory/shared/` — общие SQLite/CSV/validation adapters;
- `inventory/db.py` — legacy-compatible schema bootstrap/migrations.

## Installation-owned runtime data

- `data/warehouse.db` — IXcellerate плюс primary Administration/Reports/
  Monitoring/Knowledge contour;
- `data/warehouse_solar.db` — физически отдельный Solar Warehouse;
- `data/vacations.db` — отдельный общий календарь двух площадок;
- `data/README.md` — clone/setup/data separation policy.

Все DB ignored. В Git после clone находится только документация. Backup
создаётся во внешнем системном каталоге или `ODE_BACKUP_DIR`; restore UI
отключён.

## Offline migration и target track

- `inventory/migration/`, `scripts/migration_*` — offline tooling, не runtime;
- `migration_inputs/raw` — immutable source; `normalized/reports/workspace` —
  generated ignored review artifacts;
- `inventory/warehouse/baseline/`, `baseline_rehearsal/` — FULL Inventory
  Preview/resolution и disposable candidate rehearsal;
- `ode/`, `docs/architecture/ddl`, `tests/ode013` — side-by-side target Platform
  track; DDL не применяется напрямую к runtime Warehouse DB.

## Проверки и артефакты

- `tests/` — unit, architecture, API, contracts и headless сценарий;
- `scripts/audit_*.py` — boundaries, frontend controls, documentation и data
  separation;
- `scripts/create_clean_test_db.py` и
  `scripts/create_clean_vacations_test_db.py` — disposable test contour;
- `scripts/smoke_ui.py`, `tests/headless_smoke.js` — Chrome E2E;
- `scripts/generate_code_graph.py` — committed deterministic graph;
- `scripts/refresh_project_knowledge.py` — graph + non-persistent external
  index after topology changes;
- `release/`, exports, screenshots, backups and candidate/test DB — generated,
  ignored и никогда не commit content.
