# ODE 0.19.1 — runtime stabilization report

Дата проверки: 2026-08-02. Target: macOS local single-user runtime.

## Итог

ODE 0.19.1 готова как локальная рабочая версия исходников. Обычная команда
`python3 app.py` стартует на трёх default runtime-БД без дополнительных
аргументов. Схема SQLite, HTTP API и production data не изменялись; Windows
artifact не собирался, последний фактический ZIP остаётся `0.12.17 RC1`.

## Исправления

- устранён fresh-process circular import, блокировавший `app.py seed`;
- карточка оборудования передаёт в расход фактический остаток и единицу;
- mouse-click закрывает карточку и очищает card navigation state;
- Solar наследует demo/production contour основного Warehouse runtime;
- test launchers macOS/Windows явно подключают отдельные IXcellerate, Solar и
  Vacations DB;
- добавлен fail-closed builder пустой Vacations test DB;
- clean Warehouse builder удаляет candidate-only migration tables в
  корректном FK-порядке до promoted operational rows;
- версия поднята до 0.19.1, поэтому браузер получает новый cache key для
  CSS/JavaScript и не использует ассеты 0.19.0.

## Documentation gate

- `README.md`, `CHANGELOG.md`, `ITOG.md`, `ARCHITECTURE.md`, `AGENTS.md` и
  `CLAUDE.md` синхронизированы с 0.19.1;
- current state, test-DB runbook, API и code graph обновлены;
- HTTP API, CSV contracts, database ownership, permissions, Audit/Timeline и
  security contracts не менялись;
- restore остаётся fail-closed до ADR-013, correction/reversal — до ADR-014;
- датированный отчёт 0.19.0 сохранён без ретроспективных изменений.

## Автоматический gate

- Python compile — PASS;
- JavaScript syntax — PASS;
- module/frontend/repository-data audits — PASS;
- full discover: 635 tests, `OK (skipped=8)` под
  `-W error::ResourceWarning`;
- clean Warehouse dry-run — PASS, source SHA unchanged;
- headless Chrome smoke — PASS по Warehouse, Reports, Monitoring, Knowledge,
  Vacations, Administration, search/card/issue navigation; console/window/
  rejection/resource/HTTP/API500 errors отсутствуют;
- `git diff --check` — PASS.

## Ручная проверка default runtime

Запущена точная пользовательская команда `python3 app.py` без DB/path/env
аргументов. Startup подтвердил ODE 0.19.1, IXcellerate default path, Solar
default path, 50 019 карточек и `integrity=ok`.

В реальном контуре выполнены только read/navigation действия:

- engineer session и портал ODE;
- IXcellerate overview и реальные KPI;
- global search реального S/N `FO25021509396`;
- equipment card, mouse close и повторное открытие;
- переход `Списать эту позицию` без подтверждения: доступный остаток `1 шт`,
  `undefined`/`не число` отсутствуют;
- переключение на Solar: отдельный пустой operational contour;
- Vacations: общий календарь открывается из самостоятельной DB.

Production mutation actions не подтверждались.

## Production DB invariance

До и после startup/read-only manual QA:

- `data/warehouse.db` —
  `8681f3c34c52d12e665ddae9f9f818a7635c1108aee353baa9fc63830955305b`;
- `data/warehouse_solar.db` —
  `6eb930442fdc55bf5f460398eaa31afd0d302fc8f8081bc5787c295fca0eb257`;
- `data/vacations.db` —
  `41d226a96110e2233717ae002859f97912bc8b531da29b4f2f2fd083b9e28b4a`.

Для всех трёх: `integrity_check=ok`, FK violations `0`, SQLite sidecars
отсутствуют.

## Ограничения

Остаются ограничения, перечисленные в `AGENTS.md`/`TECH_DEBT.md`: локальный
SQLite single-user contour, отключённый restore, отсутствие correction/
reversal, server deployment и нового Windows package.
