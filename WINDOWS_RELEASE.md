# Windows release procedure — ODE 0.21.1

Статус на 2026-08-13: patch source-ZIP
`ODE_0.21.1_windows_source.zip` проходит финальный release gate; его внешний
SHA-256 хранится рядом с конкретным артефактом. ZIP нельзя называть
утверждённым рабочим rollout до физического Windows sign-off по
`docs/MANUAL_TESTING_0_21_1_WINDOWS.md`.

Архивы 0.21.0 отозваны для повторного переноса. Ошибки `'3' is not recognized`,
`'cho' is not recognized` или `'DE' is not recognized` указывают на
повреждённое для `cmd.exe` представление BAT,
а `ModuleNotFoundError: baseline_rehearsal` — на неполный runtime closure.
Такой каталог нельзя ремонтировать вручную или смешивать с новым кодом. Рабочие
SQLite-файлы не менять; 0.21.1 распаковать в новую папку и переносить данные
только после SHA/integrity/FK-проверок.

## Что входит и не входит в code release

Релиз содержит код, статические ресурсы, launcher и документацию. Он не должен
содержать рабочие, тестовые или candidate-БД, backup, exports, migration raw/
normalized/workspace, пароли и локальные правила Monitoring.

Три runtime-файла сохраняются отдельно от обновления кода:

- `data\warehouse.db` — IXcellerate и primary application contour;
- `data\warehouse_solar.db` — Solar Warehouse;
- `data\vacations.db` — изолированный Vacations bounded context.

В source package входит безопасный `.env.example`, но ODE не загружает `.env`
автоматически. API-key/Bearer/OAuth вход не реализован; фактические
CLI/env-параметры и cookie-auth описаны в `docs/RUNTIME_CONFIGURATION.md` и
`docs/AUTHENTICATION_AND_API_ACCESS.md`.

Перед подготовкой пакета остановите writers, сделайте внешний byte-copy всех
трёх файлов и проверенный SQLite backup. Зафиксируйте SHA-256, `integrity_check`
и пустой `foreign_key_check` до и после процедуры.

## Release gate

1. Обновить версию и все living-документы одним логическим изменением.
2. Выполнить Documentation Gate из `AGENTS.md`.
3. Прогнать полный набор Python/JS/audit/unit/headless проверок.
4. Проверить обычный `python app.py` на копии рабочего контура и три launcher-
   сценария: обычный, test и migration pilot.
5. На Windows вручную проверить вход, выбор площадки, поиск, приход/расход,
   карточку и состав оборудования, Reports, Monitoring, Knowledge, Vacations,
   Administration backup и завершение через `Ctrl+C`.
6. Убедиться, что runtime-БД не изменились от read-only smoke.

Команда сборки после отдельного release change:

```bat
py -3 build_windows_package.py
```

Builder обязан синхронно использовать текущие `__version__`, package name,
release notes и подтверждённое число тестов. Нельзя публиковать старое имя
архива с новым содержимым.

## Test launcher

`start_test_windows.bat` создаёт три новые disposable DB:
`warehouse_test_disposable_v1.db`,
`warehouse_solar_test_disposable_v1.db` и
`vacations_test_disposable_v1.db`. Legacy unmarked `*_test_clean.db` не
используются. Рабочие Warehouse-БД открываются только на чтение, committed WAL
включается в Backup API snapshot; рабочая Vacations DB не используется.

Все три target имеют marker `ODE_DISPOSABLE_TEST_DB_V1` с ролями
`warehouse`/`warehouse`/`vacations`. Test startup требует три явных пути и
правильные роли; ordinary startup marked test DB отвергает. Overwrite допустим
только для ранее marked target той же роли. Любой selected SQLite sidecar
(`-wal`, `-shm`, `-journal`) блокирует startup до writes. Баннер
`ТЕСТОВЫЙ КОНТУР` обязателен.

Auxiliary state test/review-контура (FULL Inventory, Knowledge, Monitoring и
backup) принудительно размещается во временном owned root; production env/path
не наследуются, live DCIM отключён, cleanup выполняется при завершении.

## Backup и restore

Administration создаёт allowlisted snapshot выбранной runtime-БД через SQLite
Backup API во внешний каталог. По умолчанию используется системный каталог;
оператор может задать `ODE_BACKUP_DIR`. Каталог внутри source/package запрещён.

Restore UI остаётся fail-closed в ODE 0.21.1. В package не должно быть рабочей
кнопки или инструкции «выбрать файл и восстановить». Полный restore требует
остановки writers, allowlisted database id, manifest/provenance, страховочной
копии, sibling `.next`, integrity/FK и атомарной публикации — см.
[ADR-013](docs/decisions/ADR-013-multi-database-backup-restore.md).

## Приёмочные артефакты

Для нового ZIP сохранить вне репозитория:

- имя и SHA-256 архива;
- версию Python/Windows и время сборки;
- полный test/gate log;
- список файлов пакета с подтверждением отсутствия данных и секретов;
- результаты установки в новую папку и обновления существующей установки;
- SHA-256 и integrity/FK всех трёх runtime-БД до/после;
- датированный Windows manual QA verdict.

До физического Windows sign-off актуальным считается source ODE 0.21.1 и его
release-candidate report, а не утверждённый рабочий rollout. Итог double-click
приёмки должен быть записан в новый manual QA; отсутствие этой записи означает
**PENDING**, а не PASS.
