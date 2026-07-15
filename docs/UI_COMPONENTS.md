# UI Components ODE 0.13

## Цель

Компонентный слой нужен, чтобы постепенно убрать копирование HTML из `inventory/webapp.py` и снизить риск ошибок вида `Cannot read properties of null`, битых `onclick`, устаревших `id` и несогласованных DOM-структур.

Этот этап не меняет бизнес-логику, API и базу данных. Внешний вид должен оставаться совместимым с ODE 0.12.

## Runtime-файлы

- `static/js/components.js` - новый UI kit и фабрики DOM-компонентов.
- `static/js/core.js` - общие helper-функции DOM, ошибок и состояния.
- `static/js/router.js` - переключение разделов и вкладок.
- `static/js/api.js` - HTTP-запросы.
- `static/js/ui.js` - legacy UI: текущие экраны и сценарии склада, перенесенные из монолитного `webapp.py`.

`inventory/webapp.py` должен отдавать HTML-каркас и подключать внешние CSS/JS. Новую UI-логику нельзя добавлять обратно в Python-строки.

Stage 0.12.2 фиксирует переходное состояние: компонентный слой создан, но legacy `innerHTML` остается в старых зонах `static/js/ui.js` и старых строках `inventory/webapp.py`. Это допустимо только для существующего legacy-кода. Новые экраны и новые render-функции должны использовать `components.js`.

## Компоненты

Базовые компоненты:

- `Button` -> `renderButton()`
- `Card` -> `renderCard()`
- `Table` -> `renderTable()`
- `Input` -> `renderInput()`
- `Select` -> `renderSelect()`
- `Toast` -> `renderToast()`
- `Dialog` -> `renderDialog()`
- `Badge` -> `renderBadge()`

Stage 0.13.3A.5 stabilization removed `renderWizard()`, `renderHeader()` и
`renderSidebar()` из `components.js`: они не имели ни одного вызова (реальный
wizard-шаг, header и sidebar собираются другими путями — `static/js/ui.js` и
`inventory/webapp.py`), это было мертвое дублирование.

Все фабрики возвращают DOM-узел. Компоненты собираются через `document.createElement`, `appendChild`, `replaceChildren`, `DocumentFragment` или `<template>`.

## Правила

1. Новый экран строится из компонентов, а не из склеенных HTML-строк.
2. Для замены содержимого используется `replaceChildren`.
3. Для событий используется `addEventListener` или передача handler в компонент.
4. Нельзя добавлять новые inline-обработчики `onclick`, `onchange`, `onblur`.
5. Нельзя добавлять новые прямые обращения к `innerHTML`.
6. Пользовательские/server values передаются только через `textContent`,
   `setText` или component `{text: ...}`. `setHtml` и `replaceContent`
   интерпретируют markup через fragment parser и допустимы только для
   доверенной статической разметки, не для imported/API data.
7. Если элемент может отсутствовать на части экранов, код обязан проверять `null`.
8. Массовая автоматическая замена `innerHTML` запрещена. Предыдущие попытки ломали синтаксис из-за плотных template string, вложенных `map` и callback-ов.
9. `innerHTML` временно разрешен только в legacy-зонах, пока конкретный экран не перенесен на компоненты.

## План миграции существующего UI

Текущий `static/js/ui.js` содержит legacy-разметку, перенесенную из монолитного `webapp.py`. Ее нельзя массово переписывать регулярными выражениями: в файле есть вложенные template string, callback-и `map`, условные выражения и inline-обработчики.

## Применение: История

Stage 0.12.5 перевел рабочий экран `История` на компонентный DOM-рендер:

- `renderElement()` строит заголовок, описание, контейнер фильтров, summary, loading/error/empty состояния.
- `renderInput()` используется для периода и поиска.
- `renderSelect()` используется для фильтра инженера и типа действия.
- `renderButton()` используется для `Сбросить фильтры`.
- `renderTable()` создает таблицу с колонками `Дата и время`, `Инженер`, `Действие`, `Объект / позиция`, `S/N или ID`, `Подробности`.

Пустое состояние отображается строкой таблицы с классом `history-empty`. Ошибки разбора данных не пробрасываются в UI как traceback: экран показывает понятное сообщение, а подробности JSON преобразуются в пары `ключ: значение` с ограничением длины.

Фильтры Истории пока клиентские. Новые id для фильтров не добавлялись: обработчики держат ссылки на созданные DOM-узлы, чтобы не расширять контракт HTML <-> JS без необходимости.

Безопасный порядок миграции:

1. Переносить по одному экрану: `overview`, `balance`, `receipt`, `issue`, `deliveries`, `reports`, `profile`.
2. Для каждого экрана сначала вынести маленькие render-функции строк таблиц и карточек.
3. Заменять таблицы на `renderTable()`.
4. Заменять кнопки на `renderButton()` с `addEventListener`.
5. Заменять формы на `renderInput()` и `renderSelect()`.
6. После каждого экрана запускать `node --check`, `smoke_ui.py` и ручной click smoke.

Перенос считается безопасным только если измененный экран проходит `scripts/audit_frontend_contracts.py` без новых missing id.

## Применение: Bulk Inventory Number

Stage 0.13.2 реализован в `static/js/warehouse/inventory.js` без новых HTML-
строк с пользовательскими данными:

- summary строится через `renderCard()`;
- статусы — через `renderBadge()`;
- строки preview/result — через `renderTable()` и `renderElement({text: ...})`;
- Confirm — через `renderButton()` с function handler;
- loading/error/result заменяют container через `replaceChildren()`.

Статические `#inventoryNumberCsv` и `#inventoryNumberImport` проверяются
frontend contract audit. Сервер возвращает максимум 100 Preview/Result rows,
поэтому общий `summary.total` может быть больше видимой таблицы; это ограничение
должно оставаться явно описанным в пользовательской документации.

## Применение: Migration Pilot Review

Stage 0.13.3A.5 реализует marker-guarded read-only экран в
`static/js/warehouse/migration_pilot.js`:

- panel, search form, filters, counters and table are built through
  `renderElement`, `renderInput`, `renderButton`, `renderCard` and
  `renderBadge`;
- every source/API string uses a text property; imported S/N is rendered in a
  whitespace-preserving `<code>` node without HTML interpretation;
- filter buttons have function handlers, not inline attributes;
- an Equipment Card button exists for `IMPORT` and linked
  `EXACT_DUPLICATE`/`CONFLICT_HISTORY_ONLY` rows, opens their one primary card
  and sends an integer selection ID;
- migration section in the card keeps source/canonical names, preservation
  status, warnings and source rows separate;
- normal mutation/navigation controls are hidden for reviewer clarity, while
  backend rejects writes independently.

The pilot screen is created only when the server returns a validated
`migration_pilot.enabled` status. It must never be made available solely by a
client-side query flag. XSS fixtures and headless smoke cover source names,
warnings and S/N values.

## Готовность

Этап считается завершенным только когда:

- `static/js/components.js` используется всеми экранами;
- в runtime JS нет прямых `innerHTML` и `insertAdjacentHTML`;
- новые обработчики не создаются через inline-атрибуты;
- smoke-test проходит без JS-ошибок;
- внешний вид не отличается от ODE 0.12.
