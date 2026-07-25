# Rollback plan

Статус: **APPROVED PLAN — не исполнялся**

## Principle

Rollback switches an entire verified application/config/DB set. It never
reverse-copies individual 0.13 rows into 0.12.

## Artifacts

- frozen 0.12 binary/source commit and configuration;
- closed 0.12 DB byte-copy + Backup API copy;
- signed manifest and hashes;
- 0.13 pre-publish backup;
- release artifacts without data;
- rollback command/runbook per platform;
- source files and Preview evidence.

## Before first 0.13 write

Rollback is direct:

1. maintenance lock;
2. stop 0.13, close handles;
3. verify old artifact hash/integrity;
4. atomic restore old DB/config;
5. start old build read-only smoke, then writes if business approves;
6. audit in external incident log.

## After 0.13 ledger writes

Automatic rollback to 0.12 would lose new operations and is prohibited. Before
opening 0.13 writes, owners set a rollback window. If incident occurs after
writes:

1. freeze physical and software movements;
2. preserve 0.13 DB/source/audit;
3. export signed list of 0.13 posted transactions;
4. business/data owner decides forward recovery or controlled manual
   re-entry into restored 0.12;
5. no automated dual-write/reverse migration.

Это decision gate cutover, не скрытая техническая компенсация.

## Publish failure

- Before replace: delete candidate; old DB unchanged.
- Replace syscall failure: retain maintenance; restore original filename from
  pre-publish path; verify hash.
- After replace before reopen: atomic restore pre-publish backup.
- After reopen verification failure: stop, preserve failed DB, restore backup.

## Drill

На копии выполняются: corrupted candidate, insufficient disk, process crash
before/after replace, stale WAL/SHM, Windows locked handle, invalid backup hash.
RTO/RPO измеряются и утверждаются; без drill cutover запрещен.

## Cleanup protection

Old DB/binary/tools не архивируются в недоступное место и не удаляются до
signed acceptance + expiration rollback window + verified long-term archive.
