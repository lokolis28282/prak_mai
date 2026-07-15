# Correction and reversal sequence

Статус: **APPROVED — ODE 0.13 architecture baseline**

~~~mermaid
sequenceDiagram
    actor A as Admin
    participant API
    participant SEC as Security
    participant APP as Correction use case
    participant UOW as SQLite UoW
    participant BAL as Balance projector
    participant AUD as Audit

    A->>API: Reauthenticate + correction/reversal command
    API->>SEC: Permission and fresh authentication
    SEC-->>API: Authorized principal
    API->>APP: Command + impact digest
    APP->>UOW: Begin write
    APP->>UOW: Validate target, impact and idempotency
    alt target belongs to current baseline and exact reversal is safe
        APP->>UOW: Insert REVERSAL and inverse lines
    else old baseline or unsafe inverse
        APP->>UOW: Rollback reversal attempt
        APP-->>API: REVERSAL_OUTSIDE_ACTIVE_BASELINE or REVERSAL_UNSAFE
        API-->>A: Explain immutable history and required forward correction
        A->>API: Separate ADJUSTMENT/TRANSFER command from physical fact
        API->>APP: Validated correction command
        APP->>UOW: Begin new correction write
        APP->>UOW: Validate active baseline, physical fact and idempotency
        APP->>UOW: Insert ADJUSTMENT/TRANSFER and lines
    end
    APP->>BAL: Apply signed delta
    APP->>AUD: Append reason and actor
    APP->>UOW: Commit all
    API-->>A: New immutable transaction
~~~
