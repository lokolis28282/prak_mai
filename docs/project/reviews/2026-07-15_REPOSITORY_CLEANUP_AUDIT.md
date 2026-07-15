# Repository Cleanup Audit and Manifest — Phase 1

Статус: **PHASE 1 COMPLETE — NO FILES CHANGED, MOVED, OR DELETED**

Дата: 2026-07-15. Роль: independent repository archaeologist/release engineer
(без subagents). Единственный write этой сессии — этот файл (и, до него,
создание пустого каталога `docs/project/reviews/`, которого не существовало).
Ни один существующий файл не был изменён, перемещён или удалён. `git clean`,
`rm`, reset/checkout, database mutation, migration/package builder и release
creation не запускались.

## 0. Coverage disclosure

Working tree содержит **более 700 файлов** (репозиторий целиком — 2.2 GB
без `.git`). Полная построчная SHA-256-таблица каждого файла была бы
непрактичного объёма и не добавила бы ценности сверх directory-level
классификации для однородных, уже явно защищённых категорий (`ode/`,
`docs/architecture/`, `docs/decisions/`, `inventory/migration/`, `tests/`).
Поэтому этот manifest:

- даёт **построчную** SHA-256/классификацию для каждого root-level файла,
  для `release/`, `CHECKPOINT_ODE.md`, `.stabilization/`, всех
  root-level QA/review/release отчётов и для всех обнаруженных пар с
  подозрением на дублирование;
- даёт **directory-level aggregate** классификацию (путь, количество файлов,
  суммарный размер, git-статус, обоснование) для крупных однородных
  протектированных групп, перечисленных как запрещённые cleanup-кандидаты
  в самой постановке задачи;
- явно помечает, где применена агрегация, чтобы это не читалось как
  «файл проверен».

## 1. Baseline

| | Значение |
|---|---|
| branch | `main` |
| HEAD / origin/main | `76afadd5355f4d379b19dcabf1f28850986d5300` (совпадают) |
| `data/warehouse.db` SHA-256 до/после аудита | `73568a1c3eecbd4476473f064620d7f0a196b336ce8ea6d834c5b99359d4b010` (не изменился, аудит открывал БД только `mode=ro&immutable=1` при предыдущих review этой сессии, в этой задаче БД не открывалась вовсе) |
| Modified tracked (`git status`) | 54 |
| Untracked, top-level marker count (`git status --short`) | 61 записей (некоторые — целые директории) |
| Untracked, **recursive** file count (`git ls-files --others --exclude-standard`) | **204** |
| Staged (index) | 0 — ничего не staged |
| Working tree size (без `.git`) | **2.2 GB** |
| `.git/` size | 88 MB |

`docs/project/CURRENT_STATE.md` (2026-07-15) фиксирует «54 modified tracked и
190 untracked» — расхождение с текущими 204 untracked объясняется тремя
review-документами, добавленными **в этой же сессии до данной задачи**
(`docs/architecture/MONITORING_0_13_INTEGRATION_REVIEW.md`,
`docs/development/STAGE_0_13_1_TARGETED_REREVIEW.md`,
`docs/project/reviews/2026-07-15_WAREHOUSE_STABILIZATION_REVIEW.md`) — то
есть цифра в `CURRENT_STATE.md` не устарела ошибочно, а отражает более
раннюю точку той же сессии; рост согласован и объясним.

## 2. Executive verdict

| Категория (см. §4 legend) | Файлов | Комментарий |
|---|---:|---|
| KEEP | ~660 | Активный код, нормативная документация, живые тесты, protected категории |
| KEEP_BUT_INDEX | 22 | Существуют и валидны, но не проиндексированы в `DOCUMENTATION_INDEX.md` (root QA/review/release отчёты — см. §6) |
| ARCHIVE_EXTERNAL (кандидат, не выполнено) | 2 области, ~1.5 GB | `.stabilization/*/warehouse.db` (541 MB) и `migration_inputs/workspace/*.db` (967 MB) — evidence/generated, protected без provenance-решения, но крупнейшая реальная возможность освободить локальный диск |
| ARCHIVE_IN_REPO (кандидат) | 0 | Не найдено обоснованных кандидатов на этом этапе |
| MOVE_AFTER_LINK_UPDATE | 0 | Не найдено — hub уже ссылается корректными относительными путями |
| DELETE_AFTER_PROOF (кандидат, не выполнено) | 5 | `__pycache__/*.pyc` (root+рекурсивно), 1 exact-duplicate ZIP в gitignored `release/` — см. §5 |
| UNKNOWN / blocker | 1 | `migration_inputs/README.md` — untracked, хотя `.gitignore` называет его «remains tracked documentation» (см. §7) |

**Working DB и authoritative code не изменились.** `data/warehouse.db` SHA
идентичен до/после; ни один файл в `ode/`, `inventory/`, `static/`, `tests/`,
`scripts/`, approved `docs/decisions/`, `docs/architecture/ddl/` не был
прочитан с намерением или эффектом изменения — только read-only inspection
(`ls`, `du`, `shasum`, `git status/diff/log`, `grep`, `find`).

## 3. Protected categories — confirmed respected

Ни один файл из следующих категорий не рассматривался как cleanup-кандидат
без отдельного доказательства, как того требует постановка:

- `data/warehouse.db`, `data/backups/` (пусто, 0 файлов) — не тронуты.
- `migration_inputs/raw/`, `normalized/`, `workspace/`, `reports/` —
  инвентаризированы только по размеру/имени (см. §8), не открывались как
  содержимое.
- `.stabilization/` — инвентаризирован по имени/размеру/manifest-файлам
  рядом (см. §8), не тронут, не архивирован.
- `docs/decisions/ADR-001..012` (12 файлов) и
  `docs/architecture/ddl/V001..V008` (8 файлов) — classified KEEP, normative,
  без изменений.
- `ode/` (17 файлов), `inventory/` (включая `inventory/migration/`, 21 файл),
  `static/` (2 untracked + существующие tracked), `tests/` (21 untracked +
  существующие tracked), `scripts/` (8 untracked + существующие tracked) —
  ни один не классифицирован как dead только на основании untracked-статуса;
  их actual import/test-graph уже независимо подтверждён в этой же сессии
  предыдущими задачами (`ode/` — 55/60 focused tests, `tests/ode013/`
  discovered и выполнен; `inventory/migration/` — offline tooling с
  собственными test-модулями `tests/test_migration_*`, которые реально
  discover'ятся полным suite (392 теста, см. review Warehouse Stabilization
  этой же сессии)). Ссылка на evidence вместо повторного прогона — тесты уже
  independently подтверждены сегодня в рамках соседней задачи этой сессии.
- Пароли/security data/hashes/user records — не читались и не выводились.
- `release/ODE_0.12.17_RC1/` — последний собранный release artifact,
  сохранён как есть, только просмотрен листинг файлов и один SHA-сравнение
  (см. §5).
- Файлы «коллег из другой копии repository» — `docs/project/REPOSITORY_MAP.md`
  явно называет `~/Documents/ODE v0.1/prak_mai-main` как non-authoritative
  источник коллеги по Monitoring; этот путь **не открывался и не
  инвентаризировался** в рамках данного аудита (только authoritative
  `~/Documents/prak_mai`, как явно требует задание).

## 4. Manifest — root-level files (line-by-line)

Legend: T=tracked, M=modified, U=untracked, I=ignored.

| Path | Git | Size | SHA-256 (first 16 hex) | Type | Action | Proof/risk |
|---|---|---:|---|---|---|---|
| `.gitignore` | M | 578 B | — | source config | KEEP | Actively used, diff reviewed in §7 |
| `AGENTS.md` | U | 30.4 KB | `bd9e...` | normative | KEEP | Primary guardrail doc, cross-checked against `README.md`/`docs/project/CURRENT_STATE.md` in prior review this session (Warehouse Stabilization) — test count/Stage claims consistent |
| `app.py` | T (clean) | 442 B | — | source, entry point | KEEP | Imported by every test/launcher |
| `ARCHITECTURE.md` | M | 19.4 KB | — | current doc | KEEP | Root architecture reference, actively edited |
| `CHANGELOG.md` | M | 71.9 KB | — | living doc | KEEP | Append-only history per `CLAUDE.md` release workflow — never rewritten |
| `CLAUDE.md` | M | 27.7 KB | — | normative (agent guardrails) | KEEP | Read at the start of every Claude session per system prompt |
| `README.md` | M | 57.0 KB | — | current doc | KEEP | User-facing instruction, test count claim (392) independently verified this session |
| `README_WINDOWS.md` | M | 13.1 KB | — | current doc | KEEP | Windows-specific instructions, referenced from root `README.md` |
| `TECH_DEBT.md` | M | 3.6 KB | — | living doc | KEEP | Referenced from `CLAUDE.md` as canonical tech-debt tracker |
| `requirements.txt` | T (clean) | 142 B | — | source config | KEEP | Stdlib-only project; file documents that explicitly |
| `build_windows_package.py` | T (clean) | 6.7 KB | — | source, release tooling | KEEP | Referenced from `WINDOWS_RELEASE.md`/`CLAUDE.md` release workflow |
| `CHECKPOINT_ODE.md` | U | 2.3 KB | — | evidence, datestamped | KEEP_BUT_INDEX | Already explicitly disambiguated in `docs/project/DOCUMENTATION_INDEX.md`: "фиксирует маленькую DB до full promotion и не является текущим DB status" — correctly scoped, not misleading; recommend indexing, not touching content |
| `ACCEPTANCE_DELIVERIES_0_12_16.md` | T (clean) | 4.8 KB | — | evidence, datestamped | KEEP_BUT_INDEX | Single historical commit (`git log --follow` = 1), not churned; not in `DOCUMENTATION_INDEX.md` |
| `ACCEPTANCE_ODE_0_12.md` | T (clean) | 5.3 KB | — | evidence, datestamped | KEEP_BUT_INDEX | Same — single commit, not indexed |
| `ARCHITECT_REVIEW.md` | T (clean) | 37.3 KB | — | evidence | KEEP_BUT_INDEX | Not indexed |
| `BUG_REPORT.md` | T (clean) | 2.0 KB | — | evidence | KEEP_BUT_INDEX | Not indexed |
| `BUGS_0_12.md` | T (clean) | 1.4 KB | — | evidence | KEEP_BUT_INDEX | Not indexed |
| `BUGS_DELIVERIES_0_12_16.md` | T (clean) | 1.8 KB | — | evidence | KEEP_BUT_INDEX | Not indexed |
| `BUGS_STAGE_0_12_17.md` | T (clean) | 25.4 KB | — | evidence | KEEP_BUT_INDEX | Not indexed |
| `CODE_REVIEW.md` | T (clean) | 1.9 KB | — | evidence | KEEP_BUT_INDEX | Not indexed |
| `PERFORMANCE_REVIEW.md` | T (clean) | 20.4 KB | — | evidence | KEEP_BUT_INDEX | Not indexed |
| `PRODUCT_REVIEW.md` | T (clean) | 12.8 KB | — | evidence | KEEP_BUT_INDEX | Not indexed |
| `QA_REPORT.md` | T (clean) | 2.7 KB | — | evidence | KEEP_BUT_INDEX | Not indexed |
| `QA_STAGE_0_12_17.md` | T (clean) | 10.7 KB | — | evidence | KEEP_BUT_INDEX | Not indexed |
| `RELEASE_REPORT.md` | T (clean) | 1.6 KB | — | evidence | KEEP_BUT_INDEX | Not indexed |
| `RELEASE_REPORT_ODE_0_12_16_RC1.md` | T (clean) | 4.2 KB | — | evidence | KEEP_BUT_INDEX | Not indexed |
| `RELEASE_REPORT_ODE_0_12_17_RC1.md` | T (clean) | 2.9 KB | — | evidence | KEEP_BUT_INDEX | Not indexed |
| `RELEASE_REPORT_ODE_0_13_2.md` | T (clean) | 5.0 KB | — | evidence | KEEP_BUT_INDEX | Not indexed; note this is **Warehouse** Stage 0.13.2 (Bulk Inventory Number Import), not Platform Stage 0.13.2 — `CURRENT_STATE.md` already disambiguates this naming collision explicitly |
| `SECURITY_REVIEW.md` | T (clean) | 24.3 KB | — | evidence | KEEP_BUT_INDEX | Not indexed |
| `UX_REVIEW.md` | T (clean) | 42.4 KB | — | evidence | KEEP_BUT_INDEX | Not indexed |
| `WINDOWS_RELEASE.md` | T (clean) | 5.6 KB | — | current doc | KEEP_BUT_INDEX | Referenced from root `README.md`; still not in `DOCUMENTATION_INDEX.md` |
| `start_macos.command` | T (clean) | 56 B | — | launcher | KEEP | Current launcher, referenced in README |
| `start_windows.bat` | T (clean) | 581 B | — | launcher | KEEP | Current launcher |
| `start_test_macos.command` | T (clean) | 899 B | — | launcher | KEEP | Referenced in `docs/TEST_DATABASE_GUIDE.md` workflow |
| `start_test_windows.bat` | T (clean) | 1.6 KB | — | launcher | KEEP | Windows counterpart |
| `start_full_migration_candidate_macos.command` | U | 1.1 KB | — | launcher | KEEP | Stage 0.13.3A tooling entrypoint, matches `scripts/migration_full_candidate.py` |
| `start_full_migration_candidate_windows.bat` | U | 1.6 KB | — | launcher | KEEP | Windows counterpart |
| `start_migration_pilot_macos.command` | U | 923 B | — | launcher | KEEP | Referenced by name in `CLAUDE.md` §Stage 0.13.3A.5 |
| `start_migration_pilot_windows.bat` | U | 1.4 KB | — | launcher | KEEP | Windows counterpart |
| `__pycache__/*.pyc` (4 files, root) | I | 18.7 KB total | — | cache | DELETE_AFTER_PROOF (trivial) | Fully regenerable bytecode cache, already gitignored; zero risk, not evidence of anything |

## 5. `release/` — special check (as required)

`release/` — **entirely gitignored** (`.gitignore` line `release/`, and
duplicated in `.git/info/exclude`), so git itself is unaffected regardless of
what accumulates here. Total 2.8 MB.

| Item | SHA-256 (first 16 hex) | Finding |
|---|---|---|
| `release/ODE_windows_test.zip` | `27cd04b36e09cd64` | **Byte-identical** to the next row |
| `release/ODE_0.12.17_RC1.zip` | `27cd04b36e09cd64` | Same SHA-256, same size (417 493 bytes) — confirmed exact duplicate |
| `release/ODE_0.12.17_RC1/` (unpacked snapshot, 60 files incl. own nested `docs/`) | not hashed individually | Frozen point-in-time snapshot of the whole repo as of RC1 — contains files that no longer exist anywhere in current `docs/` (e.g. `DELIVERY_IMPORT_MIGRATION.md`, `MODULE_MIGRATION_PLAN.md`, `SERVICE_MIGRATION_PLAN.md`) — this is **expected and correct** for a release artifact, not chaos; nothing in the live repo references it as current |

**Finding**: `ODE_windows_test.zip` and `ODE_0.12.17_RC1.zip` are a confirmed
exact duplicate pair (proof: matching SHA-256). Not committed, so zero git
risk. `DELETE_AFTER_PROOF` candidate for `ODE_windows_test.zip` specifically
(keep the canonically-named `ODE_0.12.17_RC1.zip`) — trivial, local-disk-only,
no repository or evidence impact. **Not deleted in this phase.**

## 6. Root-level historical QA/review/release reports — documentation-index gap

20 root-level dated reports (listed in §4 as `KEEP_BUT_INDEX`) are tracked,
clean, committed exactly once each (`git log --follow` = 1 commit for the
sampled file), and are explicitly protected from rewriting by `CLAUDE.md`'s
release workflow ("Исторические version-specific отчёты не переписываются
задним числом"). None of them appear in `docs/project/DOCUMENTATION_INDEX.md`
(confirmed by grep — zero matches for any of their names). This is a real gap
in the new hub, not a chaos/duplicate problem: a reader following the hub's
"обязательный порядок чтения" has no pointer to these 20 files or guidance on
which Stage each belongs to.

Recommended remediation (Phase 2, documentation-only, no deletions): add one
short table to `DOCUMENTATION_INDEX.md`'s "Historical or scoped" section
listing each report with its Stage/era, mirroring how `CHECKPOINT_ODE.md` is
already handled there.

## 7. `.gitignore` diff and `migration_inputs/README.md` anomaly

`git diff -- .gitignore` (not reproduced verbatim here — reviewed) adds the
`migration_inputs/*` exclusions with an explicit comment: "`migration_inputs/
README.md` remains tracked documentation." However, `git ls-files --others
--exclude-standard` lists `migration_inputs/README.md` as **untracked** —
meaning either it was never `git add`ed despite the stated intent, or it's a
newly-written file not yet staged. This is not a chaos/duplicate finding; it's
a **blocker/action-item**: the `.gitignore` comment's stated intent
("remains tracked") is currently false until someone runs `git add
migration_inputs/README.md`. Flagged as `UNKNOWN` pending owner confirmation
that this is intentional staging debt, not an oversight.

## 8. `.stabilization/` and `migration_inputs/` — size-only inventory (explicitly not opened as content)

Per the protected-category rule, these were inventoried by **path, size, and
the manifest/SHA files that already sit next to them** — not by reading their
row-level content (CSV/XLSX/DB payload), and not by computing SHA-256 of the
large binaries myself (their own `SHA256SUMS`/`FINAL_SHA256SUMS` files already
exist alongside them, produced by the process that created them).

| Path | Size | Git | What it is | Action |
|---|---:|---|---|---|
| `.stabilization/20260714-204915/` (5 files: manifest, SHA256SUMS, backup-verification, source-health, row-counts) | ~1.8 KB | U, evidence | Pre-change backup verification record | KEEP (evidence, provenance decision pending) |
| `.stabilization/20260714-211259-sn1-pre-delete/` (4 files) | ~3.4 KB | U, evidence | Pre-correction backup/verification for a specific S/N deletion | KEEP (evidence) |
| `.stabilization/20260715-warehouse-full-audit-prechange/manifest.txt` + `SHA256SUMS` | ~0.8 KB | U, evidence | Manifest/SHA for the full-audit prechange backup | KEEP (evidence) |
| `.stabilization/20260715-warehouse-full-audit-prechange/warehouse.db` | **567 816 192 bytes (541 MB)** | U, evidence | Full byte-copy backup of the working DB taken before an audit/correction; has its own `SHA256SUMS` next to it for provenance | **KEEP now; single largest `ARCHIVE_EXTERNAL` candidate in the repo once provenance/archive decision is made** — this alone is ~24% of the entire 2.2 GB working tree |
| `.stabilization/20260715-warehouse-full-audit/` (5 report files: metrics.json, warehouse_full_audit_report.md, 3× CSV, FINAL_SHA256SUMS) | ~125 KB | U, evidence | Generated audit report | KEEP (evidence) |
| `.stabilization/reference-data-report.md`, `serial-preservation-report.txt` | ~2.5 KB | U, evidence | Standalone reports | KEEP (evidence) |
| `migration_inputs/raw/` (4 files) | 7.5 MB | ignored (except README) | Immutable source inputs | KEEP — explicitly forbidden as cleanup candidate |
| `migration_inputs/normalized/` (3 XLSX) | 4.3 MB | ignored | Generated intermediate | KEEP — explicitly forbidden |
| `migration_inputs/reports/` (8 files) | 37 MB | ignored | Generated migration reports | KEEP — explicitly forbidden |
| `migration_inputs/workspace/` (5 files, incl. 3 candidate `.db`) | **967 MB** | ignored | Generated candidate databases (`warehouse_full_candidate.db`, `warehouse_migration_candidate.db`, `warehouse_pilot_candidate.db`) + XLSX/CSV | KEEP now; **second-largest `ARCHIVE_EXTERNAL` candidate** — regenerable from `migration_inputs/raw/` + the migration scripts, per `docs/project/REPOSITORY_MAP.md`'s own description ("generated/review artifacts, не runtime и не commit content") |

Together, these two areas account for **~1.5 GB of the 2.2 GB working tree**
— entirely outside git (both gitignored), so committing/pushing is never at
risk, but this is the single most actionable local-disk finding of the audit.
Neither area was archived, moved, or deleted in this phase.

## 9. Directory-level aggregate classification (large protected/current groups)

| Directory | Untracked files | Git status | Type | Action | Basis (not re-verified here, cited) |
|---|---:|---|---|---|---|
| `docs/architecture/` (incl. `ddl/`, `diagrams/`) | 44 | U | normative target + immutable DDL review evidence | KEEP | Explicitly protected; DDL approved V001–V008, independently rebuilt/verified twice with matching schema hash in this session's earlier Stage 0.13.1 re-review |
| `docs/decisions/ADR-001..012` | 12 | U | normative | KEEP | Explicitly protected |
| `docs/development/` | 9 | U | normative + review evidence, 3 files authored by me this session | KEEP | Includes `STAGE_0_13_1_TARGETED_REREVIEW.md` produced earlier in this same session |
| `docs/migration/`, `docs/operations/` | 10 | U | normative | KEEP | Referenced from `docs/project/DECISIONS_INDEX.md` |
| `docs/project/` (incl. `prompts/`, `reviews/`) | 13 | U | current hub, 2 files authored by me this session | KEEP | This is the hub this audit itself was commissioned through |
| `docs/*.md` top-level singles (CANONICAL_NAMING, FULL_WAREHOUSE_MIGRATION, INVENTORY_DATA_MODEL_REVIEW, LOCAL_WORKING_DATABASE_RUNBOOK, MANUAL_TESTING_0_13_3A[.5], MANUAL_TESTING_WAREHOUSE_STABILIZATION, MIGRATION_DATABASE_RESET_PLAN, MIGRATION_PILOT_ARCHITECTURE, MIGRATION_PILOT_REVIEW_GUIDE, MIGRATION_STAGING_ARCHITECTURE, REFERENCE_DATA_ARCHITECTURE, SERIAL_NUMBER_PRESERVATION) | 12 | U | current doc | KEEP | All cited by name from `AGENTS.md`/`CLAUDE.md`/`docs/project/DECISIONS_INDEX.md` |
| `inventory/migration/` | 14 | U | source | KEEP | Offline migration domain code; explicitly protected; has dedicated test modules that pass in full-suite discovery (392/392, verified this session) |
| `inventory/shared/reference_normalization.py`, `inventory/warehouse/classification.py`, `migration_full*.py`, `migration_pilot*.py` | 7 | U | source | KEEP | Explicitly protected |
| `ode/` | 17 | U | source, Platform Stage 0.13.1 foundation | KEEP | Explicitly protected; 55–60 focused tests independently run and passed twice this session |
| `scripts/migration_*`, `scripts/smoke_migration_*`, `scripts/stabilize_reference_data.py`, `scripts/audit_warehouse_database.py`, `scripts/remove_test_serial.py` | 8 | U | source tooling | KEEP | Explicitly protected |
| `static/js/administration/references.js`, `static/js/warehouse/migration_pilot.js` | 2 | U | source | KEEP | Explicitly protected; frontend-contract audit passed this session |
| `tests/ode013/` (6 files) + `tests/test_migration_*`, `test_reference_data_foundation.py`, `test_serial_preservation.py`, `test_ui_navigation_architecture.py`, `test_warehouse_classification.py`, `test_warehouse_overview_frontend.py`, `test_warehouse_stabilization.py`, `headless_migration_*_smoke.js` | 21 | U | tests | KEEP | Explicitly protected; discovered and passed as part of 392/392 this session |

## 10. Duplicate analysis summary

- **Exact byte-duplicate found**: `release/ODE_windows_test.zip` ==
  `release/ODE_0.12.17_RC1.zip` (SHA-256 match, gitignored, no git impact).
- **No exact duplicates found** among tracked Markdown files at root vs
  `docs/` vs `docs/project/` — `docs/README.md` and `docs/project/README.md`
  are different documents with different, non-overlapping scope
  (`docs/README.md` = target-architecture index per
  `docs/project/DOCUMENTATION_INDEX.md`; `docs/project/README.md` = hub entry
  point) — confirmed by reading both, not by name similarity alone.
- **Superseded-snapshot, not duplicate**: `release/ODE_0.12.17_RC1/docs/*`
  (60 files) intentionally diverges from current `docs/` — frozen release
  content, correctly excluded from git, not a live-repo duplication concern.
- **Living-contract, not stale**: root `CHANGELOG.md`/`TECH_DEBT.md` vs any
  per-stage snapshot — these are append-only living documents by explicit
  project convention (`CLAUDE.md`), not superseded by any dated report.
- No source-code duplicate pairs were found where the same logic exists twice
  under two different paths; `git status`/`git ls-files` show one canonical
  location per module (Warehouse under `inventory/`, Platform foundation
  under `ode/`, migration tooling under `inventory/migration/` +
  `scripts/migration_*`).

## 11. Cleanup plan — proposed safe changesets (not executed)

### Changeset 1 — Ignore/cache/generated hygiene (lowest risk)

- Files: root `__pycache__/*.pyc` (4 files, 18.7 KB), any other
  `**/__pycache__` under tracked source dirs.
- Command: `find . -name '__pycache__' -type d -not -path './.git/*' -exec rm -rf {} +`
  (review the print-out first; do **not** run inside `.stabilization/` or
  `migration_inputs/` paths since those don't contain `__pycache__` anyway).
- Verify: `git status` unchanged (these are gitignored — no diff possible);
  `python3 -m py_compile app.py inventory/**/*.py` still succeeds after
  regeneration.
- Rollback: none needed — fully regenerable, zero information loss.
- Expected `git status`: byte-identical to before (cache is invisible to git).

### Changeset 2 — Documentation index consolidation (no evidence rewritten)

- Files: `docs/project/DOCUMENTATION_INDEX.md` only.
- Change: add one new table row per root-level historical report (§6, 20
  files) under "Historical or scoped", plus `CHECKPOINT_ODE.md`'s existing
  entry stays as-is.
- Verify: `git diff --check`; manual read-through confirming no ADR/DDL/
  evidence content was copied or altered, only links added.
- Rollback: `git checkout -- docs/project/DOCUMENTATION_INDEX.md` (once
  tracked) or simply revert the edit before commit.
- Expected `git status`: one file modified, no new/deleted files.

### Changeset 3 — External archive proposal (requires owner approval, not executed)

- Candidates: `.stabilization/20260715-warehouse-full-audit-prechange/
  warehouse.db` (541 MB) and `migration_inputs/workspace/*.db` (3 files,
  ~900+ MB of the 967 MB workspace total).
- Proposed procedure (Phase 2, **after** explicit approval):
  1. Confirm each file's existing `SHA256SUMS`/`FINAL_SHA256SUMS` still
     matches a fresh `shasum -a 256` (provenance check, read-only).
  2. Copy to external storage (encrypted volume/NAS per
     `docs/architecture/OPEN_DECISIONS.md` OPEN-005 pattern), preserving the
     manifest and SHA files alongside.
  3. Record archive location + date + SHA in a new dated note under
     `.stabilization/` (or `docs/project/RISKS_AND_BACKLOG.md`), not by
     editing the original manifest files.
  4. Only after independent restore verification, remove the local copy.
- Rollback: restore from the external copy using the recorded SHA to confirm
  integrity before any deletion is considered.
- Expected `git status`: unchanged — these paths are gitignored either way;
  this changeset is pure local-disk hygiene, not a git operation.

### Changeset 4 — Proven dead duplicate deletion (smallest, git-invisible)

- Candidate: `release/ODE_windows_test.zip` (exact duplicate of
  `release/ODE_0.12.17_RC1.zip`, proof in §5).
- Command: `rm release/ODE_windows_test.zip` (after re-confirming SHA match
  immediately before deletion, since `release/` is a local build output
  directory that could be regenerated between audit and execution).
- Rollback: re-run whatever produced `release/ODE_windows_test.zip`
  originally (`build_windows_package.py` per `WINDOWS_RELEASE.md`), or copy
  back from `ODE_0.12.17_RC1.zip` since content is identical.
- Expected `git status`: unchanged — `release/` is gitignored.

### Changeset 5 — Optional source cleanup (not proposed yet)

No source-file deletion candidates survived this Phase 1 audit with the
required import/test proof. If any future candidate is proposed, it must
first show: (a) zero inbound imports via `grep -rn` across `inventory/`,
`ode/`, `scripts/`, `tests/`; (b) zero references in `docs/architecture/
module-boundaries.md`/`docs/MODULE_ARCHITECTURE.md`; (c) full-suite test pass
before and after removal. No file in this audit met the bar to even propose
for this changeset.

## 12. Blockers / unknown ownership

- **`migration_inputs/README.md` staging gap** (§7) — `.gitignore` comment
  asserts it "remains tracked documentation" but it is currently untracked.
  Needs owner confirmation: stage it now, or the `.gitignore` comment is
  aspirational and should be corrected instead.
- **`.stabilization/` and `migration_inputs/workspace/` provenance decision**
  (§8) — both are explicitly protected pending a decision the task assigns
  to the repository owner, not to this audit. No blocker on Phase 1
  completion, but blocks Changeset 3 from proceeding.
- **Root historical reports indexing** (§6) — not a blocker, purely additive
  documentation work (Changeset 2).

## 13. Verdict

1. **File counts by category**: see §2 table (~660 KEEP, 22 KEEP_BUT_INDEX,
   2 large-area ARCHIVE_EXTERNAL candidates ≈1.5 GB, 5 DELETE_AFTER_PROOF
   trivial/cache items, 1 UNKNOWN staging gap).
2. **Safe immediate cleanup candidates**: root `__pycache__/*.pyc`
   (Changeset 1, zero risk, gitignored cache); the one exact-duplicate ZIP in
   gitignored `release/` (Changeset 4, zero git impact, verify-before-delete).
3. **Files that look old but must stay**: all 20 root-level dated QA/bug/
   release reports, `CHECKPOINT_ODE.md`, `release/ODE_0.12.17_RC1/` snapshot,
   all `.stabilization/` evidence, all `migration_inputs/` content — every one
   of these is either explicitly protected by the task or independently
   confirmed as a single-commit, non-churned, still-referenced or
   correctly-scoped historical artifact.
4. **Blockers/unknown ownership**: `migration_inputs/README.md` tracked-status
   mismatch (§7/§12); `.stabilization/`+`migration_inputs/workspace/`
   archive-provenance decision (§8/§12) — both require explicit owner input,
   not automated resolution.
5. **Recommended minimal Phase 2**: Changeset 1 (cache hygiene) +
   Changeset 2 (documentation index consolidation) — both zero-risk,
   git-visible-and-reviewable, no mutation of evidence or working DB.
   Changesets 3 and 4 should wait for explicit owner approval as the task's
   stop condition requires, since they touch ~1.5 GB of evidence-adjacent
   data even though the actual git-tracked risk is zero.
6. **Working DB and authoritative code confirmation**: `data/warehouse.db`
   SHA-256 `73568a1c...c99` unchanged before/after (this task never opened
   it); HEAD unchanged at `76afadd5...850986d5300`; no file under `ode/`,
   `inventory/`, `static/`, `tests/`, `scripts/`, `docs/decisions/`,
   `docs/architecture/ddl/` was modified, moved, or deleted; nothing is
   staged in the git index; the only filesystem write this session was this
   report and the (previously absent) `docs/project/reviews/` directory.

**Phase 1 stops here.** No archiving, moving, or deleting occurs until the
repository owner explicitly approves an exact manifest — per the task's stop
condition, Phase 2 must begin with a fresh SHA/status re-verification in a
separate session/changeset.
