# Release Review — ODE Stage 0.13.2

Дата проверки: 2026-07-14.

## Статус версии

Текущий исходный код: Stage 0.13.2, Bulk Inventory Number Import. Runtime-
метаданные исходников и target package builder остаются `0.12.17.1 RC2`.
Последние фактически собранные архивы `release/ODE_windows_test.zip` и
`release/ODE_0.12.17_RC1.zip` идентичны, имеют SHA-256
`27cd04b36e09cd64f402e232f8d759be914ce961215a475ad712f97ac40a9501` и
содержат `ODE 0.12.17 RC1`. ZIP RC2/Stage 0.13.2 не создавался. Version bump и
Windows packaging выполняются отдельной release-процедурой.

## Scope

Stage добавляет только массовое назначение Inventory Number существующим
S/N-позициям:

- CSV Preview/Confirm/Result;
- шесть публичных статусов;
- S/N-only matching и запрет создания карточек;
- повторную проверку плана под `BEGIN IMMEDIATE`;
- атомарные update, legacy sync и audit;
- существующий Equipment Card Timeline;
- template, UI и unit/contract/API/frontend/headless tests.

Схема БД, справочники, зависимости, deployment topology и существующие
receipt/issue/delivery/inventory reconciliation business rules не менялись.

## Архитектура и документация

Нормативный контракт:
[docs/INVENTORY_NUMBER_IMPORT_ARCHITECTURE.md](docs/INVENTORY_NUMBER_IMPORT_ARCHITECTURE.md).
Ручная приемка:
[docs/MANUAL_TESTING_0_13_2.md](docs/MANUAL_TESTING_0_13_2.md).

Синхронизированы CHANGELOG, README/Windows, root/backend/module/receipt
architecture, API migration appendix, security, database ownership, events,
data model, frontend contracts/components и Mermaid diagrams. Исторические
version-specific QA/security/release/manual документы не переписывались.

## Gate

На текущем Stage source tree выполнены:

- Python syntax compile;
- syntax check всех требуемых JavaScript-файлов;
- module boundary audit;
- frontend contract audit;
- 227 unittest с `ResourceWarning` как error;
- clean test DB dry-run;
- headless Chrome smoke, включая `inventoryNumbers=true`;
- `git diff --check`;
- SQLite `integrity_check` и `foreign_key_check`.

Headless acceptance подтверждает нулевые `console.error`, `window.onerror`,
`unhandledrejection`, resource/HTTP errors и API 500. Mutation-тесты используют
только временные SQLite БД.

Контрольный SHA рабочей `data/warehouse.db` до и после gate:
`eaab698c0bb8fd5de1ebd86a5999ee29d2a89e96b59e7fbaa171b0d38a26e8db`.
`integrity_check = ok`, `foreign_key_check` пуст, WAL/journal отсутствуют.

## Artifact и deployment

Release ZIP намеренно не собирался. `build_windows_package.py` содержит, а
`WINDOWS_RELEASE.md` описывает текущий несобранный RC2 metadata/builder target;
перед следующей упаковкой необходимо одним release change обновить
`__version__`, directory/package metadata, embedded release notes/test count и
пройти физический Windows sign-off. Публиковать текущий source tree под именем
RC2 нельзя.

## Известные ограничения

- preview хранится в памяти, author-bound (не HTTP-session-bound), одноразовый,
  TTL 3600 секунд и не переживает restart/eviction;
- после server-side ошибки confirm нужен новый Preview; текущая кнопка может
  оставаться визуально активной со старым one-shot token, что является
  non-blocking UX limitation и не нарушает rollback;
- server возвращает максимум 100 Preview/Result rows; UI не показывает
  отдельную truncation-подсказку, поэтому полный размер нужно читать по counter
  `total`;
- persisted batch ID, batch summary audit, background progress/cancel отсутствуют;
- сохраняются ограничения single-process SQLite и обязательный пробный импорт
  на disposable test DB перед использованием реальных данных.

## Итог

После documentation-complete фиксации, обычного push и полного MCP reindex
Stage 0.13.2 допускается к пробному импорту Inventory Number только на тестовом
контуре. Следующий этап автоматически не начинается.
