# TEST_DATABASE_GUIDE

Как получить и использовать одноразовую тестовую копию БД ODE, не трогая
рабочую `data/warehouse.db`.

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
