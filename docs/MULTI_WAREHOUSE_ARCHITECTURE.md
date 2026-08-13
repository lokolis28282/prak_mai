# Multi-Warehouse: IXcellerate и Solar — ODE 0.21.1

Дата решения: 2026-07-26. Статус: implemented in ODE 0.17.0.

## Пользовательский контракт

- Вход в `Склад` сначала показывает выбор `IXcellerate` или `Solar`.
- Выбор хранится в пользовательской HTTP-сессии; разные браузерные сессии
  могут одновременно работать с разными складами.
- `IXcellerate` использует существующую `data/warehouse.db`.
- `Solar` использует отдельную ignored БД `data/warehouse_solar.db`.
- При первом запуске Solar не содержит приходов, расходов, allocations,
  поставок, карточек, legacy-операций или баланса.
- При первом создании Solar получает одноразовый снимок справочников
  IXcellerate. После bootstrap справочники двух складов изменяются независимо.
- Переключение склада очищает только временное состояние открытого экрана.
  Browser drafts не удаляются: их ключ содержит fingerprint конкретной БД,
  поэтому черновик одного склада нельзя подтвердить в другом.

## Физическая граница

```text
HTTP session
  ├─ primary DB: Administration / Reports / Knowledge
  ├─ no business DB: Monitoring
  ├─ standalone DB: Vacations → data/vacations.db
  └─ selected WarehouseSite
       ├─ ixcellerate → WarehouseFacade → data/warehouse.db
       └─ solar       → WarehouseFacade → data/warehouse_solar.db
```

Пользователи и вход не копируются между БД как новый источник истины.
Аутентификация выполняется общей Administration-службой IXcellerate. Для
операции Solar уже проверенный public user/role делегируется Solar Warehouse
actor context; пароль и password hash туда не передаются. Складской audit
записывается в БД того склада, где выполнена операция.

Reports и Knowledge используют primary application DB независимо от выбранного
склада. Monitoring не владеет таблицами, а Vacations всегда использует
самостоятельную `data/vacations.db`. Administration показывает topology всех
трёх runtime-БД и умеет создать проверенный snapshot IXcellerate, Solar или
Vacations через `MultiDatabaseBackupService`. Restore для любого target
остаётся fail-closed до ADR-013.

## Bootstrap Solar

`bootstrap_solar_database()`:

1. открывает IXcellerate read-only;
2. создаёт новую БД во временном sibling-файле;
3. переносит только `categories`, `locations`, `reference_values` и
   `reference_domains_v2` / `reference_values_v2` /
   `reference_aliases_v2`, если v2 присутствует;
4. доказывает нулевые counts operational-таблиц;
5. выполняет `integrity_check` и `foreign_key_check`;
6. выставляет `0600` на POSIX и публикует файл атомарным `os.replace`.

Если `data/warehouse_solar.db` уже существует, bootstrap ничего не
синхронизирует и не перезаписывает. Это защищает независимые Solar-справочники
и операции от повторного импорта IXcellerate.

## Изоляционные инварианты

- S/N уникален внутри выбранного склада, но может существовать в обоих.
- Все Warehouse reads, exports, previews и mutations используют runtime,
  выбранный в сессии.
- Preview ID, delivery ID и Full Inventory workspace нельзя переносить через
  переключение UI; transient DOM state очищается.
- Full Inventory state остаётся вне repository: Solar использует отдельный
  подкаталог `solar` внутри настроенного внешнего state-root IXcellerate.
- В API `/api/data` возвращает `warehouse_site` и fingerprint выбранной БД.
- `/api/warehouses` перечисляет доступные склады, а
  `POST /api/warehouse/select` принимает только известный key.
- Runtime DB и sidecars остаются installation-owned и не попадают в Git.

## Проверки

Автоматический контракт `tests/test_warehouse_sites.py` доказывает:

- source SHA не меняется при bootstrap;
- Solar operational tables пусты;
- справочники копируются один раз;
- повторный bootstrap не перезаписывает Solar;
- session switch меняет `/api/data`;
- приход Solar не появляется в IXcellerate и наоборот.

Для ручной проверки: выбрать Solar, убедиться в нулевом балансе и пустой
истории, добавить тестовую позицию только на disposable копии, переключиться
на IXcellerate и подтвердить отсутствие этой позиции.
