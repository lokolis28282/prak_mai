# TEST_DATABASE_GUIDE

Для нагрузки FULL Inventory используйте
`python3 scripts/benchmark_full_inventory.py --sizes 1000 10000 50000`.
Скрипт создаёт DB/XLSX во временном каталоге, проверяет byte-identical fixture
DB и не принимает путь к `data/warehouse.db`.

Как получить и использовать одноразовый тестовый контур ODE, не трогая три
рабочие БД: `data/warehouse.db`, `data/warehouse_solar.db` и
`data/vacations.db`.

**ORIGIN FACT (source Stage 0.13.3A; current runtime ODE 0.21.1):** этот UI
test contour и migration candidate — разные артефакты. Команды Warehouse ниже
создают `data/warehouse_test_disposable_v1.db` /
`data/warehouse_solar_test_disposable_v1.db`;
они не строят reference staging. Vacations получает отдельную пустую БД.

## Скрипт

```bash
python3 scripts/create_clean_test_db.py --dry-run
python3 scripts/create_clean_test_db.py --profile empty
python3 scripts/create_clean_test_db.py --profile demo --overwrite
python3 scripts/create_clean_test_db.py \
  --source data/warehouse_solar.db \
  --output data/warehouse_solar_test_disposable_v1.db \
  --profile empty --overwrite
python3 scripts/create_clean_vacations_test_db.py --overwrite
```

Аргументы:

- `--source` — рабочая база-источник (по умолчанию `data/warehouse.db`).
  Скрипт открывает ее через SQLite `mode=ro` + `query_only`, строит
  согласованный Backup API snapshot (включая committed WAL) и никогда не
  пишет в источник.
- `--output` — путь к создаваемой тестовой базе (по умолчанию
  `data/warehouse_test_disposable_v1.db`).
- `--profile empty` — очистить операционные данные, ничего не добавлять.
- `--profile demo` — очистить операционные данные и добавить небольшой
  демонстрационный набор (2 сервера, 1 SSD, 1 кабель, одно списание, один
  лог работ, одна поставка) через ту же S/N-first модель
  (`stock_receipts`/`stock_issues`), что использует само приложение.
- `--dry-run` — ничего не создавать и не изменять, только показать, что было
  бы сделано (количество строк по таблицам, путь вывода).
- `--overwrite` — обязателен, если `--output` уже существует, и разрешает
  замену только штатной disposable DB с marker той же роли. Неизвестный,
  legacy unmarked или production-файл остаётся нетронутым.

`create_clean_vacations_test_db.py` не копирует персональные данные из
рабочей Vacations DB. Он устанавливает актуальную пустую Vacations-схему в
`data/vacations_test_disposable_v1.db`, проверяет integrity/FK и публикует файл
атомарно. Рабочий путь, symbolic/hardlink рабочей БД, unmarked existing target
и target с SQLite sidecar-файлами отклоняются fail-closed.

Гарантии:

- `--source` и `--output` не могут указывать на один и тот же файл (жесткая
  проверка, скрипт завершается с ошибкой);
- SHA-256 main DB, WAL и rollback journal источника печатаются до и после
  запуска и должны совпадать (`-shm` не сравнивается: это transient
  coordination state SQLite);
- idle source в persistent WAL mode без фактического sidecar открывается через
  SQLite `mode=ro&immutable=1`, поэтому marker/read probe не создаёт пустые
  `-wal`/`-shm`; если committed `-wal` существует, источник открывается обычным
  read-only SQLite connection и Backup API включает committed WAL-строки в
  согласованный snapshot, не изменяя main DB/WAL/journal;
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
  `.db-journal`, а source/output hardlink запрещен;
- overwrite существующего target разрешён только при marker
  `ODE_DISPOSABLE_TEST_DB_V1` и совпадающей роли: `warehouse` для обоих
  складов, `vacations` для календаря.

## Marker и startup boundary

Штатные builders создают таблицу `ode_test_contour_marker` с точным marker
`ODE_DISPOSABLE_TEST_DB_V1`. IXcellerate и Solar получают роль `warehouse`,
Vacations — `vacations`.

- `ODE_TEST_MODE=1` принимает только три явно выбранных пути `--db`,
  `--solar-db`, `--vacations-db` с marker ожидаемой роли;
- ordinary startup отвергает любую выбранную marked test DB, даже если путь не
  совпадает со стандартным test-именем;
- production/default DB и их symlink/hardlink запрещены в test/demo contour;
- любой `-wal`, `-shm` или `-journal` рядом с любой выбранной runtime DB
  блокирует startup до инициализации схемы и других writes;
- marker читается immutable и fail-closed: probe не создаёт sidecar, а
  появившийся/существующий sidecar делает роль недействительной.
- IXcellerate, Solar и Vacations обязаны указывать на три разные физические БД;
  hardlink, совпадающее без учёта регистра имя и перестановка штатных путей
  между ролями отклоняются до любой записи;
- directory/FIFO/device и malformed marker считаются invalid, а не новым
  отсутствующим target;
- builders повторно сверяют marker, inode, size/timestamps и sidecars сразу
  перед `os.replace`; target, изменившийся во время долгой сборки, сохраняется.

Новые имена 0.21.1 — `warehouse_test_disposable_v1.db`,
`warehouse_solar_test_disposable_v1.db`, `vacations_test_disposable_v1.db`.
Legacy unmarked файлы `warehouse_test_clean.db`,
`warehouse_solar_test_clean.db`, `vacations_test_clean.db` не удаляются, не
переименовываются и не перезаписываются launcher'ом; благодаря новым именам они
не блокируют создание безопасного контура.

## Что очищается (операционные данные)

Candidate-only migration staging/provenance (`migration_*`) удаляется первым:
его FK указывают на promoted receipts/issues, а пустой marker в чистом
demo-контуре ошибочно выглядел бы как повреждённый full-migration candidate.
Затем очищаются `stock_receipts`,
`stock_issues`, `stock_issue_allocations`, `deliveries`,
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

Оба launcher'а перед запуском пересобирают три disposable target:

- `data/warehouse_test_disposable_v1.db` — IXcellerate с demo-операциями;
- `data/warehouse_solar_test_disposable_v1.db` — Solar без operational rows;
- `data/vacations_test_disposable_v1.db` — пустая актуальная Vacations-схема.

Затем launcher явно передаёт все три marker-validated пути в `app.py web` вместе с
`--warehouse-contour demo` и переменной окружения `ODE_TEST_MODE=1`. При этом
флаге сервер добавляет в HTML баннер
«ТЕСТОВЫЙ КОНТУР — изменения не влияют на рабочую базу» (виден на экране
входа и во всем интерфейсе). Обычные `start_macos.command` /
`start_windows.bat` эту переменную не устанавливают и всегда открывают
`data/warehouse.db`. Флаг изолирован внутри процесса launcher'а (`setlocal`
на Windows, inline environment на macOS), а сервер fail-fast отказывается
стартовать при отсутствующем пути/marker, неверной роли, production alias или
SQLite sidecar. Обычный startup, наоборот, отказывается открывать marked test
DB.
Solar наследует `demo` posting policy основного runtime, поэтому после
переключения площадки остаются видны и общий тестовый, и `DEMO`-баннеры.
FULL Inventory state, Knowledge uploads, Monitoring rules и backup-каталоги
test runtime живут только во временном owned root. Live DCIM принудительно
отключён, а временный auxiliary state удаляется после остановки процесса.

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

**HISTORICAL STAGE 0.13.3A DECISION:** на момент создания initial candidate
его promotion был будущим этапом и требовал двух backup, manual approval,
integrity/FK/reconciliation gate и явного подтверждения установки. Позднее
полный historical candidate прошёл отдельную контролируемую promotion в
IXcellerate `data/warehouse.db`; это не превращает initial Stage A candidate,
pilot или clean-test DB в разрешённый replacement. Фактическая процедура и
evidence отделены от тестового контура в
[MIGRATION_DATABASE_RESET_PLAN.md](MIGRATION_DATABASE_RESET_PLAN.md) и
[LOCAL_WORKING_DATABASE_RUNBOOK.md](LOCAL_WORKING_DATABASE_RUNBOOK.md).

**CURRENT LOCAL FACT:** штатный runtime уже использует promoted historical
IXcellerate DB; clean-test builder по-прежнему создаёт только disposable
marker contour и никогда не выполняет production promotion.

## Preservation-aware pilot DB Stage 0.13.3A.5

**PILOT ONLY:** `warehouse_pilot_candidate.db` is a third, distinct contour:

- it is not `data/warehouse_test_disposable_v1.db`;
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
