# TECH_DEBT

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

5. Warning в тестах.

   В `test_large_work_log_preview_is_limited_and_confirm_writes` есть `ResourceWarning` про незакрытые SQLite connections.

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

## Рекомендации после стабилизации

1. Зафиксировать `scripts/smoke_ui.py` как обязательный release-gate.

2. Разделить `webapp.py` минимум на `routes`, `templates`, `static_js`, `static_css`.

3. Добавить browser-test для admin, CSV upload и delivery flow в репозиторий.

4. Ввести отдельную тестовую БД/fixture с известным admin-паролем.
