# Manual Testing — Stage 0.13.3A

Дата: 2026-07-14.

## Scope

This acceptance verifies offline reference data, canonical naming, exact S/N
preservation, migration staging and a disposable candidate DB. It does **not**
import historical receipts/issues, run a production reset, change the runtime
UI/API or write to `data/warehouse.db`.

Run commands from the repository root. Keep ODE stopped during DB/sidecar
checks. Do not open/save raw XLSX files in Excel or an object-model library.

## 1. Baseline protection

```bash
pwd
git status --short
shasum -a 256 migration_inputs/raw/*
shasum -a 256 -c migration_inputs/raw/SHA256SUMS.local
shasum -a 256 data/warehouse.db
sqlite3 -readonly data/warehouse.db 'PRAGMA integrity_check;'
sqlite3 -readonly data/warehouse.db 'PRAGMA foreign_key_check;'
find data -maxdepth 1 \( -name 'warehouse.db-wal' -o -name 'warehouse.db-shm' -o -name 'warehouse.db-journal' \) -print
```

Save raw-file and working-DB SHA values for the final comparison. Expected raw
source hashes for this frozen input are:

| File | SHA-256 |
|---|---|
| `warehouse_accounting_source.xlsx` | `24173ab8b977698dbb225f7b14f08b30c15037c21f862c276e2d6e637caec462` |
| `dcim_lookup_source.xlsx` | `223b14f38d66ded9c1d8b44b6cde9933a936c8a2f95652d6457dea7645bf5198` |
| `serial_review_source.txt` | `f1312e5a30b47b1bcda0983ccb6c39a4be6b1b42607a246b7581e95f8329584f` |
| `SHA256SUMS.local` | `b52e4a56519fe044514c38a62ff980ff9110ce5a1c2969e7106c056027b00f69` |

The DB SHA is environment state and must be compared before/after, not copied
from documentation.

## 2. Focused automated contracts

```bash
python3 -W error::ResourceWarning -m unittest -v \
  tests.test_reference_data_foundation \
  tests.test_serial_preservation \
  tests.test_migration_candidate_db
python3 scripts/audit_module_boundaries.py
```

Expected focused result: 39 tests, `OK`.

Verify specifically:

- all 16 requested domains are unique and seeded as documented;
- NFKC/case/whitespace aliases can be `AUTO_APPROVED`;
- Huawei/xFusion, HP/HPE, Hunix/Hynix and different legal suppliers are not;
- model identity is vendor-scoped and Vegman R200/R220 remain distinct;
- unknown values remain candidates and do not enter production references;
- all required identifier round-trip fixtures remain exact;
- numeric identifiers use `Decimal`, not `float`;
- custom zero format returns `NUMERIC_FORMAT_RECOVERED` and manual review;
- more than 15 numeric significant digits return `SOURCE_CORRUPTED` with no
  match key;
- source/work DB immutability and security allowlists pass.

## 3. Inspect immutable sources

```bash
python3 scripts/migration_reference_data.py inspect-sources
```

Expected operational source ranges:

- `ПРИХОД!L3:L51005`;
- `РАСХОД!D2:D20358`;
- `РАСХОД!J2:J20358`.

The command must report the approved operational bounds and unchanged source
and working-DB hashes. Serial status counts are verified after candidate build
with the query in section 5. The expected 91,717 S/N-role cells are:

- `TEXT_EXACT = 72,889`;
- `NUMERIC_FORMAT_RECOVERED = 0`;
- `NUMERIC_FORMAT_UNPROVEN = 11,190`;
- `SOURCE_CORRUPTED = 4`;
- `EMPTY = 7,634`;
- `requires_manual_review = 11,538` (11,194 numeric cells and 344
  warning-bearing `TEXT_EXACT` cells).

Every non-empty numeric source cell must have an empty match key. In
particular, exponent notation remains the literal raw token in
`source_serial_value`; any expanded decimal is review display only.

The four corrupted cells must be exactly `ПРИХОД!L19513`,
`ПРИХОД!L19580`, `РАСХОД!J4826`, `РАСХОД!J4866`, each with an empty
normalized match value. The preformatted receipt blank tail and 200-row issue
formula tail outside the Excel table are not operation rows.

Re-run the manifest check immediately after inspection. Any hash change is a
release blocker.

## 4. Build the disposable candidate

Default outputs:

```text
migration_inputs/workspace/warehouse_migration_candidate.db
migration_inputs/workspace/reference_candidate_package.xlsx
migration_inputs/workspace/serial_preservation.csv
migration_inputs/workspace/candidate_validation.json
```

Build explicitly:

```bash
python3 scripts/migration_reference_data.py build-candidate --overwrite
```

`--overwrite` is required when any output already exists. Confirm that the
command rejects an output equal/hardlinked/symlinked to `data/warehouse.db` in
the automated test; do not perform that negative test against the real file
manually.

The build must use a temporary DB and publish only after integrity, FK, schema,
security and source/DB immutability checks. It must not start ODE.

## 5. Validate and report

```bash
python3 scripts/migration_reference_data.py validate-candidate
python3 scripts/migration_reference_data.py report
```

`report` must run the full source/output path and inode guard before writing.
It regenerates its allowlisted fields from the current candidate and source
checks; it must neither read nor merge an existing JSON report. Regression
tests verify that a stale file containing an injected `password_hash` and
absolute path is replaced without disclosure, and that a report path equal or
hardlinked to the source DB is rejected without changing the source bytes.

The validation must enforce one migration batch, text storage and corrupted-key
invariants; its secret-free JSON summary must show:

- `valid = true`;
- `integrity_check = ok` and zero foreign-key errors;
- no candidate WAL/journal/SHM;
- candidate file mode `600` on POSIX;
- all 16 active reference domains;
- at least one active administrator, without printing `password_hash`;
- zero rows in production operational tables;
- zero legacy production reference rows, staging decisions/target links and
  numeric S/N policy bypasses;
- all staged S/N fields stored as SQLite TEXT;
- four `SOURCE_CORRUPTED` serial cells and zero corrupted match keys;
- reference/alias/staging/source-file counts;
- no absolute source paths.

For the current source hashes, expected candidate counts are 71,360 staging
rows (`RECEIPT=51,003`, `ISSUE=20,357`), 91,717 serial cells, 893 reference
values, 916 aliases (`AUTO_APPROVED=517`, `PENDING=399`) and 358 catalog-item
proposals. The reference workbook sheets contain `DOMAINS=16`, `VALUES=893`,
`ALIASES=916`, `CATALOG_ITEMS=358`, `UNRESOLVED=973`.

Read-only spot checks:

```bash
sqlite3 -readonly migration_inputs/workspace/warehouse_migration_candidate.db 'PRAGMA integrity_check;'
sqlite3 -readonly migration_inputs/workspace/warehouse_migration_candidate.db 'PRAGMA foreign_key_check;'
stat -f '%Lp %N' migration_inputs/workspace/warehouse_migration_candidate.db
sqlite3 -readonly migration_inputs/workspace/warehouse_migration_candidate.db \
  "SELECT 'stock_receipts', COUNT(*) FROM stock_receipts UNION ALL SELECT 'stock_issues', COUNT(*) FROM stock_issues UNION ALL SELECT 'stock_issue_allocations', COUNT(*) FROM stock_issue_allocations UNION ALL SELECT 'migration_staging_rows', COUNT(*) FROM migration_staging_rows UNION ALL SELECT 'migration_serial_cells', COUNT(*) FROM migration_serial_cells;"
sqlite3 -readonly migration_inputs/workspace/warehouse_migration_candidate.db \
  "SELECT preservation_status, COUNT(*) FROM migration_serial_cells GROUP BY preservation_status ORDER BY preservation_status;"
sqlite3 -readonly migration_inputs/workspace/warehouse_migration_candidate.db \
  "SELECT requires_manual_review, COUNT(*) FROM migration_serial_cells GROUP BY requires_manual_review ORDER BY requires_manual_review;"
sqlite3 -readonly migration_inputs/workspace/warehouse_migration_candidate.db \
  "SELECT COUNT(*) FROM migration_serial_cells WHERE excel_cell_type='n' AND source_serial_value<>'' AND normalized_match_value<>'';"
sqlite3 -readonly migration_inputs/workspace/warehouse_migration_candidate.db \
  "SELECT resolution_status, COUNT(*) FROM reference_aliases_v2 GROUP BY resolution_status ORDER BY resolution_status;"
```

Do not query or print `users.password_hash` during manual acceptance.

## 6. Identifier output round-trip

The human review package is XLSX. Open it only for inspection; do not resave and
do not use it as an import file. Programmatically re-read it with the repository
reader and confirm identifier columns use OOXML `inlineStr` + `@`.

`serial_preservation.csv` is an exact UTF-8 machine export. CSV has no cell
types, so do not use desktop Excel opening behavior as a preservation proof.
Verify exact machine round-trip through the tested `read_text_csv` helper.

Required fixtures are `00012345`, `001A020`, `0000000000000001`,
`2102313CKX10LC000033`, Cyrillic, mixed-script, custom zero format, scientific
notation, more than 15 digits and internal spaces.

## 7. Full project gate

```bash
python3 -m py_compile app.py inventory/**/*.py scripts/*.py tests/*.py
for file in static/js/**/*.js tests/headless_smoke.js; do
  node --check "$file" || exit 1
done
python3 scripts/audit_module_boundaries.py
python3 scripts/audit_frontend_contracts.py
python3 -W error::ResourceWarning -m unittest discover -s tests -v
python3 scripts/create_clean_test_db.py --dry-run
python3 scripts/smoke_ui.py
git diff --check
```

The smoke is a regression gate because Stage 0.13.3A adds no runtime UI/API.
The accepted run visited all routes, including the Inventory Number workflow,
and reported `noConsoleErrors`, `noWindowErrors`, `noUnhandledRejections`,
`noResourceErrors`, `noHttpErrors` and `noApi500` as `true`.

Expected result: `Ran 266 tests`, `OK` under
`-W error::ResourceWarning`. The pre-Stage baseline was 227.

## 8. Final immutability and Git checks

Repeat all commands from section 1. Raw and working-DB hashes must match their
baseline byte-for-byte; DB integrity is `ok`, FK output empty and no working DB
sidecar exists.

```bash
git status --short
git diff --check
git diff --name-status
git diff --cached --name-status
git ls-files migration_inputs/raw migration_inputs/normalized migration_inputs/reports migration_inputs/workspace
```

Confirm:

- raw XLSX/TXT, analytical/generated artifacts, candidate DB and sidecars are
  not staged/tracked;
- `data/warehouse.db` and `CHECKPOINT_ODE.md` are not staged;
- no test DB, backup, ZIP, cache, `__pycache__`, absolute path or secret enters
  the diff;
- code/tests/current docs use the same module, CLI, table, status and count
  names;
- no commit, push, ZIP or working-DB replacement is performed as part of this
  Stage handoff.

## Acceptance result

Stage 0.13.3A is accepted only as a review-ready migration foundation. Readiness
for Stage 0.13.3B means the tooling can produce and validate an isolated
candidate while preserving all source/working bytes. It does not authorize
historical import or production replacement.
