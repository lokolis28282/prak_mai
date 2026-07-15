# ADR-008: Персональные accounts и audit

Статус: **APPROVED**

## Context

Shared write-login не доказывает actor. Legacy source часто хранит blank/code
вместо ФИО.

## Decision

Современный write требует active personal User/session/permission. Roles:
operator, admin, auditor. Deactivation сохраняет User row и FK. Domain/audit
записывают actor_user_id и immutable actor_display_name/role snapshot. Legacy
performed_by_name_raw и personnel_code_raw не имеют обязательного FK к User.
Password хранится только memory-hard hash; default credentials отсутствуют.

## Alternatives

Shared login; hard delete user; resolve every legacy actor to User.

## Consequences

Исторические actions переживают rename/deactivation; требуется bootstrap/recovery.

## Rejected options

Shared/hard-delete ломают accountability/FK; legacy binding выдумывает identity.

## Migration impact

Только reviewed personal accounts; known default hash не переносится.

## Security impact

Revocable sessions, unique login/email, role mapping, audit in same UoW.

## Performance impact

Indexed session/user lookup; audit keyset indexes.

## Rollback impact

Account changes transactional; old DB retains old auth only в rollback set.

## Approval status

Утверждено как часть ODE 0.13 architecture baseline. DDL blocker: нет.
