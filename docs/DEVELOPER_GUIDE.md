# Руководство разработчика и ревьюера ODE 0.21.0

Актуализировано: 2026-08-11. Это короткая точка входа для человека, который
читает, проверяет или изменяет код. Нормативные ограничения репозитория остаются
в корневом [`AGENTS.md`](../AGENTS.md).

## 1. Что прочитать сначала

1. [`project/CURRENT_STATE.md`](project/CURRENT_STATE.md) — фактический runtime.
2. [`project/SYSTEM_FUNCTION_MATRIX.md`](project/SYSTEM_FUNCTION_MATRIX.md) —
   экраны, API, storage и доказательства.
3. [`DATABASE_OWNERSHIP.md`](DATABASE_OWNERSHIP.md) — владельцы таблиц.
4. [`MODULE_ARCHITECTURE.md`](MODULE_ARCHITECTURE.md) и
   [`API_REFERENCE.md`](API_REFERENCE.md) — фасады и HTTP-контракт.
5. [`AUTHENTICATION_AND_API_ACCESS.md`](AUTHENTICATION_AND_API_ACCESS.md) и
   [`RUNTIME_CONFIGURATION.md`](RUNTIME_CONFIGURATION.md) — реальные способы
   входа, отсутствие API keys и поддержанные runtime settings.
6. [`project/RISKS_AND_BACKLOG.md`](project/RISKS_AND_BACKLOG.md) — открытые
   ограничения, которые нельзя выдавать за реализованные функции.

Target ODE 0.13 в `docs/architecture` — утверждённое направление, но не всегда
текущий runtime. При расхождении сначала проверяйте исполняемый код и living-
документы из списка выше.

## 2. Карта runtime

```text
app.py
  → inventory/webapp.py          HTTP/session/security shell
  → inventory/routes/            domain HTTP handlers
  → ApplicationContext
      → WarehouseFacade          inventory/warehouse
      → ReportsFacade            inventory/reports
      → MonitoringFacade         inventory/monitoring
      → KnowledgeFacade          inventory/knowledge
      → VacationFacade           inventory/vacations
      → AdministrationFacade     inventory/administration
```

Фактический frontend находится в `static/js` и `static/css`. Итоговая сборка
удаляет inline `<style>`/`<script>` из шаблона, поэтому frontend-изменение надо
проверять через `inventory.webapp.HTML` или живой сервер.

Runtime data разделены физически:

- `data/warehouse.db` — IXcellerate и primary application contour;
- `data/warehouse_solar.db` — отдельный Solar Warehouse;
- `data/vacations.db` — отдельный модуль отпусков.

Эти файлы, backup, raw migration input, exports, screenshots и release ZIP не
коммитятся.

## 3. Архитектурные правила ревью

- Новый Web/API код идёт через `ApplicationContext → public facade`; прямой
  business SQL в route/template запрещён.
- Reports читает склад только через `WarehouseEventReader`; Warehouse не пишет
  отчётные таблицы; Monitoring и Vacations изолированы от Warehouse.
- S/N — identity оборудования. Inventory Number и полка не являются fallback-
  идентификаторами и не создают вторую карточку.
- Preview не пишет business data; Confirm повторно валидирует план под lock и
  либо фиксирует всю транзакцию, либо откатывает её.
- Права определяет session user/role. ФИО отвечает за attribution и не даёт
  admin-доступ.
- Composition в `/api/position-card` — только issue-history evidence, не
  current installed state и не slot map.
- Multi-DB restore остаётся fail-closed до полного ADR-013 workflow;
  correction/reversal — до ADR-014.

## 4. Auth и API: фактический runtime

- `/api/login` принимает только два режима: `engineer` с `full_name` без
  пароля и credentialed `admin` с `email/password`.
- `mode` не заменяет backend role. Engineer mode принудительно получает
  `engineer`; credentialed user сохраняет роль записи `users`.
- Защищённые endpoints принимают только in-memory `ode_session` cookie.
  `Authorization: Bearer`, `X-API-Key`, JWT/OAuth и `ODE_API_KEY` отсутствуют.
- Cookie имеет `HttpOnly; SameSite=Strict; Path=/`, idle TTL 12 часов;
  logout/restart инвалидируют её. Cookie не `Secure`, потому что штатный
  профиль — loopback HTTP.
- Пять неудачных credentialed-входов за пять минут дают блокировку на 15 минут
  по client address + normalized email.
- POST с `Origin` проверяет exact `Origin.netloc == Host` и local/private/
  allowlisted host. Это не полноценный production CSRF/TLS profile.
- `X-Correlation-ID` — диагностический ID, не credential; допустимы 16–200
  символов `[A-Za-z0-9._:-]`.

Не используйте session cookie как «временный API key» в интеграции. Будущий
machine-auth требует отдельного principal/scopes/hash/expiry/revoke/audit/TLS
контракта и отрицательных security tests. Полная модель и безопасные локальные
примеры запросов находятся в
[`AUTHENTICATION_AND_API_ACCESS.md`](AUTHENTICATION_AND_API_ACCESS.md).

## 5. Безопасный цикл изменения

1. Выполните `git status --short --branch` и отделите чужой dirty diff.
2. Для DB-related работы зафиксируйте абсолютные пути, SHA-256 и отсутствие
   `-wal/-shm/-journal`; mutation tests запускайте только на временной копии.
3. Найдите реальный call path через `rg`, затем прочитайте route, facade,
   service/repository и существующие тесты.
4. Исправьте первопричину минимальным связным изменением и добавьте regression
   test на наблюдаемое поведение.
5. Обновите API, security, ownership, пользовательские инструкции и living-
   status, если контракт изменился.
6. Прогоните targeted tests, затем полный gate ниже.
7. Снова сравните SHA runtime-БД, выполните integrity/FK checks и проверьте
   diff на секреты и generated data.

### Reports-specific checks

- HTTP/UI обращается только к `ApplicationContext.reports → ReportsFacade`;
  `inventory/reports` не импортирует `inventory/routes` и не читает складские
  таблицы напрямую.
- Интерактивный create/update валидирует `due_date`; PNR description/status
  выводятся из backend checklist, а не доверяются JSON-клиенту.
- `ASSIGN_SECTION` принимает только активный `work_log_section`, работает
  атомарно чанками и не снимает `needs_review` при ошибке.
- Реестр и экспорт должны применять одинаковые date/search/status/section/
  review filters. Safety-window — 1000 строк, UI page — 25.
- Shift XLSX: первый лист только `Выполнено` за выбранный день; handover — весь
  незавершённый backlog с `work_date <= report_date`. Dedicated handover export
  не должен возвращать общий реестр.
- XLSX хранит значения как inline text и заменяет запрещённые XML 1.0 control-
  символы. Проверяйте ZIP/XML round-trip и открытие headless LibreOffice, если
  он доступен.
- Legacy `/export/*.csv` — read-only compatibility aliases; текущие UI-кнопки
  должны вести на `.xlsx`.
- Existing promoted DB получает `section`, `needs_review`, `due_date` и
  `pnr_checklist` только через backup-guarded `migrate_runtime_modules.py`;
  его `reports_ready` обязан проверять все четыре поля.
- Focused UI gate запускается для engineer и viewer через
  `tests/headless_reports_smoke.js`; `--login-role` меняет только disposable
  smoke copy и не касается runtime DB.

## 6. Полный gate

```bash
python3 -m compileall -q app.py inventory scripts tests
find static/js tests -name '*.js' -type f -print0 | xargs -0 -n1 node --check
python3 scripts/audit_module_boundaries.py
python3 scripts/audit_frontend_contracts.py
python3 scripts/audit_documentation.py
python3 scripts/audit_repository_data.py
python3 scripts/generate_code_graph.py --check
python3 -W error::ResourceWarning -m unittest discover -s tests -v
python3 scripts/create_clean_test_db.py --dry-run
python3 scripts/smoke_ui.py
git diff --check
```

`sqlite3.Connection` нельзя использовать как единственный context manager:
его `__exit__` завершает транзакцию, но не закрывает соединение. Используйте
проектный `inventory.db.connect()` либо
`with closing(sqlite3.connect(...)) as db, db:`. Исполняемый тест репозитория
блокирует повторное появление этого класса утечек.

## 7. Что проверить перед commit/push

- `git status`, `git diff --stat`, полный список изменённых файлов;
- отсутствие `.db`, XLSX/raw, backup, ZIP, exports, внутренних hostname,
  адресатов, токенов, паролей и password hashes;
- результаты полного gate и точное число tests/skips;
- SHA-256, `integrity_check` и `foreign_key_check` всех трёх runtime-БД до/после;
- документация входит в тот же логический commit;
- нет force push, reset или переписывания уже опубликованной истории.

Датированные release/review evidence не переписываются задним числом. Для
новой проверки создаётся новый файл в `docs/project/reviews/` и добавляется в
[`project/DOCUMENTATION_INDEX.md`](project/DOCUMENTATION_INDEX.md).
