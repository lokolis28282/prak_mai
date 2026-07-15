# TEST_DATABASE_GUIDE

Для нагрузки FULL Inventory используйте
`python3 scripts/benchmark_full_inventory.py --sizes 1000 10000 50000`.
Скрипт создаёт DB/XLSX во временном каталоге, проверяет byte-identical fixture
DB и не принимает путь к `data/warehouse.db`.

Как получить и использовать одноразовую тестовую копию БД ODE, не трогая
рабочую `data/warehouse.db`.

**FACT (source Stage 0.13.3A; runtime metadata `0.12.17.1 RC2`):** этот UI test
contour и migration candidate — разные артефакты. Команды ниже продолжают
создавать `data/warehouse_test_clean.db`; они не строят reference staging.

## Скрипт

```bash
python3 scripts/create_clean_test_db.py --dry-run
python3 scripts/create_clean_test_db.py --profile empty
python3 scripts/create_clean_test_db.py --profile demo --overwrite
```

Аргументы:

- `--source` — рабочая база-источник (по умолчанию `data/warehouse.db`).
  Скрипт открывает ее через SQLite `mode=ro` + `query_only`, строит
  согласованный Backup API snapshot (включая committed WAL) и никогда не
  пишет в источник.
- `--output` — путь к создаваемой тестовой базе (по умолчанию
  `data/warehouse_test_clean.db`).
- `--profile empty` — очистить операционные данные, ничего не добавлять.
- `--profile demo` — очистить операционные данные и добавить небольшой
  демонстрационный набор (2 сервера, 1 SSD, 1 кабель, одно списание, один
  лог работ, одна поставка) через ту же S/N-first модель
  (`stock_receipts`/`stock_issues`), что использует само приложение.
- `--dry-run` — ничего не создавать и не изменять, только показать, что было
  бы сделано (количество строк по таблицам, путь вывода).
- `--overwrite` — обязателен, если `--output` уже существует.

Гарантии:

- `--source` и `--output` не могут указывать на один и тот же файл (жесткая
  проверка, скрипт завершается с ошибкой);
- SHA-256 main DB, WAL и rollback journal источника печатаются до и после
  запуска и должны совпадать (`-shm` не сравнивается: это transient
  coordination state SQLite);
- после сборки тестовой базы выполняются `PRAGMA integrity_check` и
  `PRAGMA foreign_key_check`; при ошибке скрипт завершается кодом 1 и не
  оставляет `--output` в частично записанном состоянии;
- рабочая копия при сборке пишется во временный файл системного `/tmp`, а не
  рядом с `--output`, — это осознанное решение (не только для изоляции): на
  синхронизируемых/сетевых точках монтирования проектной папки прямая запись
  SQLite-журнала может завершаться ошибкой `disk I/O error`, тогда как в
  системный временный каталог запись всегда работает; готовая БД проходит
  integrity/FK-проверки, копируется во временный файл рядом с `--output`,
  повторно сверяется по SHA-256 и публикуется атомарным `os.replace`;
- существующий output сохраняется при любой ошибке до атомарной замены;
  overwrite блокируется, если рядом есть `.db-wal`, `.db-shm` или
  `.db-journal`, а source/output hardlink запрещен.

## Что очищается (операционные данные)

`stock_receipts`, `stock_issues`, `stock_issue_allocations`, `deliveries`,
`delivery_lines`, `work_logs`, `daily_report_uploads`, `daily_report_rows`,
`audit_log`, legacy `equipment`, legacy `operations`.

## Что сохраняется без изменений

`users` (включая хеши паролей и роли, в том числе администратора),
`categories`, `locations`, `reference_values` (справочники).

## Тестовый запуск

```bash
./start_test_macos.command      # macOS
start_test_windows.bat          # Windows
```

Оба launcher'а перед запуском пересобирают `data/warehouse_test_clean.db`
командой `create_clean_test_db.py --profile demo --overwrite`, затем
запускают `app.py web --db data/warehouse_test_clean.db` с переменной
окружения `ODE_TEST_MODE=1`. При этом флаге сервер добавляет в HTML баннер
«ТЕСТОВЫЙ КОНТУР — изменения не влияют на рабочую базу» (виден на экране
входа и во всем интерфейсе). Обычные `start_macos.command` /
`start_windows.bat` эту переменную не устанавливают и всегда открывают
`data/warehouse.db`. Флаг изолирован внутри процесса launcher'а (`setlocal`
на Windows, inline environment на macOS), а сервер fail-fast отказывается
стартовать, если `ODE_TEST_MODE=1` совмещён с рабочей БД или её hardlink.

Кнопки полной очистки рабочей БД в обычном интерфейсе нет и не планируется —
только этот отдельный CLI-скрипт и его launcher'ы.

## Offline migration candidate Stage 0.13.3A

**IMPLEMENTED:** reference/staging candidate строится отдельным CLI в ignored
workspace:

```bash
python3 scripts/migration_reference_data.py inspect-sources
python3 scripts/migration_reference_data.py build-candidate --overwrite
python3 scripts/migration_reference_data.py validate-candidate
python3 scripts/migration_reference_data.py report
```

Report всегда регенерируется из candidate/source checks после полного
path/inode guard; старый JSON не является входом и не merge-ится.

Default output:
`migration_inputs/workspace/warehouse_migration_candidate.db`. Candidate
содержит чистую актуальную production-схему, security snapshot и девять
candidate-only reference/staging tables. Таблицы складских операций и audit в
нём должны быть пустыми. Исходные XLSX/TXT и `data/warehouse.db` проверяются
по SHA до/после; рабочая БД открывается `mode=ro` + `query_only`.

Candidate нельзя:

- передавать `app.py web --db` как рабочий склад;
- копировать в `data/warehouse.db`;
- коммитить вместе с raw или другими generated artifacts;
- считать утверждённым импортом справочников, приходов или расходов.

**FUTURE STAGE:** замена тестовой operational DB реальными данными потребует
двух проверенных backup, отдельной clean DB, manual approval candidate,
integrity/FK/reconciliation gate и явного подтверждения установки. Полный план
описан в [MIGRATION_DATABASE_RESET_PLAN.md](MIGRATION_DATABASE_RESET_PLAN.md).

## Preservation-aware pilot DB Stage 0.13.3A.5

**PILOT ONLY:** `warehouse_pilot_candidate.db` is a third, distinct contour:

- it is not `data/warehouse_test_clean.db`;
- it is not the Stage A `warehouse_migration_candidate.db`;
- it is never `data/warehouse.db`;
- it contains exactly the selected pilot operations/provenance and an exact
  marker permitting only read-only review mode.

Only `start_migration_pilot_macos.command` or
`start_migration_pilot_windows.bat` may launch it. Unlike test launchers, pilot
launchers do not rebuild the DB. They require `ODE_MIGRATION_PILOT=1`, validate
marker/name/stage/status, integrity/FK and no sidecars, then print the actual
selected path. The ordinary application must refuse a marked pilot DB without
the explicit flag.

Pilot runtime denies operational writes. Headless tests must use a temporary
copy and never leave WAL/SHM/journal next to the review artifact. Delete the
disposable DB only after stopping the server; do not use the clean-test-DB
generator to transform it and never copy it over the working DB.

The pilot DB is generated by the dedicated migration pilot CLI, documented in
[MIGRATION_PILOT_REVIEW_GUIDE.md](MIGRATION_PILOT_REVIEW_GUIDE.md). Its manual
approval is not the production reset gate.
