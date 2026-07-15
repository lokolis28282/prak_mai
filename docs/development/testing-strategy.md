# Testing strategy ODE 0.13

Статус: **PROPOSED**

## Layers

| Layer | Purpose |
|---|---|
| Unit | Value objects, normalization, quantities, state transitions |
| Property-based | Mathematical/identity/idempotency invariants over generated cases |
| Integration | SQLite repository, UoW, migrations, filesystem adapters |
| Contract | Module ports, API DTO/errors, UI/API mapping, forbidden dependencies |
| Migration | Frozen source mapping, counts, hashes, rerun |
| Security | Auth/session/CSRF/permissions/upload/secrets |
| Performance | Reference dataset/machine/query plans/memory |
| E2E | Operator/admin/auditor journeys |
| Disaster recovery | Backup, failed publish, restore, rollback |

Tests never open tracked/live data/warehouse.db for write. Fixtures use temp
roots and assert source hash unchanged.

## Critical property/invariant tests

1. Adding any LegacyHistoryEvent never changes Truth(K,n).
2. Projection rebuild is deterministic for any snapshot/ledger order fixed by
   sequence.
3. Approve is atomic under exception at every write/publish checkpoint.
4. Upload/Preview/resolution leave operational DB SHA byte-identical.
5. Repeated approval/transaction idempotency key creates one result.
6. Leading zeros and raw identifier bytes survive round-trip.
7. Reversal delta + original delta = 0 for every line.
8. Repository/UoW rollback leaves no domain/projection/success-audit row.
9. Every source row migrates exactly once or has explicit quarantine.
10. No active balance/write before approved baseline.
11. Posted transaction UPDATE/DELETE is impossible through ports and
    verification query detects tampering.
12. Active projection lag is zero after every successful ledger command.
13. Transfer preserves global subject total.
14. New snapshot supersession preserves all old items.
15. Similarity never auto-resolves physical identity.

## State-machine tests

Generate InventorySession transition sequences. Any transition not listed in
inventory-lifecycle fails. Crash/retry from PREVIEWING/APPROVING exercises
durable checkpoints and candidate deletion.

## Migration corpus

Contains all current source rows for rehearsal plus minimized fixtures for:
numeric/scientific S/N, duplicate source rows, 1900/1904 date systems,
corrupted dates, blank/numeric responsible, formulas, hidden/merged cells,
vendor ambiguity, cable decimals and missing source file.

## DB tests

- migration from empty only and explicit version progression;
- foreign_keys enabled on every pool;
- busy writer/read concurrency;
- query plans and indexes;
- backup API restore;
- WAL crash recovery;
- handle leak warnings are failures;
- shadow projection activation.

## Acceptance independence

Existing green ODE 0.12 tests are evidence for old behavior, not acceptance of
new semantics. Tests requiring facade equality to WarehouseCore or legacy
equipment synchronization are archived after replacement by normative
contracts.
