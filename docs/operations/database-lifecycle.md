# Database lifecycle

Статус: **APPROVED; Stage 0.13.1 clean-create subset REVIEW_READY**

Runtime Unit of Work не является SQL console: разрешены только application
DML (`SELECT`/`INSERT`/`UPDATE`/`DELETE` и `WITH`-варианты). `ATTACH`/`DETACH`,
arbitrary `PRAGMA`, transaction-control, schema DDL, multiple statements и
прямые записи в `sqlite_schema`/`sqlite_master` запрещены typed policy error.
SQLite authorizer является дополнительной защитой runtime connection; schema
изменяет только отдельный migration runner.

## Stage 0.13.1 development lifecycle

Development/test clean create реализован отдельно от operational cutover:

```console
python3 -m ode db create --path .local/ode013/ode013-dev.db
python3 -m ode db status --path .local/ode013/ode013-dev.db
python3 -m ode db verify --path .local/ode013/ode013-dev.db
python3 -m ode db migrations --path .local/ode013/ode013-dev.db
python3 -m ode system health --path .local/ode013/ode013-dev.db
```

`create` требует отсутствующий target, строит и проверяет sibling candidate,
закрывает его без sidecars и публикует без возможности overwrite. Остальные
команды read-only; ни одна не выполняется автоматически при context build.
External development/test path требует `--allow-external-dev-path`.

Immutable `status`/`verify`/`health` допустимы только для closed/published DB.
Если рядом существует exact `-wal`, `-shm` или `-journal` (даже stale или
zero-byte), команда fail-closed с `IMMUTABLE_SNAPSHOT_UNSAFE` до выдачи health
state. Она не удаляет sidecar, не создаёт SHM, не выполняет checkpoint и не
переходит скрыто в WAL-aware режим. Оператор должен сначала завершить writer и
выполнить предусмотренную lifecycle-процедуру shutdown/checkpoint; online
WAL-aware diagnostics требует отдельного явного mode в будущем stage.

Clean DB имеет `NOT_INITIALIZED`, поэтому warehouse posting выключен. Реальная
production DB ODE 0.12 не является допустимым path этого runtime. Подробный
contract и limitations: [STAGE_0_13_1.md](../development/STAGE_0_13_1.md).

## Paths

Application binary/code, operational data, source vault, workspace, candidate,
backups and logs use separate configurable roots. Defaults must be OS data
directories, not repository/release directory.

    app/
    data/operational/warehouse.db
    data/sources/sha256/...
    state/previews/{session}.db
    state/candidates/{correlation}.db
    backups/{timestamp}/
    logs/

All publish files reside on same local volume as operational DB.

## Create

Empty DB создается explicit admin/release command from versioned migrations.
It sets application_id, user_version/schema_migrations and app_state
NOT_INITIALIZED; approved DDL не создаёт roles, users или credentials rows.
Application startup only validates
compatibility; mismatch exits read-only/error.

## Runtime open

Every connection: foreign_keys=ON, busy_timeout=10000, trusted_schema=OFF.
Writer sets WAL and synchronous=FULL. Read handles use query_only=ON and
consistent transactions. One process writer owns lock file; second writer
refuses startup.

Stage 0.13.1 реализует только immutable closed-file diagnostics; описанные здесь
process-owner lock, online readers и shutdown checkpoint остаются целевым
operational contract будущего stage, а не уже реализованным deployment.

Network filesystem and cloud-synced folder rejected by preflight where
detectable and prohibited operationally.

## Checkpoint and shutdown

Graceful shutdown:

1. stop accepting requests;
2. wait/cancel bounded jobs;
3. commit/rollback writer;
4. WAL checkpoint PASSIVE then TRUNCATE for publish/backup boundary;
5. close readers/writer;
6. release process lock.

Unclean startup checks WAL recovery, integrity quick check, schema and
projection head before enabling writes.

## Candidate publish

Protocol in [import-preview-publish.md](../architecture/import-preview-publish.md).
Disk preflight reserves:

    operational size
    + candidate estimated size
    + verified backup size
    + 25% WAL/temp margin

Candidate must have no WAL/SHM at replace. POSIX uses atomic same-filesystem
replace + directory fsync. Windows uses ReplaceFileW after proving all handles
closed. Unsupported filesystem fails closed.

Clean-create publish использует `os.link` для absent target. Если процесс
получит SIGKILL в узком окне после publish link и до удаления candidate name,
рядом может остаться candidate как второй hard-link на тот же полностью
проверенный inode. Target не является partial; автоматическое удаление такого
stale имени в Stage 0.13.1 отсутствует, поэтому требуется проверка inode и
ручная cleanup-процедура.

## Maintenance states

External lock types: PROCESS_OWNER, INVENTORY_FREEZE, PUBLISH, BACKUP,
RESTORE, REBUILD. Lock record includes public ID, owner, created/expiry,
correlation and recovery policy. Posting checks locks before UoW.

## Integrity schedule

- startup quick_check and FK/schema/app-state checks;
- daily projection head/checksum sample;
- weekly full integrity_check during maintenance;
- before/after backup, publish, restore and migration full gates;
- disk free space and WAL size continuous local monitoring.

Failure blocks writes and records operations/security event.
