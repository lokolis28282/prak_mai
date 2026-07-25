# ODE 0.13 versioned DDL review artifacts

Статус: **APPROVED_FOR_IMPLEMENTATION — не применять напрямую к data/warehouse.db**

V001–V008 являются утверждённым ODE 0.13 architecture baseline. Статус
разрешает начать отдельный implementation stage только после явного
пользовательского подтверждения; он не разрешает применять DDL к production DB.

## Migration order

| Version | File | Owner modules | Main objects |
|---:|---|---|---|
| 1 | V001__system_and_security.sql | infrastructure, application, users, security | registry, app state, users, roles, permissions, sessions |
| 2 | V002__references_and_catalog.sql | references/catalog | references, aliases, UOM, catalog, warehouse/location |
| 3 | V003__equipment_identity.sql | equipment | equipment, versioned identities, aliases, merge |
| 4 | V004__legacy_history.sql | legacy history | source manifests, events, warnings, reviewed links |
| 5 | V005__imports_and_inventory.sql | imports, inventory | committed provenance, sessions, FULL snapshots, PARTIAL cycle counts |
| 6 | V006__warehouse_ledger.sql | warehouse | immutable ledger, lines, late-operation evidence |
| 7 | V007__balance_projection.sql | balance | projection versions/rows and truth views |
| 8 | V008__audit_and_operations.sql | audit, reports, operations | audit, report jobs, backup metadata |

## Review checksum manifest

Checksums are SHA-256 of exact reviewed file bytes. Approval must freeze these
values; any later byte change requires a new review result and registry value.

| Version | SHA-256 |
|---:|---|
| 1 | `946e17453d3926648caebca0e9287af2fffc56a0a3548c37289712ba0316570b` |
| 2 | `781ea0f8a1f7e0a45188132b383b6f9d3db5e0a26003566bb5004ce91566ff50` |
| 3 | `a5e7a4e4f0dd20bbea163a0aa4204d8703653d352a49b963a22ec30896fa466f` |
| 4 | `e830e9a8d658f8528e57532ea71ea5dc2d66afa60fcab3ecebe6888a9e81d76f` |
| 5 | `1ec116d96c150a28d22a39fdde6ecdf3bdec3cb6c16d07715e52c4e3151c822a` |
| 6 | `e34ec3431786d6746b90d07ab69d0cc7222657da1f99c6784a5de51e97d4d2fb` |
| 7 | `c0fa68fe2d62fdd7929b38abd7184f7bc86e081b10dc6f5630723406d4fe28a5` |
| 8 | `25e0beaae0f6ea1883f796938ff2eed6d3095ec0374c111b7d38bc37386d52b6` |

preview_workspace_schema.sql — отдельная external workspace schema с другим
application_id; она не входит в operational V001–V008.

## Table ownership

| Table | Owner module |
|---|---|
| schema_migrations | infrastructure |
| app_state | bootstrap/application |
| users | users |
| roles | users/security |
| permissions | security |
| user_roles | users |
| role_permissions | security |
| sessions | security |
| reference_domains | references/catalog |
| reference_values | references/catalog |
| reference_aliases | references/catalog |
| uoms | references/catalog |
| catalog_items | references/catalog |
| warehouses | references/catalog |
| warehouse_locations | references/catalog |
| equipment | equipment |
| equipment_identities | equipment |
| equipment_identity_aliases | equipment |
| equipment_merges | equipment |
| legacy_source_files | legacy history |
| legacy_history_events | legacy history |
| legacy_history_warnings | legacy history |
| legacy_history_equipment_links | legacy history |
| import_commits | imports |
| import_row_links | imports |
| import_findings | imports |
| import_resolutions | imports |
| inventory_sessions | inventory |
| inventory_snapshots | inventory |
| inventory_snapshot_items | inventory |
| inventory_cycle_counts | inventory |
| inventory_cycle_count_items | inventory |
| inventory_reconciliation_items | inventory |
| warehouse_transactions | warehouse ledger |
| warehouse_transaction_lines | warehouse ledger |
| warehouse_late_operation_evidence | warehouse ledger |
| balance_projection_versions | balance |
| balance_projection_rows | balance |
| audit_events | audit |
| report_jobs | reports |
| backup_records | infrastructure/operations |

Workspace-only tables `preview_runs`, `preview_rows`, `preview_cells`,
`preview_findings`, `preview_matches`, `preview_resolutions` and
`preview_statistics` принадлежат imports и удаляются вместе с workspace по
retention policy; они не принадлежат operational schema.

## Registry

schema_migrations содержит:

- version INTEGER PK;
- name UNIQUE;
- checksum BLOB SHA-256 длиной 32;
- applied_at_us;
- applied_by;
- application_version.

Runner вычисляет checksum exact file bytes, сверяет отсутствие/совпадение
existing version, применяет file в transaction и только после успеха вставляет
registry row. PRAGMA user_version дополнительно отражает последнюю numeric
version для диагностики, но registry является источником истины.

Каждый SQL file выставляет user_version после commit. Если registry insert
падает, runner восстанавливает pre-migration backup/candidate; он не объявляет
частично зарегистрированную schema примененной.

## Future runner contract

Будущая, пока не реализованная команда:

    ode db migrate --database <candidate-path> --to-version 8 \
        --applied-by <operator> --application-version <build>

Команда обязана:

1. отказать для operational process lock и network filesystem;
2. проверить application_id/current registry/user_version;
3. создать SQLite Backup API backup;
4. включить foreign_keys=ON на connection;
5. проверить checksum и последовательность без gaps;
6. применить только pending files;
7. выполнить verify_schema.sql и verify_domain_invariants.sql;
8. не запускаться автоматически при application startup.

Повтор V001–V008 напрямую контролируемо отклоняется existing schema objects.
Runner при повторе не выполняет file, а сверяет registry checksum. Changed
checksum у applied version — fatal SCHEMA_MIGRATION_CHECKSUM_MISMATCH.

## SQLite connection profile

Каждый connection, включая tests, обязан явно выполнить:

    PRAGMA foreign_keys = ON;
    PRAGMA busy_timeout = 10000;
    PRAGMA trusted_schema = OFF;

foreign_keys не сохраняется в DB file. Review negative test подтвердил, что
connection без PRAGMA способен вставить orphan; поэтому runtime connection
factory и migration runner имеют обязательный assertion
PRAGMA foreign_keys=1.

Runtime после publish использует WAL/synchronous=FULL. Migration/candidate
может работать в single-file journal mode до checkpoint/close/atomic replace.

## Artifacts

- verify_schema.sql — schema/application/index/security inventory;
- verify_domain_invariants.sql — zero-row domain violation queries;
- synthetic_inventory_proof.sql — positive snapshot/ledger/projection proof;
- synthetic_rebaseline_proof.sql — deferred atomic successor baseline proof;
- synthetic_rebaseline_correction_proof.sql — forward correction after
  rebaseline proof;
- explain_query_plans.sql — operational access-path review;
- preview_workspace_schema.sql и explain_workspace_query_plans.sql;
- legacy proof находится в
  [legacy-history-count-proof.sql](../../migration/legacy-history-count-proof.sql).

Все proofs запускаются только на DB в temporary directory. Source XLSX и
production/candidate DB не используются.

Зафиксированный результат данного gate: [REVIEW_RESULTS.md](REVIEW_RESULTS.md).
Ответ на независимый review:
[RESPONSE_TO_INDEPENDENT_REVIEW.md](RESPONSE_TO_INDEPENDENT_REVIEW.md).

## Data placement

SQLite хранит metadata, hashes, normalized/raw fields and provenance. XLSX,
backups, live DB copies и report artifacts хранятся в filesystem object storage
по opaque key. DDL не содержит source/backups BLOB и не создает credentials.
