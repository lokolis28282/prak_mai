# Security Boundaries

Документ фиксирует минимальные границы безопасности для переходного состояния ODE 0.12.x.

## Stage 0.12.15 Delivery Import Access

Delivery import preview and confirm are write operations and require `admin` or
`engineer`. `viewer` may read delivery lists/cards through the facade but cannot
create previews or confirm delivery documents. Preview ownership is bound to the
author and optional session metadata; another user cannot confirm it.

The web layer must call delivery document import through
`ApplicationContext.warehouse`. Legacy delivery acceptance actions remain
separate and are not broadened by this stage.

## Stage 0.12.16 Delivery Acceptance Access

Delivery inspect, accept, unplanned accept, batch accept and metadata edit are
write-path operations exposed through `WarehouseFacade`. `admin` and `engineer`
may run them; `viewer` remains read-only. The actor/responsible value is taken
from the current authenticated context, not from request JSON.

## Public API

Read-only API не должен возвращать:

- `password_hash`;
- исходные пароли;
- session cookie или token;
- внутренние absolute paths, если UI их не использует;
- traceback;
- произвольные данные из файловой системы.

## Administration

Admin-only:

- список пользователей;
- audit log;
- список backup-файлов;
- database diagnostics;
- create/restore backup;
- create/disable/change users;
- production DB upload.

Доступны текущему пользователю:

- собственный профиль;
- роль;
- `must_change_password`, если используется текущим UI.

## Backup Files

Read-only список backup должен:

- читать только разрешенный `backup_dir`;
- показывать только ожидаемые `.db` файлы;
- не возвращать абсолютные пути;
- не принимать пользовательский path для чтения списка.

Restore остается write/action и не входит в read-only migration.

## Audit

`audit_log` принадлежит Administration. Warehouse и Reports могут публиковать события через существующий audit contract, но наружу административный журнал отдает только Administration.

Audit details не должны содержать исходные пароли. Если будущие actions начнут писать чувствительные поля, их нужно маскировать до записи.

## Reports Write

Reports write/import actions are allowed for `admin` and `engineer` only:

- create one work log;
- create batch work logs;
- import or confirm work-log CSV;
- upload or confirm a ready daily report.

`viewer` receives the existing insufficient-rights error. Reports write actions
use the current actor from application context/session state; shift engineer
names are preserved in audit when present.

## Warehouse Receipt Write

Equipment/component receipt write/import actions are allowed for `admin` and
`engineer` only:

- manual receipt;
- scanned S/N batch confirm;
- receipt CSV preview/confirm/import;
- receipt serial validation.

`viewer` receives the existing insufficient-rights error. The audit author comes
from the current session/application context, not from arbitrary request fields.

## Warehouse Cable Write

Cable receipt and cable issue actions are allowed for `admin` and `engineer`
only. `viewer` receives the existing insufficient-rights error.

Cable writes use the current actor from application context/session state for
audit. S/N fields are not trusted as cable identifiers and cable scanner/S/N
validation is not used.

## Warehouse Issue Write

Serialized equipment/component issue actions are allowed for `admin` and
`engineer` only:

- manual issue;
- issue scanner validation;
- scanned S/N confirm;
- issue CSV preview/confirm/import;
- strict bulk S/N issue preview/confirm.

`viewer` receives the existing insufficient-rights error. The audit author comes
from the current session/application context. Request fields such as
`responsible` are stored as operational data, not trusted as the authenticated
actor.

## Current Limitations

Stage 0.12.14 не меняет модель авторизации и не переносит authentication,
delivery writes, inventory write, Administration writes, backup/restore или
Monitoring.
