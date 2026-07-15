# Stage 0.13.1 — response to independent review

Статус: **FINAL TARGETED REVIEW REQUIRED — NF-1/NF-2 CORRECTED**

Дата: 2026-07-15. Source evidence:
`STAGE_0_13_1_INDEPENDENT_REVIEW.md` с SHA-256
`7a1b48739bea1db3d263539aa9976cc2a941b6bee314aa82c6f5ec9079a8cad8`.
Review artifact не изменялся. Stage 0.13.2 не начинался.

## Baseline

- HEAD и `origin/main`:
  `76afadd5355f4d379b19dcabf1f28850986d5300`.
- Worktree до correction уже содержал большой pre-existing dirty scope;
  `ode/`, `tests/ode013/` и Stage 0.13.1 docs были untracked.
- `data/warehouse.db`: 579461120 bytes, mtime epoch `1784105153`, SHA-256
  `73568a1c3eecbd4476473f064620d7f0a196b336ce8ea6d834c5b99359d4b010`;
  immutable `integrity_check=ok`, `foreign_key_check=0`, exact WAL/SHM/journal
  отсутствовали.
- Все repro выполнялись в `TemporaryDirectory`; production DB открывалась
  только `mode=ro&immutable=1` для baseline/final checks.

## Findings triage

| ID | Severity | Review location | Claude repro | Independent correction repro | Verdict | Root cause | Minimal response | Regression | Blocks 0.13.2 | Blocks deployment |
|---|---|---|---|---|---|---|---|---|---|---|
| F1 | MEDIUM | `ode/infrastructure/database.py:218-221` before correction | Deferred V005 FK fails at `COMMIT` as raw `sqlite3.IntegrityError` | Real `inventory_snapshots.superseded_by_snapshot_id=999`: raw error, 0 rows; immediate FK/CHECK/UNIQUE were already typed. Simulated BEGIN+close left state; commit did not attempt rollback; rollback/close could hide the original error | **CONFIRMED** | `__exit__` called raw commit/rollback and cleanup had no error precedence/taxonomy | Typed begin/commit/rollback/close errors; rollback after failed commit while transaction active; unconditional close/state cleanup; original cause retained | Real V005 deferred FK plus immediate constraints, programmer exception and simultaneous begin/commit/rollback/close failures | Yes before fix; closed by correction | Yes before fix; closed by correction |
| F2 | MEDIUM | `ode/infrastructure/migrations.py:212-213` before correction | Dangling source and denied parent creation leaked raw I/O exceptions | Dangling V001 symlink gave `FileNotFoundError`; parent-as-file gave `FileExistsError`; chmod `000` parent gave `PermissionError` | **CONFIRMED** | Source reads and pre-candidate parent `mkdir` were outside typed I/O translation | `MIGRATION_SOURCE_READ_FAILED` for source enumeration/read; `DATABASE_CREATE_FAILED` for parent preparation, preserving cause and no target/candidate | Dangling source and deterministic parent creation failure | Recommended before fix; closed by correction | Yes before fix; closed by correction |
| F3 | MEDIUM | `ode/infrastructure/diagnostics.py:52,171` before correction | Immutable connection ignored committed uncheckpointed WAL row and returned no warning | WAL-aware read=1, immutable/diagnostics=0; reproduced with active WAL+SHM, actual WAL-only, subprocess crash-stale sidecars and zero-byte sidecars. Repeated reads left main/WAL/SHM byte state unchanged | **CONFIRMED** | Sidecar booleans were computed only after immutable reads and never guarded authority | Exact WAL/SHM/journal presence fail-closes status/verify/health with `IMMUTABLE_SNAPSHOT_UNSAFE`; pre/post guard, no fallback/checkpoint/delete | Real WAL row, WAL-only, crash-stale, zero-byte, unrelated filenames, repeat and file-state checks | Yes before fix; closed by correction | Yes before fix; closed by correction |
| F4 | LOW-MEDIUM | `ode/cli.py:58-67` before correction | Crafted path emitted raw ANSI ESC in human stdout | Raw ESC, LF, CR, BEL, C1 NEL and bidi override reproduced; JSON had no raw ESC and parsed | **CONFIRMED** | Human scalar values used direct interpolation | Central terminal display encoder for C0/C1/bidi; nested human payloads sanitized; JSON untouched | Subprocess human/JSON cases and normal Cyrillic/CJK path | No | Recommended before fix; closed by correction |
| F5 | LOW | `ode/infrastructure/database.py:176-190` before correction | `uow.execute("COMMIT")` persisted despite UoW bookkeeping expecting rollback | Row persisted after manual COMMIT | **CONFIRMED** | Repository SQL could issue transaction-control statements | Reject top-level transaction-control keyword, including after leading comments | Partial write plus comment-prefixed COMMIT rejection | No | No |
| F6 | LOW | `ode/infrastructure/database.py:176-190` before correction | Runtime UoW accepted `CREATE TABLE` | Table was committed on approved-schema temp DB | **CONFIRMED** | Runtime UoW did not separate DDL from domain DML | Reject top-level CREATE/ALTER/DROP/REINDEX/VACUUM; migrations remain sole DDL owner | Comment-prefixed CREATE rejection and schema absence | No | No |
| F7 | LOW informational | `ode/infrastructure/paths.py:37-101` | NFC/NFD visually equivalent filename resolved as two Paths | Reproduced on macOS; no alias of ASCII production/source protected roots and no path-policy bypass | **PARTIALLY_CONFIRMED** | Filesystem path identity is preserved; no Unicode normalization contract exists | No code change. Documented as accepted cross-platform limitation pending path ADR | Test locks current distinct path identity | No | No for current ASCII roots; future review required for non-ASCII protected roots |

No finding was `NOT_REPRODUCED` or `REJECTED`. F7's observation is real, but
its implied security impact was not reproduced in the current ASCII-root policy.

## Corrected contracts

### SQL policy (NF-1/NF-2)

До correction runtime UoW принимал `ATTACH`/`DETACH` и позволял включить
`PRAGMA writable_schema`, после чего системная schema могла быть изменена.
Оба finding подтверждены на disposable DB. Теперь runtime execute использует
conservative allowlist только application DML (`SELECT`/`INSERT`/`UPDATE`/
`DELETE`/`WITH`), отвергает multiple statements, любые пользовательские
`PRAGMA`, `ATTACH`/`DETACH`, DDL и записи в SQLite system schema. Authorizer
дополнительно запрещает соответствующие SQLite actions и TEMP schema objects;
его lifecycle ограничен connection UoW без mutable bypass. Запрещённый SQL
даёт `UnitOfWorkError(code="SQL_OPERATION_FORBIDDEN")`, transaction откатывается
и handle закрывается обычным UoW cleanup. MigrationRunner сохраняет отдельный
privileged connection и approved DDL не изменён. Positive DML, CTE, comments,
parameters и literals с опасными словами проходят без false positives.

### Unit of Work

`UnitOfWorkBeginError`, `UnitOfWorkCommitError`,
`UnitOfWorkRollbackError`, `UnitOfWorkCloseError`,
`ReadOnlyMutationError` and `NestedUnitOfWorkError` derive from
`UnitOfWorkError`. The real V005 deferred FK now exits as
`UnitOfWorkCommitError(code="UNIT_OF_WORK_COMMIT_FAILED")` with
`sqlite3.IntegrityError` in `__cause__`. SQLite reports the commit as failed;
the UoW rolls back while `connection.in_transaction`, closes the handle, clears
ContextVar/internal state and leaves zero snapshot rows. Cleanup failures are
recorded without replacing the commit/body cause. Non-SQLite programmer errors
still propagate unchanged when cleanup succeeds.

### Immutable diagnostics

An immutable main-file view is authoritative only when exact SQLite sidecars do
not exist. WAL, SHM or rollback journal presence — regardless of size or whether
it appears stale — returns `IMMUTABLE_SNAPSHOT_UNSAFE`. Health therefore never
reports READY/NOT_INITIALIZED from the known-unsafe snapshot. Diagnostics does
not open WAL-aware, checkpoint, delete, truncate or create any sidecar. Similar
names such as `-wal-backup` and `-shm.old` do not trigger the guard.

### CLI display

Human display converts C0/C1 and bidi controls to visible `\\xNN`/`\\uNNNN`
representations, including nested payload values and error messages. Ordinary
Unicode is preserved. The canonical filesystem path is not changed. JSON uses
the original value with standard `json.dumps` escaping and remains parseable.

## Changed files

- `ode/application/errors.py`
- `ode/infrastructure/database.py`
- `ode/infrastructure/diagnostics.py`
- `ode/infrastructure/migrations.py`
- `ode/cli.py`
- `tests/ode013/test_paths_uow.py`
- `tests/ode013/test_manifest_migrations.py`
- `tests/ode013/test_diagnostics_health.py`
- `tests/ode013/test_cli_architecture.py`
- `docs/development/STAGE_0_13_1.md`
- `docs/operations/database-lifecycle.md`
- `docs/development/STAGE_0_13_1_REVIEW_RESPONSE.md`

Approved DDL V001–V008, manifest, old `app.py`, runtime `inventory/` and
production data are outside this correction diff.

## Regression and full-gate evidence

Focused correction suite: 54/54 PASS twice before the final CLI regression was
added. Seven explicit F1/F2/F3/F4/F5/F6 regression IDs passed separately.

Full gate:

- `compileall ode/` and final `compileall ode/ tests/ode013/`: PASS;
- normal order: 55/55 PASS;
- reverse order: 55/55 PASS;
- repeated in one process: 55/55 + 55/55 PASS;
- different cwd (`/tmp`, absolute discovery root): 55/55 PASS;
- final normal rerun after documentation/whitespace correction: 55/55 PASS;
- every test run used `PYTHONWARNINGS=error::ResourceWarning`; ResourceWarnings:
  0;
- two independent clean builds: schema hash
  `143bb0ae16c68c1fcd653ecc94adc62464746fed738ebfa47749057380f7f0cb`
  for create and verify in both builds;
- both builds: application ID `1329874225`, user version 8, registry 8,
  objects 41 tables / 73 explicit indexes / 73 triggers / 3 views,
  permissions `0600`, no candidate/WAL/SHM/journal;
- both builds: users/equipment/snapshots/ledger/projections = 0,
  `integrity_check=ok`, `foreign_key_check=0`, all `verify_schema.sql` checks
  PASS and all 23 `verify_domain_invariants.sql` counts 0;
- all eight DDL SHA-256 values match the unchanged manifest; approved schema
  hash and manifest SHA-256 are unchanged;
- path safety, typed migration failure cleanup, real deferred FK, active WAL,
  terminal control output and UoW misuse regressions: PASS;
- module boundary audit, security grep, `git diff --check`, scoped trailing
  whitespace scan, relevant Markdown link audit (2/2) and old `app.py` import:
  PASS;
- production DB final state equals baseline: 579461120 bytes, mtime epoch
  `1784105153`, SHA-256
  `73568a1c3eecbd4476473f064620d7f0a196b336ce8ea6d834c5b99359d4b010`,
  immutable integrity `ok`, FK violations 0, no WAL/SHM/journal.

## Remaining risks and recommendation

- Online WAL-aware diagnostics and process-owner locking remain future
  operational work; this correction deliberately fails closed instead.
- A SIGKILL after hard-link publish but before candidate-name unlink can leave a
  second filename for the same valid inode; manual inode verification/cleanup is
  documented.
- Windows hard-link/permission behavior was not exercised on this macOS host.
- NFC/NFD path normalization remains an explicit future ADR decision.

After a successful full gate, Stage 0.13.1 is suitable for a short repeat
independent Claude review. Stage 0.13.2 remains forbidden until that review and
separate explicit user confirmation.
