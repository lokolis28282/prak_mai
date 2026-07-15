# Receipt sequence

Статус: **APPROVED — ODE 0.13 architecture baseline**

~~~mermaid
sequenceDiagram
    actor O as Operator
    participant API
    participant SEC as Security
    participant APP as Receipt use case
    participant UOW as SQLite UoW
    participant BAL as Balance projector
    participant AUD as Audit

    O->>API: POST transaction RECEIPT + Idempotency-Key
    API->>SEC: Require WAREHOUSE_RECEIPT
    SEC-->>API: Principal
    API->>APP: Typed command
    APP->>UOW: Begin write
    APP->>UOW: Validate ACTIVE baseline, no freeze, identity/location
    APP->>UOW: Insert header and lines
    APP->>BAL: Apply +Q synchronously
    BAL->>UOW: Upsert projection and sequence
    APP->>AUD: Append RECEIPT_POSTED
    AUD->>UOW: Insert audit event
    APP->>UOW: Commit
    APP-->>API: Posted transaction + projection version
    API-->>O: 201
~~~
