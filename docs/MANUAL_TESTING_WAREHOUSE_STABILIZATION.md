# Manual Testing — ODE Warehouse Stabilization

Дата: 2026-07-14. Scope: только Warehouse на `data/warehouse.db`.

## Перед началом

1. Запустить `python3 app.py` без migration/pilot flags.
2. Убедиться, что открывается обычный ODE и рабочая БД содержит 50 000 приходов,
   18 798 расходов и 18 798 allocations.
3. Открыть DevTools и очистить Console/Network counters.

## Навигация и права

1. В постоянной шапке нет строки всех модулей; ODE кликабелен.
2. ODE открывает карточки Warehouse, Works, Monitoring, Reports и permission-
   gated Administration.
3. Monitoring и Reports показывают только «В разработке».
4. Warehouse subnav содержит семь складских разделов; каждый начинает со своего
   начального экрана.
5. Engineer не видит Administration; admin видит его независимо от ФИО.
6. В UX нет отдельного переключателя режима администратора.

## Reference Data

1. ЦОД: placeholder и единственное значение `Ixcellerate`.
2. Полки не содержат `Выгородка 1`, `Выгородка1`, `выгородка 1`, `лорпач`,
   пустые/ЦОД/ряды; пустое отображается как «Не указана».
3. Поставщики не содержат `?`, `N/A`, `взято из ...` и комментарии.
4. Vendors включают Dell, Huawei, xFusion, Vegman, HPE, Lenovo, Supermicro.
5. Huawei и xFusion различны; модели меняются при выборе vendor; Vegman R200 и
   R220 различны.
6. «Другое» создаёт pending proposal и не появляется canonical автоматически.
7. В Administration editor проверить aliases, usage, author/source/warning,
   deactivate, rename и merge preview. Не выполнять production merge без
   утверждённого бизнес-решения.

## Приход и расход

1. Открытие вкладки всегда показывает выбор сценария.
2. Создать незавершённый draft, перейти в другую вкладку и вернуться: ODE должен
   предложить Continue/Start over/Delete, а не прыгнуть в середину.
3. Проверить isolation другим пользователем и TTL/schema invalidation.
4. Добавить несколько S/N, удалить одну/выбранные/все строки, повторно добавить
   удалённый S/N и подтвердить только оставшиеся. Повторить для расхода и после
   reload/явного restore draft.
5. Уже подтверждённые операции не должны исчезать через draft controls.

### Scanner Operations 0.13.4

1. В расходе открыть «Сканировать оборудование» и выбрать «Один сервер».
   Один раз отсканировать/ввести целевой сервер, затем добавить несколько S/N;
   неизвестный, повторный и уже списанный S/N не должен попадать в список.
2. Очистить список и выбрать «Пары: компонент → сервер».
3. После скана компонента prompt обязан явно перейти в состояние ожидания
   сервера; следующий скан валидного оборудования создаёт ровно одну пару.
4. Ошибочный S/N сервера не создаёт пару и оставляет компонент ожидающим
   повторного скана цели.
5. После готовой пары фокус автоматически возвращается к следующему компоненту.
6. Confirm проводит всю пачку атомарно. Ошибка любой пары означает zero writes.
7. После reload явное восстановление draft сохраняет готовые пары и режим.

## Search и Equipment Card

1. Запрос из одного символа не запускает поиск; два символа запускают debounce.
2. Проверить exact S/N, prefix, vendor, model и canonical name.
3. Проверить ArrowUp/ArrowDown, Enter, Escape, click, loading/empty/error.
4. Быстро сменить запрос: stale response не должен заменить свежий.
5. Результат открывает Equipment Card с S/N, Inventory Number, canonical/source
   name, vendor/model/Part Number, location/shelf/status/balance и Timeline.
6. Обычная карточка не показывает raw XML/hash/confidence/reconciliation.

## Data safety и итог

1. Exact S/N `1` отсутствует; похожие S/N присутствуют.
2. Leading-zero, long numeric, alphanumeric, Cyrillic и mixed samples визуально
   совпадают с pre-stabilization evidence.
3. `PRAGMA integrity_check` возвращает `ok`, FK check пуст.
4. Console error, `window.onerror`, unhandled rejection, resource error,
   HTTP/API 500 — по нулям.
5. Результат: `WAREHOUSE_ACCEPTED` либо список конкретных defects. Monitoring и
   Reports этим решением не принимаются.
