# UI Contract ODE 0.13

Статус: **APPROVED CONTRACT — UI не реализован**

## Общие состояния

Каждый data screen обязан иметь Loading, Empty, Error, Stale и PermissionDenied.
Loading не очищает уже показанные проверенные данные. Stale показывает причину
и refresh action; write confirmation при stale запрещен. Tables используют
server keyset pagination, default 50/max 200, без загрузки полного набора.

Keyboard: логичный tab order, Enter не подтверждает destructive modal,
Escape закрывает только non-committed dialog, focus возвращается инициатору.
WCAG labels/status live regions обязательны. Mobile minimum поддерживает read,
exact scan lookup и простые receipt/issue; 1 млн-row review ориентирован на
desktop и использует responsive columns.

## Экраны

| Экран | Цель и данные | Действия / permission | Special states и audit visibility |
|---|---|---|---|
| Вход | Login, password, session notice | Login | Generic auth errors; no account enumeration |
| Домашний | balance state, active snapshot, ledger head, freezes, jobs | Навигация по role | NOT_INITIALIZED banner; projection inconsistency critical |
| Склад | Paginated transaction feed and stock summary | Read; create permitted transaction | Freeze/stale; actor/audit link |
| Баланс | Projection version, keyset rows, filters | Read/export report | NOT_INITIALIZED ≠ empty; checksum/version visible |
| Оборудование | Exact identity/search, equipment detail | Read; admin identity correction/merge | Ambiguous S/N grouped; raw/current identity |
| История | Unified timeline by exact S/N | Read/filter source types | Legacy source clearly labeled; date/actor quality visible |
| Приход | Destination, subject, quantity, document/comment | WAREHOUSE_RECEIPT | Idempotent submit; confirmation includes projection version |
| Расход | Source, subject, available quantity, recipient/reason | WAREHOUSE_ISSUE | Insufficient/stale blocks; no optimistic decrement |
| Перемещение | From/to, subject, quantity | WAREHOUSE_TRANSFER | Same-location blocked; net-zero explanation |
| Корректировка | In/out, evidence, reason, impact | Admin+reauth | Strong warning; audit link after post |
| Reversal dialog | Original immutable transaction, baseline and exact inverse | Admin+reauth | `REVERSAL_UNSAFE` explains unsafe inverse; `REVERSAL_OUTSIDE_ACTIVE_BASELINE` explains rebaseline and offers adjustment/transfer |
| Инвентаризация | Session state, freeze, source hash, counts | Create/upload/reject/approve by permission | Workflow status and crash recovery |
| Preview | Progress, fingerprints, statistics | Start/cancel/rerun | Source hash and no-operational-write statement |
| Findings | Paginated blocking/warning groups and raw cells | Resolve/waive allowed codes | Each resolution actor/reason; stale digest |
| Approval summary | Totals, new/missing/conflicts, reconciliation, cutoff | Explicit approve | Type inventory external ID or confirmation phrase; publish progress |
| Справочники | Domains, values, aliases, provenance/impact | Admin edit/decision/merge | Pending never silently canonical |
| Audit | Filtered immutable events | Admin/auditor read/export | Correlation navigation; sensitive details redacted |
| Backup/restore | Manifests, hashes, verification, storage | Admin+reauth | Restore two-step validate/confirm; maintenance state |
| Профиль | User/session list, password | Own profile/revoke session | Credential change invalidates other sessions |
| Reports | Job type, parameters, progress/artifact | Role-dependent | Report fingerprint; expired artifact |
| Diagnostics | DB/app state, no secrets | Admin/auditor limited | Read action audited |

Monitoring и reports имеют отдельные navigation modules и не добавляют
warehouse writes.

## Inventory flow

UI отображает source SHA, template/parser/reference versions и preview digest
на каждом review screen. Resolution изменяет отдельный resolution record, а raw
cell остается рядом. Approval button отсутствует, пока API не сообщает
READY_FOR_APPROVAL.

Во время APPROVING UI poll/stream читает publish job; повтор button не создает
новый publish благодаря idempotency key. Browser close не отменяет server job.

## Forms

- Client validation улучшает UX, server validation authoritative.
- Quantity вводится locale-aware, но API получает canonical minor units.
- S/N/Inventory Number никогда не coercion number и не auto-trim display raw.
- Scanner input exact text показывается до submit.
- Destructive/sensitive commands требуют reason; adjustment/reversal/restore
  требуют reauthentication.
- Submit disabled только визуально не считается idempotency protection.

## API mapping

Каждое действие использует endpoint из [api-contract.md](api-contract.md).
Запрещены hidden action routes и direct filesystem calls. Permission-based UI
visibility не заменяет server authorization.

## Frontend architecture

- ES modules per feature;
- one application shell and route registry;
- typed API client/generated DTO validation;
- addEventListener, no inline handlers;
- safe DOM/textContent; sanitized allowlist only for rich content;
- no service state in window globals;
- localStorage may store presentation preferences, never session, Preview or
  authoritative drafts;
- browser payload <=2 MiB per page and <=200 rows.
