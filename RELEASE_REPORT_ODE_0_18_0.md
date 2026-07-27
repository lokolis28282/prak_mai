# Release Report — ODE 0.18.0 Vacations and UX stabilization (2026-07-27)

## Verdict

ODE 0.18.0 добавляет самостоятельный модуль отпусков двух площадок и
закрывает найденные UX-регрессии Warehouse. Полный автоматический и
браузерный gate не выявил незакрытых ошибок текущего локального контура.
Рабочие базы IXcellerate, Solar и Vacations остались byte-identical.

Verdict: **READY FOR LOCAL DEMO / PILOT AND SOURCE DISTRIBUTION**.

Это не означает готовность к публичному или многопользовательскому server
deployment. Новый Windows ZIP не собирался; GitHub публикует исходный код,
тесты и документацию без рабочих БД, S/N и данных компании.

## Что вошло в 0.18.0

- отдельный `inventory/vacations` bounded context и собственная
  `data/vacations.db`;
- общий календарь IXcellerate/Solar, создание сотрудников и effective-dated
  площадок/графиков;
- правила `5/2`, четырёх групп `1/3`, подменного, покрытия смен и
  непересечения руководителей;
- очередь конфликтов с явным подтверждением исключения или отклонением;
- единый Warehouse-словарь `Приход / принять` и `Расход / списать`;
- null-safe обновление необязательных legacy-контролов при смене склада;
- переключатель склада виден только в Warehouse и не создаёт ложной связи
  модуля отпусков с выбранным складом;
- versioned CSS/JavaScript URLs, исключающие смешивание нового HTML со старым
  browser cache;
- свежая установка создаёт пустую Vacations DB; рабочий состав и ФИО не
  встроены в код, тесты или документацию;
- актуальные README, API/DB/module contracts, release review, архитектурная
  SVG-карта, интерактивный граф и GitHub PNG-снимок.

## Архитектурные границы

- Vacations обращается через `VacationFacade` и не читает/не мигрирует
  Warehouse DB;
- `vacation_*` и `vacation_audit_log` существуют только в
  `data/vacations.db`;
- IXcellerate и Solar остаются физически изолированными Warehouse runtime;
- Reports и Monitoring принадлежат отдельным направлениям и не изменялись
  бизнес-функционально;
- frontend отпусков разделён на
  `static/js/vacations/{core,calendar,requests,employee_form,employees,conflicts,index}.js`;
- HTTP-маршруты отпусков находятся в `inventory/routes/vacations.py`, правила
  и repositories — в отдельных файлах `inventory/vacations/`.

Нормативные документы:

- [`docs/VACATIONS_ARCHITECTURE.md`](docs/VACATIONS_ARCHITECTURE.md);
- [`docs/MULTI_WAREHOUSE_ARCHITECTURE.md`](docs/MULTI_WAREHOUSE_ARCHITECTURE.md);
- [`docs/DATABASE_OWNERSHIP.md`](docs/DATABASE_OWNERSHIP.md);
- [`docs/MODULE_ARCHITECTURE.md`](docs/MODULE_ARCHITECTURE.md).

## Gate

| Проверка | Результат |
|---|---|
| Python compile | OK |
| JavaScript syntax | OK |
| module-boundary audit | OK |
| frontend-contract audit | OK |
| repository data audit | OK; runtime/company artifacts absent |
| clean-test-DB dry-run | OK; source SHA unchanged |
| full `unittest discover` | 620 tests, `OK (skipped=8)` |
| headless Chrome smoke | OK; все продуктовые разделы пройдены |
| live browser IXcellerate/Solar/Vacations | OK |
| console/window/unhandled/resource/HTTP/API500 errors | 0 |
| deterministic file/import graph | 243 nodes / 494 edges; current |
| Codebase Memory full reindex | 7 067 nodes / 30 991 edges / 550 files / 42 routes; `persistence=false` |
| `git diff --check` | OK |

Восемь skip относятся к отсутствующим ignored real migration/pilot
артефактам. Все обычные unit/integration/frontend contracts выполняются.

## Сохранность рабочих данных

### IXcellerate

- `data/warehouse.db`;
- SHA-256 до/после:
  `8681f3c34c52d12e665ddae9f9f818a7635c1108aee353baa9fc63830955305b`;
- `PRAGMA integrity_check`: `ok`;
- `PRAGMA foreign_key_check`: 0 строк.

### Solar

- `data/warehouse_solar.db`;
- SHA-256 до/после:
  `6eb930442fdc55bf5f460398eaa31afd0d302fc8f8081bc5787c295fca0eb257`;
- `PRAGMA integrity_check`: `ok`;
- `PRAGMA foreign_key_check`: 0 строк.

### Vacations

- `data/vacations.db`;
- SHA-256 до/после:
  `41d226a96110e2233717ae002859f97912bc8b531da29b4f2f2fd083b9e28b4a`;
- локальный рабочий состав сохранён без публикации его содержимого;
- `PRAGMA integrity_check`: `ok`;
- `PRAGMA foreign_key_check`: 0 строк.

Во всех трёх каталогах SQLite sidecars отсутствуют. Warehouse DB не содержат
таблиц `vacation_*`. Ни одна runtime DB не отслеживается Git.

## Ограничения

- SQLite остаётся локальным однопользовательским хранилищем;
- нет корректирующих/сторнирующих Warehouse-операций;
- backup/restore отдельной Solar и Vacations DB пока не имеет общего UI;
- Сфера остаётся ручным внешним согласованием отпусков;
- нет автоматического расписания backup, квот отпусков и уведомлений;
- последний фактически собранный Windows ZIP остаётся `0.12.17 RC1`.

## Запуск

```bash
python3 app.py
```

Запуск без автоматического открытия браузера:

```bash
python3 app.py web --no-browser
```
