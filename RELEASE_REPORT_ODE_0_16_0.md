# Release Report — ODE 0.16.0 modular extraction (2026-07-26)

## Verdict

Четыре commit 0.16.0 приняты локально fast-forward без переписывания истории.
Функциональная регрессия по доступному automated/browser gate не обнаружена.
Версия совместима с текущей рабочей схемой и данными: проверка выполнялась на
точной byte-copy `data/warehouse.db`, а рабочий файл не изменялся.

Verdict: **READY FOR LOCAL DEMO / PILOT**. Это не означает готовность к
публичному или многопользовательскому server deployment; новый Windows ZIP не
собирался.

## Что изменилось

| Stage | До | ODE 0.16.0 |
|---|---|---|
| Administration | реализация внутри общего compatibility core | `AdministrationService` и `AdministrationFacade`; users/audit/backup/diagnostics вынесены физически |
| Reports | часть логики и adapter в compatibility services | единая реализация в `inventory/reports/`; Warehouse events приходят через `WarehouseEventReader` |
| Warehouse | `WarehouseCore` содержал основной business code | domain services находятся в `inventory/warehouse/`; `WarehouseCore` — thin deprecated adapter |
| Web | `inventory/webapp.py` содержал HTML и доменные handlers | HTTP shell 921 строка; handlers в `inventory/routes/`, HTML в `inventory/templates/` |

Схема SQLite, публичные URL, JSON/CSV contracts, итоговый runtime HTML и
ownership таблиц не менялись. Старые Python entry points сохраняются как
делегаты к тем же экземплярам сервисов, а не как параллельная бизнес-логика.

## Проверка совместимости с рабочей БД

- рабочий файл: `data/warehouse.db`, 580 112 384 байта, mode `0600`;
- SHA-256 до/после обновления:
  `8681f3c34c52d12e665ddae9f9f818a7635c1108aee353baa9fc63830955305b`;
- `PRAGMA integrity_check`: `ok`;
- `PRAGMA foreign_key_check`: 0 строк;
- `-wal`, `-shm`, `-journal`: отсутствуют;
- предобновленческий внешний backup:
  `~/Documents/ODE_BACKUPS/PRE_0_16_0_2026-07-26/`;
- byte-copy backup совпадает с рабочей БД по SHA; отдельный SQLite `.backup`
  также прошёл integrity/FK.

Запуск, browser smoke и mutation-сценарии выполнялись только на временной
копии. Рабочая БД не открывалась новой версией для тестовой записи.

Отдельный read-only compatibility probe на свежей точной копии подтвердил:
50 019 карточек/приходов, 18 798 расходов, по 20 последних операций в обоих
экранах, полный CSV прихода 10 822 149 байт и расхода 5 092 580 байт.
14 138 строк расхода содержат связь с целевым оборудованием; export contract
включает его S/N, hostname, наименование, модель и Inventory Number. SHA
тестовой копии после probe остался равен рабочему.

## Gate

| Проверка | Результат |
|---|---|
| tracked-data audit / отсутствие DB, serial/company artifacts | OK |
| `git diff --check` для upstream 0.16.0 | OK |
| Python compile | OK |
| JavaScript syntax | OK |
| module-boundary audit | OK |
| frontend-contract audit | OK |
| clean-test-DB dry-run на byte-copy | OK; source SHA unchanged |
| upstream full discover | 593 tests, `OK (skipped=8)` |
| local full discover после graph contract | 594 tests, `OK (skipped=8)` |
| headless Chrome smoke на byte-copy | OK; все основные разделы посещены |
| console/window/unhandled/resource/HTTP/API500 errors | 0 |
| committed code graph `--check` | OK |
| Codebase Memory full reindex | `artifact_present=false`; repository artifact отсутствует |

Восемь skip относятся к отсутствующим ignored real migration/pilot artifacts;
временные candidate scenarios и остальные contracts выполняются.

Во время повторного gate обнаружена гонка самого CDP smoke-harness: сразу
после navigation predicate мог обратиться к функции нового document до
загрузки classic scripts. `waitFor` теперь повторяет такие transient
evaluation errors и при настоящем timeout показывает последнюю ошибку.
Продуктовый runtime при этом не менялся.

## Codebase Memory и карты

Full snapshot после 0.16.0 индексирует текущий repository без SQLite,
backups, release и ignored migration data. Поддерживаемая карта находится в
`docs/CODEBASE_GRAPH.md`, интерактивный file/import graph — в
`docs/assets/code_graph.html`.

После каждого существенного изменения кода или topology выполняется:

```bash
python3 scripts/refresh_project_knowledge.py
```

Команда регенерирует committed HTML и обновляет внешний индекс только с
`persistence=false`. Структурные ответы не заменяют `rg`, чтение source и
тесты.

## Review findings и ограничения

- прямого SQL в `inventory/routes/` и `inventory/templates/` не найдено;
- `RouteRuntime` всё ещё передаёт `WarehouseService` для lock, DB metadata,
  compatibility constants и одного preview adapter; это документированный
  переходный долг, а не полностью завершённое отделение Web от compatibility
  layer;
- Reports не получил прямого доступа к Warehouse tables; event boundary
  сохранён;
- Monitoring остаётся изолированным от Warehouse/Reports compatibility core;
- runtime/data files не попали в новые commits;
- `inventory/webapp.py` всё ещё содержит auth/session/security и общий request
  dispatch; это существенно меньше прежнего монолита, но не финальная
  модульность;
- `WarehouseService`/`WarehouseCore` остаются compatibility debt и должны
  удаляться только постепенно после переноса оставшихся callers;
- SQLite остаётся локальной однопользовательской БД; server deployment,
  автоматическая baseline activation и корректирующие/storno операции не
  реализованы.
