# ADR-005: Atomic candidate publish

Статус: **APPROVED**

## Context

Approval до 1 млн rows не должен оставлять partial operational state.

## Decision

Under publish lock SQLite Backup API создает same-volume candidate. Candidate
полностью применяет approval, проверяется, checkpoint/close/fsync; verified
backup предшествует platform atomic replace.

## Alternatives

Giant in-place transaction; cross-volume copy; row compensation.

## Consequences

Нужны disk preflight, platform-specific replace и закрытие всех handles.

## Rejected options

In-place повышает recovery risk; cross-volume не atomic; compensation не
восстанавливает byte-consistency.

## Migration impact

Migration rehearsal и baseline approval используют тот же publish protocol.

## Security impact

Candidate/source permissions, hash validation, no path supplied by client.

## Performance impact

Approval offline/maintenance; runtime reads не несут импортный aggregate.

## Rollback impact

До replace old DB неизменна; после replace — whole pre-publish backup.

## Approval status

Утверждено как часть ODE 0.13 architecture baseline. Platform support OPEN-004
остаётся implementation acceptance blocker, не DDL blocker.
