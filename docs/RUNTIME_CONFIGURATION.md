# ODE 0.21.0 — runtime-конфигурация

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
`start_test_*` создают отдельные disposable DB и включают `ODE_TEST_MODE=1`.

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
| `ODE_TEST_MODE=1` | `start_test_*`, disposable DB | Startup отклоняет рабочую `data/warehouse.db` и её hardlink. |
| `ODE_MIGRATION_PILOT=1` | marker-guarded pilot DB | Требует точное имя/marker/stage/status, integrity/FK и отсутствие sidecars. |
| `ODE_FULL_MIGRATION_CANDIDATE=1` | full migration review DB | Только read-only review; не обычный launcher и не production DB. |

Не сохраняйте эти flags глобально в профиле пользователя. Обычный запуск с
review flag и рабочей БД обязан завершиться fail-closed.

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
