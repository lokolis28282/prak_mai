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

## Follow-up gate (2026-07-24)

После owner-проверки сохранён текущий UX остатков как ленивое дерево
`категория → тип → вендор → модель`. Browser smoke и пользовательская
инструкция синхронизированы с деревом; точечный расход выполняется отдельным
сценарием `Найти в балансе и списать`, карточка открывается глобальным поиском.

Повторный gate: frontend contracts `154 id / 453 ссылки`, code graph
`205 узлов / 368 связей`, полный discover `566 tests` (`skipped=8`), headless
Chrome E2E и clean-DB dry-run — PASS. Console, window, unhandled rejection,
resource, HTTP и API500 errors — 0. Рабочая БД до/после follow-up осталась
byte-identical с SHA-256
`8681f3c34c52d12e665ddae9f9f818a7635c1108aee353baa9fc63830955305b`;
`integrity_check=ok`, FK violations и sidecars отсутствуют.

## Warehouse history/export follow-up (2026-07-25)

Экран расхода синхронизирован с приходом: последние 20 операций видны всегда,
а не только внутри выбранного сценария. Для компонентного списания показаны
название, модель, инвентарный номер, S/N и hostname целевой железки.

Полная история расхода теперь читается через один Warehouse read-model:
один `stock_issues` = одна строка независимо от числа FIFO allocations,
unmatched problem rows остаются в выгрузке. Кнопки полного прихода/расхода
видимы и однозначно подписаны; пустой CSV содержит заголовки. Раздел
`Остатки` переименован в `Баланс`.

Read-only проверка на рабочем объёме: 50 019 приходов / 18 798 расходов,
CSV 10 822 149 / 5 092 580 байт, 1,64 секунды. Full discover — 574 test
(`skipped=8`); headless Chrome прошёл Warehouse/Reports/Monitoring/Knowledge/
Administration без Console/HTTP/API500 ошибок. Code graph — 206 узлов /
369 связей. Рабочая БД осталась byte-identical с SHA-256
`8681f3c34c52d12e665ddae9f9f818a7635c1108aee353baa9fc63830955305b`;
`integrity_check=ok`, FK violations и sidecars отсутствуют.

Git data boundary усилена отдельным `audit_repository_data.py`: текущий index
не содержит runtime/company DB, monitoring JSON, backup/export/release/
migration artifacts или SQLite под другим расширением. Три новых теста
проверяют gate и first-run bootstrap: clone поставляется без
`data/warehouse.db`, отсутствующая БД создаётся локально с пустыми
операционными таблицами. Историческая очистка GitHub выполняется отдельной
процедурой с внешним backup `QWERTY`.

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
