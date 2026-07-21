# ITOG — главная техническая документация ODE 0.15.0

Основной технический документ проекта. При будущих патчах начинать отсюда:
здесь описано, как работает код, где входы и выходы, какие инварианты нельзя
нарушать, и даны ссылки на всю остальную документацию.

## 1. Что это

ODE («Отдел дежурных инженеров») — локальный офлайн-инструмент дежурной смены
ЦОД: складской учёт (S/N-first), приход/расход со сканером, поставки,
инвентаризация, контроль качества данных, УВР и отчёты, база знаний, ручной
мониторинг. Python 3.10+ (только стандартная библиотека) + SQLite; UI в
браузере; 539 автоматических тестов.

Рабочая база — `data/warehouse.db` (50 000 карточек, 18 798 расходов;
предварительный provisional-баланс до утверждения FULL-инвентаризации).
**База с реальными серийниками и `data/monitoring/*.json` в git не входят**
(защищено `.gitignore`; см. «Политика данных» в `README.md`).

## 2. Вход в программу (main)

Единственная точка запуска — **`app.py`**:

- `python3 app.py` (или `gui`/`web`) → `inventory/webapp.py::main()`:
  валидация test-mode БД → `PostingPolicy` (production/demo) →
  marker-проверки миграционных БД (до любого касания файла) →
  `WarehouseService` → `create_application_context()` → печать
  контура/версии/integrity → `ThreadingHTTPServer` на `127.0.0.1:8765`.
- любой другой аргумент → `inventory/cli.py::main()` (legacy CLI-модель).
- `python3 -m ode` → отдельный foundation-CLI целевой архитектуры 0.13
  (`ode/cli.py`), с `inventory/` не связан импортами.

## 3. Сборка модулей и потоки

Все модули связываются в одном месте — `inventory/core/application.py`:

```
ApplicationContext.from_service(service)
 ├─ WarehouseFacade(service, posting_policy, full_inventory)
 ├─ ReportsFacade(service, warehouse_events=WarehouseEventReader(service))
 ├─ MonitoringFacade()          ← без service и без пути к БД
 ├─ KnowledgeFacade(service)
 └─ AdministrationFacade(service)
```

Поток любой мутации:

```
браузер → POST /api/action (webapp.py, под service.lock=RLock)
  → валидация payload → Facade (posting-guard)
  → write-service (_require_write: admin/engineer)
  → repository → SQLite-транзакция + запись в audit_log
```

Чтение: `GET /api/data` и специализированные GET (см. API-справочник).

### Входы/выходы модулей

| Модуль | Вход (HTTP) | Выход | Пишет в БД |
|---|---|---|---|
| Warehouse | `/api/action` (STOCK_*, CONFIRM_*, ASSIGN_*, FILL_*, CORRECT_*, DELETE_DUPLICATE_RECEIPT, поставки), `/api/balance`, `/api/position-card`, `/export/*` | JSON/CSV | `stock_receipts`, `stock_issues`, `stock_issue_allocations`, `deliveries`, `delivery_lines`, `reference_*_v2` |
| Reports | `/api/work-logs`, `/api/daily-report`, `/api/weekly-report`, actions `WORK_LOG*` | JSON/CSV | только `work_logs`, `daily_report_uploads`, `daily_report_rows`; склад видит **только** через `WarehouseEventReader` (read-only) |
| Monitoring | `GET /api/monitoring/status`, `POST /api/monitoring/manual-search` (вне общего лока — долгий вызов) | JSON: routing + текст письма (без автоотправки) | **ничего** — фасад создаётся без БД; правила — локальные JSON, история — localStorage браузера |
| Knowledge | `/api/knowledge/*` | JSON/файлы | `knowledge_*` |
| Administration | `/api/admin`, admin-actions | JSON | `users`, `audit_log`, backup-файлы |
| FULL Inventory | `/api/full-inventory/*` (вне общего лока) | JSON/XLSX | внешний workspace; рабочую БД читает read-only, публикация отключена |

Monitoring и Reports между собой не связаны никак (ни импортов, ни таблиц).

## 4. Инварианты (нарушение = регрессия)

1. Web/API → только публичные фасады; не `WarehouseCore`/`WarehouseService`
   напрямую.
2. S/N — identity карточки; инв.№ — вторичный; полка — placement; canonical
   name — display. Повторный приход/расход того же S/N блокируется в
   транзакции.
3. Reports не пишет складские таблицы; Warehouse не пишет отчётные;
   Monitoring изолирован полностью.
4. Fill-empty-only для исправлений: заполненные поля не перезаписываются;
   дата — provenance (только пустая, с audit-пометкой manual).
5. `inventory/migration` — offline; не импортируется runtime'ом; вывод —
   только disposable candidate. Pilot/full review — fail-closed marker-guard.
6. Внешние зависимости не добавляются (`requirements.txt` пуст).
7. Мутации рабочей БД вне приложения — только по runbook (backup + SHA-256 +
   транзакция + audit + integrity/FK post-check).
8. Инлайновые `<style>/<script>` в webapp.py до браузера не доходят
   (`_externalized_html()`); поведение живёт в `static/js/*`, стили — в
   `static/css/main.css`.

## 5. Проверки перед любым патчем (gate)

```bash
python3 -m py_compile app.py inventory/**/*.py scripts/*.py tests/*.py
for f in static/js/**/*.js tests/headless_smoke.js; do node --check "$f"; done
python3 scripts/audit_module_boundaries.py
python3 scripts/audit_frontend_contracts.py
python3 -W error::ResourceWarning -m unittest discover -s tests -v   # 539 OK
git diff --check
python3 scripts/smoke_ui.py        # E2E, нужны Node + Chrome (macOS)
```

Перед коммитом — Documentation Gate (`CLAUDE.md`, раздел Release workflow):
обновить CHANGELOG/README/затронутые доки в том же коммите.

## 6. Карта документации

Точка входа пользователя: **`README.md`** (возможности, быстрый старт,
политика данных, рабочая инструкция, запуск/перенос/backup, ограничения).

Техническая:

- **`docs/CODE_INVENTORY_0_15_0.md`** — опись каждого исполняемого файла +
  архитектура + трассировка Monitoring/Reports от main;
- **`docs/API_REFERENCE.md`** — полный справочник HTTP API (маршруты, все
  actions, payload'ы, коды ошибок, лимиты);
- **`docs/assets/code_graph.html`** — интерактивный граф связей кодовой базы
  (203 узла / 364 связи: Python-импорты + webapp→static; фильтры по модулям,
  поиск, зум). Открывается в браузере офлайн; перегенерация после патча:
  `python3 scripts/generate_code_graph.py`; проверка актуальности без записи:
  `python3 scripts/generate_code_graph.py --check`;
- `ARCHITECTURE.md` — целевая архитектура и фасады;
- `docs/README.md` — индекс архитектурного трека 0.13 (DDL, ADR, диаграммы);
- `docs/DATABASE_OWNERSHIP.md` — владение таблицами;
- `docs/DATA_QUALITY_OPERATIONS.md` — контракт операций качества данных;
- `docs/SERIAL_NUMBER_PRESERVATION.md` — контракт сохранения S/N;
- `docs/INVENTORY_NUMBER_IMPORT_ARCHITECTURE.md` — массовое назначение инв.№;
- `docs/LOCAL_WORKING_DATABASE_RUNBOOK.md` — backup/публикация/откат рабочей БД;
- `docs/MODULE_ARCHITECTURE.md`, `docs/FRONTEND_CONTRACTS.md`,
  `docs/FRONTEND_MIGRATION_PLAN.md` — модульная миграция backend/frontend;
- `docs/MONITORING_HOSTNAME_ROUTING.md`, `docs/MONITORING_KNOWLEDGE_GUIDE.md`
  — Monitoring/Knowledge;
- `CLAUDE.md` / `AGENTS.md` — правила работы с кодовой базой (люди и
  AI-агенты); `TECH_DEBT.md` — актуальный долг;
- `CHANGELOG.md`, `RELEASE_REPORT_ODE_0_15_0.md` — изменения и релизный отчёт;
- `docs/STAGES_HISTORY.md`, `docs/history/` — история этапов и датированные
  снимки старых отчётов;
- `WINDOWS_RELEASE.md`, `README_WINDOWS.md`, `build_windows_package.py` —
  Windows-сборка (имена артефактов — из `inventory.__version__`).

## 7. Ключи, секреты, конфигурация

Секретов и API-ключей в проекте **нет** — приложение офлайн, интеграции
(Zabbix/DCIM/Kaiten/почта) не реализованы. Реальные пароли/токены и рабочие
данные в репозиторий не вносятся. Что существует:

- пароли пользователей — только PBKDF2-SHA256-хеши в таблице `users`;
  начальный админ на пустой БД: `lokolis`/`lokolis` с принудительной сменой;
- session cookie `ode_session` (HttpOnly, SameSite=Strict), стор — в памяти
  процесса;
- env-переменные Monitoring: `ODE_MONITORING_RULES_DIR`,
  `ODE_MONITORING_COLLECT_DCIM`, `ODE_MONITORING_HEADLESS`,
  `ODE_MONITORING_DEV_MOCK` (пример — `.env.example`; сами значения локальны);
- marker-guard env миграционных review-контуров — только для disposable БД;
- опциональная зависимость Selenium (`requirements-monitoring.txt`) — нужна
  только для живого DCIM-сбора.

## 8. Известные ограничения и долг

Кратко: нет сторнирующих операций (data-quality исправления их не заменяют);
SQLite — однопользовательская запись; монолит `inventory/webapp.py` и
compatibility-ядро `WarehouseCore` разбираются постепенно; Windows ZIP
остаётся `0.12.17 RC1`; 291 историческая карточка `item_name='#N/A'` ждёт
отдельного data-correction этапа. Полные списки: `README.md` («Ограничения»)
и `TECH_DEBT.md`.

## 9. Как делать будущий патч (чек-лист)

1. Прочитать этот файл, `CLAUDE.md` и профильную доку затрагиваемого модуля.
2. Изменения — через фасад соответствующего модуля; инварианты п.4 не
   нарушать; Monitoring/Reports не связывать со складом.
3. Добавить/обновить тесты рядом с изменением.
4. Прогнать полный gate (п.5).
5. Обновить документацию (Documentation Gate) в том же коммите; при
   изменении структуры кода перегенерировать граф связей
   (`python3 scripts/generate_code_graph.py`).
6. Проверить `git status`: БД, backup'ы, JSON-правила и candidate-артефакты
   не должны попасть в коммит.
