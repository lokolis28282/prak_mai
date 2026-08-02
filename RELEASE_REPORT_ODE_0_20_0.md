# ODE 0.20.0 — equipment composition release report

Дата проверки: 2026-08-02. Статус: локальный source/runtime готов к
операторской приёмке; Windows ZIP не собирался.

## Результат

Обычный `python3 app.py` показывает в карточке сервера, коммутатора и другого
серийного оборудования read-only проекцию компонентов, списанных на его S/N.
Оператор видит группы, количество и полный журнал: дата, тип/наименование,
вендор/модель, S/N компонента, количество, hostname, задача/ИЗМ, инженер и
комментарий. Наведение на группу показывает три последних события, клик
фильтрует таблицу.

Проекция намеренно не изображает переднюю/заднюю панель и слоты. API возвращает
`basis=ISSUE_HISTORY`, `current_state_confirmed=false` и
`placement_known=false`; UI явно сообщает, что фактическое наличие, заводская
комплектация и физические слоты не подтверждены. Timeline использует событие
«Компонент списан на оборудование», а не недоказуемое «Установлен компонент».

Исторические ИЗМ/задачи сначала берутся из структурированных task-полей. Если
они пусты, известный префикс ИЗМ/ЗНР/ПНР/ЗНО/ИНЦ извлекается из комментария с
`task_reference_source=comment`; исходная строка БД остаётся неизменной.

## Архитектура и данные

- read-path: `UI → /api/position-card → WarehouseFacade →
  WarehouseDomainService → EquipmentCompositionService`;
- источник: существующие `stock_issues` и `stock_issue_allocations` с
  реквизитами исходного `stock_receipts`;
- новых таблиц, SQLite-миграций и внешних зависимостей нет;
- все mutation-тесты выполнены только на временных БД;
- code graph: 247 модулей / 506 связей;
- внешний Codebase Memory index: 7 368 узлов / 31 382 ребра,
  `skipped_count=0`, `artifact_present=false`, `persistence=false`.

## Автоматические проверки

- Python compile: PASS;
- JavaScript syntax: PASS;
- module/frontend/repository-data audits: PASS;
- committed graph check: PASS;
- clean production-derived DB builder `--dry-run`: PASS, источник не изменён;
- full discover под `-W error::ResourceWarning`: 639 тестов,
  `OK (skipped=8)`;
- headless Chrome E2E: PASS, включая пару «трансивер → сервер», глобальный
  поиск целевого S/N, карточку, предупреждение, tooltip и group filter;
- Chrome E2E: no console/window/unhandled/resource/HTTP/API-500 errors;
- `git diff --check`: PASS.

## Проверка реального контура

Запущена точная default-команда `python3 app.py`: ODE 0.20.0,
`data/warehouse.db`, `data/warehouse_solar.db`, 50 019 карточек,
`integrity=ok`. Через видимый браузер найден реальный коммутатор Huawei
XH9230-128DQ по S/N `102597538859`. Карточка показала 128 связанных
трансиверов, их модели/S/N, hostname `MSK-IXCS-GPU-SPINE-02`, дату и
`ИЗМ-000112008`; фильтр группы и tooltip работают. Confirm/mutation-действия
на рабочем контуре не выполнялись.

SHA-256 рабочих БД до проверки:

- `data/warehouse.db` —
  `8681f3c34c52d12e665ddae9f9f818a7635c1108aee353baa9fc63830955305b`;
- `data/warehouse_solar.db` —
  `6eb930442fdc55bf5f460398eaa31afd0d302fc8f8081bc5787c295fca0eb257`;
- `data/vacations.db` —
  `41d226a96110e2233717ae002859f97912bc8b531da29b4f2f2fd083b9e28b4a`.

После ручной проверки все три SHA совпали с приведёнными выше;
`integrity_check=ok`, `foreign_key_check` пуст и SQLite sidecars отсутствуют.

## Ограничения и следующий этап

Текущая версия отвечает на вопрос «что когда-либо было списано на этот S/N»,
но не «что физически установлено сейчас». Для последнего нужны отдельные
INSTALL/REMOVE/REPLACE-события, опциональный slot/port и явная операторская
сверка комплектации. До появления такого источника истины UI обязан сохранять
текущую evidence-only маркировку.
