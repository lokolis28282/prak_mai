# Migration verification gates

Статус: **APPROVED — ODE 0.13 architecture baseline**

Каждый gate имеет machine-readable result, evidence path, timestamp, tool
version and approver. Blocking failure запрещает publish/cutover.

## Source gates

- frozen DB SHA/size match manifest;
- byte-copy and Backup API copy open read-only;
- integrity_check=ok and foreign_key_check empty;
- schema dump/checksum captured;
- every source file exists and SHA/size match;
- table counts and aggregate hashes complete;
- restore rehearsal succeeds.

## Mapping gates

- no UNKNOWN disposition;
- 71 360 reconciliation rows → 71 360 legacy events;
- event source keys unique;
- all source file/serial/warning rows accounted;
- linked receipts/issues counts equal source and target ledger count remains 0;
- reference/catalog decisions explicit;
- reference/location parent graphs are acyclic and same-domain/same-warehouse;
- users have no known/default credential;
- quarantine count/reasons signed.

## Candidate schema gates

- application_id/user_version/schema_migrations correct;
- foreign_keys ON;
- integrity/FK checks pass;
- all required indexes exist and query plans pass;
- hierarchy trigger coverage and recursive zero-violation queries pass;
- app_state NOT_INITIALIZED before first inventory;
- no warehouse transaction/projection before baseline;
- no startup migration required on open.

## Baseline approval gates

- source/digest/versions/fingerprints match;
- no unresolved blocking finding;
- ledger head equals freeze cutoff;
- exactly one active APPROVED snapshot;
- snapshot item/source row counts/checksums match Preview;
- serialized quantities and identity uniqueness pass;
- projection rebuild equals published projection;
- legacy tables excluded from balance proof;
- approval idempotency replay returns same snapshot.

## Security/operations gates

- role matrix tests pass;
- shared/default login absent;
- session/CSRF/Origin/Host/upload controls pass;
- release manifest contains no data/source/backup/workspace;
- backup hash and isolated restore pass;
- POSIX and Windows replace failure drills documented for supported platforms;
- disk-space preflight covers current+candidate+backup+WAL margin.

## Performance gates

Dataset/hardware/tool manifest required. Apply gates in
[performance.md](../architecture/performance.md), capture EXPLAIN plans and
memory. Full scan in exact/page query is blocking regardless of latency.

## Cutover acceptance

Signed by business owner, data owner, security owner and technical owner:

- history sample acceptance;
- reconciliation totals;
- baseline physical totals;
- rollback artifact tested;
- monitoring and support runbooks ready;
- cleanup not yet executed.
