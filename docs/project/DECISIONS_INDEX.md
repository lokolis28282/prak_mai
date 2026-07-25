# Decisions Index

## Approved target architecture

- ADR-001..ADR-012: [`../decisions/`](../decisions/)
- Architecture baseline: [`../architecture/overview.md`](../architecture/overview.md)
- Module boundaries: [`../architecture/module-boundaries.md`](../architecture/module-boundaries.md)
- Security: [`../architecture/security.md`](../architecture/security.md)
- Transaction model: [`../architecture/transaction-model.md`](../architecture/transaction-model.md)
- Inventory lifecycle: [`../architecture/inventory-lifecycle.md`](../architecture/inventory-lifecycle.md)
- Ledger/projection: [`../architecture/warehouse-ledger.md`](../architecture/warehouse-ledger.md),
  [`../architecture/balance-projection.md`](../architecture/balance-projection.md)
- Approved DDL/review: [`../architecture/ddl/README.md`](../architecture/ddl/README.md)
- Open decisions: [`../architecture/OPEN_DECISIONS.md`](../architecture/OPEN_DECISIONS.md)

## Current Warehouse contracts

- Module architecture: [`../MODULE_ARCHITECTURE.md`](../MODULE_ARCHITECTURE.md)
- Ownership: [`../DATABASE_OWNERSHIP.md`](../DATABASE_OWNERSHIP.md)
- Security boundaries: [`../SECURITY_BOUNDARIES.md`](../SECURITY_BOUNDARIES.md)
- Warehouse events: [`../WAREHOUSE_EVENTS.md`](../WAREHOUSE_EVENTS.md)
- S/N preservation: [`../SERIAL_NUMBER_PRESERVATION.md`](../SERIAL_NUMBER_PRESERVATION.md)
- Reference data: [`../REFERENCE_DATA_ARCHITECTURE.md`](../REFERENCE_DATA_ARCHITECTURE.md)
- Local DB runbook: [`../LOCAL_WORKING_DATABASE_RUNBOOK.md`](../LOCAL_WORKING_DATABASE_RUNBOOK.md)

## Interpretation rule

Approved target ADR/DDL defines the future cutover architecture. Current
Warehouse contracts define existing operational behavior. Нельзя объявлять
target behavior уже реализованным или менять working Warehouse только потому,
что target ADR его описывает.
