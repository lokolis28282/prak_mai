# History search by S/N

Статус: **APPROVED — ODE 0.13 architecture baseline**

~~~mermaid
sequenceDiagram
    actor U as Authenticated user
    participant API
    participant EQ as Equipment lookup
    participant H as Legacy history query
    participant I as Inventory query
    participant W as Ledger query
    participant A as Audit query

    U->>API: Exact S/N + optional vendor + cursor
    API->>EQ: Resolve conservative serial key
    EQ-->>API: zero, one or ambiguous Equipment candidates
    par independent read-only queries
        API->>H: Legacy events by serial key
        API->>I: Snapshot evidence by candidates
        API->>W: Current transactions by candidates
        API->>A: Identity/admin events by candidates
    end
    H-->>API: Raw provenance + quality
    I-->>API: Snapshot DTO
    W-->>API: Ledger DTO
    A-->>API: Audit DTO
    API->>API: Merge DTOs, retain source_type, keyset cursor
    API-->>U: Grouped timeline; ambiguity never hidden
~~~
