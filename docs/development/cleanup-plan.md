# Cleanup plan after ODE 0.13 cutover

Статус: **PROPOSED — ничего не удалять сейчас**

Удаление возможно только после replacement contract tests, signed cutover,
rollback-window expiration и verified archive. Current Git tag/old DB остаются
способом восстановления.

## DELETE AFTER CUTOVER

| Path | Причина / текущая evidence | Dependency proof перед удалением | Момент / rollback impact |
|---|---|---|---|
| inventory/services/ | String ServiceAdapter dispatch; большинство файлов 10–23 lines proxy в 3828-line warehouse_service.py | rg imports + architecture graph + new API/E2E no old service | После new UI/API only; rollback использует old tag, не mixed tree |
| inventory/service.py | 317-line compatibility facade с __getattr__ | No imports from new ode stack; old tests replaced | То же |
| inventory/models/ | Placeholder dataclasses без runtime ownership | Static import/type scan | После domain model replacement |
| inventory/warehouse/balance.py, history.py, inventory.py, models.py | По 1 строке, пустая модульность | Exact import graph and coverage | После new context modules |
| inventory/administration/audit.py, backup.py, diagnostics.py, users.py | По 1 строке | Exact import graph | После operations/security vertical |
| inventory/reports/weekly.py, exports.py | По 1 строке | Report contract/E2E | После reports vertical |
| inventory/monitoring/models.py | 1 строка | Monitoring disabled or replaced | После decision in integrated stage |
| inventory/warehouse/issues.py, receipts.py, issue_previews.py | Re-export shims | No external import consumers | После ledger vertical |
| inventory/shared/csv_tools.py | Re-export shim | No imports/new XLSX contract | После Preview vertical |
| static/js legacy aliases/marker-only submodules | window global aliases, no independent behavior | Static dependency/DOM/E2E and bundle graph | После new ES-module UI |
| release/ODE_windows_test.zip | Tracked generated binary and stale/data risk | Verified external artifact/archive if needed | После release audit; no runtime rollback dependency |
| __pycache__, *.pyc, generated local reports | Reproducible artifacts | Build clean from source | Any approved cleanup |

## ARCHIVE AFTER CUTOVER

| Path/group | Why retained | Evidence before archive | Removal from runtime |
|---|---|---|---|
| inventory/migration/full_builder.py, pilot_builder.py, candidate_db.py and other one-off builders | Reproduce 0.12 migration interpretation | Tool hash, environment, source manifests, successful independent archive run | After full migration signed |
| inventory/warehouse/migration_full.py, migration_full_review.py, migration_pilot.py, migration_pilot_review.py | Candidate/pilot review runtime only | New legacy UI/mapping acceptance | Never package in 0.13 |
| scripts/migration_full_candidate.py, migration_pilot.py, migration_reference_data.py, audit_warehouse_database.py, stabilize_reference_data.py, remove_test_serial.py | One-off operational tools | Commands/dependencies/tool hashes in archive README | After cutover |
| scripts/smoke_migration_full_ui.py, smoke_migration_pilot_ui.py and headless migration smoke files | Stage UI evidence | Replacement migration/E2E tests pass | After rehearsal |
| start_full_migration_candidate_macos.command/.bat, start_migration_pilot_macos.command/.bat | Old launchers | No support/runbook reference | After archive |
| tests/test_migration_candidate_db.py, test_migration_full_candidate.py, test_migration_full_frontend_contract.py, test_migration_pilot_*.py | Freeze old behavior | New mapping/contract tests cover retained invariants | Archive with old tag |
| stage-specific manual testing and migration Markdown | Historical decisions/evidence | Unique facts transferred and link audit | docs/archive/0.12 after acceptance |
| candidate/pilot DB artifacts | Rehearsal evidence only | Manifest/hash/retention decision | Encrypted external archive, never runtime |

## KEEP AND REFACTOR

| Current part | Target | Why |
|---|---|---|
| inventory/migration/xlsx_cells.py | imports/xlsx reader | Hardened raw OOXML and cell evidence; re-contract/test |
| inventory/migration/serial_preservation.py | equipment/import identity value objects | Leading-zero/raw preservation |
| inventory/shared/reference_normalization.py and migration/reference_data.py | references normalization policy | Preserve only deterministic reviewed rules |
| temp-DB test helpers and scanner fixtures | tests/support | Atomicity and identifier evidence |
| security/atomicity tests | new contract/security suite | Invariants remain valuable |
| scripts/smoke_ui.py concept | new E2E runner | Replace selectors/contracts, not copy globals |
| current classification logic | imports/reference proposal engine | Similarity only findings, never canonical decision |

## REPLACE

| Current | Replacement | Gate |
|---|---|---|
| inventory/ runtime package | new modular implementation after approval | All vertical stages/cutover |
| inventory/db.py SCHEMA+initialize | explicit versioned migrations/UoW | Empty/mismatch/migration tests |
| inventory/services/warehouse_service.py | bounded use cases | No compatibility calls |
| inventory/webapp.py and /api/action | API v1 + UI shell | API/UI contract E2E |
| flat reference_values + v2 | one reference/catalog model | Mapping signed |
| in-memory PreviewStore variants | workspace SQLite | Crash/1m tests |
| stock_balance aggregate query | active balance projection | Rebuild proof |
| shared engineer/default admin login | personal accounts/bootstrap | Security acceptance |
| build_windows_package.py behavior | allowlist data-free build | Denylist scan |

## Root/document disposition

| Files | Destination after unique-fact transfer |
|---|---|
| BUGS_0_12.md, BUGS_DELIVERIES_0_12_16.md, BUGS_STAGE_0_12_17.md, BUG_REPORT.md | docs/archive/0.12/reviews/bugs/ |
| QA_REPORT.md, QA_STAGE_0_12_17.md, CODE_REVIEW.md, PRODUCT_REVIEW.md, PERFORMANCE_REVIEW.md, ARCHITECT_REVIEW.md, SECURITY_REVIEW.md, UX_REVIEW.md, TECH_DEBT.md | docs/archive/0.12/reviews/ |
| ACCEPTANCE_*.md, RELEASE_REPORT*.md, WINDOWS_RELEASE.md | docs/archive/0.12/releases/ |
| ARCHITECTURE.md and old docs/*ARCHITECTURE*.md | docs/archive/0.12/architecture/ after target facts verified |
| docs/*MIGRATION*.md and docs/*MIGRATION_PLAN*.md | docs/archive/0.12/migration/ |
| docs/MANUAL_TESTING*.md | docs/archive/0.12/testing/ |
| docs/context_diagram.md, er_diagram.md, process_diagram.md | archive after new diagrams approved |
| docs/DATA_MODEL_ODE_013.md | archive explicitly as superseded receipt-as-card proposal |
| CHECKPOINT_ODE.md | archive with timestamp/commit after unique operational facts copied to release evidence |
| README_WINDOWS.md | replace by active installation doc or archive if unsupported |
| CLAUDE.md | keep only short current agent instructions; archive historical project claims |
| README.md, CHANGELOG.md | keep and rewrite at actual release, not this gate |

## Special artifacts

| Artifact | Decision |
|---|---|
| data/warehouse.db | Never delete at cutover. Remove from new runtime/Git only after two verified archive copies, manifest/SHA and rollback window. Retain ≥10 years. |
| Any 0.12 candidate DB | Deduplicate by SHA; retain source candidate if referenced by marker/manifests; external encrypted archive. |
| reports | New reports module retained as read-model consumer; generated artifacts expire. Old report code kept only if query contract tests prove reusable. |
| MCP cache | External developer cache, not release/data archive. Reindex after structural changes; delete/rebuild safely if stale. |
| .stabilization | External/archive decision after hashes copied and restore verified; never package. |
| migration_inputs | Immutable source vault/archive; never Git/release. Retention follows source evidence. |

## USER DECISION REQUIRED

- Corporate retention longer than the proposed minimum.
- Whether old Git history containing DB/ZIP needs security rewrite.
- Final archive storage/owners and encryption.
- Monitoring scope for ODE 0.13.

Эти решения не разрешают удалить данные; default — retain safely.
