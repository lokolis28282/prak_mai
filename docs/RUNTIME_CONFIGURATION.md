# ODE 0.21.1 — runtime-конфигурация

Patch сохраняет CLI/env defaults и добавляет fail-closed защиту от выбора
production runtime-файла для test/disposable DB.

Статус: **CURRENT RUNTIME CONTRACT**. Этот документ перечисляет поддержанные
аргументы процесса и env-переменные. Он не является инструкцией сетевого
production deployment.

## Как задаётся конфигурация

ODE читает параметры командной строки и environment текущего процесса.
`.env.example` — только безопасный пример: приложение **не загружает `.env`
автоматически**. На Windows используйте `set NAME=value` в текущем `cmd`, в
PowerShell — `$env:NAME='value'`, на macOS/Linux — `NAME=value command`.

Обычный рабочий запуск не требует специальных переменных:

```bash
python3 app.py
```

## Аргументы web runtime

Полная форма: `python3 app.py web [options]`.

| Аргумент | Default | Назначение |
|---|---|---|
| `--db` | `data/warehouse.db` | Primary IXcellerate/application DB. Не подставлять test/candidate вместо рабочей. |
| `--solar-db` | вычисляется рядом с primary | Отдельная Solar Warehouse DB. |
| `--vacations-db` | `data/vacations.db` для обычного запуска | Отдельная Vacations DB. |
| `--host` | `127.0.0.1` | Адрес прослушивания. `0.0.0.0` не является утверждённым production profile. |
| `--port` | `8765` | Локальный HTTP-порт. |
| `--no-browser` | false | Не открывать браузер автоматически. |
| `--warehouse-contour` | `production` | `demo` допустим только с отдельной disposable DB. |
| `--inventory-state-root` | системный внешний state root | Workspace FULL Inventory; не размещать в Git/release. |

`start_windows.bat` и `start_macos.command` используют безопасные defaults.
`start_test_*` создают отдельные disposable DB, явно передают все три пути и
включают `ODE_TEST_MODE=1` только для дочернего процесса.

В test и marker-guarded pilot/full review значения production auxiliary env не
используются: state FULL Inventory, Knowledge uploads, Monitoring rules и
backup roots принудительно направляются во временный owned-каталог. Live DCIM
отключён; временный каталог очищается при завершении runtime.

## Рабочие env-переменные

| Переменная | Default | Контракт и чувствительность |
|---|---|---|
| `ODE_BACKUP_DIR` | внешний системный каталог | Корень verified multi-DB backup. Должен находиться вне репозитория; это не путь restore от HTTP-клиента. |
| `ODE_KNOWLEDGE_UPLOAD_DIR` | `data/uploads` рядом с primary DB | Private attachments Knowledge. Каталог ignored, требует собственного backup/retention. |
| `ODE_KNOWLEDGE_MAX_ATTACHMENT_MB` | `15` | Целое 1…50; неверное значение возвращает default 15. |
| `ODE_ALLOWED_HOSTS` | пусто | Дополнительные hostname через запятую для POST Origin/Host проверки. Не включает TLS и не делает LAN/server deployment безопасным. |

## Monitoring

| Переменная | Default | Назначение |
|---|---|---|
| `ODE_MONITORING_DCIM_BASE_URL` | `https://dcim.x5.ru` | Базовый URL optional DCIM collector; не API-key. |
| `ODE_MONITORING_RULES_DIR` | `data/monitoring` | Каталог `Hostname Tech.json` и `Hostname Digital.json`; содержит corporate data, не коммитится. |
| `ODE_MONITORING_EDGE_PROFILE_DIR` | платформенный Edge profile | Локальный профиль браузера для разрешённой DCIM-сессии; считать credential material. |
| `ODE_MONITORING_COLLECT_DCIM` | `true` | `true/false`: разрешить явный live сбор после нажатия пользователем. |
| `ODE_MONITORING_HEADLESS` | `false` | Запустить Edge без видимого окна; для первичной авторизации обычно нужен `false`. |
| `ODE_MONITORING_DEV_MOCK` | `false` | Явный development mock. Допустим только на test contour; результат маркируется `[DEV]`. |

Boolean принимает `1/true/yes/on` и `0/false/no/off` без учёта регистра;
другое значение завершает конфигурацию контролируемой ошибкой.

Live collector требует отдельной установки
`requirements-monitoring.txt` и совместимого Microsoft Edge/WebDriver. Без
live collector основной runtime остаётся stdlib-only. ODE не отправляет
email/Rooms и не принимает transport API keys.

## Только test/review режимы

| Переменная | Где допустима | Защита |
|---|---|---|
| `ODE_TEST_MODE=1` | `start_test_*`, три явные disposable DB | Обязательны `--db`, `--solar-db`, `--vacations-db`; marker `ODE_DISPOSABLE_TEST_DB_V1` и роли `warehouse`/`warehouse`/`vacations`. Production aliases, неверная роль, отсутствие marker и любой SQLite sidecar отклоняются до writes. |
| `ODE_MIGRATION_PILOT=1` | marker-guarded pilot DB | Требует точное имя/marker/stage/status, integrity/FK и отсутствие sidecars. |
| `ODE_FULL_MIGRATION_CANDIDATE=1` | full migration review DB | Только read-only review; не обычный launcher и не production DB. |

Не сохраняйте эти flags глобально в профиле пользователя. Обычный запуск с
review flag и рабочей БД обязан завершиться fail-closed.

`scripts/create_clean_test_db.py` и
`scripts/create_clean_vacations_test_db.py` применяют ту же allowlist boundary:
ни один disposable output не может указывать на любую из трёх runtime-БД или
быть её filesystem alias. Existing output перезаписывается только с
`--overwrite`, exact marker `ODE_DISPOSABLE_TEST_DB_V1` и той же ролью;
unmarked/foreign DB и target с `-wal`/`-shm`/`-journal` остаются нетронутыми.
Непосредственно перед атомарной заменой builders повторно проверяют marker,
роль, inode/content metadata и sidecars; target, появившийся или изменившийся
за время сборки, не заменяется.

Штатные пути 0.21.1:

- `data/warehouse_test_disposable_v1.db` — IXcellerate, роль `warehouse`;
- `data/warehouse_solar_test_disposable_v1.db` — Solar, роль `warehouse`;
- `data/vacations_test_disposable_v1.db` — Vacations, роль `vacations`.

Legacy unmarked `*_test_clean.db` launcher не использует и не переименовывает.
Обычный production startup отвергает marked test DB независимо от её имени.
Три выбранных runtime-path должны быть попарно различны (включая hardlink и
совпадение имени по регистру), а installation-owned IX/Solar/Vacations path
может использоваться только в своей роли.
Кроме test mode, любой обычный/review startup fail-closed, если рядом с любой
выбранной DB уже существует `-wal`, `-shm` или `-journal`; проверка завершается
до schema initialization.

Warehouse clean builder сохраняет источник неизменным: без фактического
sidecar idle persistent-WAL DB читается `mode=ro&immutable=1`; при существующем
committed WAL используется обычное read-only соединение и SQLite Backup API,
чтобы snapshot включал committed WAL rows. SHA-256 main DB/WAL/journal
сравниваются до и после.

## Чего нет

- `ODE_API_KEY`, bearer/JWT/OAuth configuration;
- SMTP, Rooms, Kaiten, ITSM или Zabbix credentials;
- автоматической загрузки `.env`;
- production TLS/reverse-proxy profile;
- разрешённого restore path/filename из HTTP request;
- автоматического backup schedule/rotation/encryption.

Текущая auth-модель описана в
[AUTHENTICATION_AND_API_ACCESS.md](AUTHENTICATION_AND_API_ACCESS.md). Перед
любым изменением путей БД используйте
[LOCAL_WORKING_DATABASE_RUNBOOK.md](LOCAL_WORKING_DATABASE_RUNBOOK.md).
