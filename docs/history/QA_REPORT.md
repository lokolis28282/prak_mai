# QA_REPORT

Дата проверки: 2026-07-10

## Проверки

Python syntax:

```bash
python3 -m py_compile app.py inventory/*.py build_windows_package.py scripts/smoke_ui.py
```

Результат: OK.

Unit regression:

```bash
python3 -m unittest -v tests.test_warehouse
```

Результат: 80 tests OK. Есть `ResourceWarning` в одном тесте, без падения.

SQLite:

```bash
sqlite3 data/warehouse.db 'PRAGMA integrity_check; PRAGMA foreign_key_check;'
```

Результат: `ok`, FK-ошибок нет.

UI E2E:

```bash
python3 scripts/smoke_ui.py
```

Результат: OK на временной копии БД. Проверены вход инженера, главная, переход ODE -> главная, склад, приход сканером, черновик, подтверждение, расход, баланс, история, отчеты, мониторинг, профиль, поставки, инвентаризация.

`tests/headless_smoke.js` явно проверяет:

- отсутствие `console.error` / Chrome Runtime exceptions;
- отсутствие `window.onerror` через `interfaceError`;
- отсутствие `unhandledrejection` через `interfaceError` и Runtime events;
- переход ODE -> главная;
- разделы `Склад`, `Приход`, `Расход`, `Баланс`, `История`, `Отчеты`, `Профиль`.

Frontend contract:

```bash
python3 scripts/audit_frontend_contracts.py
```

Результат: OK, явных missing static id нет.

Admin UI:

Проверен headless Chrome на временной БД с дефолтным админом. Результат: админ-раздел видим, вкладки `admin_users`, `admin_backups`, `admin_database`, `references`, `admin_audit` открываются без `interfaceError`.

Stress:

Временная БД: 100 приходов, 100 расходов, 100 приемок поставки, 1000 строк CSV-прихода, 10000 work logs. Результат: 11.138 сек, integrity OK, зависаний нет.

Release:

`python3 build_windows_package.py` успешно пересобрал `release/ODE_windows_test.zip`. Архив содержит 14 runtime-файлов, без tests/backups/.git/exports/screenshots. БД release integrity OK.

## Ограничения

Реальная Windows-машина не запускалась в этой среде. Проверены `.bat`, состав ZIP и запуск portable Python-файлов на macOS.

`pytest` не установлен; вместо него пройден `unittest`.
