# Administration API Migration ODE 0.12.9

Stage 0.12.9 переводит только read-only административные маршруты на `AdministrationFacade`.
URL, JSON, роли, авторизация, БД и пользовательское поведение не меняются.

## Карта endpoint

| URL | Method | Текущий legacy-метод | Целевой метод `AdministrationFacade` | Роль | Читает | Формат ответа | Экран | Риск |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `/api/data` | GET | `service.current_user()` через compatibility service | `get_current_user()` / `get_profile()` | Любой вошедший пользователь | `users` только текущая запись | Общий JSON приложения, ключ `current_user` | Все экраны, профиль | Средний: нельзя раскрыть `password_hash`, нельзя сломать engineer-session override |
| `/api/admin` | GET | `service.list_backups()`, `service.audit_entries()`, `service.users()` | `get_administration_overview()` | `admin` | `users`, `audit_log`, `data/backups/*.db` | `{backups,audit,users}` | Администрирование | Средний: role check и сортировка должны сохраниться |
| `/export/audit.csv` | GET | `service.audit_entries(limit=5000)` | `list_audit_entries(limit=5000)` | `admin` | `audit_log` | CSV `action_log.csv`, UTF-8 BOM | Журнал действий | Низкий: сохранить заголовки и порядок строк |

## Не мигрируется в этом этапе

| Flow | Причина |
| --- | --- |
| `/api/login` | authentication/write-flow session; остается compatibility-layer |
| `/api/logout` | session write-flow |
| `CREATE_USER` | write/admin action |
| `CHANGE_PASSWORD` | write/admin action |
| `UPDATE_PROFILE` | write-flow профиля |
| `CREATE_BACKUP` | filesystem/write action |
| `RESTORE_BACKUP` | filesystem/write action |
| `CHECK_DATABASE` | явное admin action с audit-записью |
| `/api/upload-prod-db` | destructive write action |

## Контракт фасада

`AdministrationFacade` предоставляет read-only методы:

- `get_current_user()`
- `get_profile()`
- `list_users()`
- `get_user(email)`
- `list_audit_entries(limit=200, filters=None)`
- `list_backups()`
- `get_database_status()`
- `get_administration_overview()`
- `get_diagnostics_summary()`

Все методы возвращают plain `dict/list`, не возвращают `sqlite3.Row`, `password_hash`, cookie/session token или секреты.

## Фактический статус 0.12.9

Мигрированы:

- `/api/data` для `current_user`;
- `/api/admin`;
- `/export/audit.csv`.

Оставлены legacy:

- login/logout;
- profile update;
- password change;
- user create/role changes;
- backup/create/restore;
- integrity check action;
- production DB upload.
