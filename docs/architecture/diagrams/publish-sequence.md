# Atomic candidate publish

Статус: **APPROVED — ODE 0.13 architecture baseline**

~~~mermaid
sequenceDiagram
    participant API
    participant L as External publish lock
    participant DB as Operational DB
    participant C as Same-volume candidate
    participant B as Backup storage
    participant FS as Filesystem

    API->>L: Acquire freeze/publish lock
    API->>DB: Read-only fingerprints
    API->>C: SQLite Backup API copy
    API->>C: BEGIN IMMEDIATE approval transaction
    API->>C: Recheck active snapshot and ledger head
    API->>C: Reserve successor internal snapshot_id
    API->>C: Supersede old snapshot with reserved successor ID
    API->>C: Insert successor, immutable items and projection
    API->>C: Update app_state and append audit
    API->>C: Domain and deferred FK checks
    API->>C: Commit
    API->>C: integrity/FK/domain/checksum checks
    API->>C: WAL checkpoint and close handles
    API->>DB: SQLite Backup API pre-publish backup
    API->>B: Hash, verify-open, fsync manifest
    API->>DB: Stop requests, checkpoint, close all handles
    API->>FS: fsync candidate and directory
    API->>FS: Atomic replace DB with candidate
    API->>DB: Reopen read-only and verify
    API->>DB: Reopen runtime WAL
    API->>L: Release lock
~~~
