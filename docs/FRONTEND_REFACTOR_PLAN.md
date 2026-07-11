# FRONTEND_REFACTOR_PLAN

Дата: 2026-07-10

## Цель

Снизить риск JS-регрессий в ODE 0.12 перед переходом к ODE 0.13. Не менять внешний вид радикально, бизнес-логику, БД и существующие маршруты.

## Текущая проблема

`inventory/webapp.py` содержит одновременно:

- HTML страницы.
- CSS.
- JavaScript.
- API handler.
- CSV templates.
- поздние `.replace(...)` для изменения HTML.

Из-за этого любой текстовый replace может сломать `id`, `onclick`, `querySelector`, форму или секцию. Типовые ошибки: `Cannot read properties of null`, устаревшие `onclick`, битые `data-section`, битые `data-view`.

## Целевое разбиение файлов

Минимальный первый шаг:

```text
static/
  css/
    main.css
  js/
    core.js
    api.js
    router.js
    ui.js
```

Позже:

```text
static/js/modules/
  receipt.js
  issue.js
  balance.js
  deliveries.js
  reports.js
  admin.js
  scanner.js
  imports.js
```

## Назначение модулей

### `static/js/core.js`

Базовые безопасные helper-функции:

- `byId(id)`
- `setText(id, value)`
- `setHtml(id, html)`
- `show(target)`
- `hide(target)`
- `esc(value)`
- `option(value, label)`
- `notify(message, error)`
- глобальный обработчик `window.onerror`
- глобальный обработчик `unhandledrejection`

Правило: модуль не должен знать бизнес-сценарии склада.

### `static/js/api.js`

Обертки над fetch:

- `request(url, options)`
- `actionJson(data)`
- `uploadCsv(kind, file, options)`
- `downloadCsv(url)`

Правило: все API ошибки должны превращаться в понятный `Error`, а UI должен показывать их через `notify`.

### `static/js/router.js`

Навигация и секции:

- `sections`
- `showSection(name)`
- `showView(id)`
- `openTask(section, view)`
- `showProfile()`

Правило: если секция или view отсутствует, показывать interface error, а не падать на `null`.

### `static/js/ui.js`

Общие UI-render функции:

- `fillSelects()`
- `renderBalance()`
- `renderProblems()`
- `renderRecentReceipts()`
- `renderWarehouseHistory()`
- `renderDraftPanel()`

Правило: UI-функции используют только безопасные helpers.

## HTML-шаблоны

Первый этап без template engine:

- оставить `LOGIN_HTML` в `webapp.py`;
- оставить базовый app shell в `webapp.py`;
- подключить `<link rel="stylesheet" href="/static/css/main.css">`;
- подключить `<script src="/static/js/core.js"></script>` и остальные модули;
- удалить inline `onclick` постепенно, не одномоментно.

Следующий этап:

```text
templates/
  login.html
  app.html
  sections/
    home.html
    receipt.html
    issue.html
    balance.html
    deliveries.html
    reports.html
    admin.html
    profile.html
```

## UI-компоненты

Нужны повторяемые компоненты:

- `Button`
- `StatusToast`
- `Modal`
- `Table`
- `CsvPreview`
- `ScannerPanel`
- `ScenarioCards`
- `PositionCard`
- `ReportTable`
- `AdminPanel`

В ODE 0.12 это должны быть простые функции, возвращающие HTML-строки или создающие DOM-узлы. Framework не нужен.

## Безопасные правила DOM

1. Запрещены прямые `document.getElementById(...).innerHTML = ...` без проверки.

2. Для обязательного элемента использовать:

```js
const el = requireId("balanceBody")
```

3. Для опционального элемента использовать:

```js
setText("balanceLimit", text)
```

4. Все обработчики вешать после загрузки DOM или после создания конкретного блока.

5. `onclick` в HTML допускается только на переходном этапе. Новые обработчики - через `addEventListener`.

## Порядок refactor без изменения бизнес-логики

1. Добавить static serving в `webapp.py`.

2. Вынести CSS в `static/css/main.css`.

3. Вынести safe helpers в `static/js/core.js`.

4. Вынести `request/actionJson` в `static/js/api.js`.

5. Вынести `showSection/showView/openTask` в `static/js/router.js`.

6. Вынести render-функции в `static/js/ui.js`.

7. После каждого шага запускать:

```bash
python3 -m unittest -v tests.test_warehouse
node --check static/js/core.js
node --check static/js/api.js
node --check static/js/router.js
node --check static/js/ui.js
python3 scripts/smoke_ui.py
sqlite3 data/warehouse.db 'PRAGMA integrity_check; PRAGMA foreign_key_check;'
```

## Обновление smoke-test

`scripts/smoke_ui.py` должен проверять:

- вход инженера;
- главную;
- клик ODE -> главная;
- Склад;
- Приход;
- Расход;
- Баланс;
- История;
- Отчеты;
- Профиль;
- отсутствие `interfaceError`;
- отсутствие console exceptions через Chrome DevTools.

## Release-gate

Release ZIP не пересобирать до прохождения:

- `unittest`;
- `node --check`;
- `smoke_ui.py`;
- `integrity_check`;
- `foreign_key_check`;
- ручной smoke в браузере.
