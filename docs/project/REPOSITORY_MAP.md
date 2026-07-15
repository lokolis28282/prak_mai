# Repository Map

## Authoritative repository

`~/Documents/prak_mai` — единственная рабочая копия.

`~/Documents/ODE v0.1/prak_mai-main` — не authoritative; возможный источник
изменений коллеги по Monitoring. Только read-only inventory/hash/diff и
утверждённый integration plan.

## Runtime Warehouse

- `app.py` — entry point.
- `inventory/webapp.py` — HTTP/API/HTML composition.
- `static/` — реально загружаемые CSS/JS.
- `inventory/core/` — ApplicationContext и общие contracts.
- `inventory/warehouse/` — Warehouse domain/services/repositories.
- `inventory/administration/` — users/audit/backup/diagnostics.
- `inventory/reports/` — отдельный Reports context.
- `inventory/monitoring/` — placeholder.
- `inventory/shared/` — SQLite/CSV/validation adapters.
- `inventory/db.py` — действующая legacy-compatible schema initialization.
- `data/README.md` — clone/setup policy для installation-owned runtime data.
- `data/warehouse.db` — единственная локальная рабочая DB; ignored и никогда
  не является содержимым Git, clone или code release.

`data/` после clone содержит только документацию. Новая установка явно выбирает
и создаёт собственный DB path. `.gitignore` — canonical repository policy;
`.git/info/exclude` не переносится между clone и используется только как
локальная дополнительная защита. Backup хранится вне repository.

## Target ODE platform

- `ode/` — side-by-side platform foundation.
- `docs/decisions/` — approved ADR.
- `docs/architecture/ddl/` — approved target DDL and immutable review evidence.
- `tests/ode013/` — focused platform tests.

Target DDL не применяется к `data/warehouse.db`.

## Migration artifacts

- `inventory/migration/` и `scripts/migration_*` — offline tooling.
- `migration_inputs/raw/` — immutable sources.
- `migration_inputs/normalized/`, `reports/`, `workspace/` — generated/review
  artifacts, не runtime и не commit content.
- `.stabilization/` — local evidence; не production source of truth.

## Tests and releases

- `tests/` — unit/contract/API/browser contracts.
- `scripts/create_clean_test_db.py` — disposable Warehouse DB builder.
- `scripts/smoke_ui.py` — browser smoke на временной копии.
- `release/` — generated artifacts, не source; ZIP не коммитятся. Code release
  не должен содержать локальную runtime DB. До исправления package builder
  создание нового release заблокировано.
