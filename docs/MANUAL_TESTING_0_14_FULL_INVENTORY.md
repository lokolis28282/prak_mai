# ODE 0.14 — ручная приёмка FULL Inventory

Дата: 2026-07-16. Scope: локальный Warehouse, external Preview workspace и
disposable baseline rehearsal. Реальный publish/cutover не входит в приёмку.

## Перед началом

1. Зафиксировать SHA-256, размер и права `data/warehouse.db`.
2. Проверить `PRAGMA integrity_check`, `foreign_key_check` и отсутствие
   `-wal`, `-shm`, `-journal`.
3. Запустить обычный `python3 app.py`; не использовать demo contour для этой
   проверки.
4. Убедиться, что постоянного warning-banner нет, обзор называется `Текущий
   баланс склада`, а system-status содержит `PROVISIONAL_HISTORICAL`,
   `authoritative=false`, `baseline_timestamp=null`, `posting_allowed=true`.
5. Проверку прихода/расхода выполнять только на временной byte-copy: production
   contour должен пропустить запрос до обычной бизнес-валидации, а неизвестный
   contour — остаться fail-closed.

## Основной сценарий

1. Открыть `Склад → Инвентаризация`, нажать `Скачать XLSX для
   сканирования`.
2. Проверить пять листов: `Manifest`, `Inventory`, `Инструкция`,
   `Справочник`, `Номенклатура`. Не менять имена обязательных листов/колонок.
3. Убедиться, что в `Справочнике` есть точный тип `Оперативная память`
   с `ItemKind=SERIALIZED`, `Quantity=1`, `UOM=шт`, а SFP/QSFP отнесены к
   `Трансиверам`. AOC/DAC должны быть в `Кабельных сборках`.
4. Проверить, что `LocationCode` содержит только активные полки. Для новой
   полки: добавить её в ODE, скачать XLSX заново и только затем
   начинать сканирование.
5. В `Inventory` сканировать S/N в колонку A. S/N и Inventory Number вводить
   только как text; для RowId штучной позиции допустимо скопировать тот же S/N.
   Если точного наименования нет в `Номенклатуре`, ввести новое точное
   `Description`; похожую модель подставлять запрещено.
6. Создать FULL session, загрузить XLSX и построить Preview.
7. Проверить summary, pagination строк и фильтр blocking findings.
8. Создать тестовые blockers на disposable копии source: duplicate S/N,
   duplicate Inventory Number, неизвестную локацию, numeric/formula identifier.
9. Для корректируемой строки выбрать `Исправить`; проверить, что raw остаётся
   прежним, а corrected value виден отдельно после повторной проверки.
10. Для физического дубля использовать `MARK_DUPLICATE` или exclusion с
   обязательной причиной. Конфликтующее решение должно потребовать explicit
   supersede.
11. Нажать `Повторно проверить`. Старый Preview run должен сохраниться, digest
   измениться детерминированно, unresolved blocker count — пересчитаться.
12. `READY_FOR_APPROVAL` допустим только при нуле unresolved BLOCKING.
13. Во время Preview кнопки повторной отправки и отмены должны быть disabled;
    второй/stale запрос обязан завершиться без создания второго active run.

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
но не Preview и не проверка физической ведомости. Загрузка и Preview сами по
себе не пересчитывают рабочий баланс: новый остаток вступит в силу только после
отдельной approval/activation с backup и остановкой writers.

## Финальная проверка

Повторить SHA/integrity/FK/sidecars рабочей БД. Если SHA изменилась, приёмка
немедленно прекращается: FULL Inventory workflow не имеет права писать в
`data/warehouse.db`.
