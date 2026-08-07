# Полный стабилизационный аудит ODE 0.20.0

Дата: 2026-08-07<br>
Ветка: `release/0.20.0`<br>
Исходный commit: `7b94127 docs: publish current ODE 0.20.0 code graph`

## Итог

**PASS WITH FIXES.** Проверены архитектурные связи, backend, транзакции,
permissions, SQLite boundaries, Web/API, фактически загружаемый frontend,
основные пользовательские маршруты, документация и Git data hygiene. Семь
подтверждённых дефектов исправлены и закрыты regression tests. Рабочие БД не
изменялись; все mutation/E2E сценарии выполнялись на временных БД.

Verdict относится к локальному ODE 0.20.0. Он не объявляет готовыми server
deployment, multi-DB restore, correction/reversal или Windows ZIP 0.20.0.

## Исправленные findings

| Приоритет | Finding | Исправление и evidence |
|---|---|---|
| High | Серийный приход принимал `quantity>1` или нештучную единицу, позволяя повторно списать один S/N | Единый validator требует `quantity=1`, `unit=шт` для manual/batch/import; cable flow не изменён |
| High | Batch/import не замечал сохранённый S/N с внешними пробелами; bulk Inventory Number возвращал `NOT_FOUND` | Все lookup сравнивают `trim(column) COLLATE NOCASE`, raw S/N не переписывается |
| High | При нескольких normalized-match карточках Inventory Number мог назначаться произвольно | Preview и direct assignment fail-closed с требованием устранить дубли |
| Medium | Огромное/повреждённое поле PBKDF2 iterations выбрасывало необработанный `OverflowError` | Hash parser проверяет algorithm, iteration policy, strict Base64 и длины; login возвращает controlled denial |
| Medium | Authenticated GET неизвестного пути не отправлял HTTP-ответ | Общий dispatch возвращает JSON `404 Страница не найдена` |
| Medium | Scanner drafts разных ФИО в одном браузере использовали общий id/email `lokolis` | Draft schema v4 ключуется по normalized session display identity + DB fingerprint; Chrome проверяет смену инженера |
| Low | Два raw `with sqlite3.connect(...)` оставляли connection до GC, а обычный unittest exit code скрывал destructor warning | Использован `contextlib.closing`; AST test запрещает повторение anti-pattern |

Два living-документа также ссылались на несуществующий
`/api/equipment-composition`; фактический состав находится в `composition`
ответа `/api/position-card`. Контракт исправлен и защищён documentation audit.

## Объём проверки

- 323 Python/JavaScript source и test файла, 1 796 объявлений функций/методов
  в `app.py`, `inventory` и `scripts`;
- `ApplicationContext`, публичные facade и границы Warehouse, Reports,
  Monitoring, Knowledge, Vacations, Administration;
- S/N-first receipt/issue/allocation, Preview/Confirm, rollback, reference data,
  delivery, Inventory Number, equipment card/composition;
- auth/session/rate limit/role override, upload guards, backup allowlist,
  integrity/FK/schema/SHA manifest и fail-closed restore;
- externalized HTML, все `static/js`, DOM/button bindings, navigation, drafts,
  Multi-Warehouse и headless Chrome operator journeys;
- living docs, local links, graph, tracked files и disguised SQLite detection.

## Автоматический gate

| Проверка | Результат |
|---|---|
| Python compile | PASS |
| Node syntax: весь `static/js` и JS tests | PASS |
| Module boundaries | PASS |
| Frontend contracts | PASS: 162 HTML ID, 317 static references, 53 controls |
| Documentation contracts | PASS: 205 Markdown-файлов, version/local links |
| Repository data audit | PASS: runtime/company artifacts отсутствуют |
| Code graph | PASS: 248 узлов / 506 связей |
| Codebase Memory full reindex | PASS: 7 465 узлов / 31 742 ребра, `persistence=false`, artifact отсутствует |
| Clean test DB `--dry-run` | PASS, source SHA unchanged |
| `unittest -W error::ResourceWarning` | PASS: 649 tests, `skipped=8`, ResourceWarning=0 |
| Headless Chrome E2E | PASS, console/window/resource/HTTP/API-500 errors=0 |
| `git diff --check` | PASS |

Восемь skips — ожидаемые platform/optional ignored migration-artifact
сценарии. Неожиданных skips и warning нет.

## Рабочие БД — read-only evidence

| Runtime DB | SHA-256 baseline | Integrity | FK |
|---|---|---|---:|
| `data/warehouse.db` | `8681f3c34c52d12e665ddae9f9f818a7635c1108aee353baa9fc63830955305b` | `ok` | 0 |
| `data/warehouse_solar.db` | `6eb930442fdc55bf5f460398eaa31afd0d302fc8f8081bc5787c295fca0eb257` | `ok` | 0 |
| `data/vacations.db` | `41d226a96110e2233717ae002859f97912bc8b531da29b4f2f2fd083b9e28b4a` | `ok` | 0 |

Read-only business-invariant query подтвердил: в обеих Warehouse DB нет
серийных строк с `quantity!=1` или `unit!='шт'`. В IXcellerate присутствуют
1 030 S/N с внешними пробелами и 160 групп, совпадающих после удаления только
этих пробелов. Код предотвращает новые normalized-дубли и неоднозначную
mutation, но историческая коррекция не выполнялась: она требует отдельного
backup/provenance/transaction/audit/post-check процесса.

## Документация и handoff

- [`../../USER_GUIDE.md`](../../USER_GUIDE.md) — пошаговая инструкция
  оператора и безопасная реакция на ошибки;
- [`../../DEVELOPER_GUIDE.md`](../../DEVELOPER_GUIDE.md) — карта runtime,
  правила code review, полный gate и commit/data checklist;
- function matrix, frontend contracts, current state, risks, technical debt и
  changelog синхронизированы с исправленным runtime.

## Открытые ограничения

- 160 normalized S/N duplicate groups и 291 `#N/A` names требуют отдельной
  production data-correction процедуры;
- restore, backup schedule/rotation/encryption и disaster-recovery drill не
  реализованы;
- correction/reversal проведённых складских операций не реализован;
- SQLite contour не прошёл concurrent/server acceptance;
- Composition остаётся issue-history evidence, а не installed current-state;
- Windows ZIP 0.20.0 не собран; transports email/Rooms/Kaiten отсутствуют.
