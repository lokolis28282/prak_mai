# Полный аудит ODE 0.20.0

Дата: 2026-08-02<br>
Ветка: `release/0.20.0`<br>
Базовый commit: `96da2e2 feat: release ODE 0.20.0 equipment composition`

## Итог

**PASS.** Текущий source/runtime ODE 0.20.0 согласован с living-
документацией, архитектурными границами и пользовательским интерфейсом.
Автоматический набор, headless Chrome и read-only проверка реального контура
не обнаружили runtime regression, пересечения владельцев данных, неработающих
статических кнопок, console/HTTP/API 500 ошибок или изменения рабочих БД.

Это verdict текущей локальной однопользовательской версии. Он не означает
готовность server deployment, restore, correction/reversal или Windows ZIP
0.20.0 — эти ограничения перечислены ниже.

## Что актуализировано

- создан единый [`SYSTEM_FUNCTION_MATRIX.md`](../SYSTEM_FUNCTION_MATRIX.md):
  экраны, facade/API, storage owner, read/write/fail-closed статус и evidence;
- переписан индекс документации: current, normative target и immutable history
  больше не смешиваются;
- синхронизированы Project Hub, product context, roadmap, repository map,
  handoff, risks и technical debt;
- Windows-документы переведены на ODE 0.20.0, три runtime-БД, внешний backup
  root и отключённый restore;
- исправлен frontend contract: Monitoring/Reports описаны как рабочие модули,
  добавлен evidence-only Equipment Composition;
- обновлены security, backend и Administration backup contracts;
- добавлен `scripts/audit_documentation.py` и его regression test;
- frontend audit расширен проверкой уникальности ID, доступного имени и
  статического binding кнопок, а также отсутствия restore/upload-prod controls
  в итоговом runtime HTML.

Исторические release/manual/migration reports не удалялись и не переписывались:
они явно отделены как датированное evidence своего этапа. Это сохраняет audit
trail и одновременно не позволяет принять старый документ за current guide.

## Автоматический gate

| Проверка | Результат |
|---|---|
| Python compile: `app.py`, `inventory/**/*.py`, `scripts/*.py`, `tests/*.py` | PASS |
| Node syntax: весь `static/js/**/*.js`, `tests/headless_smoke.js` | PASS |
| Module boundaries | PASS |
| Frontend contracts | PASS: 162 HTML ID, 317 static JS references, 53 кнопки |
| Documentation contracts | PASS: 201 Markdown-файл, версия и local links |
| Repository data audit | PASS: 589 tracked-файлов, runtime/company data отсутствуют |
| Code graph | PASS: 248 узлов / 506 связей |
| Clean test DB dry-run | PASS |
| `unittest -W error::ResourceWarning` | PASS: 641 тест, skipped=8 |
| Headless Chrome E2E | PASS |
| `git diff --check` | PASS |

Восемь skipped-тестов — заранее определённые platform/optional migration-
artifact сценарии; неожиданных skip или warning нет.

## Browser/UI gate

Headless Chrome посетил и использовал:

- главную, login/session/profile и навигацию;
- Warehouse overview, приход, расход, баланс, историю и поставки;
- глобальный поиск, Equipment Card и фильтр Equipment Composition;
- Inventory Number Preview/Confirm;
- Reports, Monitoring, Knowledge, Vacations и Administration;
- reload/back и cleanup scanner drafts.

Mutation flows выполнялись только на трёх disposable test DB. Результат smoke:
`noConsoleErrors`, `noWindowErrors`, `noUnhandledRejections`,
`noResourceErrors`, `noHttpErrors`, `noApi500` — все `true`.

Static audit отдельно доказал, что каждая из 53 базовых кнопок имеет доступное
имя и форму/обработчик. Динамические таблицы и кнопки покрыты browser smoke и
профильными UI contract tests.

## Реальный контур — только read-only

Проверен уже запущенный точной default-командой `python app.py` сервер
`http://127.0.0.1:8765`, title `ODE 0.20.0 — учет работ и склада`.

- IXcellerate: 45 482 единицы, 31 221 активная позиция; основные категории и
  последние операции отрисованы;
- поиск S/N `102597538859`: открыта карточка Huawei XH9230-128DQ, hostname
  `MSK-IXCS-GPU-SPINE-02`;
- Composition: 128 issue-history операций группы `Трансиверы`, видны S/N,
  дата, hostname, `ИЗМ-000112008` и автор; disclaimer о неподтверждённом
  current-state/slot присутствует;
- Solar: выбран через session switcher, баланс и операции равны нулю;
- Vacations: отдельный общий календарь открылся, показал 12 сотрудников и
  расписание смен.

Confirm/save/delete/backup кнопки на рабочих данных не нажимались.

## Сохранность рабочих БД

| Runtime DB | SHA-256 до/после | Integrity | FK | Sidecars |
|---|---|---|---:|---|
| `data/warehouse.db` | `8681f3c34c52d12e665ddae9f9f818a7635c1108aee353baa9fc63830955305b` | `ok` | 0 | нет |
| `data/warehouse_solar.db` | `6eb930442fdc55bf5f460398eaa31afd0d302fc8f8081bc5787c295fca0eb257` | `ok` | 0 | нет |
| `data/vacations.db` | `41d226a96110e2233717ae002859f97912bc8b531da29b4f2f2fd083b9e28b4a` | `ok` | 0 | нет |

Все SHA совпали с baseline byte-for-byte.

## Подтверждённые границы

- Warehouse, Reports, Monitoring, Knowledge, Vacations и Administration идут
  через публичные facade и не владеют чужими business tables;
- IXcellerate/Solar/Vacations физически разделены;
- S/N остаётся identity, raw operation history не переписывается;
- restore fail-closed, legacy upload-prod control отсутствует в runtime HTML;
- historical docs сохраняются только как явно scoped evidence;
- candidate/test/runtime/release data lifecycles не смешиваются.

## Открытые ограничения

- точный физический slot/current installed state компонентов не известен;
- restore, backup schedule/rotation/encryption не реализованы;
- correction/reversal проведённых складских операций не реализован;
- SQLite contour не прошёл server/concurrent operator acceptance;
- Windows ZIP 0.20.0 не собран; последний фактический ZIP — 0.12.17 RC1;
- email/Rooms/Kaiten transports отсутствуют.

Эти ограничения отражены одинаково в README, Windows guide, roadmap, risks,
technical debt и function matrix.
