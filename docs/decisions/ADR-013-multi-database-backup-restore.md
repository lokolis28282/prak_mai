# ADR-013 — Multi-database backup and restore

Статус: **ACCEPTED / PARTIALLY IMPLEMENTED**
Дата: 2026-07-27
Реализовано: read-only status и create backup в ODE 0.18.1.
Не реализовано: preview/confirm/restore publish.

## Context

ODE использует три независимых SQLite-файла:

- `warehouse_ix` — IXcellerate и общий application contour;
- `warehouse_solar` — изолированный Solar Warehouse;
- `vacations` — самостоятельный Vacations bounded context.

Копирование активного `.db` обычным filesystem copy не образует надёжный
snapshot. Выбор restore только по filename не доказывает target/schema и не
защищает от cross-database замены. Частично реализованный destructive workflow
опаснее отсутствующей кнопки.

## Decision

### Registry

`RuntimeDatabaseRegistry` содержит только:

- allowlisted database id;
- операторское label;
- exact lexical path;
- профиль `warehouse`/`vacations`;
- минимальный набор обязательных таблиц.

Registry не открывает БД, не владеет таблицами и не вызывается из
Warehouse/Vacations facades для filesystem mutations.

### Backup — implemented

`Administration -> MultiDatabaseBackupService`:

1. требует session role `admin`;
2. принимает только database id;
3. блокирует отсутствующий файл, symlink и hardlink source;
4. берёт общий application write-lock;
5. создаёт snapshot SQLite Backup API во внешний `<root>/<database_id>/...next`;
6. проверяет `integrity_check`, `foreign_key_check` и required tables;
7. вычисляет SHA-256 и записывает manifest;
8. fsync-ит оба файла и публикует atomic rename;
9. пишет `RUNTIME_DATABASE_BACKUP_CREATE` в Administration audit без данных
   таблиц.

Backup root задаётся `ODE_BACKUP_DIR`/runtime settings или системным каталогом
данных ODE. Путь внутри Git repository и symlink root запрещены.

### Restore — required design, not implemented

Restore состоит из двух API-фаз.

#### Preview

Admin передаёт `target_database_id` и backup id/basename из allowlisted
каталога этого же database id. Service:

1. повторно разрешает exact registry target;
2. блокирует symlink/hardlink target, backup и storage directories;
3. проверяет manifest SHA, database id/profile, integrity/FK/schema;
4. запрещает Warehouse↔Vacations и Solar↔IX restore;
5. проверяет свободное место и отсутствие `-wal/-shm/-journal`;
6. создаёт короткоживущий opaque preview token, связанный с actor, session,
   target id, backup SHA, current target SHA и expiry;
7. ничего не меняет и пишет `RUNTIME_DATABASE_RESTORE_PREVIEW`.

Token хранится только в памяти, одноразовый и не содержит path/secret.

#### Confirm and publish

Confirm требует reauth/reason, target database id и preview token. Под общим
writer-stop/write-lock service:

1. атомарно consume-ит token и повторяет все preview checks;
2. доказывает, что target SHA и backup SHA не изменились;
3. создаёт и проверяет safety backup текущего exact target;
4. восстанавливает backup SQLite API в sibling `<target>.next`;
5. повторно проверяет candidate и fsync;
6. выполняет единственный `os.replace(candidate, target)`;
7. открывает target read-only и проверяет его ещё раз;
8. пишет `RUNTIME_DATABASE_RESTORE_COMPLETED` либо внешний failure audit.

До `os.replace` working target byte-identical. При любой pre-publish ошибке
`.next` удаляется, target не меняется. Ошибка самого `os.replace` также оставляет
target неизменным. После publish failure отдельный rollback использует
проверенный safety backup и получает собственный audit/event contract.

## UI

0.18.1 показывает status, last backup, create button и список копий.
Restore preview/confirm/result не отображаются до полной реализации всех
пунктов выше. Legacy `RESTORE_BACKUP` fail-closed.

## Tests required before enabling restore

- restore каждой из трёх БД;
- cross-database/profile mismatch blocked;
- corrupt/hash/FK/schema failures blocked;
- symlink/hardlink/sidecar blocked;
- safety backup and manifest verified;
- expired/reused/wrong-session token blocked;
- atomic replace failure preserves original SHA;
- viewer/engineer denied;
- audit success/failure contains no table contents;
- crash/restart rehearsal on target Windows filesystem.

## Consequences

- 0.18.1 безопасно создаёт копии всех runtime-БД, но не обещает runtime restore.
- Legacy single-DB restore code остаётся compatibility debt и не доступен через
  активный UI/action.
- Retention, encryption at rest, offline replication and restore drills remain
  operational backlog.
