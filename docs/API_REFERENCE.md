# ODE 0.20.0 — справочник HTTP API

Фактическая поверхность локального HTTP API (`inventory/webapp.py` и
`inventory/routes/`, порт по умолчанию `8765`). Составлен по коду версии
0.20.0. API предназначен
для собственного браузерного UI; внешние интеграции появятся после 1.0.

## Общий контракт

- Все запросы/ответы — JSON (`Content-Type: application/json`), кодировка
  UTF-8; загрузка файлов — `application/octet-stream` + заголовок
  `X-Filename` (URL-encoded имя).
- Аутентификация — session cookie `ode_session` (`HttpOnly; SameSite=Strict`),
  выдаётся `POST /api/login`. Все `/api/*`, кроме login, требуют сессию.
- Роли: `viewer` (только чтение), `engineer` (складские/отчётные записи),
  `admin` (всё). Ролевая проверка выполняется на сервере
  (`_require_write`/`_require_role`); отдельные действия дополнительно требуют
  админ-режим сессии (`_require_admin_session`).
- Все мутации `/api/action` выполняются под `RLock` выбранного склада и одной
  SQLite-транзакцией; каждая значимая мутация пишет запись в `audit_log`
  выбранной Warehouse БД.
- Складские мутации дополнительно проходят posting-guard: в состояниях
  `NOT_INITIALIZED`/`DEGRADED`/чужой контур запись блокируется (HTTP 409).
- Warehouse API работает с выбранным в HTTP-сессии site. IXcellerate и Solar
  используют разные SQLite-файлы; Reports/Monitoring/Knowledge/Admin остаются
  в общем application contour. Vacations также остаётся общим и не зависит от
  выбранного склада.

### Коды ошибок

| Код | Значение |
|---|---|
| 400 | Ошибка валидации / некорректный payload (`{"error": "..."}`) |
| 401 | Нет или истекла сессия |
| 403 | Недостаточно прав (роль/админ-режим) |
| 404 | Объект или маршрут не найден |
| 409 | Posting заблокирован состоянием склада (`{"error", "code"}`) |
| 429 | Rate-limit попыток входа |
| 500 | Внутренняя ошибка (без traceback в ответе) |

## Аутентификация

| Метод и путь | Назначение |
|---|---|
| `POST /api/login` | Вход: `{email, password, mode?}`; `mode:"admin"` открывает админ-режим; rate-limit → 429. Ставит cookie. |
| `POST /api/logout` | Завершение сессии, сброс cookie. |
| `POST /api/warehouse/select` | Выбрать склад для текущей сессии: `{"warehouse":"ixcellerate"}` или `{"warehouse":"solar"}`. Неизвестный key → 400. |

## Чтение данных (GET)

| Путь | Назначение |
|---|---|
| `/api/warehouses` | Доступные Warehouse sites, выбранный key, display label и безопасное имя DB-файла. |
| `/api/data` | Основной снапшот выбранного склада: `warehouse_site`, stats/KPI, последние 20 обычных приходов (`recent_receipts`), последние 20 расходов (`recent_issues`) с целевым оборудованием, проблемы качества данных (`problems`, `problem_counts`), справочники, история склада, текущий пользователь, сводка категорий/типов и `warehouse_model_options`. Обычный UI запрашивает `include_balance=0`; без него сохраняется совместимый ограниченный список первых 500 строк (`balance_limit`, `balance_truncated`). |
| `/api/warehouse-stock-tree` | Текущий read-path экрана остатков: агрегированное ленивое дерево `category → item_type → vendor → model`. Принимает `level`, родительский путь, фильтры баланса, `limit` 1…200 и `offset` до 1 000 000; возвращает узлы, итоги и признак следующей страницы. UI загружает по 100 групп при раскрытии ветви. |
| `/api/balance` | Совместимый плоский серверный поиск/сортировка баланса по всей БД: фильтры `query`, category/type, project/object, supplier/vendor, unit/datacenter и stock state; `limit` 1…5000, `offset` до 1 000 000, ответ содержит `has_previous`/`has_more`. Используется экспортом и вспомогательными сценариями, но не является текущим read-path дерева остатков. |
| `/api/position-card?serial_number=…` (или `position_key`) | Полная карточка позиции: реквизиты, остаток, размещение, поставка, Timeline и `composition` — read-only проекция компонентов, списанных на S/N оборудования. `composition.basis=ISSUE_HISTORY`, `current_state_confirmed=false` и `placement_known=false`; группы и операции не являются подтверждением текущего физического состава или слотов. Операция содержит дату, исходный S/N, наименование/тип/вендора/модель, количество, hostname, `task_type`, сырой `task_number`, удобный `task_reference`, `task_reference_source`, инженера и комментарий. Если исторические task-поля пусты, известный префикс ИЗМ/ЗНР/ПНР/ЗНО/ИНЦ может быть извлечён из комментария с `task_reference_source=comment`; исходная запись не меняется. |
| `/api/position-search?query=…` | Поиск позиций (лимитированный, для «Списать»/карточек). |
| `/api/global-search?query=…` | Глобальный поиск от 2 символов по S/N, инв.№, hostname, наименованию, вендору, модели, поставке, проекту, полке, ЦОД, инженеру (limit 500). |
| `/api/scan-serial?serial=…` | Проверка одного отсканированного S/N (приход/расход сценарии). |
| `/api/deliveries` / `/api/delivery?id=…` | Реестр поставок / одна поставка со строками. |
| `/api/work-logs?…` | УВР с фильтрами (период, поиск, статус, раздел). |
| `/api/daily-report?date=…` | Отчёт за смену из событий склада. |
| `/api/weekly-report?date_from=…&date_to=…` | Недельная агрегация. |
| `/api/uploaded-daily-report?id=…` | Строки загруженного готового отчёта. |
| `/api/admin` | Только admin: `databases` (IX/Solar/Vacations health/path/last backup), `database_backups`, `backup_capabilities`, legacy `backups`, пользователи и журнал аудита. Содержимое бизнес-таблиц не возвращается. |
| `/api/warehouse/system-status` | Состояние складского контура (baseline/provisional, authoritative). |
| `/api/monitoring/status` | Статус Monitoring-модуля и его capabilities. |
| `/api/vacations/bootstrap?date_from=…&date_to=…` | Общий календарь, сотрудники, effective assignments, отпуска, pending-конфликты и справочники статусов. Доступен всем аутентифицированным пользователям. |
| `/api/vacations/history?limit=…` | История изменений отпусков/графиков и решений, максимум 1000 строк. |
| `/api/migration-pilot`, `/api/migration-full` | Read-only review disposable миграционных БД (только при marker-guard). |

## `POST /api/action` — единая точка мутаций

Тело: `{"action": "<ИМЯ>", …поля}`. Ответ: `{"ok": true, …результат}`.
Неизвестные поля и неверные типы отклоняются валидатором payload.

### Склад: приход / расход

| Action | Payload (ключевое) | Результат |
|---|---|---|
| `STOCK_RECEIPT` | реквизиты партии + `serial_number` | Приход одной позиции (S/N-first: повторный S/N отклоняется). |
| `STOCK_ISSUE` | `serial_number` либо кабельный ключ, задача | Списание; кабель — FIFO по партиям. |
| `CONFIRM_SCANNED_RECEIPTS` / `CONFIRM_SCANNED_ISSUES` / `CONFIRM_SCANNED_ISSUE_PAIRS` | общие поля + список S/N (или пар компонент→цель) | Проведение скан-списка одной транзакцией. |
| `CONFIRM_BULK_ISSUE` | `preview_id` | Подтверждение массового списания из CSV. |
| `CONFIRM_IMPORT_PREVIEW` | `kind` (`receipt`/`issue`/`work_logs`/`daily_report`), `preview_id` | Подтверждение проверенного CSV/XLSX preview. |

### Склад: карточка и качество данных

| Action | Payload | Результат |
|---|---|---|
| `ASSIGN_INVENTORY_NUMBER` | `serial_number`, `inventory_number` | Назначение инв.№ только в пустое поле; идемпотентно. |
| `UPDATE_POSITION_CARD` | `serial_number`, `fields{…}` | Редактирование описательных полей; обязательны наименование и ровно один тип; S/N и история не меняются. |
| `FILL_RECEIPT_FIELDS` | `receipt_id`, `values{project,shelf,vendor,model}` | Fill-empty-only; конфликты возвращаются, не применяются. Audit `RECEIPT_FIELDS_FILLED`. |
| `FILL_RECEIPT_DATE` | `receipt_id`, `receipt_date` | Заполнение только пустой даты, валидация формата, audit `RECEIPT_DATE_FILLED` (`manual: true`). |
| `CORRECT_DUPLICATE_SERIAL` | `receipt_id`, `new_serial_number` | Новый S/N: непустой, отличный, уникальный (NOCASE). Audit `RECEIPT_SERIAL_CORRECTED`. |
| `DELETE_DUPLICATE_RECEIPT` | `receipt_id` | Удаление лишней дублирующей карточки; fail-closed (второй дубль обязан остаться; блок при списаниях/поставке/миграционных связях). Снимок строки в audit `RECEIPT_DELETED`. |

### Поставки

| Action | Назначение |
|---|---|
| `CONFIRM_DELIVERY` | Подтверждение импорта документа снабжения из preview. |
| `INSPECT_DELIVERY_SERIAL` / `ACCEPT_DELIVERY_SERIAL` | Проверка/приёмка одного S/N сканером (внеплановые — отдельным флагом). |
| `ACCEPT_DELIVERY_BATCH` | Батч-приёмка выбранных строк (`line_ids`, `common_values`). |
| `UPDATE_DELIVERY_LINES` | Заполнение полей строк (allowlist полей, `only_empty`). |
| `DELIVERY_ACCEPTANCE_SUMMARY` / `DELIVERY_CONFLICTS` | Сводка приёмки / конфликтные строки. |
| `CLOSE_DELIVERY` | Закрытие поставки (дальнейшая приёмка запрещена). |

### Отчёты (Reports)

| Action | Назначение |
|---|---|
| `WORK_LOG` / `WORK_LOGS` | Создание одной/нескольких записей УВР. |
| `UPDATE_WORK_LOG` / `DELETE_WORK_LOG` | Правка/удаление записи УВР. |

### Справочники

| Action | Назначение |
|---|---|
| `ADD_REFERENCE` / `PROPOSE_REFERENCE` | Новое значение (сразу активное / pending на approve). |
| `TOGGLE_REFERENCE` | Включение/отключение значения (deactivate, не удаление). |
| `REFERENCE_RENAME`, `REFERENCE_MERGE_PREVIEW`, `REFERENCE_MERGE` | Только админ-режим: canonical rename/merge с обязательным preview; operational raw/S/N не перезаписываются. |

### Администрирование (админ-режим сессии обязателен)

| Action | Назначение |
|---|---|
| `CREATE_RUNTIME_BACKUP` | Обязателен `database_id`: `warehouse_ix`, `warehouse_solar` или `vacations`. Создаёт проверенный SQLite snapshot и manifest во внешнем storage. |
| `CREATE_BACKUP` | Fail-closed: требуется выбрать конкретный `database_id`. |
| `CHECK_DATABASE` | `PRAGMA integrity_check` + проверка ключевых таблиц. |
| `RESTORE_BACKUP` | Начиная с 0.18.1 всегда отклоняется: безопасный preview-token/confirm/publish vertical ещё не реализован. |
| `CREATE_USER`, `UPDATE_PROFILE`, `CHANGE_PASSWORD` | Пользователи и профиль (PBKDF2-хеши). |

### Legacy (совместимость CLI-модели)

`RECEIPT`, `ISSUE`, `MOVE`, `ADD` — операции старой модели
`equipment/operations`; браузерным UI не используются.

## Импорт файлов

| Метод и путь | Назначение |
|---|---|
| `POST /api/preview-csv?kind=…` | Preview CSV (приход/расход/УВР/массовое списание/инв.№): статистика, первые 100 строк, до 200 ошибок; БД не меняется. |
| `POST /api/preview-xlsx?sheet=…` | Preview XLSX (УВР). |
| `POST /api/import-csv?kind=…` | Прямой импорт для допустимых kind (одной транзакцией). |
| `POST /api/upload-prod-db` | Legacy admin-only endpoint; в UI отсутствует начиная с 0.18.1 и не является multi-DB restore. Не использовать вместо ADR-013 workflow. |

Лимиты: файл ≤ 50 МБ, ≤ 40 000 непустых строк; разделители `;`/`,`;
кодировки UTF-8 BOM и Windows-1251; preview живёт в памяти до 1 часа.

## FULL-инвентаризация (`/api/full-inventory/*`)

Отдельный контур вне общего лока (работает с внешним workspace, рабочую БД
читает read-only): `sessions` (POST — создать), `session` (GET),
`template.xlsx` (GET — строгий шаблон), `upload` (POST), `summary`, `rows`,
`findings` (GET, пагинация/фильтры), `resolutions` (POST — классификация
блокирующих строк). Требует `X-Correlation-ID` (или генерируется). Публикация
в рабочую БД отключена (`publish_available=false`).

## Monitoring

`POST /api/monitoring/manual-search` — `{host, problem}` → routing-решение,
DCIM-данные (если включён collector) и подготовленный текст письма; ничего не
отправляет и не пишет в БД. Выполняется вне общего лока. Ошибки → 400.

## База знаний (`/api/knowledge/*`)

`GET/POST /api/knowledge/articles`, `GET/PUT/DELETE /api/knowledge/<id>`,
вложения — отдельными подмаршрутами (upload/download с containment-проверкой
путей). Запись — `engineer`/`admin`; удаление — soft-delete.

## Отпуска (`/api/vacations/*`)

Все операции доступны любому аутентифицированному пользователю; actor
фиксируется в `vacation_history` и `vacation_audit_log` отдельной
`data/vacations.db`. Складские БД API не читает и не изменяет.

| Метод и путь | Назначение |
|---|---|
| `POST /api/vacations/employees` | Добавить сотрудника и начальное назначение. Payload: `first_name`, `last_name`, `site`, `schedule_type`, `shift_group`, `valid_from`, optional `note`, `is_site_senior`, `is_department_head`, `is_substitute`. |
| `POST /api/vacations/requests` | Создать отпуск. Payload: `employee_id`, `date_from`, `date_to`, `sfera_status`, optional `sfera_reference`, `substitute_employee_id`, `comment`. Конфликтная запись возвращается с `conflict_status=PENDING`. |
| `POST /api/vacations/requests/{id}/update` | Изменить период/статус/подменного и повторно вычислить конфликты. |
| `POST /api/vacations/conflicts/{request_id}/resolve` | `{"decision":"APPROVED"|"REJECTED","comment":"…"}` — подтвердить исключение либо отклонить отпуск. |
| `POST /api/vacations/employees/{employee_id}/assignment` | Effective-dated смена `site`, `schedule_type`, `shift_group`, `valid_from`, `note`. |

## Экспорт и шаблоны (GET)

`/export/*.csv` — balance, stock, receipt, issue (+`*-current` — только
последний проверенный файл), log, work-logs, daily-report,
uploaded-daily-report, weekly-report, problem-issues, delivery, audit.
Все CSV — `;` + UTF-8 BOM (Excel-совместимо). `receipt.csv` содержит все
приходы, включая признак opening balance; `issue.csv` содержит ровно одну
строку на каждую операцию расхода, включая несопоставленные строки, matched /
unmatched quantity и название, модель, инв. №, S/N и hostname целевого
оборудования. Пустые полные выгрузки сохраняют строку заголовков.

`/import/*-template.csv` — шаблоны: receipt, issue, bulk-issue, work-logs,
daily-report, delivery, inventory, inventory-numbers, equipment.

## Статика и страница

`GET /` — SPA-страница (HTML собирается на сервере, инлайновые style/script
вырезаются `_externalized_html()`); CSS/JS подключаются с
`?v=<inventory.__version__>`, чтобы браузер не смешивал runtime разных
релизов. `GET /static/…` — CSS/JS c anti-traversal проверкой;
`GET /favicon.ico`.
