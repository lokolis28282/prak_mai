# Границы модулей ODE 0.13

Статус: **APPROVED — ODE 0.13 architecture baseline**

## Правило композиции

Domain code зависит только от собственных value objects и общих примитивов.
Application use case зависит от публичных ports других контекстов. Concrete
SQLite repositories подключаются только composition root. Межмодульный вызов
repository запрещен.

События в таблицах ниже — типизированные синхронные application events. Они
обрабатываются до commit в общей Unit of Work. Внешний broker отсутствует.

## Контракты модулей

| Модуль | Владеет и изменяет | Public commands | Public queries | Только читает | Publishes / consumes | Запрещено |
|---|---|---|---|---|---|---|
| bootstrap/application | Composition, config, lifecycle, cross-context UoW | Start/stop, maintenance, orchestrated approve/publish | Health/readiness | Все ports, не таблицы | Consumes all for coordination | Business rules, SQL, global service locator |
| equipment | Equipment, identities, merge links | Register, correct identity, merge, change lifecycle | Get, exact lookup, resolve stock key | Approved catalog/reference queries | EquipmentRegistered/IdentityChanged/Merged | Balance, XLSX, legacy writes |
| inventory | Session handoff, snapshots, reconciliation | Approve/reject/supersede full inventory | Session, snapshot, reconciliation | Equipment/reference ports, ledger head | InventoryApproved/Superseded | Parse XLSX, post ledger |
| warehouse | Immutable transactions and lines | Receipt, issue, transfer, adjustment, reversal | Transaction detail/feed, ledger head | Equipment/catalog/location/balance availability ports | LedgerTransactionPosted; consumes InventoryApproved state | Legacy history, projection SQL |
| balance | Projection versions/rows/state | Apply snapshot, apply ledger event, rebuild | Balance page, availability, consistency | Snapshot and ledger query ports | ProjectionActivated/Inconsistent; consumes InventoryApproved/LedgerTransactionPosted | Own business movements |
| legacy history | Source files, history events/warnings | Offline import only | Exact S/N timeline, source detail | Equipment resolution query | LegacyHistoryImported; optional consumes EquipmentMerged for display resolution | Ledger/projection writes |
| imports | Source vault manifest, workspace rows/findings/resolutions | Upload, preview, resolve, retry, cancel, prepare publish | Preview/findings/statistics | Read-only equipment/reference/baseline fingerprints | PreviewReady/Stale/Failed | Operational DB writes before publish |
| references/catalog | Domains, values, aliases, catalog, UOM, warehouse/location | Approve/reject alias, create/deactivate/rename/merge | Resolve exact, browse, version fingerprint | Audit actor port | ReferenceChanged/CatalogChanged | Create canonical on read, semantic auto-merge |
| users | User profile, user-role assignments | Create/deactivate user, assign role, change password | User/profile | Roles | UserChanged | Sessions, domain writes |
| security | Sessions, authentication, authorization policy | Login/logout/revoke/reauthenticate | Current principal, permission decision | User/role queries | Authenticated/SessionRevoked | Shared identity, business mutation |
| audit | Append-only audit events | Append event in caller UoW | Filtered audit feed/detail | Actor snapshots | AuditRecorded | Ledger or provenance duplication |
| reports | Report definitions and exported artifacts | Request/cancel export | Report status/result | Public query contracts only | ReportRequested/Completed | Direct table SQL, authoritative totals |
| API | HTTP routes, DTO, error envelope | Transport only | Transport only | Application facades | Correlation lifecycle | SQL, business branching, HTML |
| UI | Screens, client state, accessibility | User intent through API | API resources | API only | Browser events | SQL, hidden permissions, global legacy aliases |
| infrastructure | SQLite UoW/repositories, filesystem, clock, UUID, backup | Technical adapters | Technical adapters | OS/SQLite | None as domain owner | Domain decisions |

## Принадлежащие сущности

| Модуль | Сущности |
|---|---|
| equipment | Equipment, EquipmentIdentity, EquipmentMerge |
| inventory | InventorySession, InventorySnapshot, InventorySnapshotItem, InventoryCycleCount, InventoryCycleCountItem, InventoryReconciliationItem |
| warehouse | WarehouseTransaction, WarehouseTransactionLine |
| balance | BalanceProjectionVersion, BalanceProjectionRow |
| legacy history | LegacySourceFile, LegacyHistoryEvent, LegacyHistoryWarning, LegacyHistoryEquipmentLink |
| imports | InventoryPreview, InventoryFinding, InventoryResolution, PreviewRun/Row/Match/Statistics, ImportCommit, ImportRowLink, committed ImportFinding/Resolution |
| references/catalog | ReferenceDomain, ReferenceValue, ReferenceAlias, CatalogItem, Uom, Warehouse, WarehouseLocation |
| users | User, Role, UserRole |
| security | Session, Principal, Permission, RolePermission |
| audit | AuditEvent |
| reports | ReportRequest, ReportArtifact |

## Dependency matrix

Ячейка означает допустимую прямую зависимость через публичный port. Пустая
ячейка означает запрет.

| Consumer ↓ / Provider → | Eq | Inv | Wh | Bal | Hist | Imp | Ref | Usr | Sec | Aud | Rep | Infra |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| equipment | — | | | | | | R | | | A | | P |
| inventory | Q | — | Q | C | | C | Q | | S | A | | P |
| warehouse | Q | Q | — | Q | | | Q | | S | A | | P |
| balance | Q | Q | Q | — | | | Q | | | A | | P |
| legacy history | Q | | | | — | | Q | | S | A | | P |
| imports | Q | Q | Q | | | — | Q | | S | A | | P |
| references/catalog | | | | | | | — | | S | A | | P |
| users | | | | | | | | — | S | A | | P |
| security | | | | | | | | Q | — | A | | P |
| audit | | | | | | | | Q | | — | | P |
| reports | Q | Q | Q | Q | Q | Q | Q | | S | | — | P |
| API | C/Q | C/Q | C/Q | Q | Q | C/Q | C/Q | C/Q | C/Q | Q | C/Q | |
| UI | Через API | | | | | | | | | | | |
| bootstrap/application | C/Q | C/Q | C/Q | C/Q | C/Q | C/Q | C/Q | C/Q | C/Q | C | C/Q | C |

Легенда: C — command port, Q — query port, R — reference query, S — security
decision, A — append audit, P — repository/UoW implementation.

Infrastructure не является допустимой зависимостью domain models. Обозначение P
означает constructor injection реализации на application boundary.

## Публичные query contracts

- EquipmentLookup: exact identity, equipment detail, canonical redirect.
- InventoryQuery: active snapshot, session, reconciliation, cutoff.
- LedgerQuery: ledger head, transaction detail, stream after sequence.
- BalanceQuery: page by keyset, availability, projection state.
- LegacyHistoryQuery: exact serial timeline and source provenance.
- ImportPreviewQuery: findings, matches, statistics and digest.
- ReferenceQuery: exact code/alias resolution and version fingerprint.
- SecurityQuery: principal and permission.
- AuditQuery: filtered keyset feed.

Query contracts возвращают immutable DTO, а не ORM rows или SQLite cursors.

## Enforcement

CI проверяет запрещенные imports, SQL tokens вне infrastructure adapters,
dynamic getattr dispatch, Any в public ports, commit/rollback в repositories,
циклы между contexts и пустые Python/JS modules.

См. [modules diagram](diagrams/modules.md) и
[coding standards](../development/coding-standards.md).
