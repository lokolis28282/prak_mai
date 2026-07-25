# Backup and restore

Статус: **PROPOSED**

## Backup set

A recoverable set includes:

- operational DB from SQLite Backup API;
- source vault manifest and referenced immutable files;
- schema/application/config version;
- projection checksum and ledger head;
- audit/manifest hash;
- optional workspace for active inventory;
- encrypted secret/config material by separate secret procedure.

Release binary is referenced by immutable build hash, not embedded in data
backup.

## Backup procedure

1. Admin reauth and reason.
2. Disk/target/permission preflight.
3. Backup API to temporary local artifact while runtime may read/write.
4. Open backup read-only; integrity/FK/schema checks.
5. SHA-256/size/ledger head manifest.
6. Copy source objects missing from backup repository.
7. fsync and atomic artifact rename.
8. Optionally copy verified artifact to offline storage.
9. Audit BACKUP_CREATED.

Plain file copy is allowed only for a closed/checkpointed DB during freeze.

## Retention

Default proposal: 7 daily, 5 weekly, 12 monthly, pre/post-release indefinitely
for 10-year system horizon. Corporate policy may increase retention. Deletion
requires manifest/reference check so no source object used by retained snapshot
is removed.

Backups encrypted at rest by approved platform mechanism and access logged.

## Restore validation

Restore plan checks:

- manifest/hash/signature;
- application_id/schema compatibility;
- integrity/FK;
- app_state/snapshot/projection/ledger consistency;
- required source objects;
- target disk space;
- supported application build.

Validation never modifies operational DB.

## Restore publish

Maintenance lock, close handles, preserve current DB as incident artifact,
prepare same-volume restore candidate, add RESTORE_COMPLETED audit in candidate
where semantically safe, checkpoint/close/fsync, atomic replace, read-only
verify, start WAL and smoke.

Restore never overwrites the only copy of current DB.

## Disaster recovery test

Quarterly isolated restore proves:

- backup opens without original installation;
- exact S/N/history/balance queries work;
- projection rebuild matches;
- personal accounts can recover through documented bootstrap;
- RTO/RPO measured;
- source files referenced by history available.
