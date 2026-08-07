# ODE 0.20.0 — Reports branch integration audit

Дата проверки: 2026-08-07. Объект: remote commit `bb83690` ветки `reports`,
интегрированный поверх `release/0.20.0` (`4dbd34b`).

## Решение по веткам

`origin/reports` и текущий release были sibling-ветками от `7b94127`: в
Reports отсутствовал общий стабилизационный commit `4dbd34b`. Поэтому commit
коллеги сначала проверен в отдельном worktree, затем перенесён без blind merge,
а конфликт generated code graph разрешён регенерацией из текущих исходников.

## Что реализовал коллега

- УВР встроен в экран отчёта за смену: общий реестр, фильтры, сортировка и
  UI-пагинация по 25 строк поверх server safety-window в 1000 строк.
- Для PNR добавлены зависимый checklist, вычисляемые description/status,
  прогресс и передача оставшихся действий следующей смене.
- Добавлены обязательный срок интерактивной задачи, разделы и массовый разбор
  импортированных строк `needs_review`.
- CRUD доступен из реестра и таблицы смены; viewer остаётся read-only.
- Отчёты переведены на форматированные XLSX; shift export содержит два листа.
- Добавлены статистика смены, handover view и styled confirm dialog.

## Подтверждённые проблемы и исправления

1. Безопасный runtime-installer не добавлял новые `due_date` и
   `pnr_checklist`. На текущей promoted DB чтение Reports падало с
   `sqlite3.OperationalError: no such column: due_date`. Поля добавлены в
   `install_reports_uvr_schema`, а `migrate_runtime_modules.py` теперь считает
   Reports готовым только при наличии всех четырёх UVR-колонок.
2. Reports UI брал `task_source` из складского v2 `operation_source`, поэтому
   PNR отсутствовал. Добавлен Reports-owned `reference_options` через
   `ApplicationContext.reports → ReportsFacade`.
3. Карточка «Отчёты» открывала удалённый `reports/worklogs` и давала пустой
   экран. Маршрут исправлен на `reports/daily → Все работы`.
4. PNR не скрывал поле ручного описания из-за несовпадения CSS-класса. Контракт
   исправлен и закреплён frontend-тестом.
5. После быстрого сохранения форма ещё три секунды молча блокировала следующую
   запись. Reports теперь снимает duplicate-submit guard сразу после
   фактического завершения async flow.
6. Viewer видел форму создания, import и bulk controls. Недоступные действия
   скрыты; browser smoke проверяет отдельную viewer-сессию.
7. Edit из handover передавал только ID и мог не найти старую строку вне
   1000-row window; после сохранения handover не обновлялся. Теперь передаётся
   объект строки и callback refresh.
8. Лист «Выполненные работы» включал незавершённые задачи. Теперь это только
   `status=Выполнено` выбранного дня; handover включает старый backlog до даты
   отчёта и исключает будущие строки.
9. Handover export скачивал общий реестр. Добавлен отдельный
   `/export/handover.xlsx` с теми же date/search/status filters.
10. Status/section фильтровались только на клиенте поверх первых 1000 строк.
    Фильтры и экспорт переведены на сервер.
11. `ASSIGN_SECTION` принимал неизвестный раздел и мог превысить SQLite
    999-bind limit. Значение теперь проверяется по активному справочнику, а до
    1000 ID обновляются 500-id чанками в одной транзакции.
12. XLSX допускал запрещённые XML 1.0 control characters. Writer заменяет их
    на U+FFFD; все значения остаются inline text, включая ведущие нули и строки
    вида `=1+1`.
13. Reports facade импортировал HTTP route constants. Export mappings
    перенесены в Reports ownership, boundary audit запрещает обратный импорт.
14. Глобальный Enter мог подтвердить destructive dialog независимо от фокуса.
    Escape отменяет, а подтверждение выполняет только сфокусированная кнопка.
15. Удалённые CSV download URLs ломали сохранённые ссылки. Они оставлены как
    read-only compatibility aliases; новый UI использует XLSX.
16. Shortcut «Искать в работах» стоял выше реального результата и повторял
    запрос, поэтому S/N выглядел как карточка, но открывал Reports. Реальные
    складские совпадения теперь первичны, cross-module shortcut расположен
    последним.

## Проверки

- warning-clean `unittest discover`: **685 tests**, `OK (skipped=8)`;
- focused Reports/API/schema suite: 64 теста после финальных исправлений;
- headless Chrome engineer: навигация, обычная и PNR-запись, поиск, edit,
  cancel/delete, handover, XLSX/legacy CSV exports и mobile layout — OK;
- headless Chrome viewer: create/import/bulk controls скрыты — OK;
- XLSX ZIP/XML round-trip и открытие headless LibreOffice — OK;
- Python compile, JS syntax, module/frontend/documentation/repository audits,
  generated code graph check и `git diff --check` входят в release gate.

Все browser/mutation проверки выполнялись на disposable копиях. Runtime DB не
изменялись. Контрольные SHA-256:

- `data/warehouse.db` —
  `8681f3c34c52d12e665ddae9f9f818a7635c1108aee353baa9fc63830955305b`;
- `data/warehouse_solar.db` —
  `6eb930442fdc55bf5f460398eaa31afd0d302fc8f8081bc5787c295fca0eb257`;
- `data/vacations.db` —
  `41d226a96110e2233717ae002859f97912bc8b531da29b4f2f2fd083b9e28b4a`.

Для существующей promoted DB перед первым запуском этого release нужна
остановка writers и явная backup-guarded миграция:

```bash
python3 scripts/migrate_runtime_modules.py --db data/warehouse.db
python3 scripts/migrate_runtime_modules.py --db data/warehouse.db \
  --backup-dir /external/path/runtime-modules-20260807 --apply
```

Backup-каталог обязан быть новым и находиться вне репозитория. Текущая рабочая
БД в рамках code release намеренно не мигрировалась.

## Оставшееся ограничение

`GET /api/work-logs-page` остаётся server-bounded выборкой до 1000 строк, а
страницы по 25 строятся на клиенте. Фильтры применяются до limit и поэтому
корректны, но для реестра больше 1000 совпадений нужна настоящая cursor/server
pagination; задача сохранена в `TECH_DEBT.md`.
