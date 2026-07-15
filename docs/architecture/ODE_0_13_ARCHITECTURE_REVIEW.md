# ODE 0.13 — архитектурная ревизия и целевая модель

Статус: **SOURCE REVIEW — не нормативная спецификация реализации**
Дата ревизии: 15 июля 2026
Область: архитектура, данные, миграция, безопасность, UI/API, производительность, тесты и документация
Ограничение этапа: продуктовый код, схема рабочей БД и пользовательские данные не изменяются

Нормативный proposed-комплект разделен по ответственности и начинается с
[docs/README.md](../README.md). Этот файл сохранен как evidence исходной
ревизии и перечень найденных фактов; при конфликте применяется приоритет из
нового индекса документации.

## 1. Решение в одном абзаце

ODE 0.13 следует строить как новый модульный монолит рядом с ODE 0.12, а не как цепочку исправлений внутри текущего WarehouseCore. Существующая система смешивает архив миграции, оперативный склад, текущий баланс, импорт, HTTP, авторизацию и отчеты. Критически важно, что мигрированные исторические приходы и расходы сейчас участвуют в расчете остатков. Это прямо противоречит новой бизнес-модели. Рекомендуемая архитектура вводит явное состояние NO_BASELINE, утвержденный инвентаризационный снимок как единственную начальную точку баланса, неизменяемый операционный журнал после снимка и пересобираемую проекцию текущего баланса. Legacy-история переносится в отдельный архив и никогда не становится бухгалтерским основанием остатка.

## 2. Что было проверено

Ревизия охватывала:

- весь отслеживаемый и неотслеживаемый состав репозитория;
- Python- и JavaScript-зависимости, маршруты, фасады, сервисы и точки доступа к БД;
- рабочую SQLite-БД, ее схему, объемы, индексы, планы запросов и фактические данные;
- текущие потоки Excel/CSV, Preview и миграционные инструменты;
- историю по серийному номеру и происхождение строк;
- авторизацию, роли, сессии, аудит и упаковку релиза;
- UI, HTTP API и границы модулей;
- тесты, архитектурные проверки и документацию;
- индекс графа кода после полного обновления.

Контрольная точка репозитория на момент ревизии:

- ветка: main;
- commit: 76afadd5355f4d379b19dcabf1f28850986d5300;
- рабочее дерево уже содержало 54 измененных и 52 новых файла;
- эти изменения считаются пользовательским исходным состоянием и не откатывались;
- версия в коде: 0.12.17.1 RC2, тогда как часть документов уже использует обозначения 0.13;
- новая версия ODE 0.13 должна быть установлена только после реализации и приемки архитектуры.

Проверки:

- 332 существующих теста завершились успешно;
- проверка границ модулей завершилась успешно;
- DOM-аудит завершился успешно;
- git diff --check не обнаружил ошибок;
- тестовый прогон выдавал предупреждения о незакрытых SQLite-соединениях;
- зеленые тесты подтверждают текущую реализацию, но не подтверждают правильность новой бизнес-модели.

## 3. Критические проблемы текущей системы

| Приоритет | Проблема | Последствие |
|---|---|---|
| Critical | Старые движения преобразованы в stock_receipts и stock_issues и входят в stock_balance | Архив определяет текущий баланс, что запрещено новой моделью |
| Critical | Нет inventory_sessions, утвержденного snapshot и snapshot items | Невозможно доказать, от какого снимка начался баланс |
| Critical | Полная инвентаризация не имеет долговечного Preview/Approve-процесса | Проверка оператора не является транзакционной границей |
| Critical | Релизный пакет включает рабочую data/warehouse.db | Риск утечки пользователей, истории и паролей; смешение продукта и данных |
| Critical | Любое ФИО инженера может войти через общий встроенный аккаунт и получить write-права | Нет надежной идентификации и персональной ответственности |
| High | WarehouseCore содержит 3828 строк, webapp.py — 1836 строк | Изменение одной области затрагивает множество несвязанных областей |
| High | Сервисы вызываются строками через ServiceAdapter и __getattr__ | Компилятор и статический анализ не видят реальные контракты |
| High | initialize выполняет миграции схемы и бизнес-данных при запуске | Запуск приложения способен неявно изменить рабочую БД |
| High | Preview хранится в памяти процесса | Перезапуск теряет состояние; подтверждение не воспроизводимо |
| High | Большинство read-вызовов открывают read/write-соединение и делают commit | Лишняя блокировка и неясные транзакционные границы |
| High | Flat references и v2 references используются одновременно | Два источника истины и скрытое создание справочников |
| High | Аудит дублирует миграционную provenance построчно | Рабочая БД раздута и технический аудит смешан с источниками данных |
| High | Единственный action-based API и HTML в Python | Невозможно независимо развивать API и UI |
| Medium | REAL используется для количества | Возможен дрейф дробных значений |
| Medium | Документация раздроблена на десятки stage/review/bug файлов | Нет устойчивой точки входа и действующего архитектурного контракта |

## 4. Фактическое состояние данных

Рабочая data/warehouse.db на момент ревизии имела размер около 579 MB. Основные количества:

| Объект | Строк |
|---|---:|
| migration_staging_rows | 71 360 |
| migration_full_reconciliation | 71 360 |
| migration_serial_cells | 91 717 |
| migration_full_identities | 50 000 |
| migration_full_warnings | 129 813 |
| audit_log | 146 641 |
| stock_receipts | 50 000 |
| stock_issues | 18 798 |
| stock_issue_allocations | 18 798 |
| equipment | 0 |
| operations | 0 |
| users | 1 |

Наибольший объем занимают migration_full_reconciliation, migration_staging_rows и audit_log. Операционная БД фактически является одновременно рабочим хранилищем, staging-зоной, архивом миграции и отчетом о миграции.

Дополнительные выводы:

- schema user_version равен 0;
- нет реестра примененных версий схемы;
- текущий migration marker имеет статус READY_FOR_MANUAL_ACCEPTANCE;
- даты используют внутренние миграционные статусы, а не целевой набор exact, missing, estimated, corrupted;
- оборудования в таблице equipment нет, а карточки фактически представлены строками прихода;
- уникальность S/N привязана к приходу, а не к самостоятельной карточке оборудования;
- текущий баланс агрегирует все receipts и allocations;
- запрос баланса строит временные B-tree для GROUP BY и ORDER BY;
- точный поиск S/N индексируется, но широкий поиск выполняет сканирование;
- текущая схема не имеет доказуемого ledger cutoff для инвентаризационного снимка.

## 5. Почему постепенная правка текущей архитектуры не рекомендуется

Текущие границы модулей в основном номинальны. В inventory/services находятся десятки однострочных прокси, которые по строковому имени возвращаются в WarehouseCore. WarehouseFacade использует Any, собирает множество псевдосервисов и продолжает зависеть от общего совместимого ядра. Поэтому перенос методов по файлам не даст модульности: источник состояния, транзакции, ошибки и зависимости останутся общими.

Постепенная совместимость также опасна для данных. Старое ядро считает legacy-движения рабочими операциями, а новое ядро обязано их игнорировать. Dual-write между этими моделями создаст два разных баланса. Рекомендуется:

1. строить ODE 0.13 рядом с ODE 0.12;
2. заморозить запись на короткое окно переключения;
3. перенести данные в новую БД по явному манифесту;
4. проверить новую БД;
5. атомарно переключить приложение;
6. сохранить старую БД только для rollback.

## 6. Непереговорные инварианты ODE 0.13

1. Legacy-история никогда не изменяет баланс.
2. До первого утвержденного снимка баланс имеет состояние NOT_INITIALIZED, а не нулевое значение.
3. До появления baseline запрещены проводки прихода, расхода, перемещения и корректировки.
4. Только APPROVED snapshot может стать baseline.
5. Preview не изменяет ни один байт рабочей БД.
6. После утверждения snapshot и складские проводки неизменяемы; исправление выполняется новой корректировкой или reversal.
7. Текущий баланс всегда воспроизводим из утвержденного снимка и операционного ledger после его cutoff.
8. Проекция баланса является ускорителем чтения, а не самостоятельным источником истины.
9. Каждая импортированная строка имеет воспроизводимую provenance: файл, hash, лист, номер строки, raw values и версию парсера.
10. ФИО участника исторического события сохраняется как обязательный raw-текст, даже если пользователь не найден.
11. Технический audit, legacy history и warehouse ledger — три разные сущности.
12. UI, API и reports не выполняют SQL напрямую.
13. Repository не делает commit; транзакцией управляет unit of work/use case.
14. Запуск приложения не мигрирует схему и не переносит бизнес-данные.

## 7. Предлагаемая архитектура

Архитектурный стиль: модульный монолит с явными bounded contexts и одним контролируемым процессом записи. Микросервисы сейчас не нужны: они увеличат операционную сложность, но не улучшат корректность локального складского приложения.

Поток зависимостей:

    UI -> API -> application use cases/facades
                    |
                    +-> equipment
                    +-> inventory
                    +-> warehouse
                    +-> balance
                    +-> history
                    +-> references
                    +-> users/security
                    +-> imports
                    +-> reports
                    +-> audit
                             |
                             v
                    infrastructure/db

Правила:

- доменные модули не импортируют API, UI и конкретный SQLite-драйвер;
- application-слой координирует один use case;
- infrastructure реализует repository-протоколы;
- cross-module вызов идет через типизированный публичный контракт;
- facade допускается только как небольшой публичный контракт контекста;
- запрещены string dispatch, service: Any и универсальный WarehouseCore.

## 8. Целевая структура проекта

    ode/
        bootstrap/
            application.py
            configuration.py
            lifecycle.py
        equipment/
            models.py
            repository.py
            service.py
            validators.py
            queries.py
            facade.py
        warehouse/
            models.py
            repository.py
            service.py
            validators.py
            queries.py
            facade.py
        inventory/
            models.py
            repository.py
            service.py
            validators.py
            queries.py
            facade.py
        history/
            models.py
            repository.py
            queries.py
            facade.py
        balance/
            models.py
            projector.py
            repository.py
            service.py
            queries.py
            facade.py
        references/
            models.py
            repository.py
            service.py
            validators.py
            queries.py
        users/
            models.py
            repository.py
            service.py
        security/
            authentication.py
            authorization.py
            sessions.py
            password_policy.py
        audit/
            models.py
            repository.py
            service.py
            queries.py
        imports/
            models.py
            service.py
            validators.py
            preview_store.py
            xlsx/
                reader.py
                identifiers.py
                normalization.py
                schema_detection.py
        reports/
            models.py
            service.py
            queries.py
        api/
            app.py
            routes/
            dto/
            errors.py
        ui/
            templates/
            static/
                js/
                css/
        infrastructure/
            db/
                connection.py
                unit_of_work.py
                migrations/
                sqlite/
            files/
            clock.py
            identifiers.py
        shared/
            errors.py
            types.py
    tests/
        unit/
        integration/
        contract/
        migration/
        performance/
        e2e/
    docs/
    tools/

Это не требование механически создавать каждый файл. Файл появляется только при наличии ответственности. Пустые modules.py и facade.py запрещены.

## 9. Ответственность модулей

### equipment

Владеет карточкой физического оборудования: внутренний ID, raw и normalized S/N, инвентарный номер, модель/каталог, жизненный статус. Не знает о формате Excel и не вычисляет остатки.

### warehouse

Владеет неизменяемым ledger операций после baseline: приход, расход, перемещение, положительная и отрицательная корректировка, reversal. Не читает legacy_history.

### inventory

Владеет сессиями полной инвентаризации, утверждением снимка, cutoff и reconciliation. Координирует создание/сопоставление equipment, но не парсит XLSX.

### history

Владеет архивной историей и единым read-only timeline по S/N. Источник legacy_history никогда не экспортируется в balance.

### balance

Владеет формулой баланса и projection. Умеет полностью пересобрать projection и доказать ее равенство snapshot + ledger.

### imports

Владеет чтением внешних файлов, Preview workspace, findings, match/duplicate resolution и provenance. Не пишет в рабочую БД до approve.

### references

Единственный владелец справочников и aliases. Не создает canonical value молча при чтении или нормализации.

### users и security

Users хранит учетные записи и профиль. Security выполняет аутентификацию, сессии, роли и permissions. ФИО из legacy не обязано быть пользователем.

### audit

Хранит технические и security-события: вход, изменение пользователя, утверждение snapshot, публикация импорта, backup/restore. Не дублирует каждую исходную Excel-строку.

### reports

Читает публичные query contracts и read models. Не зависит от таблиц другого контекста напрямую.

### api и ui

API валидирует транспортные DTO и вызывает use cases. UI является отдельным потребителем API; Python не строит большие HTML-фрагменты.

## 10. Целевая модель БД

Имена приведены как логический контракт. Точный DDL оформляется отдельной версионированной миграцией после согласования.

### Системные таблицы

| Таблица | Назначение |
|---|---|
| schema_migrations | Версия, checksum, время и исполнитель миграции |
| app_state | Состояние NO_BASELINE/ACTIVE/MAINTENANCE и активные идентификаторы |

### Пользователи и безопасность

| Таблица | Назначение |
|---|---|
| users | Персональная учетная запись, ФИО, password hash, active |
| roles | Нормализованный набор ролей |
| user_roles | Связь пользователей и ролей |
| sessions | Долговечные отзываемые сессии, если используется web-режим |

Рекомендуемые роли первой версии: operator, admin, auditor. Инженер является автором/участником исходных данных, но не получает неидентифицированный write-доступ.

### Справочники

| Таблица | Назначение |
|---|---|
| reference_domains | Типы справочников |
| reference_values | Канонические значения |
| reference_aliases | Проверенные варианты исходных значений |
| catalog_items | Модели/типы оборудования и расходных материалов |
| warehouses | Склады |
| warehouse_locations | Зоны и места хранения |

Flat и v2-схемы объединяются. У каждого alias есть provenance и статус рассмотрения.

### Оборудование

| Таблица | Назначение |
|---|---|
| equipment | Самостоятельная карточка, не зависящая от прихода |

Ключи и ограничения:

- внутренний INTEGER ID для эффективных joins;
- serial_raw сохраняет исходное значение;
- serial_key — канонический ключ точного поиска;
- inventory_number_raw и inventory_number_key разделены;
- частичные unique indexes применяются только к непустым ключам;
- история изменения идентификаторов записывается в audit либо отдельную таблицу identity history.

### Импорт

| Таблица | Назначение |
|---|---|
| import_commits | Только утвержденные импорты и их manifest |
| import_row_links | Связь утвержденной строки с созданными сущностями |

Preview-таблицы не находятся в рабочей БД. Отдельная workspace-БД содержит:

- preview_runs;
- preview_rows;
- preview_findings;
- preview_matches;
- preview_resolutions.

### Инвентаризация

| Таблица | Назначение |
|---|---|
| inventory_sessions | Жизненный цикл DRAFT/PREVIEWED/APPROVED/REJECTED |
| inventory_snapshots | Утвержденный immutable snapshot, import commit, ledger cutoff |
| inventory_snapshot_items | Позиции снимка и их provenance |
| inventory_reconciliation_items | Разница с предыдущим состоянием для объяснения оператору |

Snapshot items не обновляются после утверждения. Новый полный пересчет создает новый snapshot.

### Операционный склад

| Таблица | Назначение |
|---|---|
| warehouse_transactions | Заголовок posted-транзакции, вид, время, actor, comment |
| warehouse_transaction_lines | Неизменяемые движения по equipment/item/location |

Виды: RECEIPT, ISSUE, TRANSFER, ADJUSTMENT_IN, ADJUSTMENT_OUT, REVERSAL. Для серийной карточки quantity всегда равен одной единице. Для массового материала используется quantity_minor INTEGER и определенный scale/UOM, а не REAL.

### Баланс

| Таблица | Назначение |
|---|---|
| balance_projection_state | Snapshot ID, последний примененный ledger sequence, checksum |
| balance_projection | Материализованный текущий остаток |

Projection обновляется в той же транзакции, что и posted ledger, либо достраивается идемпотентным projector. Ее можно удалить и восстановить без потери истины.

### Архивная история

| Таблица | Назначение |
|---|---|
| legacy_source_files | Файл, SHA-256, workbook metadata, дата загрузки |
| legacy_history | Одна нормализованная архивная запись на исходное событие |

Обязательные поля legacy_history:

- serial_raw и serial_key;
- event_type_raw и normalized_event_type;
- performed_by_name;
- accepted_by_name, если применимо;
- occurred_at;
- date_quality: exact, missing, estimated или corrupted;
- date_raw и estimation_basis;
- comment_raw;
- source_file_id;
- source_sheet;
- source_row_number;
- source_payload или ссылка на неизменяемую raw-строку.

### Технический аудит

| Таблица | Назначение |
|---|---|
| audit_log | Структурированные append-only действия пользователя и системы |

Audit хранит batch-level события импорта. Построчная provenance находится в import_row_links и legacy_history, а не копируется в audit_log.

## 11. Формула баланса и состояния системы

До первой инвентаризации:

    app_state = NO_BASELINE
    balance = NOT_INITIALIZED
    legacy history = доступна только для чтения
    warehouse posting = запрещен

После утверждения:

    balance(t) =
        latest approved snapshot at ledger_cutoff
        + posted receipts after cutoff
        - posted issues after cutoff
        ± posted adjustments after cutoff
        + net transfers by location after cutoff

Каждый snapshot содержит точный ledger_cutoff_id. Поэтому операция, проведенная одновременно с инвентаризацией, не может быть учтена дважды или потеряна.

Новый полный snapshot может стать новым baseline. Предыдущий snapshot сохраняется навсегда, а reconciliation объясняет разницу между расчетным состоянием до утверждения и фактическим Excel-снимком.

## 12. Идеальный процесс Excel Preview

### Upload

1. Оператор загружает XLSX.
2. Система вычисляет SHA-256 и сохраняет файл вне рабочей БД.
3. Создается отдельная disposable workspace-БД.
4. Reader потоково читает workbook и сохраняет raw cells без потери ведущих нулей.
5. Parser фиксирует версию схемы и правила нормализации.

### Preview

Preview показывает отдельными страницами:

- blocking errors;
- warnings;
- точные совпадения;
- вероятные совпадения;
- дубликаты внутри файла;
- конфликты с рабочими идентификаторами;
- новые карточки;
- отсутствующие ожидаемые карточки;
- неизвестные справочники;
- неверные или сомнительные даты;
- raw source, лист и строку Excel для каждого результата.

Preview обрабатывается потоково и пакетами. Ограничение в десятки тысяч строк в памяти недопустимо.

### Перед подтверждением

Повторно проверяются:

- source file hash;
- parser и schema version;
- preview digest;
- все operator resolutions;
- fingerprint рабочей БД;
- текущий ledger head;
- активный baseline;
- права оператора;
- актуальность справочников.

Если хоть один fingerprint изменился, Preview считается stale и перестраивается.

### Publish

Наиболее надежный для SQLite вариант:

1. включить краткий maintenance lock;
2. SQLite backup API копирует рабочую БД в warehouse.db.next;
3. в candidate применяются approved snapshot, equipment, provenance и projection;
4. выполняются integrity_check, foreign_key_check и доменные проверки;
5. projection полностью пересобирается и сравнивается с ожидаемым результатом;
6. candidate синхронизируется на диск;
7. создается проверенный pre-publish backup;
8. соединения закрываются;
9. candidate атомарно становится рабочей БД;
10. при любой ошибке candidate удаляется, а рабочая БД остается неизменной.

Такой publish лучше одной гигантской транзакции: Preview буквально не касается рабочей БД, а утверждение 1 000 000 строк не оставит пользователю полупримененное состояние.

## 13. История по S/N

Карточка истории строится read-only запросом из нескольких независимых источников:

1. legacy_history — события до baseline;
2. inventory_snapshot_items — факт присутствия в утвержденных снимках;
3. warehouse_transactions — операции после baseline;
4. audit_log — административные действия с карточкой.

UI обязан явно помечать source type. Legacy-событие нельзя визуально выдавать за современную складскую проводку.

Для каждого события показываются:

- кто выполнил;
- кто принял, если применимо;
- дата и качество даты;
- действие;
- комментарий;
- имя файла;
- лист;
- строка Excel;
- raw source value;
- import/snapshot/transaction ID.

Основной индекс: legacy_history(serial_key, occurred_at, id). Точный поиск работает по serial_key; fuzzy-поиск не используется для финансового сопоставления.

## 14. Производительность на 500 000–1 000 000 карточек

Основное решение — не агрегировать весь ledger при каждом открытии страницы. Запрос текущего баланса читает balance_projection, а расчетная истина остается воспроизводимой.

Обязательные меры:

- INTEGER primary keys и узкие covering indexes;
- fixed-point INTEGER для количеств;
- batch insert/upsert;
- keyset pagination вместо глубокого OFFSET;
- отдельные индексы для raw и normalized identifiers;
- FTS5 только для общего текстового поиска;
- точный S/N и инвентарный номер всегда через B-tree;
- WAL и busy_timeout для локального диска;
- один контролируемый writer и несколько readers;
- read-only соединения для запросов;
- запрет размещения SQLite-файла на сетевой файловой системе;
- явные лимиты и backpressure для Preview;
- online progress и отмена долгих импортов.

Приемочные performance gates на типовом оборудовании:

| Сценарий | Цель |
|---|---:|
| Точный поиск S/N при 1 млн карточек | p95 менее 100 ms |
| Страница баланса 100 строк | p95 менее 300 ms |
| История одного S/N | p95 менее 300 ms |
| Preview 1 млн строк | bounded memory, без изменения рабочей БД |
| Полная rebuild projection | измеримый offline job с progress и checksum |

Абсолютные времена следует утвердить после фиксации минимальной поддерживаемой машины. Архитектурные gates — отсутствие full scan в точных запросах и ограниченная память — обязательны независимо от железа.

## 15. Разделение текущих сервисов

Из WarehouseCore должны быть извлечены самостоятельные use cases:

| Текущая ответственность | Новый владелец |
|---|---|
| login, users, roles | users/security |
| references и aliases | references |
| receipt/issue/transfer/adjustment | warehouse |
| stock_balance и position_card balance | balance |
| inventory_compare | inventory + imports |
| migration/full/pilot imports | imports/migration tools |
| position history | history |
| reports/export | reports |
| audit write/read | audit |
| backup/diagnostics | infrastructure/operations |
| HTTP route switch | api/routes |
| HTML generation | ui |

Одна функция выполняет одну фазу. Например, XLSX reader возвращает raw rows; normalizer возвращает normalized rows; matcher возвращает matches; validator возвращает findings; publisher выполняет один утвержденный use case в unit of work.

## 16. Файлы и компоненты для удаления после согласованной реализации

Удаление выполняется не сейчас, а после переноса контрактов и прохождения migration gates.

### Удалить как архитектурные заглушки или compatibility layer

- inventory/service.py;
- inventory/services/ целиком после замены string-dispatch;
- inventory/models/ с неиспользуемыми placeholder dataclasses;
- inventory/warehouse/balance.py;
- inventory/warehouse/history.py;
- inventory/warehouse/inventory.py;
- inventory/warehouse/models.py;
- inventory/administration/audit.py;
- inventory/administration/backup.py;
- inventory/administration/diagnostics.py;
- inventory/administration/users.py;
- inventory/reports/weekly.py;
- inventory/reports/exports.py;
- inventory/monitoring/models.py;
- re-export-only inventory/warehouse/issues.py;
- re-export-only inventory/warehouse/receipts.py;
- re-export-only inventory/warehouse/issue_previews.py;
- re-export-only inventory/shared/csv_tools.py;
- JavaScript-файлы, которые содержат только legacy marker или alias к window globals;
- отслеживаемый release/ODE_windows_test.zip;
- generated cache, pyc и локальные отчеты выполнения.

Перед удалением каждый кандидат проверяется поиском импортов и contract tests. Пустой файл не сохраняется ради видимости модульности.

### Удалить или исправить подтвержденные кандидаты

Ревизия выявила кандидатов на неиспользуемые импорты, включая AuditLogEventReader в application.py, Iterable в нескольких migration/repository файлах, json в warehouse/references.py и sys в audit_module_boundaries.py. Это не основание для массового удаления: после новой раскладки запускаются Ruff/Pyright и удаляется только подтвержденное.

## 17. Компоненты для временной архивации

После успешного cutover они не должны входить в runtime и релиз:

- inventory/migration/full_builder.py;
- inventory/migration/pilot_builder.py;
- inventory/migration/candidate_db.py;
- остальные one-off full/pilot builders;
- inventory/warehouse/migration_full*.py;
- inventory/warehouse/migration_pilot*.py;
- scripts/migration_full_candidate.py;
- scripts/migration_pilot.py;
- scripts/migration_reference_data.py;
- scripts/audit_warehouse_database.py;
- scripts/stabilize_reference_data.py;
- scripts/remove_test_serial.py;
- migration smoke scripts;
- start_*migration* launchers;
- старые candidate/pilot tests;
- stage-specific manual test и migration документы.

Архив хранится вне runtime package, например tools/archive/0.12-migration или в отдельном release artifact. Он не импортируется приложением.

## 18. Код, который следует сохранить и извлечь

Ценными являются не текущие фасады, а проверенные низкоуровневые правила:

- безопасное чтение raw OOXML cells;
- сохранение строковых S/N и ведущих нулей;
- serial preservation;
- часть reference normalization после повторной доменной проверки;
- временные БД в тестах;
- security/atomicity tests;
- smoke runner;
- fixtures с проблемными идентификаторами и датами.

Эти компоненты переносятся в imports/xlsx и test support с новыми типизированными контрактами. One-off orchestration вокруг них не переносится.

## 19. UI и API

### Текущие проблемы

- make_handler — функция примерно на 1076 строк с очень высокой сложностью;
- webapp.py одновременно содержит сервер, маршруты, HTML и CSS;
- /api/action является универсальным switch;
- часть write-импортов доступна напрямую без единой Preview-модели;
- JS использует множество window globals, innerHTML и inline handlers;
- несколько файлов под видом модулей только переэкспортируют legacy globals.

### Целевой API

Примеры ресурсов:

- POST /api/v1/inventory-sessions;
- POST /api/v1/inventory-sessions/{id}/preview;
- POST /api/v1/inventory-sessions/{id}/approve;
- POST /api/v1/inventory-sessions/{id}/reject;
- GET /api/v1/equipment/{id};
- GET /api/v1/equipment/by-serial/{serial};
- GET /api/v1/equipment/{id}/timeline;
- POST /api/v1/warehouse-transactions;
- POST /api/v1/warehouse-transactions/{id}/reverse;
- GET /api/v1/balance;
- GET /api/v1/legacy-history.

DTO валидируются на границе. Ошибки имеют стабильные machine codes. API versioning защищает UI и внешних потребителей.

### Целевой UI

- один application shell;
- реальные ES modules по feature;
- route registry вместо огромного switch;
- templates/components находятся в ui, не в Python;
- addEventListener вместо inline onclick/onchange;
- безопасное создание DOM вместо бесконтрольного innerHTML;
- server-side pagination для больших таблиц;
- отдельные экраны Preview findings, resolution и approval summary.

## 20. Безопасность

Обязательные изменения:

1. удалить общий дефолтный admin/password из production bootstrap;
2. создать персональные учетные записи;
3. отказаться от произвольного входа по ФИО инженера;
4. хранить роль и permissions на сервере;
5. сделать сессии отзываемыми и долговечными;
6. разделить operator, admin и auditor;
7. записывать actor user ID и snapshot ФИО в каждое критичное действие;
8. не включать live DB, backups и preview workspaces в build/release;
9. добавить CSRF-защиту для cookie-based write routes;
10. установить Secure cookie в HTTPS-режиме;
11. установить лимиты upload, rate limits и file-type validation;
12. шифрование диска считать операционной обязанностью, но не заменой access control.

## 21. Новая структура документации

В корне остаются:

- README.md — единственная точка входа;
- CHANGELOG.md;
- LICENSE, если применимо;
- краткий CLAUDE.md только с инструкциями для агента, если он действительно нужен.

Целевая структура:

    docs/
        README.md
        architecture/
            overview.md
            modules.md
            data-model.md
            imports.md
            security.md
        decisions/
            ADR-001-modular-monolith.md
            ADR-002-snapshot-ledger-balance.md
            ADR-003-external-preview-workspace.md
            ADR-004-sqlite-publish-model.md
        development/
            setup.md
            testing.md
            packaging.md
            codebase-memory.md
        operations/
            backup-restore.md
            database-runbook.md
        migration/
            0.12-to-0.13.md
        releases/
            0.13.md
        archive/
            0.12/

### Объединить

- BUGS, BUG_REPORT, BUG_STAGE и аналогичные документы — в один архивный 0.12/reviews/bugs.md;
- QA и QA_STAGE — в 0.12/reviews/qa.md;
- CODE_REVIEW, PRODUCT_REVIEW, PERFORMANCE_REVIEW, ARCHITECT_REVIEW — в 0.12/reviews/;
- stage-specific implementation plans — в 0.12/stages/;
- migration manuals и candidate reports — в 0.12/migration/;
- текущие README по подпапкам — либо в один действующий документ, либо в локальный README только при реальной необходимости.

### Удалить

- полностью дублирующиеся документы;
- автоматически генерируемые отчеты, которые можно воспроизвести;
- документы, описывающие уже удаленный код и не имеющие исторической ценности;
- временные bug/status файлы после переноса уникальной информации.

Старый DATA_MODEL_ODE_013.md не должен оставаться действующей спецификацией, если он сохраняет receipt-as-card и compatibility architecture. Его нужно архивировать после принятия этого документа.

## 22. План миграции без потери данных

### Этап 0. Freeze manifest

- остановить запись;
- закрыть все SQLite handles;
- создать минимум две проверенные копии рабочей БД;
- зафиксировать SHA-256, размер, schema dump, table counts и integrity_check;
- зафиксировать hashes всех исходных XLSX;
- сохранить commit приложения и версию migration tools;
- убедиться, что backup восстанавливается в отдельный путь.

Контрольная сумма, снятая в этой ревизии, является только диагностической. Для миграции создается новый manifest после freeze.

### Этап 1. Новая схема рядом

- создать чистую ODE 0.13 candidate DB;
- применить versioned migrations;
- установить app_state = NO_BASELINE;
- не открывать candidate старым приложением.

### Этап 2. Пользователи и справочники

- перенести только проверенные учетные записи;
- заставить сменить дефолтный/известный пароль;
- сопоставить роли с operator/admin/auditor;
- объединить flat/v2 references;
- сгенерировать mapping report для каждого alias;
- неизвестное значение не превращать автоматически в canonical.

### Этап 3. Legacy archive

- использовать authoritative migration reconciliation и source registry;
- перенести каждую из 71 360 исходных строк ровно один раз;
- связать строку с source file hash, sheet и Excel row;
- сохранить raw identifiers, ФИО, комментарий и date quality;
- отдельно обнаружить и перенести возможные операции после миграционного cutover;
- не копировать stock_receipts/stock_issues как основание нового баланса;
- не копировать построчные migration audit events в новый audit_log.

### Этап 4. Проверка архива

- source row count и hashes совпадают;
- нет потерянных или повторных source keys;
- выборка S/N воспроизводит все исходные события;
- corrupted/missing/estimated dates имеют явные статусы;
- performed_by_name заполнен либо запись помещена в blocking quarantine;
- ни одна legacy_history row не имеет ссылки на balance projection.

### Этап 5. Первый baseline

- оператор загружает фактическую полную инвентаризацию;
- система строит внешний Preview;
- оператор разрешает конфликты;
- до approve hash рабочей БД не меняется;
- approve создает equipment, import_commit, inventory_session, snapshot items и projection в candidate;
- ledger cutoff фиксируется;
- snapshot становится APPROVED только после всех проверок.

### Этап 6. Приемка candidate

- PRAGMA integrity_check;
- PRAGMA foreign_key_check;
- domain invariant checks;
- ровно один активный approved baseline;
- projection rebuild дает тот же checksum и те же totals;
- legacy history не участвует в rebuild;
- все equipment identifiers уникальны по правилам;
- history-by-S/N показывает source provenance;
- security role matrix проходит;
- performance suite проходит на 1 млн синтетических карточек;
- release package не содержит пользовательскую БД.

### Этап 7. Cutover

- создать final pre-cutover backup;
- остановить старый процесс;
- атомарно переключить DB/config/application;
- выполнить read-only smoke;
- открыть запись;
- записать audit event о cutover;
- наблюдать ошибки, lock time и latency.

### Этап 8. Rollback

Rollback — это возврат к нетронутой ODE 0.12 DB и старому binary/config, а не обратное копирование частично новых таблиц. Условия и максимальное окно rollback фиксируются до cutover.

### Этап 9. Очистка

Только после подписанной приемки:

- убрать compatibility layer;
- переместить migration builders в archive;
- прекратить отслеживать live data/warehouse.db;
- удалить release ZIP из Git;
- уплотнить документацию;
- установить версию ODE 0.13;
- создать release notes и финальный migration manifest.

## 23. Тестовая стратегия ODE 0.13

### Unit

- нормализация без БД;
- date quality;
- serial preservation;
- duplicate classification;
- balance arithmetic;
- role/permission matrix.

### Integration

- каждый SQLite repository;
- unit of work rollback;
- explicit migrations;
- snapshot approval;
- ledger posting и reversal;
- projection rebuild;
- history union;
- backup/publish/restore.

### Contract

- публичные facades/use cases;
- API DTO и error codes;
- отсутствие импортов между запрещенными слоями;
- запрет SQL в UI/API/reports.

### Migration

- полный набор 71 360 source rows;
- повторный запуск дает тот же результат;
- прерванный import не меняет рабочую БД;
- hashes и provenance сохраняются;
- current legacy receipts/issues не попадают в ledger;
- rollback восстанавливается.

### Performance

- 1 млн equipment;
- несколько миллионов legacy events;
- ledger growth;
- exact ID search;
- paginated balance;
- Preview memory bound;
- concurrent readers и один writer.

### Security

- default credential отсутствует;
- произвольное ФИО не дает вход;
- CSRF/session expiration/revocation;
- upload limits;
- path traversal и malformed XLSX;
- audit actor integrity.

Старые тесты, которые требуют синхронизации legacy equipment или равенства нового facade старому WarehouseCore, архивируются. Тесты идентификаторов, atomicity и security адаптируются и сохраняются.

## 24. Контроль качества реализации

Изменение допускается в main только при выполнении:

- Ruff/formatter без исключений по новым модулям;
- Pyright или mypy для публичных контрактов;
- cyclomatic complexity gate;
- запрет файла свыше согласованного размера без ADR;
- repository interfaces не содержат Any;
- нет динамического getattr dispatch по именам use cases;
- нет implicit schema migration на startup;
- нет live DB в Git/package;
- все write use cases имеют audit, permission и atomicity tests;
- DB migration имеет forward verification и documented rollback;
- README указывает только на действующие документы.

Рекомендуемый мягкий предел — 400 строк на production-файл и 50 строк на функцию. Превышение возможно только при доказанной cohesive responsibility и review.

## 25. Файлы, которые не изменялись на этапе ревизии

На этом этапе не менялись:

- product Python/JavaScript/CSS;
- data/warehouse.db;
- DB schema и данные;
- версия приложения;
- существующие документы и release artifacts;
- пользовательские текущие изменения.

Создан только этот proposed architecture document. Индекс графа кода был обновлен во внешнем MCP cache для анализа; это не изменение репозитория или рабочей БД.

## 26. Решения для согласования

Предлагается согласовать пакет целиком:

1. Чистый пакет ode/ и side-by-side DB вместо развития compatibility shell inventory/.
2. Legacy history является только архивом; первый approved snapshot — единственный начальный баланс.
3. До baseline система показывает NOT_INITIALIZED и блокирует складские проводки.
4. Preview хранится во внешней workspace-БД; рабочая БД до approve не меняется.
5. Approve выполняется через проверенный candidate DB и атомарную публикацию.
6. Balance projection используется для скорости, но полностью пересобирается из snapshot + ledger.
7. Старые движения не копируются в новый warehouse ledger.
8. Общий инженерный login удаляется; используются персональные operator/admin/auditor accounts.
9. Live DB и backups исключаются из Git и release package.
10. One-off migration code и stage-documents архивируются после cutover.
11. Версия ODE 0.13 устанавливается только после прохождения migration и acceptance gates.

## 27. Итог по восьми пунктам задания

1. Проблемы: выявлены и ранжированы в разделах 3–5.
2. Изменения: новая модель и инварианты определены в разделах 6–14.
3. Файлы для удаления: перечислены в разделе 16.
4. Файлы и документы для объединения: разделы 17 и 21.
5. Новые модули: разделы 7–9.
6. Разделение сервисов: раздел 15.
7. Итоговая структура: раздел 8.
8. Миграция без потери данных: раздел 22, с проверками и rollback.

После согласования следующим артефактом должен стать не код, а короткий набор ADR и точный versioned DDL с migration mapping specification. Только затем начинается реализация по вертикальным срезам: infrastructure → history → imports/preview → inventory/snapshot → balance → warehouse → API/UI → cutover.
