# Self-review архитектурной спецификации

Статус: **PROPOSED — audit evidence**

## Traceability

| Requirement | Owner document |
|---|---|
| Business truth/boundaries | overview, ADR-002/003 |
| Modules/dependencies/events | module-boundaries |
| Entities/identity/terms | domain-model, ADR-006/007 |
| Tables/owners/retention/indexes | data-model |
| Inventory states/cutoff/reconciliation | inventory-lifecycle |
| XLSX/workspace/publish | import-preview-publish, ADR-004/005 |
| Ledger/reversal/idempotency | warehouse-ledger |
| Projection proof/rebuild | balance-projection |
| Legacy source/FIO/date | legacy-history |
| References/catalog | references-catalog |
| Permissions/audit | security |
| Transactions/rollback | transaction-model |
| Endpoints/UI actions | api-contract, ui-contract |
| Scale/gates | performance |
| Migration/mapping/rollback | migration/* |
| Cleanup/order/tests | development/* |
| DB/backup/release operations | operations/* |

## Contradictions found and resolved

1. Review implied all InventorySession states could live in operational DB;
   final model assigns authority to workspace until publish.
2. Review did not define consistent point-in-time for later inventory; final
   model requires external posting-freeze and cutoff before physical count.
3. Review suggested S/N unique normalized field; final ADR makes S/N
   vendor-scoped and preserves ambiguity.
4. Review did not distinguish reversal state vs transaction; original posted
   row is now immutable and reversal is a new transaction.
5. Review required FIO but source has blanks/codes; final model stores raw +
   quality and never invents name.
6. Review did not decide partial inventory; it cannot create baseline.
7. Review did not formalize visible projection lag; active lag is exactly zero.
8. Review did not specify candidate platform constraints; same-volume,
   closed-handle and platform atomic replace are mandatory.
9. Review described quarantine but logical event schema lacked a complete
   classification; record_status IMPORTED/QUARANTINED/EXCLUDED added.
10. Review could be read as new snapshot creating adjustments; final model
    stores reconciliation only and directly rebaselines after approval.
11. Review mixed Preview lifecycle rows with operational inventory sessions;
    DDL stores DRAFT..APPROVING only in workspace and APPROVED/SUPERSEDED only
    in operational DB.
12. Review left PARTIAL inventory ambiguous; it is now an immutable CycleCount
    that cannot create or replace a global baseline.

## Completeness checks

- Every entity has owner in domain/module tables.
- Every working DB table has owner and retention.
- Every write endpoint maps to a permission, UoW and audit.
- Every UI write action maps to API.
- Every endpoint uses typed use case; no /api/action.
- All inventory statuses have transitions/recovery.
- Legacy has no dependency edge to balance/ledger.
- Projection has deterministic formula/checksum/rebuild/failure state.
- Source mapping accounts for current significant tables and no legacy ledger.
- Cleanup protects rollback artifacts.
- No pre-baseline posting exception exists.
- Kafka/microservices/server deployment are explicitly out of scope.

## Remaining risk classes

- Data quality: personnel codes, pending catalog and location mapping.
- Operations: supported OS, archive storage, hardware profile.
- Security: possible historical Git artifact exposure.

Они перечислены только в [OPEN_DECISIONS.md](OPEN_DECISIONS.md) и не скрывают
другой balance/domain source of truth.

## Implementation gate conclusion

Review-only ADR freeze, versioned DDL/SQL and field mapping подготовлены.
Начинать runtime implementation нельзя до отдельного технического утверждения
этого комплекта и entry criteria Stage 0.13.1.
