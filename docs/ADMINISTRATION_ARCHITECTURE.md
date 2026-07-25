# Administration Architecture

Administration владеет административным контуром ODE:

- текущий пользователь и профиль;
- пользователи и роли;
- единый audit log;
- список резервных копий;
- легкий статус БД и диагностика;
- административные read-only данные для UI.

## Stage 0.12.9

В 0.12.9 web/API слой получает read-only административные данные через:

`inventory/routes/administration.py -> ApplicationContext -> AdministrationFacade -> compatibility service`

С ODE 0.16.0 Stage 3 `WarehouseCore` остается только deprecated compatibility
adapter без business SQL. Administration по-прежнему является отдельной
реализацией и не зависит от Warehouse composition.

С ODE 0.16.0 Stage 4 `inventory/webapp.py` отвечает только за общий HTTP shell,
auth/session/security и dispatch; административные HTTP-ветви принадлежат
`inventory/routes/administration.py`.

## Профиль и Administration

Профиль текущего пользователя:

- `first_name`;
- `last_name`;
- `position`;
- `email`;
- `role`;
- `must_change_password`;
- engineer-session override для обычного входа по ФИО.

Административная информация:

- список пользователей;
- audit entries;
- backup files;
- database status;
- diagnostics summary.

Профиль доступен по существующим правилам авторизации. Административные данные остаются `admin`-only.

## Read Contract

`AdministrationFacade`:

- `get_current_user()`;
- `get_profile()`;
- `list_users()`;
- `get_user(email)`;
- `list_audit_entries(limit=200, filters=None)`;
- `list_backups()`;
- `get_database_status()`;
- `get_administration_overview()`;
- `get_diagnostics_summary()`.

## Security Rules

- `password_hash` не возвращается наружу;
- session token/cookie не возвращается наружу;
- абсолютные пути backup не возвращаются в read API;
- audit read доступен только admin;
- users read доступен только admin;
- backup list доступен только admin;
- write/admin actions остаются compatibility-layer до отдельного этапа.

## Legacy

Остаются legacy:

- login/logout;
- create user;
- change password;
- update profile;
- create/restore backup;
- production DB upload;
- explicit integrity check action.
