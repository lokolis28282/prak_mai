# Security Boundaries

## FULL Inventory 0.14

- create/upload/Preview/resolution требуют authenticated admin/engineer actor;
- baseline candidate rehearsal требует backend role `admin`;
- actor identity берётся из session user stable ID, имя — только snapshot;
- reason обязателен, resolution append-only, конфликт требует explicit
  `supersedes_resolution_id`;
- path source/workspace/candidate не принимается из HTTP payload;
- API не возвращает абсолютный filesystem path candidate;
- production posting fail-closed; publish/cutover endpoint отсутствует.

## Warehouse stabilization authorization

Права определяет backend session user и роль `admin/engineer/viewer`. ФИО,
фамилия, подпись инженера и видимый title никогда не используются как grant.
Отдельного UI-переключателя «режим администратора» нет.

Чтение editor catalog, activate/deactivate, rename и merge требуют admin.
Engineer может создать только inactive pending proposal через контролируемый
workflow «Другое». Payload валидируется, SQL параметризован, ошибки возвращаются
как controlled 4xx без traceback. UI hiding не считается authorization.

Production correction exact S/N требует validated external backups, immutable
evidence manifest, exact predicate, transaction, post-commit integrity/FK и
append-only correction audit. Массовое изменение S/N запрещено.

Документ фиксирует минимальные границы безопасности переходного состояния ODE,
актуальные для source Stage 0.13.3A.5.

**CURRENT LOCAL FACT:** builder/reference/staging logic remains offline, while
the validated full historical operational copy is now the ordinary local
`data/warehouse.db`. Migration provenance tables in that file are diagnostic;
they do not turn normal startup into candidate mode. The exact candidate and
pilot filenames remain separate marker-guarded read-only review artifacts.
This is not a server production deployment.

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

Successful ordinary administrator authentication writes the existing `LOGIN`
audit event. Authentication against pilot/full read-only review verifies the
same preserved hash but deliberately suppresses that audit write, otherwise a
login would mutate an immutable review DB before the POST mutation guard. This
exception applies only when the validated runtime status is read-only; promoted
`data/warehouse.db` uses ordinary login audit behavior.

## Promoted Full Working Database Boundary

- A file named `warehouse_full_candidate.db` requires explicit full-review
  opt-in, exact marker/schema, mode `0600`, clean integrity/FK/sidecars and is
  read-only at HTTP and audit levels.
- A validated marker descendant at the configured working path is ordinary
  local storage. Operational writes remain role-gated and pass through the
  existing facades/services; provenance tables have no normal write endpoint.
- Marker/provenance/raw status and reconciliation rows are not exposed in the
  engineer warehouse workspace or ordinary Equipment Card. The full review
  remains an admin diagnostic route.
- The working DB, candidate, pilot and external backups are local sensitive
  files and are excluded from Git/release artifacts. Password hashes are never
  printed in manifests, docs, UI or validation output.

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

## Inventory Number Assignment — Stage 0.13.1/0.13.2

Одиночное и массовое назначение Inventory Number являются warehouse write
operations. Preview и Confirm требуют аутентифицированную сессию и роль
`admin` или `engineer`; `viewer` отклоняется backend независимо от скрытия
кнопок UI. Шаблон может скачать вошедший пользователь, но он не даёт права на
запись.

Для bulk flow:

- `preview_id` создаётся через `secrets.token_urlsafe`, одноразовый и живёт не
  более 3600 секунд;
- preview привязан к author application context, но не к конкретному HTTP
  session token; нельзя передавать ID другому actor;
- actor/audit author берётся из текущего context, CSV не может его задать;
- body ограничен 50 МБ, parser — 40 000 непустых строк, preview store имеет
  per-author/global/row limits;
- `POST /api/import-csv?kind=inventory_numbers` намеренно запрещён;
- Confirm повторно анализирует план под `BEGIN IMMEDIATE`; stale или
  конфликтующий план отклоняется без частичной записи;
- S/N используется как единственный lookup key; запрос не создаёт карточки и
  не позволяет overwrite заполненного другого номера.

Полный security/API lifecycle —
[INVENTORY_NUMBER_IMPORT_ARCHITECTURE.md](INVENTORY_NUMBER_IMPORT_ARCHITECTURE.md).

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

Authentication, session storage, Administration writes, backup/restore and
Monitoring UI remain compatibility/in-memory boundaries. Monitoring hostname
routing читает только локальные ignored JSON rules, не отправляет email и не
обращается к Warehouse/Reports. Inventory Number preview
ownership is author-bound rather than session-bound and preview state does not
survive process restart. Server/multi-process deployment therefore requires a
separate persistent job/ownership design.

## Offline Migration Boundary — Stage 0.13.3A

### Trust boundaries

**IMPLEMENTED:**

- raw XLSX/TXT читаются как untrusted, immutable input; source hash
  проверяется до и после extraction;
- XLSX ZIP/XML parser не выполняет formulas, macros, external links или
  embedded content и не сохраняет source workbook;
- source/output paths проверяются; candidate output, равный,
  hardlinked или symlinked с `data/warehouse.db`, должен быть
  отклонён;
- рабочая БД и source files открываются без mutation; их
  SHA/integrity сверяются до/после;
- candidate DB публикуется только после integrity/FK/schema
  validation и не является production backup;
- raw, normalized, reports, workspace DB/sidecars и local manifests не
  коммитятся и не включаются в release ZIP.

### Sensitive data

Migration source/staging may include operational comments and personal fields.
Markdown management reports must omit them unless required for a specific
decision. Candidate DB and detailed reports must be treated as local sensitive
artifacts.

If the candidate profile preserves security identity for schema/reset testing:

- `password_hash` is copied byte-for-byte only through an explicit allowlist;
- hash values are never printed, returned by a report, written to CSV/Markdown
  or stored in staging raw payload;
- validation may report only user/role counts and boolean equality;
- candidate file permissions and retention follow the same local sensitivity as
  a database backup.

**IMPLEMENTED:** on POSIX the builder sets the candidate DB to mode `0600` and
the validator rejects group/other permission bits. Windows uses local file
ACLs because POSIX mode bits are not an equivalent security control there.

The `report` command uses the full candidate output path/inode guard, then
regenerates a fixed allowlisted report from the validated candidate and current
source checks. It never merges an existing report, so stale/injected
`password_hash`, secret or absolute-path keys cannot survive regeneration.

### Reference decisions

Machine confidence is not authorization. Auto-approval is restricted to case,
outer/repeated whitespace and safe Unicode spelling variants. Semantic aliases,
legal names and model/vendor ownership remain manual. `approved_by` and
`approved_at` stay empty for pending decisions. Safe `AUTO_APPROVED` aliases
use the explicit non-human actor `ODE_SAFE_RULE_V1`; manual approvals must use
an authorized human actor and must not reuse that marker.

Unknown candidate values are not passed to current production soft-reference
writers. Huawei/xFusion, HP/HPE, Hunix/Hynix, distinct legal suppliers and
distinct models are never silently merged.

### Identifier safety

Source S/N and normalized match key are separate. Logs/reports must not claim a
guessed value for a precision-lost numeric cell. `SOURCE_CORRUPTED` blocks future
entity creation until independent evidence exists. Full rules are in
[SERIAL_NUMBER_PRESERVATION.md](SERIAL_NUMBER_PRESERVATION.md).

### FUTURE STAGE

Receipt reference UI, approval permissions, production reference schema,
historical import and DB reset are not authorized by this Stage. The reset
workflow in [MIGRATION_DATABASE_RESET_PLAN.md](MIGRATION_DATABASE_RESET_PLAN.md)
requires separate explicit confirmation and verified backups.

## Preservation-Aware Pilot Boundary — Stage 0.13.3A.5

### Startup guard

Pilot mode is opt-in and fail-closed. Before `ApplicationContext` initializes,
the runtime verifies:

- `ODE_MIGRATION_PILOT=1`;
- selected file exists, has exact basename
  `warehouse_pilot_candidate.db` and is not the same file as
  `data/warehouse.db`;
- exactly one `ODE_MIGRATION_PILOT` marker with stage `0.13.3A.5`, status
  `READY_FOR_REVIEW`, `pilot_only=1` and `review_read_only=1`;
- exact required pilot table set and no unknown `migration_pilot_*` tables;
- `integrity_check=ok`, empty `foreign_key_check`, no `-wal`, `-shm` or
  `-journal` sidecar.

A marker DB without the environment flag and a flag without a valid marker both
fail. Launchers only validate/start an existing artifact; they never create,
overwrite or install a database.

### Roles and HTTP surface

Only authenticated `admin` and `engineer` may call:

- `GET /api/migration-pilot` for allowlisted list/filter/search data;
- `GET /api/position-card?pilot_selection_id=<positive id>` for an `IMPORT`
  row or linked duplicate/conflict row that resolves to the same primary card;
- ordinary `GET /api/data`, which adds only safe pilot status metadata.

`viewer` is rejected by backend. Pilot mode hides mutation controls and denies
all operational POST routes in the handler; login/logout remain session
infrastructure. The denial is server-side and must not rely on CSS/JavaScript.
The card resolves by linked receipt ID and verifies exact source S/N rather than
accepting an arbitrary S/N path parameter.

### Data minimization and XSS

The browser projection is allowlisted. It excludes raw XML token, raw payload,
password hash, local absolute path and internal receipt linkage. Source filename
is reduced to basename; displayed DB path is logical/relative. Audit details
apply the same basename/path-redaction policy.

Pilot JS renders source/API strings through component `{text: ...}` /
`textContent` nodes; imported values are never assigned to `innerHTML`.
Selection IDs are parsed as positive integers. Query/filter/limit/offset are
bounded and filter values use a closed allowlist.

### Database sensitivity and mutations

The pilot DB contains copied security rows plus detailed source provenance, so
it has backup-level local sensitivity and POSIX mode `0600`. It is ignored and
must not be committed, packaged, uploaded through Administration or shared as a
release artifact.

The builder is the only pilot writer and owns one transaction. It may insert
only rows classified `IMPORT`; quarantine, duplicate, conflict-history,
quantity and corrupted decisions cannot create receipts. Runtime opens pilot
review queries read-only and provides no approval/edit/destructive API.
Pilot startup explicitly disables the normal `WarehouseService` schema
initializer after marker validation; this option is pilot-only and defaults to
normal initialization everywhere else. Headless smoke additionally requires
the runtime copy's SHA to remain unchanged across the full browser scenario.

### NOT PRODUCTION / FUTURE 0.13.3B

Manual review does not grant a production permission. Case-distinct S/N schema,
numeric approval, reference approval and bulk historical import/reset require a
separate ADR, role/audit contract, backups and explicit confirmation.
