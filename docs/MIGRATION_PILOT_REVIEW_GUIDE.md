# Migration Pilot Review Guide — Stage 0.13.3A.5

Дата: 2026-07-14.

## What this review is

**PILOT ONLY / NOT PRODUCTION.** This guide reviews a deterministic 200-row
sample in the disposable `warehouse_pilot_candidate.db`. It does not run the
51,003-row historical receipt migration, does not import issues or `БАЛАНС`,
and never replaces `data/warehouse.db`.

The authoritative architecture and decision semantics are in
[MIGRATION_PILOT_ARCHITECTURE.md](MIGRATION_PILOT_ARCHITECTURE.md).

## Artifacts

Expected local, ignored artifacts:

```text
migration_inputs/reports/PILOT_RECEIPT_SELECTION.xlsx
migration_inputs/reports/PILOT_RECEIPT_SELECTION.md
migration_inputs/workspace/warehouse_pilot_candidate.db
```

The XLSX is a text-safe detailed review table. The Markdown file contains the
non-secret summary, selection rule, counts and unavailable source requirements.
The DB is sensitive because it carries a security allowlist and source
provenance; on POSIX it must have mode `0600`.

Raw XLSX/TXT, Stage 0.13.3A candidate DB and `data/warehouse.db` are inputs, not
pilot outputs. Record their hashes before and after review.

## Build and validate

Use the dedicated migration-pilot CLI documented by its `--help`; never pass
`data/warehouse.db` as output. The safe workflow is:

```bash
python3 scripts/migration_pilot.py --help
python3 scripts/migration_pilot.py select
python3 scripts/migration_pilot.py build
python3 scripts/migration_pilot.py validate
```

An existing pilot DB is not overwritten implicitly. Rebuild requires the CLI's
explicit overwrite option and must be performed only while the review server is
stopped and no `-wal`, `-shm` or `-journal` file exists.

Before trusting the output, verify:

```bash
sqlite3 -readonly migration_inputs/workspace/warehouse_pilot_candidate.db \
  'PRAGMA integrity_check; PRAGMA foreign_key_check;'
```

Expected: `integrity_check` prints `ok`; `foreign_key_check` prints nothing.
The marker must report stage `0.13.3A.5`, status `READY_FOR_REVIEW`, exactly
200 selected rows and `pilot_only=1` / `review_read_only=1`.

## Read the selection report first

Confirm the fixed decision distribution:

| Decision | Expected |
|---|---:|
| `IMPORT` | 130 |
| `QUARANTINE` | 10 |
| `MANUAL_REVIEW` | 7 |
| `EXACT_DUPLICATE` | 6 |
| `CONFLICT_HISTORY_ONLY` | 35 |
| `QUANTITY_POSITION_DEFERRED` | 10 |
| `SOURCE_CORRUPTED_REJECTED` | 2 |

Check that every row has source sheet/row, preservation evidence, selection
reason, decision, warnings and structured naming fields. Identifier columns
must reopen as text. The report must explicitly state that Vegman R200 is
unavailable in the real source; absence is not repaired with a synthetic row.

The report must also explain why exact duplicates are only six: only those
literal raw-equivalent groups have a primary with both a proven date and safe
reference/alias resolution. The seventh candidate has a pending supplier alias.
The remaining duplicate coverage is 26 identity conflicts and 9
date/shelf/order history variations; these must not be relabeled
`EXACT_DUPLICATE`.

## Start review mode

macOS:

```bash
./start_migration_pilot_macos.command
```

Windows:

```bat
start_migration_pilot_windows.bat
```

The launcher must show `МИГРАЦИОННЫЙ ПИЛОТ` and the actual DB path in its
console. The browser banner must say the same but must not expose an absolute
local path. If the marker, filename, integrity, foreign keys or sidecar gate
fails, stop; do not bypass the guard with the ordinary launcher.

After this guard ODE skips its normal schema initializer for the pilot DB.
Stopping an otherwise read-only review must leave the DB SHA unchanged; a
changed SHA is a failed review gate.

## Browser review

Log in as `admin` or `engineer`. The pilot opens a read-only selection screen
with filters:

- `IMPORT`;
- `QUARANTINE` (includes manual review);
- `CONFLICT` (exact duplicates and conflict history);
- `CORRUPTED`.

Search accepts exact displayed S/N, source/canonical item text, vendor/model or
logical source row. `IMPORT` rows and linked `EXACT_DUPLICATE` /
`CONFLICT_HISTORY_ONLY` rows have an Equipment Card button and open the same
single primary card; quarantine/manual/corrupted/quantity rows do not.

For every reviewed card compare:

1. table S/N, card S/N and `source_serial_value` code-point-for-code-point;
2. source item name and independently generated canonical name;
3. object kind, category/type, vendor, model and Part Number;
4. optional shelf and every alternate shelf in provenance/history;
5. preservation status and warnings;
6. source filename/sheet/row and historical source date;
7. Timeline label `Исторический приход (миграция)` and migration audit facts.

Do not infer correctness from `normalized_match_value`; it is not the stored
identifier.

## Mandatory manual sample

Review at least:

- all selected leading-zero S/N, including report examples such as
  `02122509D1`, `0212250945`, `0212250937`, `02122508ED`, `0212250920`,
  `0206260609`, `02122505F7` and `035DNGLDR8003286` when present in the
  generated selection;
- long text S/N and values with mixed case, Cyrillic, internal spaces or
  hyphens;
- Dell server rows;
- Vegman R220 rows and the R220 vendor/model conflict provenance;
- Huawei and xFusion rows as separate vendors;
- all 6 exact-duplicate rows and all 35 conflict-history rows;
- a repeated S/N with different shelves;
- all 10 numeric quarantines and both receipt-side corrupted rows;
- all quantity-deferred and unknown-reference rows.

For leading-zero identifiers, copy the visible value into a code-point-aware
text comparison; never open/save the source workbook to "check" it.

## Approval record

Manual approval should record:

- reviewer and date outside the source files;
- selection SHA and pilot DB SHA;
- accepted/rejected canonical-name examples;
- every numeric/corrupted decision and the independent evidence, if any;
- reference aliases approved or still pending;
- accepted duplicate/conflict policy;
- unresolved case-distinct S/N/schema concern;
- explicit statement that approval is for proceeding to Stage 0.13.3B design,
  not for production installation.

## Stop and remove disposable artifacts

Stop the local server with `Ctrl+C`. Confirm no pilot DB process is running and
no SQLite sidecar exists. Pilot artifacts may then be deleted from
`migration_inputs/reports/` and `migration_inputs/workspace/`; do not delete or
modify `migration_inputs/raw/`, the Stage 0.13.3A candidate or
`data/warehouse.db`.

If review is rejected, retain the hashes/decision notes and regenerate from
immutable inputs after a separately reviewed code/rule change. Never edit pilot
rows directly in SQLite or Excel.

## FUTURE 0.13.3B

Stage 0.13.3B remains blocked until the review owner accepts the preservation,
identity, reference, naming, Timeline and quarantine behavior and an explicit
production reset/import plan is approved. Historical issues and balance
reconciliation are not automatically authorized by receipt-pilot approval.
