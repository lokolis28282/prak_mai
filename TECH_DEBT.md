# TECH_DEBT

## ODE 0.14 follow-up

- target Equipment Query Port и безопасный link-existing workflow;
- grouped Catalog resolution UI для production-scale (50k) inventory;
- controlled approval/cutover с external backup, writer stop, sibling candidate,
  atomic publish и rollback drill;
- отдельный 1m-row acceptance benchmark; 50k Preview уже потоковый и занимает
  около 69 MiB peak RSS;
- correction/reversal operations после active baseline.

Дата проверки: 2026-07-10

## Долг

1. Монолитный `inventory/webapp.py`.

   В одном файле находятся HTTP handler, HTML, CSS, JS и CSV templates. Это затрудняет точечные изменения и review.

2. Сборка UI через `.replace(...)`.

   Несколько слоев замен зависят от точного текста старой разметки. Это главный риск битых id, обработчиков и секций.

3. Нет отдельного dev/test requirements.

   `pytest` не установлен в текущем окружении, хотя команда естественна для QA.

4. UI smoke покрывает ключевой happy path, но не все формы ввода файлов.

   Для полноценного release-gate стоит расширить E2E: CSV preview/import, delivery upload, inventory upload, work logs upload, uploaded reports.

5. FULL Inventory Preview пока не имеет cooperative cancel/resume.

   Отмена во время активного Preview безопасно блокируется, но для будущего
   1m-row контура нужны checkpoint/progress и остановка не позднее 5 секунд.

6. Administration diagnostics пока легковесная.

   Stage 0.12.9 не запускает `integrity_check` в read API, чтобы не утяжелять `/api/data` и admin overview. Нужен отдельный будущий diagnostics endpoint с явным запуском и отдельными contract tests.

7. Administration write/actions остаются compatibility-layer.

   `login/logout`, `CREATE_USER`, `CHANGE_PASSWORD`, `UPDATE_PROFILE`, `CREATE_BACKUP`, `RESTORE_BACKUP`, `CHECK_DATABASE` и upload prod DB пока не перенесены на `AdministrationFacade`.

8. Delivery acceptance UI/E2E coverage is still light.

   Stage 0.12.16 migrated backend acceptance paths. The current delivery UI is
   still embedded in `webapp.py`; deeper browser coverage for inspect cards,
   batch acceptance and conflict presentation should be added before a major UI
   rewrite.

9. Delivery close/admin correction remains compatibility-layer.

   Stage 0.12.16 migrated physical acceptance, but `close_delivery` and any
   destructive override/admin correction remain legacy or future work.

10. 291 карточки (0.58% из 50000 промоутнутых) имеют `item_name = '#N/A'`.

    Excel-артефакт из исходника исторической миграции (S/N и другие поля у
    этих карточек валидны, но наименование не восстановить без исходника).
    Найдено при финальной стабилизации 2026-07-14. Правка production data
    требует отдельного data-correction этапа: внешний byte-copy + SQLite
    `.backup`, доказательства provenance, транзакция, audit,
    post-check integrity/FK — не одноразовая правка внутри code review.

## Рекомендации после стабилизации

1. Зафиксировать `scripts/smoke_ui.py` как обязательный release-gate.

2. Разделить `webapp.py` минимум на `routes`, `templates`, `static_js`, `static_css`.

3. Добавить browser-test для admin, CSV upload и delivery flow в репозиторий.

4. Ввести отдельную тестовую БД/fixture с известным admin-паролем.
