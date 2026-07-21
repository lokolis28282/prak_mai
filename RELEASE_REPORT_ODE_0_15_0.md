# Release Report — ODE 0.15.0 (2026-07-19)

Предрелизная стабилизация и финальная проверка перед сдачей проекта.

## Объём релиза

1. **Контроль качества данных** — рабочий инструмент исправлений:
   инлайн-заполнение пустых полей неполных строк (проект, полка, вендор,
   модель, дата с валидацией и пометкой «вручную»), исправление S/N дублей с
   проверкой уникальности, удаление лишней дублирующей карточки с
   подтверждением и fail-closed защитой (наличие второй карточки S/N,
   отсутствие списаний/поставок/миграционных связей). Новые audit-коды:
   `RECEIPT_FIELDS_FILLED`, `RECEIPT_DATE_FILLED`, `RECEIPT_SERIAL_CORRECTED`,
   `RECEIPT_DELETED`. Контракт: `docs/DATA_QUALITY_OPERATIONS.md`.
2. **Карточка оборудования** — сняты блокировки редактирования исторических
   карточек: описательные поля («Поставщик», «Объект», «ЦОД», «Единица»)
   более не обязательны; обязательны наименование и ровно один тип.
3. **Совместимость с Python 3.10** — исправлены `enum.StrEnum`
   (`inventory/warehouse/baseline/models.py`) и `set_authorizer(None)`
   (`ode/infrastructure/database.py`); README-требование «Python 3.10+»
   теперь выполняется фактически.
4. **UI** — операционные KPI и лента операций на обзоре склада, суммарный
   счётчик кабеля, серверный поиск и догрузка баланса блоками по 500,
   единые SVG-иконки сценариев, lazy rendering скрытых тяжёлых таблиц и
   корректное открытие новых разделов сверху на desktop/mobile.
5. **FULL Inventory XLSX** — scan-first лист с S/N в первой колонке,
   отдельные инструкция, типы/категории, активные полки и номенклатура из
   read-only снимка Warehouse; vendor/model подсказки ограничены реально
   наблюдавшимися сочетаниями и не меняют рабочую БД.
6. **Релизная гигиена** — версия задаётся только в `inventory/__init__.py`;
   `build_windows_package.py` выводит имена артефактов из версии; README
   реструктурирован для GitHub; история этапов — `docs/STAGES_HISTORY.md`;
   `code_graph.html` синхронизирован (203 узла / 364 связи), а генератор
   поддерживает fail-fast проверку `--check`.
7. **Bootstrap logs** — известные начальные учётные данные compatibility
   runtime больше не выводятся в application/CI logs; поведение защищено
   отдельным regression-тестом и не меняет существующую рабочую БД.

## Политика данных

`data/warehouse.db` (реальные серийные номера) и `data/monitoring/*.json`
(внутренние hostname/адресаты) не входят в репозиторий и защищены
`.gitignore`. Репозиторий содержит только код, тесты и документацию.

## Проверки (gate)

| Проверка | Результат |
|---|---|
| `py_compile` (все .py: app, inventory, ode, scripts, tests) | OK |
| `node --check` (все static/js и тестовые .js) | OK |
| `scripts/audit_module_boundaries.py` | OK |
| `scripts/audit_frontend_contracts.py` | OK (153 id / 456 ссылок) |
| `scripts/generate_code_graph.py --check` | OK (203 узла / 364 связи) |
| Полный unittest discover | **539 тестов, все зелёные** (8 ожидаемых skip для отсутствующих ignored migration artifacts) |
| Headless Chrome E2E | OK; Warehouse/Reports/Monitoring/Knowledge/Admin, Console/HTTP/API500 errors = 0 |
| `git diff --check` | OK |
| SHA-256 рабочей БД | `68f06d7a764ac8d2ccde1b59d99ad7977cb665808602d2980a3dfdc87c4a5314`, до/после commit gate одинаков; предыдущий evidence SHA изменён только обычным audit-событием `LOGIN` пользователя |
| SQLite safety | `integrity_check=ok`, FK=0, sidecars отсутствуют |

## Глубокое код-ревью

- SQL: все динамические подстановки (`f-string`) идут только из allowlist'ов
  полей/таблиц; пользовательские значения — только через параметры;
- файловые endpoint'ы: static (`..`/absolute guard), backup
  (`Path(name).name == name` + suffix), вложения Knowledge
  (resolve + containment) — path traversal исключён;
- сессии: server-side store, cookie `HttpOnly; SameSite=Strict`, отдельный
  админ-режим, purge истёкших сессий;
- конкурентность: все `/api/action` выполняются под `service.lock` (RLock);
- XSS: единый `esc()`; inline-обработчики принимают только числовые id,
  константы или `encodeURIComponent` — строковые аргументы из данных удалены;
- monitoring/reports: проверены read-only, границы модулей подтверждены
  аудитом; исправления не вносились.

## Известные ограничения

Без изменений относительно README «Ограничения»: нет сторнирующих операций
(точечные data-quality исправления их не заменяют), SQLite рассчитана на
локальную однопользовательскую запись, Windows ZIP остаётся `0.12.17 RC1`
(новый артефакт не собирался). FULL Inventory Preview и disposable rehearsal
готовы, но approval/atomic activation первоначального baseline остаются
отдельным контролируемым этапом с backup и остановкой writers.

Известная пара bootstrap-учётных данных для новой пустой compatibility-БД
сохраняется до отдельного production bootstrap design; сервер блокирует все
admin-действия, кроме обязательной смены пароля. Поэтому verdict этого отчёта —
**READY FOR LOCAL DEMO / PILOT**, но не готовность к публичному или
многопользовательскому серверному deployment.
