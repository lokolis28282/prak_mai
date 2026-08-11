# Windows release procedure — ODE 0.21.0

Статус на 2026-08-11: source-ZIP `ODE_0.21.0_windows_source.zip` собран и
проверен; его внешний SHA-256 хранится рядом с конкретным артефактом. ZIP
нельзя называть утверждённым рабочим rollout до физического Windows sign-off.

## Что входит и не входит в code release

Релиз содержит код, статические ресурсы, launcher и документацию. Он не должен
содержать рабочие, тестовые или candidate-БД, backup, exports, migration raw/
normalized/workspace, пароли и локальные правила Monitoring.

Три runtime-файла сохраняются отдельно от обновления кода:

- `data\warehouse.db` — IXcellerate и primary application contour;
- `data\warehouse_solar.db` — Solar Warehouse;
- `data\vacations.db` — изолированный Vacations bounded context.

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

`start_test_windows.bat` создаёт три disposable DB: IXcellerate demo, пустой
Solar и чистый Vacations. Рабочие Warehouse-БД открываются только на чтение,
рабочая Vacations DB не используется. Баннер `ТЕСТОВЫЙ КОНТУР` обязателен.

## Backup и restore

Administration создаёт allowlisted snapshot выбранной runtime-БД через SQLite
Backup API во внешний каталог. По умолчанию используется системный каталог;
оператор может задать `ODE_BACKUP_DIR`. Каталог внутри source/package запрещён.

Restore UI остаётся fail-closed в ODE 0.21.0. В package не должно быть рабочей
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

До физического Windows sign-off актуальным считается source ODE 0.21.0 и его
проверенный переносимый кандидат, а не утверждённый рабочий rollout.
