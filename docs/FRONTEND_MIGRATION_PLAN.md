# FRONTEND_MIGRATION_PLAN

Дата: 2026-07-10

## Статус

Stage 0.12.2: `components.js` создан, `router.js` частично переведен на компоненты, `static/js/ui.js` остается legacy UI. Массовая замена `innerHTML` запрещена. Перенос выполняется только маленькими итерациями, по одному экрану.

После каждого экрана:

- `node --check static/js/*.js tests/headless_smoke.js`
- `python3 scripts/smoke_ui.py`
- `python3 scripts/audit_frontend_contracts.py`
- ручной click smoke измененного экрана.

## Главная — migrated in Stage 0.12.3

Перенесено на `components.js`:

- `warehouseLanding`

Осталось legacy рядом, но не входит в экран Главной:

- `openWarehouseHub`
- `openMonitoringHub`
- `openShiftProfile`

DOM id:

- `home`
- `overview`
- `monitoring`
- `profile`
- `currentUser`
- `pageTitle`

Компоненты:

- `renderCard`
- `renderButton`
- `renderHeader`
- `renderBadge`

Smoke:

- вход инженера;
- старт на главной;
- клик по ODE возвращает на главную;
- карточки `Склад`, `Отчеты`, `Мониторинг`, `Профиль` открываются без `interfaceError`.

## Навигация

Статус: migrated in Stage 0.12.3 для базовой навигации разделов и клика по ODE.

Перенесено на `components.js`:

- `showSection`
- `showView`
- `openTask`
- `showProfile`
- `goHome`
- `initSectionNavigation`
- часть `modernShell`, отвечающая за бренд ODE и кнопку профиля

DOM id:

- `subnav`
- `pageTitle`
- `home`
- `warehouse`
- `reports`
- `monitoring`
- `profile`

Компоненты:

- `renderButton`
- `renderSidebar`
- `renderHeader`

Smoke:

- ODE -> главная;
- вкладки склада;
- вкладки отчетов;
- переходы не создают console error.

## Баланс — migrated in Stage 0.12.4

Статус: migrated for working balance screen.

Перенесено на `components.js`:

- KPI-карточки `Серверы`, `Диски`, `Память`, `Сеть`, `Кабели`, `Прочее`;
- активная подсветка KPI-фильтра;
- кнопка `Сбросить фильтр`;
- рабочие фильтры `balanceQuery`, `uxBalanceCategory`, `uxBalanceType`, `uxBalanceProject`;
- заголовок таблицы;
- строки таблицы баланса;
- кнопки строк `Открыть карточку` и `Списать`.

Legacy fallback:

- старый `renderBalance()` остается для раннего pre-UX render-прохода и совместимости, но рабочий экран после `initEngineerUX()` использует `renderSimpleBalance()` на DOM-компонентах.

Legacy-функции:

- `renderBalance`
- `renderSimpleBalance`
- `renderBalanceKpis`
- `setBalanceCardFilter`
- `clearBalanceFilters`
- `openPositionCard`
- `selectForIssue`

DOM id:

- `balance`
- `balanceBody`
- `balanceLimit`
- `balanceExport`
- `balanceKpis`
- `balanceQuery`
- `uxBalanceCategory`
- `uxBalanceType`
- `uxBalanceProject`
- `positionModal`
- `positionDetails`
- `positionHistory`
- `positionProblems`

Компоненты:

- `renderTable`
- `renderCard`
- `renderButton`
- `renderBadge`
- `renderDialog`
- `renderInput`
- `renderSelect`

Smoke:

- открыть `Склад` -> `Баланс`;
- увидеть KPI-карточки;
- применить KPI-фильтр;
- открыть карточку позиции;
- перейти из карточки к списанию.

## История — migrated in Stage 0.12.5

Статус: migrated for working warehouse history screen.

Перенесено на `components.js`:

- заголовок и описание экрана;
- фильтры периода, инженера, действия и поиска;
- кнопка `Сбросить фильтры`;
- таблица истории;
- пустое состояние;
- сообщение об ошибке;
- человекочитаемые названия действий;
- безопасное отображение `details` и комментариев.

Фильтрация сейчас клиентская: `/api/data` отдает `warehouse_history`, а экран фильтрует уже загруженную выборку. Серверная пагинация и серверные фильтры остаются задачей ODE 0.13, потому что на этом этапе API и БД не менялись.

Legacy-функции:

- `renderOperations` — compatibility alias, сам HTML больше не строит;
- `downloadPositionHistory`

DOM id:

- `journal`
- `operationBody`
- `positionHistory`

Компоненты:

- `renderTable`
- `renderButton`
- `renderInput`
- `renderSelect`
- `renderElement`

Smoke:

- открыть `Склад` -> `История`;
- таблица истории или корректное пустое состояние отображается;
- поиск работает;
- сброс фильтров работает;
- нет `interfaceError`;
- нет `console.error`, `window.onerror`, `unhandledrejection` и resource errors;
- после тестового прихода операция появляется в истории.

Оставшийся legacy рядом:

- карточка позиции и `positionHistory`;
- экспорт CSV журнала через существующие ссылки;
- серверная выборка `warehouse_history(limit=300)` без пагинации.

## Приход

Статус: legacy.

Legacy-функции:

- `startReceiptWizard`
- `renderScannedReceipts`
- `removeScannedReceipt`
- `saveSimpleReceipt`
- `setReceiptMode`
- `receiptCategoryChanged`
- `updateReceiptFields`
- `updateReceiptSuggestions`
- `renderPreview`
- `confirmPreview`

DOM id:

- `receipt`
- `stockReceiptForm`
- `scanReceiptForm`
- `receiptScanner`
- `scanReceiptBody`
- `confirmScanReceipts`
- `receiptCsv`
- `receiptPreview`
- `simpleReceiptForm`
- `simpleReceiptTitle`
- `wProject`
- `wShelf`
- `wDc`
- `wSupplier`

Компоненты:

- `renderWizard`
- `renderButton`
- `renderInput`
- `renderSelect`
- `renderTable`
- `renderCard`
- `renderToast`

Smoke:

- `Склад` -> `Приход`;
- мастер сканирования оборудования;
- ввод 2 S/N;
- черновик отображается;
- удаление строки;
- подтверждение прихода;
- баланс и история обновлены.

## Расход

Статус: legacy.

Legacy-функции:

- `renderScannedIssues`
- `removeScannedIssue`
- `selectForIssue`
- `saveCableIssue`
- `previewCsv`
- `confirmPreview`
- `renderPreview`
- `issueSearchForm.onsubmit`

DOM id:

- `issue`
- `stockIssueForm`
- `scanIssueForm`
- `issueScanner`
- `scanIssueBody`
- `confirmScanIssues`
- `issueSearchForm`
- `issueSearchBody`
- `bulkIssueForm`
- `bulk_issuePreview`
- `cableIssueForm`

Компоненты:

- `renderWizard`
- `renderButton`
- `renderInput`
- `renderSelect`
- `renderTable`
- `renderCard`
- `renderToast`

Smoke:

- открыть `Расход`;
- сценарии расхода отображаются;
- поиск в балансе ведет к расходу;
- массовый preview не ломает UI;
- нет console error.

## Поставки

Статус: legacy.

Legacy-функции:

- `loadDeliveries`
- `openDelivery`
- `scanDelivery`
- `fillDelivery`
- `saveDeliveryCell`
- `closeDelivery`
- `confirmDelivery`

DOM id:

- `deliveries`
- `deliverySearch`
- `deliveryList`
- `deliveryCard`
- `deliveryCsv`
- `deliveryPreview`
- `deliveryScanner`
- `deliveryLines`
- `deliveryFillField`
- `deliveryFillValue`

Компоненты:

- `renderTable`
- `renderCard`
- `renderButton`
- `renderInput`
- `renderSelect`
- `renderDialog`
- `renderBadge`

Smoke:

- открыть `Поставки`;
- список поставок не падает на пустых данных;
- поиск поставки;
- preview CSV вручную проверяется отдельным сценарием на временной БД.

## Отчеты

Статус: legacy.

Legacy-функции:

- `loadWorkLogs`
- `clearWorkLogFilter`
- `renderDaily`
- `buildDaily`
- `showUploadedReport`
- `showUploadedReportList`
- `buildWeekly`
- `addDailyRow`
- `saveDailyLogs`

DOM id:

- `daily`
- `dailyForm`
- `dailyBody`
- `downloadDaily`
- `uploadedReport`
- `uploadedReportList`
- `uploadedReportBody`
- `weeklyForm`
- `weeklyCards`
- `weeklyProjects`
- `weeklyTypes`
- `worklogs`
- `workLogFilter`
- `workLogBody`
- `exportWorkLogs`
- `dailyLogRows`
- `dailyLogDate`

Компоненты:

- `renderTable`
- `renderCard`
- `renderButton`
- `renderInput`
- `renderSelect`
- `renderToast`

Smoke:

- открыть `Отчеты`;
- ежедневный отчет;
- недельный отчет;
- логи работ;
- экспортные ссылки формируются без ошибок.

## Профиль

Статус: legacy, кроме входа в профиль из Главной.

Stage 0.13.3A.5 stabilization: top bar больше не дублирует вход в профиль
(кнопки `Профиль` и `Сменить пароль` в `.profile-actions` убраны вместе с DOM
id `adminPassword`). Единственная точка входа — карточка `Профиль` в
`.portal-grid` Главной (`onOpen -> openShiftProfile()`), рядом с карточкой
`Мониторинг`. `openShiftProfile()` уже был role-aware (admin видит
`profileForm`+смену пароля, инженер — `shiftProfileCard`), поэтому
объединение точек входа не потеряло функциональность.

Legacy-функции:

- `showProfile`
- `openShiftProfile`
- `profileForm.onsubmit`
- `passwordForm.onsubmit`
- `logout`

DOM id:

- `profile`
- `profileForm`
- `passwordForm`
- `currentUser`

Компоненты:

- `renderCard`
- `renderButton`
- `renderInput`
- `renderDialog`

Smoke:

- открыть `Профиль` через карточку главной (`[data-module-open="profile"]`);
- кнопка ODE возвращает на главную;
- форма профиля не создает JS errors.
