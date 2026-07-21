# Acceptance-test ODE 0.12

Дата проверки: 2026-07-09  
Версия: ODE 0.12  
Проверенная рабочая БД: `data/warehouse.db`  
Backup проекта: `acceptance_backups/project_pre_acceptance_20260709_013028.tar.gz`  
Backup БД: `acceptance_backups/warehouse_pre_acceptance_20260709_013028.db`

## SHA-256 БД

- До проверки: `990c108a46afa06bd5191fe76a4dcb5ab8591fd24b242add41b39e0ad38e4d99`
- После проверки: `6290ee05149f0c179a85cd7fe1bab3f94d796f16ba992f1c23af5b4e60ce4a8f`

Схема и основные таблицы не изменились. Отличие dump только в `sqlite_sequence`
(`categories`, `reference_values`, `stock_receipts`). Бизнес-строки, audit_log,
users, stock_receipts и stock_issues по счетчикам не изменились.

## Пройденные проверки

- `python3 -m py_compile app.py inventory/*.py tests/*.py` — OK.
- `python3 -m unittest discover -s tests -v` — OK, 80 тестов.
- `node --check tests/headless_smoke.js` — OK.
- Встроенные HTML `<script>` проверены через `node --check` — OK.
- `sqlite3 data/warehouse.db "PRAGMA integrity_check;"` — `ok`.
- `sqlite3 data/warehouse.db "PRAGMA foreign_key_check;"` — без строк.
- Размер БД: 237568 bytes.
- Основные таблицы существуют: `stock_receipts`, `stock_issues`,
  `stock_issue_allocations`, `deliveries`, `delivery_lines`, `work_logs`,
  `audit_log`, `users`.
- `python3 app.py` — сервер стартует на `127.0.0.1:8765`, HTTP 200, корректно
  завершается по Ctrl+C.
- `python3 app.py web --no-browser` — поддерживается, сервер стартует на
  временной БД, HTTP 200, корректно завершается.
- `scripts/smoke_ui.py` — OK: главная, приход сканером, черновик прихода,
  баланс, история, профиль, отчеты, мониторинг, поставки, инвентаризация.
- Stage 0.12.2 UI smoke дополнительно фиксирует отсутствие `console.error`,
  `window.onerror` и `unhandledrejection`, а также явные переходы ODE -> главная,
  Склад, Приход, Расход, Баланс, История, Отчеты и Профиль.
- `python3 scripts/audit_frontend_contracts.py` — OK, явных missing static id нет.
- На временной копии БД проверены: скан-приход, блокировка повторного S/N,
  баланс, расход, повторный расход как проблемная строка/блокировка, кабели,
  поставки new/existing, история, audit, ежедневный и недельный отчет, профиль.
- Admin `lokolis / lokolis52` проверен на временной копии БД, пароль не сброшен.

## Release ZIP

`release/ODE_windows_test.zip` создан из текущей проверенной версии проекта.

- SHA-256: `993f127674baa95b8179901a9f4dd3bfdfa83e471b407221e5d8ddda6c332eaf`
- `unzip -t release/ODE_windows_test.zip` — OK, ошибок нет.
- В архив входят `app.py`, `inventory/`, `data/warehouse.db`, `README.md`,
  `WINDOWS_RELEASE.md`, `CHANGELOG.md`, `requirements.txt`, `start_windows.bat`.
- В архив не входят `backups`, `acceptance_backups`, `__pycache__`, `*.pyc`,
  `.DS_Store`, `tests`, старый `release` и временные файлы.
- `ODE/inventory/webapp.py` внутри архива совпадает с текущим
  `inventory/webapp.py`.
- `PRAGMA integrity_check` для `ODE/data/warehouse.db` внутри архива — `ok`.

## Найденные баги

- Low: запуск приложения на рабочей БД изменяет `sqlite_sequence`, даже без
  пользовательских операций. Деловые данные не изменились, но SHA файла БД
  меняется.

## Критичные баги

Нет открытых критичных багов. Critical-баг с отсутствующим release ZIP закрыт.

## Некритичные баги

- Старт приложения не полностью read-only для SQLite-файла из-за изменения
  `sqlite_sequence`.

## Что можно тестировать на рабочем ноутбуке

- Локальный запуск из исходной папки проекта.
- Вход инженера смены и профиль.
- Навигацию: главная, склад, отчеты, мониторинг, профиль.
- Приход и расход на тестовой копии БД.
- Баланс, карточки, история, отчеты, поставки, кабели.

## Что нельзя тестировать

- Продуктивную эксплуатацию без тестового периода.

## Рекомендация

Готово к переносу ODE 0.12 на рабочий ноутбук для тестовой эксплуатации.
