# ADR-009: SQLite operating model

Статус: **APPROVED**

## Context

Локальный масштаб достижим SQLite при одном writer; network FS/multi-writer
нарушают guarantees.

## Decision

Local filesystem, one writer, query-only readers, WAL, synchronous=FULL,
foreign_keys=ON, busy_timeout=10s, application_id=0x4F444531.
schema_migrations authoritative; PRAGMA user_version отражает последнюю
numeric version. Migration runner запускается отдельной будущей CLI-командой,
никогда startup.

## Alternatives

Server DB; SQLite network share; schema_migrations без user_version; startup
migration.

## Consequences

Explicit operations workflow и compatibility check; server deployment требует
нового ADR/storage adapter.

## Rejected options

Network/multi-writer unsafe; startup migration скрыто меняет data.

## Migration impact

V001–V008 применяются только runner к empty/candidate after backup and checks.

## Security impact

DB permissions, no extension loading, trusted_schema=OFF, no secret defaults.

## Performance impact

WAL/readers/projection; query plans/index gates обязательны.

## Rollback impact

Schema migration rollback через verified whole DB backup, не automatic down SQL.

## Approval status

Утверждено как часть ODE 0.13 architecture baseline. DDL blocker: нет.
