# Full Project UX Regression — 2026-07-26

## Scope

Проверен текущий ODE 0.17.0 после Multi-Warehouse release: старт приложения,
выбор IXcellerate/Solar, Warehouse, основные экраны Reports, Monitoring,
Knowledge, Profile и Administration. Все операции записи выполнялись только
на disposable копиях SQLite; рабочие базы не изменялись.

Отдельный ручной UX-аудит был сосредоточен на пользовательских названиях
Warehouse. Бизнес-логика Monitoring и Reports не менялась: эти направления
остаются изолированными рабочими потоками коллег.

## Найдено и исправлено

- расход одновременно назывался `Расход`, `Списание` и `Выдача`;
- обзор склада показывал `Выдано сегодня` и кнопку `Выдать`, хотя экран
  операции и история используют `Списать`;
- карточки способов прихода и расхода были названы по разным шаблонам:
  `Сканировать оборудование`, `Ручное добавление`, `Импорт поставки` против
  `Списать сканером`, `Ручное списание`, `Импорт расхода`;
- CLI описывал команду `issue` как оформление выдачи;
- общий `fillSelects` без проверки записывал `innerHTML` в необязательные
  legacy-контролы и мог уронить уже открытую вкладку после переключения
  IXcellerate/Solar. Теперь отсутствующие элементы пропускаются, а
  регрессионный browser-сценарий удаляет такой select перед сменой склада.

Принят единый пользовательский словарь:

- существительное процесса: `Приход` / `Расход`;
- действие: `Принять` / `Списать`;
- способы прихода: `Принять сканером`, `Принять вручную`,
  `Принять кабели`, `Принять из поставки`;
- способы расхода: `Списать сканером`, `Найти в балансе и списать`,
  `Списать кабели`, `Импорт расхода`, `Списать вручную`.

## Browser QA

Ручной проход в локальном браузере на disposable IXcellerate/Solar проверил:

- вход инженера и главный экран;
- выбор обоих складов и пустой Solar;
- обзор склада, приход, расход, баланс, инвентаризацию, поставки,
  справочники и историю;
- видимость новых подписей после полной перезагрузки приложения;
- отсутствие старых `Выдать / Выдано` на рабочем обзоре.

Полный headless Chrome smoke завершился без ошибок и посетил Warehouse,
Receipt, Issue, Balance, History, Reports, Knowledge, Profile,
Administration, Monitoring, Global Search и Inventory Number import.
Проверены реальные scanner/draft/reload сценарии, складские записи на
одноразовой БД и изоляция Solar.

Итоговые browser-сигналы:

- `noConsoleErrors=true`;
- `noWindowErrors=true`;
- `noUnhandledRejections=true`;
- `noResourceErrors=true`;
- `noHttpErrors=true`;
- `noApi500=true`.

## Automated gate

- Python compile: PASS;
- JavaScript syntax: PASS;
- module boundary audit: PASS;
- frontend contract audit: PASS;
- repository data audit: PASS, 535 tracked files, runtime/company data absent;
- code graph freshness: PASS, 221 nodes / 455 edges;
- external Codebase Memory full reindex: PASS, 6 961 nodes / 29 322 edges /
  526 files / 35 routes, `artifact_present=false`;
- clean test DB dry-run: PASS;
- `git diff --check`: PASS;
- full unittest discover: **599 tests PASS**, `skipped=8`;
- headless Chrome E2E: PASS.

## Production data proof

До и после проверки:

- IXcellerate `data/warehouse.db` SHA-256:
  `8681f3c34c52d12e665ddae9f9f818a7635c1108aee353baa9fc63830955305b`;
- Solar `data/warehouse_solar.db` SHA-256:
  `6eb930442fdc55bf5f460398eaa31afd0d302fc8f8081bc5787c295fca0eb257`;
- обе базы: `PRAGMA integrity_check = ok`;
- обе базы: `PRAGMA foreign_key_check` без строк;
- WAL/journal sidecars отсутствуют.

## Не выполнялось

На рабочих базах намеренно не запускались destructive/mutation проверки:
Full Inventory publish, restore/replace базы, удаление справочников и реальные
приходы/расходы. Эти ветви покрыты unit/integration и disposable browser
tests; production drill требует отдельного backup-guarded сценария и явного
подтверждения.
