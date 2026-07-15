# Monitoring — ODE 0.13 Integration Review

Статус: **READ-ONLY REVIEW — не изменяет код, DDL, JSON или тесты**
Baseline: branch `main`, HEAD `76afadd5355f4d379b19dcabf1f28850986d5300` (2026-07-14,
"feat: add bulk inventory number import"), working tree содержит несочтённые
Stage 0.13.x изменения (см. `git status`). Дата review: 2026-07-15.

Этот документ отвечает на входной запрос «read-only monitoring integration
architecture review» и фиксирует, что реально существует в репозитории, а не
то, что было описано в постановке задачи. Расхождение с постановкой —
находка №1 этого review и определяет весь дальнейший объём документа.

---

## 1. Executive verdict

**Входная посылка задачи неверна.** Формулировка задачи описывает «коллега
завершил старый модуль мониторинга» с hostname routing, manual search и JSON
rule files, готовыми к классификации/переносу. Ни один из этих компонентов не
существует в рабочем дереве, ни в одном коммите на любой ветке, ни в stash.
Единственный существующий backend — неактивная Stage 0.12.6 заглушка (19
строк facade, 1 строка models, `enabled: false`), которая уже отмечена в
`docs/architecture/ODE_0_13_ARCHITECTURE_REVIEW.md` (раздел 16) как кандидат
на удаление после cutover. Подтверждено с пользователем: review продолжен как
**greenfield-проектирование**, а не как классификация существующего кода.

Из этого следует:

- Разделы «что переносить почти без изменений» и «hostname routing review
  существующего алгоритма» (пункты 5, 6 постановки) **не применимы** —
  переносить нечего, алгоритма для аудита ReDoS/Unicode/duplicate-rules не
  существует. Ниже даны требования к будущей реализации вместо аудита
  несуществующего кода.
- `docs/architecture/module-boundaries.md` (ODE 0.13 approved baseline) **не
  содержит строки `monitoring`** в таблице контрактов модулей — monitoring не
  является утверждённым bounded context. Любой новый код должен сначала
  пройти тот же ADR/module-boundaries процесс, что и остальные 12 контекстов.
- `docs/architecture/OPEN_DECISIONS.md` уже содержит **OPEN-009 — Monitoring
  release scope**: рекомендация product owner — «health/diagnostics only;
  full monitoring later», non-blocker для Stage 0.13.1 core. Roadmap-раздел
  ниже (§15) согласован с этим открытым решением, а не противоречит ему.
- Жёсткая зависимость monitoring на Equipment identity (`EquipmentLookup`
  query port) **тоже ещё не реализована** в `ode/` — на момент review в
  `ode/` есть только `bootstrap/application` и `system` (health/diagnostics).
  Equipment DDL (`V003__equipment_identity.sql`) утверждён и применяется
  Stage 0.13.1 migration runner, но application/domain слой Equipment
  context в `ode/` отсутствует. Это реальный блокер для любой части
  monitoring, которая должна резолвить hostname/S/N в Equipment.

Рекомендация: возможно и стоит начинать **изолированное** hostname-routing
ядро (чистые value objects + rule matcher, без Equipment-зависимости и без
persistence) параллельно с текущей работой — оно не зависит ни от чего в
`ode/`. Всё, что требует `EquipmentLookup`, должно ждать реализации Equipment
bounded context. См. §14 и §15.

---

## 2. Existing module map

### 2.1 Что реально существует (verified)

| Файл | Строк | SHA-256 | Содержание |
|---|---:|---|---|
| `inventory/monitoring/facade.py` | 19 | `2a896c4f34b2e25b1191217769eda853fc43cae4e84acf0e755430bc4a355d85` | `MonitoringFacade.module_status()` → `{"enabled": false, "status": "В разработке"}` |
| `inventory/monitoring/models.py` | 1 | `f621eea37621f101baf8c3dba9bbe0d44970ee19d2911907f42f3c68b4bd5177` | Только docstring: "intentionally empty in Stage 0.12.6" |
| `inventory/monitoring/__init__.py` | — | `26e56168f288ca5bc360dc2aba433fb21cbcf554f183f636fa4496b7435ec995` | Пустой пакет-маркер |
| `inventory/monitoring/README.md` | 11 | `6743b9ea5e3d6243cde38881cd551cd60c5119313f835d433ca79c15336f25c4` | Заявляет "isolated future product module" |
| `inventory/services/monitoring_service.py` | 12 | `fe30716bf64468145a284ba337bac3bc016f88caf4a7980793e43ce74f9f67fb` | `MonitoringService(ServiceAdapter)` — 2 метода-заглушки (`data_quality_problems`, `check_integrity`), делегирующие в string-dispatch backend, который тоже не реализован |
| `static/js/monitoring/index.js` | 8 | `b86d85ab348688f9e97335cb0a9a065c1d33f064def946addb300ed8234e9048` | `window.ODE.monitoring = {enabled:false, status:'В разработке', dependencies:[]}` |
| `docs/MONITORING_MODULE_BOUNDARIES.md` | 40 | `22ffb6b525e0048f8323bdef82734d208c4cea25429e23c62ea6a4b05ecd2e8f` | Формальный boundary-документ для Stage 0.12.6 заглушки |
| `inventory/core/application.py` | — | — | Импортирует `MonitoringFacade`, конструирует `monitoring=MonitoringFacade()` в legacy `ApplicationContext` |
| `inventory/core/context.py` | — | — | `FEATURE_MONITORING: bool = False` |
| `inventory/webapp.py` | — | — | HTML placeholder: nav-кнопка `data-section="monitoring"`, секция `<h2>Мониторинг __DATACENTER__</h2><div class="placeholder">В разработке</div>` |
| `static/js/product.js` | — | — | `openMonitoringHub()` вызывает `showDevelopmentPlaceholder(...)`, никакой бизнес-логики |
| `static/css/main.css` | — | — | 3 CSS-правила `.monitoring-placeholder`/`.monitoring-icon`, чисто визуальные |

### 2.2 Что описано в постановке задачи, но не существует (verified absent)

Проверено: полный working tree, `git log --all` (все ветки), `git stash
list`, полнотекстовый поиск по имени файла и по содержимому.

| Заявленный файл | Статус |
|---|---|
| `inventory/monitoring/hostname_routing.py` | **Отсутствует** — нет ни в рабочем дереве, ни в истории |
| `inventory/monitoring/manual_search.py` | **Отсутствует** |
| `scripts/generate_hostname_rules.py` | **Отсутствует** |
| `data/monitoring/Hostname Digital.json` | **Отсутствует**, каталог `data/monitoring/` не существует |
| `data/monitoring/Hostname Tech.json` | **Отсутствует** |
| `tests/test_monitoring_hostname_routing.py` | **Отсутствует** |
| `docs/MONITORING_HOSTNAME_ROUTING.md` | **Отсутствует** |

`git log --all --oneline -- '**/monitoring*' '**/hostname*'` возвращает ровно
один коммит (`16db9b6`, "release: prepare ODE 0.12.16 RC1" — release
snapshot, не разработка функциональности). Ни один коммит в истории проекта
не создавал и не удалял hostname-routing или manual-search код.

### 2.3 Существующая документация про ODE 0.13 monitoring (verified present)

- `docs/architecture/OPEN_DECISIONS.md` — **OPEN-009**, ещё не решено.
- `docs/architecture/ODE_0_13_ARCHITECTURE_REVIEW.md` строка 623 —
  `inventory/monitoring/models.py` в списке "Файлы для удаления как
  архитектурные заглушки" (раздел 16).
- `docs/architecture/ui-contract.md` — "Monitoring и reports имеют отдельные
  navigation modules и не добавляют warehouse writes."
- `docs/development/cleanup-plan.md` — `inventory/monitoring/models.py`
  помечен "После decision in integrated stage".
- `docs/architecture/module-boundaries.md` — **monitoring отсутствует** в
  таблице 12 утверждённых контекстов ODE 0.13 (bootstrap/application,
  equipment, inventory, warehouse, balance, legacy history, imports,
  references/catalog, users, security, audit, reports, API, UI,
  infrastructure).

Вывод: существующая ODE 0.13 архитектурная документация уже последовательно
трактует monitoring как «будущий, ещё не спроектированный контекст» — этот
review первый раз формально его проектирует.

---

## 3. Hidden dependencies

Полнотекстовый поиск по репозиторию (`MonitoringFacade`, `MonitoringService`,
`FEATURE_MONITORING`, `data-section="monitoring"`, `monitoring_`,
`openMonitoringHub`, `/api/monitoring`) даёт следующий граф:

```
inventory/webapp.py (nav button, placeholder <section>, showSection())
        │
        ▼
static/js/product.js: openMonitoringHub() → showDevelopmentPlaceholder()
        │  (no HTTP call — no /api/monitoring endpoint exists anywhere)
        ▼
static/js/monitoring/index.js: window.ODE.monitoring = {enabled:false}
        (dead-end constant, ничем не читается дальше)

inventory/core/context.py: FEATURE_MONITORING=False
        │
        ▼
inventory/core/application.py: import MonitoringFacade; monitoring=MonitoringFacade()
        │
        ▼
inventory/monitoring/facade.py: module_status() (единственный вызываемый метод)

inventory/services/monitoring_service.py: MonitoringService(ServiceAdapter)
        │  (наследует string-dispatch адаптер;
        │   ни `data_quality_problems`, ни `check_integrity`
        │   не реализованы ни на одном backend)
        ▼
        NOT WIRED — не найдено ни одного вызывающего кода
        (grep по MonitoringService() не даёт конструкторов вне самого класса)
```

**Нарушений module-boundary нет** — `inventory/monitoring/facade.py`
действительно не импортирует Warehouse/Reports/`WarehouseService`/
`WarehouseCore`, как требует `docs/MONITORING_MODULE_BOUNDARIES.md`. Граница
формально соблюдена, но потому что по сути ничего не сделано, а не потому что
существует продуманная изоляция реальной бизнес-логики.

Скрытых зависимостей на `data/warehouse.db`, `inventory/warehouse/*` или
`WarehouseFacade` не найдено — ни прямых, ни через `getattr`/dynamic dispatch.

`inventory/services/monitoring_service.py` формально не мёртв (он
инстанцируется где-то в `inventory/service.py` string-dispatch registry по
шаблону остальных `*_service.py`), но не имеет ни одного реального вызывающего
пути из UI/API — это тот же паттерн, что и остальной `inventory/services/`,
который весь целиком помечен на удаление в
`docs/architecture/ODE_0_13_ARCHITECTURE_REVIEW.md`.

---

## 4. File classification

| Файл | Категория | Причина | Использует | Source of truth | Целевой путь в `ode/` |
|---|---|---|---|---|---|
| `inventory/monitoring/facade.py` | ARCHIVE → DELETE_AFTER_CUTOVER | 19-строчная disabled заглушка, единственный метод возвращает статичный статус | `inventory/core/application.py` | Нет бизнес-логики | Нет прямого аналога; `module_status()`-эквивалент переносится в новый `ode` health/diagnostics контракт (см. §11), не в отдельный monitoring endpoint |
| `inventory/monitoring/models.py` | ARCHIVE → DELETE_AFTER_CUTOVER | Пустой docstring; уже в списке удаления `ODE_0_13_ARCHITECTURE_REVIEW.md` §16 | — | — | — |
| `inventory/monitoring/__init__.py` | ARCHIVE → DELETE_AFTER_CUTOVER | Пустой пакет-маркер | — | — | — |
| `inventory/monitoring/README.md` | ARCHIVE | Документирует несуществующую функциональность как "future"; заменяется этим review + будущим `ode/monitoring/README.md` | — | — | — |
| `docs/MONITORING_MODULE_BOUNDARIES.md` | ARCHIVE | Формальный boundary-документ для 0.12.6 заглушки; monitoring ещё не в `module-boundaries.md` ODE 0.13 | — | Заменяется строкой в `module-boundaries.md`, когда контекст будет утверждён | — |
| `inventory/services/monitoring_service.py` | ARCHIVE → DELETE_AFTER_CUTOVER | Часть `inventory/services/` string-dispatch слоя, целиком помечен на удаление | Не найдено активных вызывающих | — | — |
| `static/js/monitoring/index.js` | ARCHIVE → DELETE_AFTER_CUTOVER | 8 строк, единственная константа `enabled:false`, ничем не читается | `inventory/webapp.py` через `_externalized_html()` script tag | — | Новый independent frontend entrypoint под будущим API (не наследует этот файл структурно, слишком тривиален для "адаптации") |
| `inventory/webapp.py` (monitoring `<section>`/nav button) | ARCHIVE → DELETE_AFTER_CUTOVER | Чистый HTML placeholder, ноль динамики | — | — | Не переносится: `ode`/новый UI не должен зависеть от `inventory/webapp.py` (жёсткое правило постановки, совпадает с общим cutover-планом ODE 0.13) |
| `static/js/product.js` (`openMonitoringHub`, `sections.monitoring`) | ARCHIVE (частично, только monitoring-специфичные строки) | Просто открывает placeholder, не бизнес-логика | `inventory/webapp.py` | — | — |
| `static/css/main.css` (`.monitoring-placeholder`, `.monitoring-icon`) | ARCHIVE | 3 тривиальных правила, no reuse value | — | — | Новый UI получит свой design-system-consistent набор стилей |
| `inventory/core/application.py` / `context.py` (monitoring wiring) | UNCERTAIN | Это legacy `inventory/` composition root, не входит в объём этой задачи и не входит в `ode/`; момент удаления wiring зависит от общего legacy cutover графика, не от monitoring-проекта | `inventory/webapp.py` | — | Аналог в `ode/application/context.py` появится, когда сам `ode/monitoring` package будет реализован — паттерн уже виден в `ode/application/context.py` (`build_application_context`) |
| — | REWRITE | **Пустая категория.** REWRITE предполагает наличие ошибочной реализации, которую нужно заменить. Реального hostname-routing/manual-search кода нет нигде — нечего "переписывать", есть только "написать впервые" (см. §1, §6) | — | — | — |

Итог: **KEEP = 0, ADAPT = 0, REWRITE = 0.** Всё содержательное относится к
ARCHIVE/DELETE_AFTER_CUTOVER (легаси-заглушка) либо UNCERTAIN (одна точка
wiring вне scope задачи). Ни один файл не переносится автоматически — это
согласуется с прямым запретом постановки.

---

## 5. Proposed domain model

Ниже — минимальная модель, спроектированная с нуля под правила из постановки
и под уже утверждённый ODE 0.13 паттерн identity (`ADR-006`,
`V003__equipment_identity.sql`: append-only identity rows, explicit supersede,
never mutate raw/key fields). Сущности без конкретного use case в первом срезе
(§10, §11) не создаются как отдельные таблицы сейчас — они помечены "future" и
не разрабатываются раньше §14 шага 9.

| Сущность | Identity | Lifecycle | Ownership | Immutable / append-only | Mutable config | Внешние ключи | Связь с Equipment | Связь с hostname | Удаление/архивация |
|---|---|---|---|---|---|---|---|---|---|
| `MonitoringSource` | `source_id` (surrogate) + `code` (unique, human-readable, напр. site/team scope) | `ACTIVE` / `RETIRED` | monitoring | Создание append-only; переименование запрещено (только retire+new) | `display_name`, `contact` | — | Нет прямой | Нет прямой | RETIRE, не DELETE |
| `MonitoringRuleSet` | `rule_set_id` + `source_id` + `version` (monotonic per source) | `DRAFT` → `ACTIVE` → `SUPERSEDED` | monitoring | Версия immutable после активации (тот же supersede-паттерн, что `equipment_identities`) | Draft-версия mutable до publish | `source_id` | Нет | Нет | Старые версии сохраняются для audit/rollback, не удаляются |
| `MonitoringRule` | `rule_id` + `rule_set_id` + `priority` | Живёт внутри одной ruleset-версии, immutable после публикации версии | monitoring | Append-only per version | — | `rule_set_id` | Нет прямой (routing только определяет target site/team, не equipment) | Да — `pattern`, `match_kind` | Наследует lifecycle ruleset-версии |
| `MonitoringObject` *(future — не в первом срезе)* | `object_id` + `(source_id, external_object_key)` unique | `ACTIVE` / `ARCHIVED` | monitoring | Identity-поля immutable, статус mutable | `display_hostname` (текущий, может меняться) | `source_id` | Опционально, через `MonitoringEquipmentLink` | Да, текущий hostname — атрибут, не identity | ARCHIVE, не DELETE (нужна для истории alert/observation) |
| `MonitoringEquipmentLink` *(future)* | `link_id` + `object_id` + `valid_from` | Append-only, retire-only (как `equipment_identities`) | monitoring (не equipment — monitoring не пишет в equipment identity) | Полностью immutable, кроме статуса ACTIVE→RETIRED | — | `object_id` (monitoring), `equipment_public_id` (equipment, через query, не FK на чужую таблицу — см. §7) | Прямая, ровно эта таблица её и есть | Косвенная через `MonitoringObject` | RETIRE при повторном resolve/merge на стороне equipment |
| `MonitoringObservation` *(future — после Stage vertical slice 2)* | `observation_id` + `object_id` + `observed_at` | Строго append-only, никогда не обновляется/не удаляется вручную | monitoring | 100% append-only | — | `object_id` | Нет | Нет | Retention policy обязательна (см. §12) — bounded, не "храним вечно" |
| `MonitoringAlert` *(future)* | `alert_id` | `OPEN → ACK → RESOLVED` (mutable state machine) | monitoring | Создание из observation append-only, переходы состояния — controlled mutation с audit | Статус, assignee | `object_id`, порождающие `observation_id` | Нет прямой (через object) | Нет | RESOLVED хранится, не удаляется (compliance/audit trail) |
| `MonitoringIncident` *(future)* | `incident_id` | Агрегирует несколько `MonitoringAlert` | monitoring | Mutable агрегация, append-only timeline событий внутри | Статус, priority | `alert_id[]` | Нет прямой | Нет | Хранится, не удаляется |

Сущности, которые **не создаются**, потому что нет реального use case на
сейчас:

- `MonitoringCheck` — конфигурация "что именно проверять" (ping/port/porog)
  нужна только когда появится реальный источник наблюдений; без него это
  сущность без данных. Отложено до момента, когда появится первый реальный
  observation-источник.
- `ManualSearchRequest`/`ManualSearchResult` — это **не доменные сущности**,
  а форма stateless read-запроса (query DTO). Материализовать их в таблицу
  означало бы персистить то, что не имеет lifecycle и не нужно хранить.
  Manual search реализуется как query port, не как entity (см. §11).

---

## 6. Hostname routing review

**Нечего ревьюить.** Ни алгоритма, ни JSON rule-файлов, ни теста не
существует (см. §2.2). Пункты постановки («формат правил», «приоритет»,
«пересечения», «Unicode», «ReDoS» и т.д.) переформулированы ниже как
**обязательные требования к будущей первой реализации**, а не как находки
аудита существующего кода.

### 6.1 Обязательные требования к формату правил

- **Pattern language: не произвольный regex.** ReDoS-риск на произвольном
  regex над hostname, приходящим из внешних источников/manual search, не
  оправдан бизнес-необходимостью. Использовать anchored literal / prefix /
  suffix / bounded glob (`*` только как единственный wildcard, без
  вложенных квантификаторов) — так же, как проект уже избегает
  "guessed"-эвристик в S/N-preservation (`docs/SERIAL_NUMBER_PRESERVATION.md`)
  вместо magic-парсинга.
- **Case sensitivity / Unicode:** нормализация NFKC + casefold + trim только
  внешних пробелов/invisible format controls — тот же контракт, что уже
  утверждён для S/N match key (`ADR-006`, `SerialKey`). Не изобретать вторую
  нормализационную схему в том же проекте.
- **Пустой hostname:** запрещён как валидный вход правила и как валидный
  `MonitoringObject.display_hostname`; должен быть отклонён на границе
  (application validation), не долетать до matcher.
- **Приоритет и детерминизм:** явное целочисленное `priority` в правиле +
  tie-break по `rule_id` (стабильный, не по времени создания, не по порядку
  в файле) — совпадения не должны зависеть от порядка вставки.
- **Duplicate/overlap detection:** обязателен на этапе Preview/publish
  ruleset-версии (см. ниже), не на этапе matching в runtime — совпадающий
  `(pattern, priority)` в одной версии — ERROR, не warning.
- **Stale rules:** ruleset — versioned append-only объект (см. §5), поэтому
  "устаревшее правило" не редактируется на месте — публикуется новая версия.
  Отдельного "stale" флага не нужно: неактивная версия уже неприменима.

### 6.2 JSON vs DB source of truth

Рекомендация: **DB — canonical source, JSON (или CSV) — только export/import
формат для review**, по прямой аналогии с уже утверждённым в проекте
паттерном Preview→Confirm (`docs/architecture/import-preview-publish.md`,
и `CLAUDE.md`/S/N-first: "обязательны Preview и Confirm, direct import
запрещён"). Причины:

- Versioning/rollback/audit ("нужно ли делать откат ошибочного ruleset")
  требуют устойчивого append-only хранилища с транзакциями — то, что уже
  делает `SqliteUnitOfWork` в `ode/infrastructure/database.py`, а плоский
  JSON-файл в git не даёт (нет транзакционной публикации, нет per-row actor/
  audit, откат = git revert, который в проекте явно запрещён как способ
  правки production-данных).
- **Compiled ruleset:** нужен — matcher должен строиться один раз на
  activated `rule_set_id` и кэшироваться по `(rule_set_id, version)`, не
  пересобираться на каждый lookup. Инвалидация кэша — по смене
  `active rule_set_id`, не по времени (deterministic, не polling).
- **Preview:** ruleset publish повторяет уже одобренный в проекте паттерн:
  DRAFT версия строится, diff против текущей ACTIVE версии показывается
  (какие hostname сменят маршрут), Confirm атомарно активирует новую версию
  и ретайрит старую — Preview не пишет в DB (тот же инвариант, что у
  Inventory Number import: "Preview не меняет БД/audit").
- **Rollback:** активировать предыдущую immutable версию — не "исправление
  на месте", а новая публикация, указывающая на старый набор правил. Это
  тот же принцип, что `equipment_identities`: коррекция создаёт новую
  строку, не переписывает старую.

### 6.3 Производительность matcher

Не заявляется числовой p95 без бенчмарка (см. §12) — только структурное
требование: exact-hostname lookup должен быть O(1)/O(log n) через индекс
нормализованного ключа (аналог `ux_equipment_serial_active` в V003), а
pattern-правила — небольшой bounded список (ожидаемый порядок — десятки,
не тысячи правил на источник), поэтому линейный проход по отсортированному
по приоритету списку compiled правил допустим без отдельной trie/DFA
структуры на первом срезе.

---

## 7. Equipment integration contract

### 7.1 Что уже утверждено (не предмет этого review, а constraint)

`docs/architecture/module-boundaries.md` уже определяет единственный
разрешённый способ чтения Equipment для любого контекста:
**`EquipmentLookup` query port** — "exact identity, equipment detail,
canonical redirect". Dependency matrix явно разрешает только `Q`
(query port), никогда прямой repository/SQL доступ к чужим таблицам.
`ADR-006` определяет форму идентичности:

- `equipment_id` (internal PK, никогда не пересекает границу контекста),
  `public_id` (UUID, безопасен для внешнего использования monitoring'ом);
- `lifecycle_status`: `ACTIVE | QUARANTINED | RETIRED | MERGED`;
- identity — отдельные append-only строки `equipment_identities`
  (`SERIAL_NUMBER` или `INVENTORY_NUMBER`), с `scope_key` (vendor-scoped или
  `UNSCOPED`) и `status`: `ACTIVE | RETIRED | CONFLICT | UNVERIFIED`;
- merge — отдельная `equipment_merges` таблица с `source→survivor` redirect,
  без переписывания истории.

### 7.2 Контракт Monitoring → Equipment

```
Monitoring (manual search / equipment link resolver)
        │  query only, через EquipmentLookup port
        ▼
Equipment bounded context (не реализован в ode/ на момент review)
```

Monitoring **может** искать Equipment по S/N, Inventory Number, vendor/model
(через `EquipmentLookup.resolve_by_identity` / аналогичный exact-lookup, а не
free-text SQL) — hostname и «внешний monitoring identifier» **не входят** в
Equipment identity model (`ADR-006` разрешает только `SERIAL_NUMBER` и
`INVENTORY_NUMBER`), поэтому hostname-based lookup — это monitoring-side
эвристика поверх результата S/N-lookup, не альтернативный identity path
внутри Equipment.

Monitoring **не может**:

- писать в `equipment` / `equipment_identities` / `equipment_merges` —
  никаких correction/merge command вызовов;
- трактовать `MonitoringEquipmentLink` как источник правды для S/N или
  Inventory Number — это однонаправленная ссылка "что мы думаем, к какому
  Equipment относится этот monitoring object", а не альтернативная identity;
- порождать warehouse ledger операции ни при каких обстоятельствах —
  monitoring не входит в `warehouse`/`balance` dependency matrix вообще.

### 7.3 Поведенческая матрица

| Ситуация | Поведение Monitoring |
|---|---|
| Equipment найден однозначно (exact identity match) | Создать/обновить `MonitoringEquipmentLink` со `status=ACTIVE`, `equipment_public_id`, `method` (`EXACT_SERIAL` / `EXACT_INVENTORY_NUMBER` / `MANUAL`) |
| Не найден | `MonitoringObject` существует без link; UI показывает "не найдено на складе", не блокирует остальную функциональность monitoring |
| Найдено несколько кандидатов (`AMBIGUOUS` — возможно между vendor-scope, см. `ADR-006` Consequences) | Link не создаётся автоматически; возвращается список кандидатов для ручного выбора оператором monitoring (append `MonitoringEquipmentLink` только после явного выбора — audit фиксирует actor) |
| Equipment ещё не на балансе (identity существует, но `lifecycle_status` не `ACTIVE`, напр. в `QUARANTINED`) | Link создаётся с explicit warning-статусом в ответе query, не блокируется — monitoring не решает, что можно/нельзя линковать по warehouse-состоянию |
| Hostname изменился | Не equipment-событие. Обновляется `MonitoringObject.display_hostname` (mutable атрибут, не identity), существующий `MonitoringEquipmentLink` не трогается |
| Equipment merged (`equipment_merges`) | Query port должен возвращать canonical redirect (`survivor_equipment_id`/`public_id`) прозрачно; monitoring обновляет `MonitoringEquipmentLink.equipment_public_id` на survivor через штатный resolve, не пишет напрямую |
| Equipment archived (`RETIRED`) | Link сохраняется как historical fact (append-only), UI помечает как "оборудование списано", link не удаляется |
| Monitoring object существует без equipment | Валидное постоянное состояние, не ошибка — большая часть объектов может никогда не резолвиться (напр. сетевое оборудование, которого нет на складе ODE) |

---

## 8. Data ownership

| Data | Owner | Reader | Writer | Retention | Source of truth |
|---|---|---|---|---|---|
| Equipment identity (S/N, Inventory Number, lifecycle) | equipment context | monitoring (через `EquipmentLookup`, read-only) | equipment context only | Постоянно, append-only | `equipment_identities` (equipment context) |
| Hostname (текущее значение) | monitoring | monitoring, equipment (опционально, через query) | monitoring | Текущее значение mutable; история — через `MonitoringObject` append events, не отдельная versioned identity | `MonitoringObject.display_hostname` |
| Monitoring rules / rulesets | monitoring | monitoring UI, matcher runtime | monitoring (через Preview/Confirm) | Все версии хранятся постоянно (audit/rollback) | `monitoring_rule_sets` / `monitoring_rules` |
| Observations | monitoring | monitoring UI, alert engine | monitoring (append-only writer, вероятно отдельный ingest worker в будущем) | Bounded retention (см. §12), не "навсегда" | `monitoring_observations` |
| Alerts | monitoring | monitoring UI, incident aggregator | monitoring | Постоянно (compliance/history), возможна архивация RESOLVED после N лет | `monitoring_alerts` |
| Incidents | monitoring | monitoring UI | monitoring | Постоянно | `monitoring_incidents` |
| Equipment links | monitoring | monitoring UI, equipment (опционально, "где используется этот equipment" reverse-query) | monitoring | Постоянно, append-only (retire, не delete) | `monitoring_equipment_links` |
| Raw source payload (сырой ответ внешнего источника до нормализации) | monitoring | monitoring (debug/audit only) | monitoring ingest adapter | Короткий bounded retention — не хранить произвольный чужой payload бессрочно (см. §11 security) | Не отдельная domain-таблица; если нужен, то отдельный short-TTL raw-log, не смешивается с `monitoring_observations` |
| Audit events по monitoring-командам (rule publish, manual link, retire) | audit context (общий для всего ODE 0.13, см. `module-boundaries.md`) | audit context readers | monitoring вызывает `AuditQuery`/append-port audit context в своём UoW | Postоянно | `audit` context, не monitoring-локальная таблица |

---

## 9. Proposed package layout

```
ode/monitoring/
├── __init__.py
├── models.py       # value objects, enums, immutable dataclasses (как ode/system/models.py)
├── queries.py       # Protocol ports: HostnameRoutingQuery, EquipmentLinkQuery, ManualSearchQuery
├── service.py       # policy over ports (как ode/system/service.py над DiagnosticsQuery)
├── routing.py        # чистый rule matcher: (hostname, compiled ruleset) -> RouteResult
└── errors.py        # MonitoringError с machine-readable code, по образцу ode/application/errors.py
```

Repository/infrastructure слой **не создаётся заранее** — по образцу
`ode/system`, где `DiagnosticsQuery` — Protocol, а конкретная SQLite-реализация
подключается только в composition root (`ode/application/context.py`), не
внутри `ode/system/`. `routing.py` в первом срезе не требует SQLite вообще —
он принимает уже загруженный/скомпилированный ruleset и является чистой
функцией, что делает его тривиально unit-testable без БД (см. §13 миграцию,
шаг 3).

Dependency direction (только через approved ports, по образцу
`module-boundaries.md`):

```
UI → API → ode.application (composition) → ode.monitoring (queries.py Protocol)
                                                   │
                                                   ▼
                                       ode.equipment.EquipmentLookup (Q port, когда появится)
```

`ode/monitoring` не импортирует `ode.equipment` конкретную SQLite-реализацию
— только Protocol port, инжектируемый composition root'ом, аналогично тому,
как `ode/system/service.py` зависит только от `DiagnosticsQuery` (Protocol),
а не от `SQLiteConnectionFactory` напрямую.

Facade/service/repository слои сверх этого **не создаются**, пока нет
конкретного use case — `routing.py` как отдельный модуль оправдан, потому что
это единственная часть с нетривиальной чистой логикой (matcher), которую
осмысленно unit-тестировать в изоляции; для остального пока достаточно
`service.py`+`queries.py`, без отдельного `repository.py` (он появится вместе
с первой SQLite-реализацией `queries.py`-портов внутри `ode/infrastructure`
или в отдельном `ode/monitoring/sqlite_queries.py`, по решению на момент
реализации, не сейчас).

---

## 10. Proposed DB table inventory

Только табличный inventory, без DDL (по прямому запрету постановки).

| Таблица | Назначение | Ключи | Ограничения | Индексы | Объём (оценка) | Retention | Append-only / mutable | Нужна в первом срезе? |
|---|---|---|---|---|---|---|---|---|
| `monitoring_sources` | Реестр источников/scope (напр. site/team, аналог "Digital"/"Tech" из постановки — не подтверждено, что это реальные источники, трактовать как пример) | `source_id` PK, `code` UNIQUE | `code` immutable после создания | по `code` | Единицы-десятки строк | Постоянно | Мутируется только статус | **Да** |
| `monitoring_rule_sets` | Версии ruleset per source | `rule_set_id` PK, `(source_id, version)` UNIQUE | Одна `ACTIVE` версия на `source_id` одновременно (partial unique index по образцу `ux_equipment_serial_active`) | по `(source_id, status)` | Десятки-сотни версий за время жизни проекта | Постоянно (rollback/audit) | Append-only после активации | **Да** |
| `monitoring_rules` | Отдельные правила внутри версии | `rule_id` PK, `(rule_set_id, priority)` | `pattern` non-empty, `match_kind` enum | по `(rule_set_id, priority)` | Сотни на ruleset | Наследует ruleset | Append-only | **Да** |
| `monitoring_objects` | Наблюдаемые объекты от источника | `object_id` PK, `(source_id, external_object_key)` UNIQUE | — | по `(source_id, external_object_key)`, по `display_hostname` (не unique — hostname может повторяться/меняться) | Потенциально тысячи-десятки тысяч (масштаб ЦОД) | Постоянно, `ARCHIVED` вместо DELETE | Identity append-only, статус/hostname mutable | Нет — Slice 2 (после появления реального источника объектов) |
| `monitoring_equipment_links` | Связь object↔equipment | `link_id` PK, `object_id` FK | Только retire-transition (по образцу `trg_equipment_alias_only_retire`) | по `object_id`, по `equipment_public_id` | Подмножество `monitoring_objects` | Постоянно | Append-only, retire-only | Нет — Slice 2 |
| `monitoring_observations` | Сырые измерения/check-результаты | `observation_id` PK, `(object_id, observed_at)` | — | по `(object_id, observed_at)` для time-range запросов | **Высокий** — потенциально миллионы строк/год при регулярных проверках | **Bounded**, обязательна политика удаления/downsampling (см. §12) — единственная таблица в этом наборе, где "хранить всё" неприемлемо | Строго append-only | Нет — Slice 3 |
| `monitoring_alerts` | Производное состояние из observations | `alert_id` PK | State machine `OPEN→ACK→RESOLVED` | по `(status, object_id)` | На порядки меньше observations | Постоянно | Mutable state с audit переходов | Нет — Slice 3 |
| `monitoring_incidents` | Агрегация alerts | `incident_id` PK | — | по `status` | Малый объём | Постоянно | Mutable агрегация | Нет — Slice 3 |

Только `monitoring_sources` + `monitoring_rule_sets` + `monitoring_rules`
нужны для первого среза (§11). Остальные пять — сознательно отложены, что
соответствует и migration-плану постановки (шаг 9 "только затем
observations/alerts"), и уже одобренному OPEN-009 ("health/diagnostics only;
full monitoring later").

---

## 11. API/UI first slice

Первый срез = **read-only**: hostname route preview, manual search,
equipment link result (query, не command — создание link не входит в первый
срез, пока нет `monitoring_equipment_links`), health/status ruleset.
Соответствует postановке ("Не проектировать большой dashboard, пока нет
данных") и OPEN-009.

По образцу `docs/architecture/api-contract.md` (JSON envelope с
`data`/`meta`, cursor-based pagination, `Idempotency-Key`, permission-коды):

| Resource | Permission | Request → Response | Errors | Audit |
|---|---|---|---|---|
| `GET /api/v1/monitoring/rulesets/{source}/active` | `MONITORING_READ` | `source_code` → `RuleSetSummary` (version, activated_at, rule_count) | `NOT_FOUND` | — |
| `POST /api/v1/monitoring/rulesets/{source}:preview` | `MONITORING_WRITE` | draft rules payload → `RuleSetPreviewDiff` (added/changed/removed routes) | `422` validation (empty pattern, duplicate priority, invalid Unicode) | Preview не пишет audit (не мутация, аналог Inventory Number Preview) |
| `POST /api/v1/monitoring/rulesets/{source}:publish` | `MONITORING_WRITE` + `Idempotency-Key` | подтверждённый draft → активированная версия | `409` conflict (кто-то опубликовал раньше), `412` stale base version | `MonitoringRuleSetPublished` audit event |
| `GET /api/v1/monitoring/hostname:route?hostname=` | `MONITORING_READ` | hostname → `RouteResult` (matched rule, target site/team) или `NO_MATCH` | `INVALID_HOSTNAME` (пустой/control chars) | — |
| `GET /api/v1/monitoring/search?query=` | `MONITORING_READ` | free-text (S/N, Inventory Number, hostname) → `Page<SearchCandidate>` | `QUERY_TOO_BROAD` (по образцу `legacy-history:lookup`) | Возможен audit чтения при работе с чувствительными данными — решение product owner, не blocking |
| `GET /api/v1/monitoring/equipment-link:preview?object=` | `MONITORING_READ` | `object_id`/hostname/S/N → `EquipmentLinkCandidate[]` (может быть 0, 1 или несколько — см. §7.3) | `AMBIGUOUS` возвращается как валидный multi-candidate ответ, не ошибка | — |
| `GET /api/v1/monitoring/health` | `MONITORING_READ` | — → module status (по аналогии с `ode/system` `SystemHealth`) | — | — |

### Состояния UI

- **Empty**: источник существует, ruleset ещё не опубликован — явное
  "правила не настроены", не пустая таблица без объяснения.
- **Loading**: стандартный skeleton, ничего monitoring-специфичного.
- **Degraded**: `EquipmentLookup` port недоступен (equipment context ещё не
  реализован/не в этом deployment) — hostname-preview и ruleset publish
  должны продолжать работать **без** equipment-функциональности; UI обязан
  явно показывать "equipment linking недоступен", а не падать целиком —
  monitoring не должен иметь hard runtime dependency на equipment для своей
  собственной (routing) части.
- **Error**: стандартный envelope из `api-contract.md`.

### Что нельзя переносить 1:1 из legacy UI

`inventory/webapp.py`/`product.js` monitoring-код — чистый placeholder,
переносить нечего (см. §4). Отдельно стоит явно зафиксировать: паттерн
"`sections.monitoring=[['monitoring','Мониторинг']]`" + строковый dispatch
`showSection`/`showView` из старого `inventory/webapp.py` **не должен**
использоваться как образец для нового UI — он относится к монолитному
`_externalized_html()`-подходу, который сам проект уже признаёт техдолгом
(`CLAUDE.md`, раздел про `inventory/webapp.py`).

---

## 12. Security findings

Поскольку кода нет, находки — это **требования**, не CVE-подобные находки в
существующем коде.

- **JSON injection / rule-file parsing:** при переходе на DB-canonical
  ruleset (см. §6.2) риск JSON injection из файла снимается почти полностью;
  если экспорт/импорт JSON всё же остаётся как обмен-формат — парсер обязан
  strict-schema validate (типы полей, отсутствие лишних ключей), не
  `eval`/динамический импорт.
- **ReDoS:** закрыт архитектурным решением §6.1 — не использовать
  произвольный regex-движок на pattern, приходящем из ruleset. Если в
  будущем понадобится regex, обязателен bounded/linear-time движок
  (напр. RE2-подобный) и лимит длины pattern/hostname на входе.
- **Path traversal:** неактуально при DB-canonical подходе; если JSON-файлы
  всё же читаются с диска — путь должен быть фиксированным списком, не
  собираться из `source_code`/пользовательского ввода.
- **Unsafe dynamic imports / getattr dispatch:** ODE 0.13 CI уже проверяет
  это на уровне всего репозитория (`module-boundaries.md`, "Enforcement");
  `ode/monitoring` должен пройти тот же CI gate, без исключений.
- **HTML interpolation:** `RouteResult`/`SearchCandidate` рендерятся через
  безопасный UI framework/escaping, не через `.replace()`-конкатенацию
  (текущий `inventory/webapp.py` паттерн — уже признанный техдолг, не
  наследуется).
- **Raw payload leakage:** raw source payload (см. §8) не должен попадать в
  `monitoring_observations` как есть, если содержит потенциально
  чувствительные поля (напр. учётные данные из некоторых monitoring-
  интеграций) — обязательна allowlist полей на границе ingest, не "сохраняем
  всё, разберёмся потом".
- **Hostname / control character handling:** входной hostname проверяется на
  control characters и на длину до нормализации (§6.1), до того как попадёт
  в matcher или в SQL-параметр (параметризованные запросы — обязательны,
  как и везде в проекте; `ode/infrastructure/database.py` уже даёт
  `PRAGMA trusted_schema = OFF` + parameterized `execute`, паттерн
  сохраняется).
- **Access control:** `MONITORING_READ`/`MONITORING_WRITE` как отдельные
  permission-коды (не переиспользовать `WAREHOUSE_*`/`EQUIPMENT_*`) — monitoring
  не должен получать warehouse-права "бесплатно" через shared permission.
- **Confidentiality:** monitoring данные (какие hosts опрашиваются, incident
  detail) сами по себе не должны становиться доступны через
  `EQUIPMENT_READ` — direction связи одностороння (monitoring читает
  equipment, не наоборот), поэтому по умолчанию equipment context не
  получает monitoring detail без отдельного query port, если это вообще
  понадобится (сейчас — не понадобится, use case не заявлен).
- **Auditability:** ruleset publish, manual equipment-link (когда появится в
  Slice 2) — обязательные audit events (по образцу `AuditQuery`/`A` в
  dependency matrix), не "молчаливая" мутация.
- **DoS через manual search:** `QUERY_TOO_BROAD` error (уже есть прецедент —
  `legacy-history:lookup` в `api-contract.md`) + обязательный bounded
  `limit`/max 200 (тот же контракт, что у остальных list endpoints) — free-
  text search без границ на потенциально больших `monitoring_objects` может
  быть дешёвым DoS-вектором, если не ограничить заранее.

---

## 13. Performance considerations

Без бенчмарка числовой p95 не заявляется (по прямому требованию постановки).
Структурные требования:

- **Monitoring objects:** ожидаемый порядок — от сотен до низких десятков
  тысяч (масштаб инфраструктуры ЦОД, не веб-трафика) — не требует
  специальной sharding-стратегии на первых стадиях.
- **Routing rules:** десятки-сотни на источник (см. §10) — линейный проход
  по compiled отсортированному списку допустим, отдельная trie/автомат не
  оправдана на этом объёме.
- **Observations per day:** потенциально высокий объём при регулярном
  polling — это единственная таблица в модели, где "не проектировать
  большой dashboard, пока нет данных" (постановка) напрямую означает "не
  проектировать retention/partitioning без реального источника нагрузки" —
  Slice 3, не сейчас.
- **Exact hostname lookup:** обязателен индекс на нормализованный hostname-
  ключ (аналог `ux_equipment_serial_active`), не full scan.
- **Equipment linking:** каждый lookup — это один exact-identity query через
  `EquipmentLookup` port; при batch-операциях (напр. bulk manual search)
  обязателен bounded batch size, не N+1 отдельных round-trip на UI-инициируемый
  список результатов.
- **Bounded-result contracts:** каждый list endpoint первого среза уже
  спроектирован с cursor pagination и max 200 (см. §11) — обязательное
  условие, не "добавим потом".

---

## 14. Migration plan

Безопасный порядок реализации (адаптирован под verified findings §1-§4 —
шаг "freeze current monitoring module" тривиален, так как замораживать
нечего, кроме уже существующей disabled заглушки):

1. **Зафиксировать текущее состояние** — этот review и есть fixation;
   заглушка (`inventory/monitoring/*`, `inventory/services/monitoring_service.py`)
   остаётся as-is до момента реального cutover, не трогается сейчас.
2. Явно закрыть/подтвердить **OPEN-009** с product owner — без этого нет
   утверждённого release scope для дальнейших шагов.
3. **Изолированное routing-ядро** (`ode/monitoring/routing.py` + `models.py`)
   — чистые функции без Equipment-зависимости, без SQLite-зависимости,
   можно писать и unit-тестировать уже сейчас, параллельно остальной работе
   над Stage 0.13.1 correction (не пересекается с тем, что чинит Codex).
4. Добавить independent unit-тесты на matcher (нормализация, приоритет,
   duplicate-detection, Unicode/control-char edge cases из §6.1) — до
   какой-либо DB-интеграции.
5. Формально утвердить `monitoring` как ODE 0.13 bounded context —
   добавить строку в `docs/architecture/module-boundaries.md` (не эта
   задача — отдельное ADR-подобное решение, т.к. это "APPROVED baseline"
   документ) и, вероятно, отдельный ADR (следующий номер после ADR-012).
6. Реализовать `ode/monitoring` queries.py Protocol ports +
   `monitoring_sources`/`monitoring_rule_sets`/`monitoring_rules` DDL (после
   отдельного DDL review — не в рамках read-only задачи).
7. Adapter к `EquipmentLookup` — **блокирован** до реализации equipment
   bounded context в `ode/` (см. §1, §15). Может быть написан как Protocol +
   fake/test-double заранее, но реальная интеграция ждёт.
8. Read-only route-preview/manual-search vertical slice (§11) — первый
   реально ship-able срез.
9. Targeted review (архитектурный + security) конкретно этого среза, по
   аналогии с тем, как сейчас идёт independent review Stage 0.13.1.
10. Только затем — `monitoring_objects`/`monitoring_equipment_links`
    (Slice 2), и только после этого — `monitoring_observations`/`alerts`/
    `incidents` (Slice 3).
11. Legacy UI removal (`inventory/monitoring/*`, `static/js/monitoring/`,
    placeholder HTML в `inventory/webapp.py`) — после cutover, синхронно с
    остальным legacy `inventory/` cleanup-графиком
    (`docs/development/cleanup-plan.md`), не раньше и не изолированно.

**Никакого dual-write** — легаси-заглушка ничего не пишет, поэтому вопрос
dual-write в принципе не возникает для этого модуля (в отличие от, например,
warehouse legacy↔ODE 0.13 миграции).

---

## 15. Roadmap placement

Варианты из постановки:

- **A. Сразу после Stage 0.13.1** — возможно только для **изолированного
  routing-ядра** (шаги 3-4 в §14), которое не зависит ни от Equipment, ни от
  warehouse. Не подходит для equipment-linking части.
- **B. После equipment identity/history** — верно для **всего, что требует
  `EquipmentLookup`** (manual search resolve, equipment-link preview, Slice 2
  целиком). Это реальный, а не гипотетический блокер: `ode/equipment` ещё не
  реализован (только DDL утверждён).
- **C. После baseline/warehouse core** — **не обязательно**: monitoring не
  входит ни в один warehouse/balance dependency matrix cell (§module-
  boundaries.md), баланс ему не нужен ни для routing, ни для equipment-
  linking (identity ≠ balance).
- **D. После полного складского UI** — избыточно консервативно; создаёт
  ложную зависимость там, где её architecturally нет.

**Рекомендация: гибрид A+B**, а не единственный вариант:

1. Routing-ядро (Slice 0, чистый код) — **сейчас/параллельно** Stage 0.13.1
   correction, поскольку ноль пересечения с тем, что правит Codex, и ноль
   зависимости от Equipment/Warehouse.
2. Formal module-boundary approval + DDL для `monitoring_sources/
   rule_sets/rules` (Slice 1) — как только Stage 0.13.1 foundation
   стабилизирован и есть DB-слой, на который можно вешать новую схему;
   не обязательно ждать Equipment.
3. Equipment-linking (Slice 2) — **только после** equipment bounded context
   реализован в `ode/` (вариант B) — это единственный настоящий hard blocker.
4. Observations/alerts/incidents (Slice 3) — после Slice 2, в согласии с
   OPEN-009 ("full monitoring later") и с §14 шагом 10.

Это использует то, что colleague-модуль изначально задумывался готовым
(сроки поджимают), но не жертвует architectural gating — там, где
зависимости реальны (Equipment), они не обходятся, а там, где зависимости
искусственны (Warehouse/баланс, полный UI), работа не блокируется зря.

---

## 16. Risks and blockers

| Риск/блокер | Тип | Влияние |
|---|---|---|
| Постановка задачи описывала несуществующий код как готовый | Process | Устранено этим review; риск для будущих задач — обновить внешнее описание состояния проекта, откуда взялась постановка |
| `EquipmentLookup` port не реализован в `ode/` | Hard blocker | Блокирует §7/§11 equipment-linking часть (Slice 2); не блокирует Slice 0/1 |
| `monitoring` отсутствует в `module-boundaries.md` (ODE 0.13 approved baseline) | Process blocker | Формально нельзя писать production `ode/monitoring` код до утверждения строки в этом документе — не техническая, а governance-зависимость |
| OPEN-009 не закрыт | Process blocker | Нет утверждённого release scope; без этого Slice 2/3 не должны начинаться, даже если технически возможны |
| Retention/объём `monitoring_observations` неизвестен без реального источника | Design risk (не blocker для Slice 0/1) | Нельзя проектировать DDL/индексы для этой таблицы до Slice 3 без придумывания цифр — сознательно отложено |
| Legacy `inventory/monitoring/*` и `inventory/services/monitoring_service.py` формально существуют и подключены в `inventory/core/application.py` | Low risk | Не мешает новой работе в `ode/` (разные пакеты), но требует координации с общим legacy cutover, чтобы не удалить раньше времени/не задвоить |
| Нет ADR под monitoring bounded context | Process gap | Нужен отдельный ADR (следующий свободный номер после ADR-012) перед §14 шагом 5 |

---

## 17. Exact next implementation stage

**Slice 0 — изолированное hostname-routing ядро**, ограниченное строго:

- `ode/monitoring/models.py` (value objects: `HostnameKey`, `RoutingRule`,
  `RuleSet`, без persistence);
- `ode/monitoring/routing.py` (чистый matcher, §6.1 требования);
- unit-тесты на нормализацию/приоритет/duplicate-detection/edge cases;
- **без** DDL, **без** API endpoint, **без** `EquipmentLookup` зависимости,
  **без** правки `module-boundaries.md` (это отдельное governance-решение,
  не implementation).

Это единственный кусок, который можно начать реализовывать прямо сейчас без
дальнейших approval-шагов, потому что: не трогает БД, не трогает legacy
`inventory/`, не пересекается физически ни с одним файлом, который сейчас
правит Codex в Stage 0.13.1 correction, и не зависит от ещё не построенного
Equipment context.

Всё остальное (DDL, API, `EquipmentLookup` интеграция, UI) требует
предварительно: (a) закрытия OPEN-009, (b) formal module-boundary approval,
(c) для Slice 2 — существования Equipment bounded context в `ode/`.

---

## 18. Claude recommendation

Переиспользовать существующий "модуль мониторинга" **нельзя** — его нет.
Рекомендую:

1. Скорректировать источник постановки задачи (кто бы её ни писал) — описание
   "коллега завершил модуль" не соответствует репозиторию ни на одной ветке.
2. Начать со Slice 0 (§17) — самый низкий риск, самая высокая параллельность
   с текущей Stage 0.13.1 работой.
3. Не открывать Equipment-linking работу, пока `ode/equipment` не существует
   — это не перестраховка, это единственная реальная техническая
   зависимость, найденная в этом review.
4. Закрыть OPEN-009 явно, прежде чем писать что-либо за пределами Slice 0 —
   документ уже существует и ждёт product owner решения, дублировать его
   этим review не нужно.
5. DB-canonical ruleset с Preview/Confirm (§6.2), не JSON-as-source-of-truth
   — это прямое продолжение уже одобренного в проекте паттерна, не новая
   концепция.

**Финальные ответы по контрольному списку (§16 постановки):**

1. Переиспользовать текущий модуль — **нет**, он пустая заглушка.
2. KEEP — **ни один файл**.
3. ADAPT — **ни один файл**.
4. REWRITE — **ни один файл** (нечего переписывать, только писать заново).
5. ARCHIVE/DELETE_AFTER_CUTOVER — все 7 существующих monitoring-related
   файлов + monitoring-фрагменты `inventory/webapp.py`/`product.js`/`main.css`
   (§4).
6. Скрытые зависимости — **не найдены** (граница реально не нарушена, §3),
   но и защищать было почти нечего.
7. Hostname routing изолирован — **вопрос неприменим**, кода нет; будущая
   реализация обязана быть изолирована по требованиям §6.1/§9.
8. JSON authoritative source — **нет таких JSON**; для будущей реализации
   рекомендован DB-canonical подход (§6.2).
9. Ruleset versioning нужен — **да**, обязателен (§6.2, §10).
10. Связь с Equipment — через `EquipmentLookup` query port, односторонняя,
    read-only, без записи в equipment identity (§7).
11. Warehouse balance — **не нужен** monitoring'у ни для routing, ни для
    equipment-linking (§15).
12. Таблицы для первого среза — только `monitoring_sources`,
    `monitoring_rule_sets`, `monitoring_rules` (§10).
13. API для первого среза — route preview, ruleset preview/publish, manual
    search, equipment-link preview (read-only), health (§11).
14. Security risks — ReDoS (архитектурно закрыт выбором pattern language),
    unbounded manual search (закрыт cursor+limit), raw payload leakage
    (требует allowlist на ingest) — все закрыты design-требованиями, не
    найдены как existing vulnerabilities, потому что нет existing кода
    (§12).
15. Performance risks — объём `monitoring_observations`, единственная
    таблица, отложенная до Slice 3 именно по этой причине (§13).
16. Stage — гибрид: Slice 0 сейчас/параллельно Stage 0.13.1 correction;
    Equipment-linking (Slice 2) после реализации `ode/equipment` (§15, §17).
17. Блокирует интеграцию (полную) — отсутствие `ode/equipment`, незакрытый
    OPEN-009, отсутствие строки `monitoring` в `module-boundaries.md` (§16).
18. Параллельно со складом — Slice 0 (routing-ядро) можно вести полностью
    параллельно любой warehouse-работе, ноль пересечения файлов/таблиц (§17).
19. Изменённые файлы — **только этот документ**,
    `docs/architecture/MONITORING_0_13_INTEGRATION_REVIEW.md`. Код, DDL,
    JSON, тесты не менялись.
20. Отдельная реализация другим агентом после принятия плана — **да,
    возможна для Slice 0** без дополнительного контекста, при условии, что
    у него будет этот документ и `ADR-006`/`V003__equipment_identity.sql`
    для справки; Slice 2+ потребует, чтобы к тому моменту существовал
    `ode/equipment`, иначе реализующий агент упрётся в тот же блокер, что
    описан здесь.
