# Backup and restore

Статус: **PARTIALLY IMPLEMENTED** — create/status реализованы с ODE 0.18.1 и
поддерживаются в текущем ODE 0.21.0; restore остаётся **PROPOSED** по ADR-013.

## Current ODE 0.21.0 runtime slice

Administration регистрирует три независимых файла:

| database id | Profile | Runtime target |
|---|---|---|
| `warehouse_ix` | Warehouse | `data/warehouse.db` |
| `warehouse_solar` | Warehouse | `data/warehouse_solar.db` |
| `vacations` | Vacations | `data/vacations.db` |

Backup root задаётся `ODE_BACKUP_DIR`; без него используется внешний системный
каталог данных ODE. Каталог внутри repository отклоняется. HTTP-клиент передаёт
только database id, не filesystem path.

Snapshot выполняется SQLite Backup API под общим application write-lock в
sibling `.next`. До atomic rename проверяются integrity, foreign keys,
required tables и отсутствие alias source (symlink/hardlink). Рядом сохраняется
manifest с database id/profile/source path/time/size/SHA/method/verification.
Backup и manifest имеют mode `0600` на POSIX.

Admin UI показывает health и последнюю копию, но не строки бизнес-таблиц.
Успех пишет `RUNTIME_DATABASE_BACKUP_CREATE` в primary Administration audit;
details содержат только технические metadata.

Restore-кнопки нет. `RESTORE_BACKUP` fail-closed до завершения ADR-013.

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
