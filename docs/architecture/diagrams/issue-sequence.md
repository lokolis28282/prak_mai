# Issue sequence

Статус: **APPROVED — ODE 0.13 architecture baseline**

~~~mermaid
sequenceDiagram
    actor O as Operator
    participant API
    participant APP as Issue use case
    participant UOW as SQLite UoW
    participant BAL as Balance query/projector
    participant AUD as Audit

    O->>API: POST transaction ISSUE + expected state
    API->>APP: Authorized typed command
    APP->>UOW: Begin write
    APP->>BAL: Read available Q in same transaction
    BAL-->>APP: Q and projection version
    alt insufficient or stale
        APP->>UOW: Rollback
        API-->>O: 409/412
    else valid
        APP->>UOW: Insert header and lines
        APP->>BAL: Apply -Q synchronously
        APP->>AUD: Append ISSUE_POSTED
        APP->>UOW: Commit all
        API-->>O: 201 posted
    end
~~~
