# ODE 0.14 — ручная приёмка FULL Inventory

Дата: 2026-07-16. Scope: локальный Warehouse, external Preview workspace и
disposable baseline rehearsal. Реальный publish/cutover не входит в приёмку.

## Перед началом

1. Зафиксировать SHA-256, размер и права `data/warehouse.db`.
2. Проверить `PRAGMA integrity_check`, `foreign_key_check` и отсутствие
   `-wal`, `-shm`, `-journal`.
3. Запустить обычный `python3 app.py`; не использовать demo contour для этой
   проверки.
4. Убедиться, что banner говорит: склад не инициализирован, остаток
   исторический, реальные складские записи заблокированы.

## Основной сценарий

1. Открыть `Склад → Инвентаризация`, скачать шаблон.
2. Не менять имена листов/колонок. Все значения, особенно S/N и Inventory
   Number, вводить как text.
3. Создать FULL session, загрузить XLSX и построить Preview.
4. Проверить summary, pagination строк и фильтр blocking findings.
5. Создать тестовые blockers на disposable копии source: duplicate S/N,
   duplicate Inventory Number, неизвестную локацию, numeric/formula identifier.
6. Для корректируемой строки выбрать `Исправить`; проверить, что raw остаётся
   прежним, а corrected value виден отдельно после повторной проверки.
7. Для физического дубля использовать `MARK_DUPLICATE` или exclusion с
   обязательной причиной. Конфликтующее решение должно потребовать explicit
   supersede.
8. Нажать `Повторно проверить`. Старый Preview run должен сохраниться, digest
   измениться детерминированно, unresolved blocker count — пересчитаться.
9. `READY_FOR_APPROVAL` допустим только при нуле unresolved BLOCKING.

## Disposable candidate rehearsal

Candidate — инженерное доказательство target schema, не рабочая БД. Для
небольшого acceptance XLSX администратор явно задаёт Catalog decision для
каждой включённой строки, а для serialized — equipment decision, затем снова
запускает revalidation и нажимает `Собрать baseline-кандидат`.

Ожидается:

- `status=REHEARSAL_READY`, `publish_available=false`;
- target `application_id=0x4F444531`, `user_version=8`;
- `integrity_check=ok`, FK=0, domain invariant violations=0;
- ровно один active approved snapshot и projection;
- snapshot/projection difference=0;
- `legacy_history_events=0`;
- candidate имеет 0600 и не имеет sidecars;
- повторная сборка того же digest возвращает тот же SHA.

Production-scale catalog/equipment decisions пока не выполнять: групповой
Catalog UI и target Equipment Query Port относятся к следующему этапу.
`LINK_EXISTING_EQUIPMENT` fail-closed. Это stop condition реального cutover,
но не Preview и не проверка физической ведомости.

## Финальная проверка

Повторить SHA/integrity/FK/sidecars рабочей БД. Если SHA изменилась, приёмка
немедленно прекращается: FULL Inventory workflow не имеет права писать в
`data/warehouse.db`.
