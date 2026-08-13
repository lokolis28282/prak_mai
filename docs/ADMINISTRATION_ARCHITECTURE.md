# Administration Architecture — ODE 0.21.1

Administration владеет административным контуром ODE:

- текущий пользователь и профиль;
- пользователи и роли;
- единый audit log;
- список резервных копий;
- topology, status и диагностика трёх runtime-БД;
- создание проверенного snapshot выбранной allowlisted DB через SQLite Backup
  API во внешний каталог;
- административные read-only данные для UI.

## Stage 0.12.9

В 0.12.9 web/API слой получает read-only административные данные через:

`inventory/routes/administration.py -> ApplicationContext -> AdministrationFacade -> AdministrationService`

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
- делегированный engineer session context для обычного входа по ФИО.

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
- backup list/create и database diagnostics доступны только admin;
- restore и production DB upload не отображаются как доступные действия и
  остаются fail-closed.

## Историческая граница Stage 0.12.9

В Stage 0.12.9 оставались legacy:

- login/logout;
- create user;
- change password;
- update profile;
- create/restore backup;
- production DB upload;
- explicit integrity check action.

В текущем ODE 0.21.1 login/users/profile/diagnostics и создание multi-DB
snapshot уже принадлежат `AdministrationService`. Из перечисленного опасные
restore/upload остаются недоступными, а logout является только операцией
in-memory HTTP session.
