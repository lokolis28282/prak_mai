# Release Report — ODE 0.17.0 Multi-Warehouse (2026-07-26)

## Verdict

ODE 0.17.0 разделяет Warehouse на два локальных изолированных контура:
IXcellerate и Solar. Регрессий по доступному automated/browser gate не
обнаружено. Рабочая IXcellerate DB во время разработки и проверок осталась
byte-identical.

Verdict: **READY FOR LOCAL DEMO / PILOT AND SOURCE DISTRIBUTION**.
Это не означает готовность к публичному или многопользовательскому server
deployment. Новый Windows ZIP не собирался; GitHub публикует исходный код,
тесты и документацию без рабочих БД.

## Что изменилось

- Вход в раздел `Склад` предлагает выбрать `IXcellerate` или `Solar`.
- Выбранный Warehouse хранится в HTTP-сессии.
- IXcellerate использует `data/warehouse.db`; Solar —
  `data/warehouse_solar.db`.
- Первый Solar bootstrap атомарно создаёт новую БД с нулевыми operational
  rows и одноразовым снимком legacy/v2 справочников IXcellerate.
- Повторный запуск не синхронизирует и не перезаписывает существующую Solar
  DB.
- Warehouse reads, exports, previews, imports, mutations, locks, audit,
  browser drafts и Full Inventory state используют выбранный runtime.
- Reports, Monitoring, Knowledge и authentication остаются общими
  application-модулями.
- UI показывает компактные карточки складов без лишних поясняющих подписей.

Нормативный контракт:
[`docs/MULTI_WAREHOUSE_ARCHITECTURE.md`](docs/MULTI_WAREHOUSE_ARCHITECTURE.md).

## Проверка локальных баз

### IXcellerate

- путь: `data/warehouse.db`;
- SHA-256 до/после:
  `8681f3c34c52d12e665ddae9f9f818a7635c1108aee353baa9fc63830955305b`;
- `PRAGMA integrity_check`: `ok`;
- `PRAGMA foreign_key_check`: 0 строк;
- SQLite sidecars отсутствуют.

### Solar

Локальный bootstrap создан только как installation-owned ignored файл:

- equipment / operations / receipts / issues / allocations / deliveries /
  delivery lines: 0 строк;
- legacy reference rows: 934;
- v2 domains / values / aliases: 20 / 940 / 927;
- `PRAGMA integrity_check`: `ok`;
- `PRAGMA foreign_key_check`: 0 строк;
- POSIX mode: `0600`.

Ни одна из этих БД не отслеживается Git. После clone приложение создаёт
локальные DB-файлы установки; GitHub не содержит S/N или данные компании.

## Gate

| Проверка | Результат |
|---|---|
| Python compile | OK |
| JavaScript syntax | OK |
| module-boundary audit | OK |
| frontend-contract audit | OK |
| repository data audit | OK; runtime/company artifacts absent |
| clean-test-DB dry-run | OK; source SHA unchanged |
| full `unittest discover` | 598 tests, `OK (skipped=8)` |
| headless Chrome smoke | OK; оба склада и основные разделы пройдены |
| console/window/unhandled/resource/HTTP/API500 errors | 0 |
| deterministic file/import graph | 221 nodes / 455 edges; current |
| `git diff --check` | OK |

Восемь skip относятся к отсутствующим ignored real migration/pilot
артефактам. Builders, временные candidate-сценарии и остальные contracts
выполняются.

## Ограничения

- Administration backup/restore пока управляет основной IXcellerate DB;
  отдельный production-grade backup UI для Solar требует следующего этапа.
- Reports, Monitoring и Knowledge не переключаются вместе со складом — это
  отдельные общие продуктовые контуры по текущему архитектурному решению.
- SQLite остаётся локальным однопользовательским хранилищем.
- Корректирующие/сторнирующие Warehouse-операции не реализованы.
- Последний фактически собранный Windows ZIP остаётся `0.12.17 RC1`.

## Запуск

```bash
python3 app.py
```

Для консольного запуска без автоматического открытия браузера:

```bash
python3 app.py gui --no-browser --port 8765
```
