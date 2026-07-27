# Проверка общего модуля отпусков — 2026-07-27

## Итог

Модуль `Отпуска` реализован как самостоятельный application-контур для
IXcellerate и Solar. Он не зависит от выбранного склада и хранит данные только
в `data/vacations.db`. Ни `data/warehouse.db`, ни
`data/warehouse_solar.db` не содержат таблиц отпусков.

## Зафиксированные правила

- календарные дни считаются включительно;
- площадка и график сотрудника меняются effective-dated записью;
- поддерживаются графики `5/2` и `1/3`;
- цикл IXcellerate `1/3` начинается 26.07.2026 и последовательно использует
  четыре группы;
- отпуск сотрудника с признаком подменного не пересекается с отпусками других
  сотрудников `1/3`;
- отпуска начальника отдела и старших площадок не пересекаются;
- каждая активная смена IXcellerate должна сохранять хотя бы одного
  дежурного;
- конфликтная заявка сохраняется в статусе ожидания и попадает в отдельную
  очередь; пользователь может подтвердить исключение с комментарием либо
  отклонить отпуск;
- ограничений по роли нет, но автор каждой мутации сохраняется в
  `vacation_history` и собственном `vacation_audit_log`;
- Сфера остаётся внешним ручным согласованием: в ODE сохраняются статус,
  номер/ссылка и комментарий, без интеграции и отправки заявки.

## Реализованный контур

- backend: короткие composition shells `service.py` / `repository.py`,
  правила в `validation.py`, `conflict_rules.py`, `calendar.py`, хранение в
  `repositories/{registrations,employees,requests,conflicts,audit}.py`;
- HTTP: `inventory/routes/vacations.py`;
- UI: семь файлов `static/js/vacations/{core,calendar,requests,employee_form,employees,conflicts,index}.js`,
  четыре экрана:
  `Календарь`, `Список отпусков`, `Сотрудники и графики`, `Конфликты`;
- данные: `vacation_employees`, `vacation_assignments`,
  `vacation_requests`, `vacation_conflicts`, `vacation_history`,
  `vacation_audit_log`;
- свежая база: пустой состав; сотрудники добавляются через публичные UI/API;
- локальный рабочий состав сохранён только в ignored `vacations.db`;
- обычный web-start идемпотентно создаёт/проверяет отдельную Vacations DB;
- clean-test и headless-smoke контуры используют отдельные временные
  `warehouse.db` и `vacations.db`.

## Ручная браузерная проверка

Проверка выполнена на byte-copy БД, не на рабочих файлах.

- вход под инженером и карточка `Отпуска` на главном экране;
- открытие всех четырёх подэкранов;
- отображение 42-дневной сетки и четырёхгруппового цикла дежурств;
- создание отпуска фиктивного дежурного без подмены:
  конфликт `DUTY_COVERAGE`;
- подтверждение конфликта как исключения с inline-комментарием;
- создание пересечения фиктивного сотрудника и отклонение заявки;
- effective-dated смена площадки/графика тестового инженера;
- блокировка перевода единственного инженера из смены IXcellerate до
  назначения замены;
- повторный запуск: отклонённая заявка отсутствует в календаре,
  подтверждённая остаётся;
- интерфейс не показывает системные `confirm/prompt`, `null`, ошибки
  `#interfaceError` или ошибки консоли;
- переключатель Warehouse скрыт на всех экранах отпусков и возвращается
  только при открытии склада; CSS/JS загружаются с версией продукта в URL.

## Автоматические проверки

- `python3 -W error::ResourceWarning -m unittest discover -s tests -v`:
  **620 тестов PASS**, `skipped=8`;
- `python3 scripts/smoke_ui.py`: PASS, посещены Warehouse, Receipt, Issue,
  Balance, History, Reports, Knowledge, Profile, Administration, Monitoring
  и Vacations; console/window/unhandled/resource/HTTP/API500 errors — 0;
- Python compile и `node --check`: PASS;
- `scripts/audit_module_boundaries.py`: PASS;
- `scripts/audit_frontend_contracts.py`: PASS;
- `scripts/audit_repository_data.py`: PASS, 535 tracked files, runtime/company
  data artifacts отсутствуют;
- `scripts/create_clean_test_db.py --dry-run`: PASS;
- `git diff --check`: PASS;
- code graph: 243 узла / 494 связи, `--check` PASS;
- Codebase Memory full reindex: 7 067 узлов / 30 991 ребро / 550 файлов /
  42 HTTP routes, `persistence=false`, `artifact_present=false`.

## Сохранность рабочих данных

- IXcellerate SHA-256:
  `8681f3c34c52d12e665ddae9f9f818a7635c1108aee353baa9fc63830955305b`;
- Solar SHA-256:
  `6eb930442fdc55bf5f460398eaa31afd0d302fc8f8081bc5787c295fca0eb257`;
- Vacations SHA-256 после первого штатного запуска:
  `41d226a96110e2233717ae002859f97912bc8b531da29b4f2f2fd083b9e28b4a`;
  локальный состав сохранён без публикации его содержимого;
- обе БД: `integrity_check=ok`, FK violations отсутствуют;
- `.db-wal`, `.db-shm`, `.db-journal` отсутствуют.

## Оставшиеся ограничения

- backup/restore отдельной `vacations.db` пока выполняется файловой процедурой
  при остановленном приложении, отдельного UI ещё нет;
- интеграции со Сферой нет;
- автоматическое планирование отпусков и квоты не реализованы;
- обязательное покрытие дежурных Solar будет добавлено, когда появится график
  `1/3` этой площадки;
- это локальный SQLite-контур, не многопользовательский сервер.
