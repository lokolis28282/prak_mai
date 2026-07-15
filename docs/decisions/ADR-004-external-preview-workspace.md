# ADR-004: Внешний Preview workspace

Статус: **APPROVED**

## Context

Preview до approval не должен изменять operational DB, должен переживать crash
и обрабатывать 1 млн rows.

## Decision

Immutable XLSX хранится в filesystem source vault. Pre-approval session, rows,
cells, findings, matches, resolutions и statistics находятся в отдельной
versioned workspace SQLite DB. При publish finalized evidence копируется в
operational import tables.

## Alternatives

Memory, operational staging tables, browser localStorage.

## Consequences

Durable resume/digest и byte-identical operational DB; нужен cleanup/retention.

## Rejected options

Memory/localStorage недолговечны; operational staging нарушает trust boundary.

## Migration impact

Старый staging не переносится как new Preview; только committed provenance.

## Security impact

Workspace/source вне web root, opaque storage key, upload/XML limits.

## Performance impact

Batch streaming и bounded memory; indexed workspace queries.

## Rollback impact

Failed Preview удаляет/retains workspace по policy, operational DB неизменна.

## Approval status

Утверждено как часть ODE 0.13 architecture baseline. DDL blocker: нет.
