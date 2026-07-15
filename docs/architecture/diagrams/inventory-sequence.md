# Full inventory sequence

Статус: **APPROVED — ODE 0.13 architecture baseline**

~~~mermaid
sequenceDiagram
    actor O as Operator
    participant API
    participant W as External workspace
    participant V as Source vault
    participant P as Preview worker
    participant DB as Operational DB
    participant C as Candidate publisher

    O->>API: Create FULL inventory session
    API->>DB: Read active snapshot and ledger head
    DB-->>API: Fingerprint
    API->>W: Create session and posting-freeze
    O->>API: Upload approved XLSX
    API->>V: Stream, hash, validate, fsync
    API->>W: Store immutable source reference
    O->>API: Start Preview
    API->>P: Parse source by batches
    loop each committed batch
        P->>W: rows, findings, matches, statistics
    end
    P->>W: Final digest and READY/REVIEW_REQUIRED
    O->>API: Add resolutions
    API->>W: Append resolution
    O->>API: Approve with digest/fingerprint
    API->>DB: Read-only stale check
    API->>C: Build and validate candidate
    C->>DB: SQLite Backup API
    C->>C: Snapshot + projection + audit transaction
    C->>C: Integrity, FK, domain and checksum gates
    C->>DB: Close handles and atomic replace
    C->>W: Publish receipt
    API-->>O: APPROVED snapshot
~~~
