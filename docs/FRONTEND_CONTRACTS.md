# FRONTEND_CONTRACTS

## Warehouse stabilization contract

- постоянной строки глобальных модулей нет; ODE возвращает на module cards;
- Warehouse subnav содержит ровно семь складских разделов;
- Monitoring и Reports UI показывают только «В разработке»; готовый Monitoring
  hostname-routing backend не включается скрыто без отдельного UI/API slice;
- `Администрирование ODE` видит только session user с backend permission;
- role может быть скрыта из UX, но frontend не заменяет backend check;
- reference dropdown использует `state.references`, active canonical значения
  и `parent_key` для vendor → model; hardcoded vendor/model arrays запрещены;
- draft schema v3 включает user, DB fingerprint, operation, step, fields, rows,
  timestamps и TTL 14 дней; restore только после явного выбора;
- смена вкладки сохраняет draft, но новая вкладка открывает начальный экран;
- scanner поддерживает delete one/selected/all и повторное добавление до confirm;
- global search: минимум 2 символа, debounce, AbortController, sequence guard,
  Arrow keys/Enter/Escape, safe DOM, loading/empty/controlled error;
- обычная Equipment Card не показывает migration confidence/raw XML/hash;
- Главная показывает ровно один вход в профиль — карточку `Профиль` в
  `.portal-grid` (рядом с `Мониторинг`); top bar `.profile-actions` не
  дублирует вход в профиль или смену пароля отдельными кнопками;
  `openShiftProfile()` остается единственной, role-aware точкой входа.

Дата актуализации: 2026-07-14

## Зачем нужен контракт

ODE сейчас находится в переходном состоянии: HTML-каркас приходит из `inventory/webapp.py`, часть UI вынесена в `static/js`, а часть legacy-разметки еще создается динамически. Ошибки `Cannot read properties of null` обычно появляются, когда JavaScript обращается к id, которого больше нет в HTML.

`scripts/audit_frontend_contracts.py` проверяет контракт HTML <-> JS:

- собирает id из `LOGIN_HTML` и итогового `HTML`;
- читает `inventory/webapp.py` и `static/js/*.js`;
- ищет статические обращения `getElementById("...")`, `byId("...")`, `querySelector("#...")`, `querySelectorAll("#...")`;
- выводит missing static ids;
- не падает на динамических id из whitelist.

## Как запускать

```bash
python3 scripts/audit_frontend_contracts.py
```

Ожидаемый результат:

```text
frontend-contracts: OK, no missing static ids
```

Exit code:

- `0` - явных missing static id нет;
- `1` - найдено обращение к id, которого нет в HTML и нет в whitelist.

## Как добавлять новые id

1. Если элемент статический, добавьте его в HTML-шаблон или компонент.
2. Если JS обращается к нему через `getElementById`, `byId` или `querySelector("#...")`, запустите audit.
3. Если audit показывает missing id, исправьте HTML/компонент, а не whitelist.

## Как добавлять whitelist

Whitelist допустим только для id, который создается динамически до использования:

- wizard-поля;
- preview-контейнеры;
- lazy panels;
- временные элементы, создаваемые конкретной render-функцией.

Добавление в whitelist делается в `DYNAMIC_ID_WHITELIST` внутри `scripts/audit_frontend_contracts.py`. Рядом должна быть понятная группа или комментарий. Нельзя добавлять id в whitelist, если элемент должен существовать в базовом HTML.

## Ограничения

Скрипт не является полноценным JavaScript parser. Он намеренно проверяет только статические строковые обращения. Динамические template string id и сложные CSS-селекторы должны покрываться smoke UI и ручным click smoke.

## Scanner Draft Isolation

Receipt/issue scanner drafts use an ODE-owned localStorage key scoped by all of
the following: draft schema version, stable working-DB/runtime fingerprint,
current user identity and operation kind. The payload repeats that scope,
contains `saved_at`/`expires_at`, and expires after 14 days. A key or payload
from another DB/user/version must not be restored.

Legacy `ode_receipt_draft`/`ode_issue_draft` keys are removed when inspected;
only those known ODE keys may be cleaned. Parse, quota, disabled-storage and
other localStorage errors are caught and cannot block UI startup. The ordinary
`Очистить` action removes the current scoped draft. Contract tests verify key,
version, TTL and error handling; browser smoke seeds the old receipt key and
requires it to disappear without showing an active draft.

The DB fingerprint comes from `/api/data.runtime.database_fingerprint`. A full
promoted working DB uses its stable migration build key, so drafts do not
depend on an inode changed by backup/atomic publication.

## Promoted Full Working UI

`migration_full.enabled` may be true for provenance diagnostics while
`migration_full.read_only` is false. Candidate banner/body classes, automatic
review landing and mutation hiding depend on `read_only`, not on marker
presence. Normal warehouse summary has four non-duplicated server-backed cards
and obtains total card/category/supplier values from the existing facade. The
technical full review is rendered only inside the admin migration subtab.

## Stage 0.13.2 Inventory Number Import

HTML shell обязан содержать статические targets:

- `#inventoryNumberCsv` — выбор CSV;
- `#inventoryNumberImport` — loading/error/preview/result container;
- `/static/js/warehouse/inventory.js` — runtime module.

Модуль использует `renderElement`, `renderCard`, `renderTable`, `renderButton`,
`renderBadge` и `replaceChildren`. S/N, Inventory Number, server messages и
статусы передаются только как `text`, без `innerHTML`. Confirm renderится только
для `engineer/admin` и только при server-side `can_confirm=true` плюс
непустом `preview_id`; backend permission остаётся обязательной границей.

Все шесть публичных статусов являются frontend/API contract. Их изменение
требует одновременной правки UI, архитектурного документа, contract tests и
headless smoke. Headless должен посещать этот блок (`inventoryNumbers=true`) и
фиксировать ноль console/window/unhandled/resource/HTTP/API500 errors.

## Stage 0.13.3A.5 Migration Pilot Review

`/static/js/warehouse/migration_pilot.js` dynamically creates the review panel
only when `/api/data.migration_pilot.enabled=true`. Its dynamic targets belong
to one render lifecycle and must remain covered by frontend audit/headless tests.

Imported/API values—S/N, source/canonical names, warnings, vendor/model and
source coordinates—are passed only as component `{text: ...}` / text nodes.
They must never be interpolated into `innerHTML`. The permanent pilot banner is
static trusted shell text; the displayed database value is a server-provided
logical path, never an absolute path.

Filters are the closed set `IMPORT`, `QUARANTINE`, `CONFLICT`, `CORRUPTED`.
`IMPORT` rows and linked `EXACT_DUPLICATE`/`CONFLICT_HISTORY_ONLY` rows render
an Equipment Card button; all linked rows open the single imported primary
card. That button sends the positive `pilot_selection_id`, never a user-provided
normalized S/N. Backend role/mutation enforcement remains authoritative even
though normal section and mutation controls are hidden in pilot mode.

Pilot headless coverage must exercise a leading-zero S/N card, source/canonical
names, Timeline and conflict/quarantine filters while keeping
console/window/unhandled/resource/HTTP/API500 counters at zero.
