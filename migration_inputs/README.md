# Migration inputs and disposable workspace

`migration_inputs/` is a local migration circuit, not a production import
directory.

- `raw/` contains immutable source Excel/TXT files and the local SHA-256
  manifest. Never save or rewrite those files.
- `normalized/` and `reports/` contain the analytical pre-0.13.3 source review
  artifacts. They are evidence and preview data, not approved import files.
- `workspace/` contains disposable Stage 0.13.3A outputs, including
  `warehouse_migration_candidate.db`, `reference_candidate_package.xlsx`,
  `serial_preservation.csv` and `candidate_validation.json`. Stage 0.13.3A.5
  additionally creates `warehouse_pilot_candidate.db`; the corresponding
  `PILOT_RECEIPT_SELECTION.xlsx`/`.md` stay under ignored `reports/`. The full
  historical build creates a third, non-overwriting artifact
  `warehouse_full_candidate.db` plus `FULL_WAREHOUSE_MIGRATION_REPORT.*` and
  `FULL_WAREHOUSE_OPERATIONAL_CLEANLINESS.*`.

All four data directories are ignored by Git. This README is the only tracked
file in `migration_inputs/`. The candidate database may contain copied user
security rows (including password hashes) and must not be published or
committed; the builder applies mode `0600` on POSIX. Historical
receipts/issues are staged only as source evidence and are not written to
production operation tables or `data/warehouse.db` by Stage 0.13.3A.

The 0.13.3A.5 pilot contains only 130 selected historical receipt cards from a
deterministic 200-row review sample. It is **PILOT ONLY / NOT PRODUCTION**:
issues, `БАЛАНС` and the remaining receipt rows are not imported. Build and
validate it with `scripts/migration_pilot.py`; open it only through the
marker-guarded migration-pilot launcher. Stop ODE and confirm there are no
SQLite sidecars before removing pilot DB/reports. Never delete `raw/`, the
Stage A candidate or `data/warehouse.db` as part of pilot cleanup.

The full candidate processes all 51,003 receipt and 20,357 issue staging rows
from an operationally empty Stage A candidate. It retains only schema,
security/system/reference/staging data before import; no operational row from
`data/warehouse.db` is copied. Build/validate with
`scripts/migration_full_candidate.py`, and review only through the
`start_full_migration_candidate_*` launcher. The build is disposable and
generated: fix a source/rule and rebuild with explicit `--overwrite`; never use
manual SQLite edits as migration input. See
[`docs/FULL_WAREHOUSE_MIGRATION.md`](../docs/FULL_WAREHOUSE_MIGRATION.md).
