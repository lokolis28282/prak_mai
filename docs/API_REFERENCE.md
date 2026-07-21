# ODE 0.15.0 — справочник HTTP API

Фактическая поверхность локального HTTP API (`inventory/webapp.py`,
порт по умолчанию `8765`). Составлен по коду версии 0.15.0. API предназначен
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
- Все мутации `/api/action` выполняются под глобальным `RLock` и одной
  SQLite-транзакцией; каждая значимая мутация пишет запись в `audit_log`.
- Складские мутации дополнительно проходят posting-guard: в состояниях
  `NOT_INITIALIZED`/`DEGRADED`/чужой контур запись блокируется (HTTP 409).

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

## Чтение данных (GET)

| Путь | Назначение |
|---|---|
| `/api/data` | Основной снапшот UI: stats/KPI, первые 500 строк баланса (`balance_limit=500`, `balance_truncated`), последние приходы, проблемы качества данных (`problems`, `problem_counts`), справочники, история склада, текущий пользователь, сводка категорий/типов и `warehouse_model_options` (модели, наблюдавшиеся для конкретных vendor+type). |
| `/api/balance` | Серверный поиск/сортировка баланса по всей БД: фильтры `query`, category/type, project/object, supplier/vendor, unit/datacenter и stock state; `limit` 1…5000, `offset` до 1 000 000, ответ содержит `has_previous`/`has_more`. UI догружает блоки по 500 при прокрутке. |
| `/api/position-card?serial_number=…` (или `position_key`) | Полная карточка позиции: реквизиты, остаток, размещение, поставка, Timeline. |
| `/api/position-search?query=…` | Поиск позиций (лимитированный, для «Списать»/карточек). |
| `/api/global-search?query=…` | Глобальный поиск от 2 символов по S/N, инв.№, hostname, наименованию, вендору, модели, поставке, проекту, полке, ЦОД, инженеру (limit 500). |
| `/api/scan-serial?serial=…` | Проверка одного отсканированного S/N (приход/расход сценарии). |
| `/api/deliveries` / `/api/delivery?id=…` | Реестр поставок / одна поставка со строками. |
| `/api/work-logs?…` | УВР с фильтрами (период, поиск, статус, раздел). |
| `/api/daily-report?date=…` | Отчёт за смену из событий склада. |
| `/api/weekly-report?date_from=…&date_to=…` | Недельная агрегация. |
| `/api/uploaded-daily-report?id=…` | Строки загруженного готового отчёта. |
| `/api/admin` | Только admin: backup-файлы, пользователи, журнал аудита. |
| `/api/warehouse/system-status` | Состояние складского контура (baseline/provisional, authoritative). |
| `/api/monitoring/status` | Статус Monitoring-модуля и его capabilities. |
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
| `CREATE_BACKUP` | Согласованная копия в `data/backups`. |
| `CHECK_DATABASE` | `PRAGMA integrity_check` + проверка ключевых таблиц. |
| `RESTORE_BACKUP` | `filename` (только basename, `.db`), `confirmed: true`; автоматический страховочный backup, атомарная публикация. |
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
| `POST /api/upload-prod-db` | Только admin: загрузка `.db` с backup, проверкой и откатом при ошибке. |

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

## Экспорт и шаблоны (GET)

`/export/*.csv` — balance, stock, receipt, issue (+`*-current` — только
последний проверенный файл), log, work-logs, daily-report,
uploaded-daily-report, weekly-report, problem-issues, delivery, audit.
Все CSV — `;` + UTF-8 BOM (Excel-совместимо).

`/import/*-template.csv` — шаблоны: receipt, issue, bulk-issue, work-logs,
daily-report, delivery, inventory, inventory-numbers, equipment.

## Статика и страница

`GET /` — SPA-страница (HTML собирается на сервере, инлайновые style/script
вырезаются `_externalized_html()`); `GET /static/…` — CSS/JS c
anti-traversal проверкой; `GET /favicon.ico`.
