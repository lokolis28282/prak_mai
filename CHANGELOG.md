# Changelog ODE

## Интеграция и стабилизация ветки Reports (2026-08-07)

Commit коллеги `bb83690` из remote-ветки `reports` перенесён поверх текущего
`release/0.20.0` после отдельного branch/ancestry review. Ветка была основана
на `7b94127` и не включала общий стабилизационный commit `4dbd34b`, поэтому
blind merge не использовался.

Интегрированы: новый экран УВР внутри отчёта за смену, PNR-чек-лист и
автоматические description/status, обязательный срок интерактивной записи,
передача незавершённых задач, действия edit/delete/view, server-bounded реестр
с UI-страницами по 25 строк, массовый разбор `needs_review`, форматированные
XLSX-выгрузки и общий styled confirm dialog.

По результатам независимого code/logic review исправлены дефекты исходного
commit:

- лист `Выполненные работы` теперь содержит только закрытые задачи выбранной
  смены; handover-лист включает текущий и старый незавершённый backlog, но не
  будущие строки;
- кнопка `Передача по смене → Выгрузить в Excel` получает отдельный
  `handover.xlsx` с теми же date/search/status filters, а не общий work-log;
- status/section фильтруются на сервере и участвуют в экспорте, поэтому записи
  за пределами первых 1000 строк не теряются при уточнении выборки;
- bulk section принимает только активный справочник, не снимает review при
  ошибке и обновляет до 1000 выбранных строк SQL-чанками без 999-bind failure;
- XLSX writer заменяет запрещённые XML 1.0 control characters и сохраняет все
  значения как text; проверен XML round-trip;
- export columns перенесены в Reports ownership; audit запрещает зависимость
  `inventory/reports → inventory/routes`;
- Enter больше не подтверждает destructive dialog на уровне document: Escape
  отменяет, а Enter действует только на реально сфокусированную кнопку;
- старые read-only `/export/*.csv` URLs сохранены для совместимости, текущий UI
  использует XLSX.
- безопасный runtime-installer теперь действительно добавляет новые
  `due_date`/`pnr_checklist` и проверяет полную Reports-схему; до исправления
  текущая promoted DB падала при чтении с `no such column: due_date`;
- Reports получил собственный `task_source` contract, поэтому PNR больше не
  теряется из-за складского `operation_source`; исправлены пустой маршрут
  карточки Reports, скрытие PNR description, edit/refresh из handover и
  read-only интерфейс viewer;
- форма снимает duplicate-submit lock по завершению запроса, поэтому следующая
  быстрая запись больше не блокируется молча три секунды.
- реальные результаты глобального поиска снова идут раньше дополнительного
  перехода «Искать в работах»: S/N больше не выглядит как ложный Reports-hit.

Full warning-clean discover после интеграции: 685 tests, `skipped=8`; полный
release gate и DB SHA/integrity evidence находятся в
`docs/project/reviews/2026-08-07_ODE_0_20_0_REPORTS_INTEGRATION_AUDIT.md`.

## Отчёты: чистка дашборда, конкретная передача, форматированный Excel (2026-08-05)

Итерация по замечаниям смены к разделу «Отчёты»:

- **Работы за смену можно изменять и удалять прямо в таблице «За смену»**
  (вкладка «Отчёт за смену»). У каждой строки — действия «Изменить» и
  «Удалить» (у роли viewer — только «Просмотр»); действия переиспользуют
  контроллер реестра, после правки/удаления таблица смены обновляется на
  месте. Раньше действия были только в реестре «Все работы». Кнопки прижаты к
  правому краю столбца.
- **Красивое подтверждение удаления** вместо браузерного `confirm()`: общий
  компонент `confirmDialog` (в стиле сайта, `static/js/components.js`) —
  модалка с заголовком, текстом (с именем задачи) и кнопками «Отмена» /
  «Удалить» (красная). Закрывается по Esc и клику вне карточки. Тем же
  компонентом оформлено подтверждение импорта из Excel. Применён и в реестре
  «Все работы» (там убраны «Просмотр» и быстрый «✓ Выполнено» — остались
  «Изменить»/«Удалить»).
- **Дашборд смены упрощён**: убран индикатор «PNR прогресс». Остаются три
  карточки — «Работ за смену», «Выполнено», «Незавершённых».
- **Передача по смене показывает, что осталось сделать**. Для незавершённой
  PNR-задачи описание в передаче заменяется конкретными оставшимися
  действиями, выведенными из невыполненных этапов чек-листа: один шаг →
  «Необходимо выполнить: <шаг>.», несколько → маркированный список. Логика
  общая для таблицы передачи и листа «Передача по смене» в Excel
  (`pnr_handover_text`/`pnr_remaining_steps` в `inventory/reports/validators.py`).
- **Удалено поле «Тип задачи»** из формы и реестра работ (дублировало «Источник
  задачи»). «Описание работ» сохранено. Имя задачи теперь формируется из
  источника и номера (`Источник-Номер`); при пустом номере — только источник.
  Колонка `task_type` в БД сохранена для совместимости импорта, но UI её не
  показывает и не требует.
- **Убраны стрелки-переходы** («← Отчёт за смену», «Отчёт за неделю →») с
  вкладки «Передача по смене» — навигация только через подвкладки раздела.
- **Реестр «Все работы» — постраничная навигация по 25 записей** вместо
  бесконечной прокрутки: страница 1 — записи 1–25, страница 2 — 26–50 и т.д.
  Номера страниц, стрелки и переход к первой/последней; смена фильтра, поиска
  или сортировки возвращает на первую страницу. Пагинация клиентская поверх
  загруженного набора (серверный лимит выборки не изменился).
- **Последний столбец реестра больше не обрезается**: колонка «Действия» не
  сжимается и не переносится, таблица прокручивается по горизонтали.
- **Выгрузка отчётов переведена с CSV на форматированный `.xlsx`**
  (кнопки «Выгрузить в Excel»): реестр работ, передача, отчёт за смену/неделю и
  выгруженные отчёты. **Импорт CSV не изменён** (работы, ежедневный отчёт,
  инвентаризация, назначение инвентарных номеров). Складские выгрузки
  (приход/расход/баланс/аудит) остались в CSV — вне рамок изменения.
- **Стиль Excel-выгрузок**: наш stdlib-writer (`inventory/shared/xlsx_writer.py`)
  расширен форматированием — объединённый заголовок листа (строка 7,
  светло-зелёная заливка, жирный, по центру), шапка столбцов (строка 8 от
  столбца C, светло-жёлтая заливка, жирный), тонкие рамки таблицы и авто-ширина
  столбцов. Файл открывается без «восстановления» в Microsoft Excel и
  LibreOffice Calc.
- **Тесты**: контракт экспортов Отчётов переведён с CSV на XLSX
  (`tests/test_reports_api_contract.py`), обновлены проверки двухлистового
  экспорта и `full_task_name` (`tests/test_reports_handover.py`,
  `tests/test_uvr_workflow.py`); обновлён хэш `webapp.HTML`.

## Отчёты: UX-переработка реестра, дашборд смены и масштабируемость (2026-08-04)

По результатам UX-анализа раздела «Отчёты» глазами инженера:

- **УВР встроен в «Отчёт за смену»** как переключатель «За смену / Все работы».
  Отдельной вкладки УВР в навигации больше нет; порядок вкладок раздела:
  Отчёт за смену → Передача по смене → Отчёт за неделю → Складские операции.
  «За смену» — дашборд и работы за день (дефолт), «Все работы» — полный реестр
  с фильтрами, поиском и выгрузкой всего в Excel.
- **Пагинация реестра**: `GET /api/work-logs-page` отдаёт до 1000 строк с
  общим счётчиком и флагом усечения; поиск, диапазон дат и фильтр
  «требует проверки» выполняются на сервере, поэтому реестр остаётся отзывчивым
  при тысячах записей.
- **Дашборд смены** (`GET /api/shift-stats`): карточки «Работ за смену»,
  «Выполнено %», «Незавершённых», «PNR прогресс».
- **Массовый разбор `needs_review`**: чекбоксы в реестре + групповое назначение
  раздела выбранным строкам (`ASSIGN_SECTION`) со снятием флага проверки.
- **Быстрые действия в строке**: «✓ Выполнено» без открытия формы (кроме PNR,
  чей статус вычисляется), режим просмотра записи (только чтение, с PNR-шагами),
  подсветка просроченных задач (срок < сегодня и статус ≠ «Выполнено»).
- **Порядок полей формы** приведён к логике ввода: Дата → Источник → Номер →
  Описание → Тип → Раздел → Статус → Срок.
- **Автоподсказки описания** из истории: для источников без предопределённого
  списка предлагаются недавние описания инженера по этому источнику
  (свободный ввод сохраняется).
- **Глобальный поиск** получил закреплённый пункт «Искать в работах (УВР)»,
  открывающий реестр с подставленным запросом (без нарушения границ модулей).
- **Счётчик** числа задач к передаче на подвкладке «Передача по смене».

## Отчёты: PNR-зависимости, умное описание и обязательный срок (2026-08-04)

Доработка раздела «Отчёты» по обратной связи со сменой:

- **Вкладка «Передача по смене»** теперь всегда видна в разделе «Отчёты»
  наравне с УВР и Отчётом за смену (исправлен рассинхрон навигации, где
  `product.js` перезаписывал список вкладок без неё); добавлены ссылки-переходы
  между связанными вкладками.
- **PNR-работы переименованы**: «Установка оборудования в стойки», «Установка
  трансиверов», «Маркировка кабеля»; названия обновлены в чек-листе, описании,
  экспорте и фильтрах.
- **Последовательность PNR**: «Прокладка кабеля» доступна только после
  «Маркировка кабеля», «Коммутация кабельных систем» — только после «Прокладка
  кабеля». Недоступный шаг заблокирован, показывает причину, а порядок хранится
  в данных (`normalize_pnr_checklist` отсекает шаг без выполненного
  предшественника, поэтому запрос не может его обойти).
- **Процент выполнения PNR**: чек-лист показывает прогресс-бар и процент
  (0/17/33/…/100%), рассчитанный из числа выполненных этапов.
- **Умное поле «Описание работ»** по источнику задачи: `ЗНР` и новый источник
  `ИНЦ` — выпадающий список с возможностью свободного ввода (searchable +
  free text); `Outlook` — подсказка «Введите тему письма»; `ИЗМ` — «Введите
  номер ЗНР». Добавлен источник задачи `ИНЦ`.
- **«Срок выполнения» обязателен** при ручном вводе записи (клиентская и
  серверная валидация); поле по умолчанию заполняется сегодняшней датой, чтобы
  не замедлять ввод. Массовый CSV/XLSX-импорт срок не требует.
- **«Раздел» теперь необязателен**.
- **Excel**: из листа «Выполненные работы» убран столбец «Срок» (эти задачи уже
  выполнены); в листе «Передача по смене» срок сохранён.
- **Тесты**: `tests/test_reports_handover.py` дополнен проверками зависимостей
  PNR, процента, обязательного срока, необязательного раздела и источника ИНЦ.

## Отчёты: ручной ввод смены, PNR чек-лист и передача по смене (2026-08-04)

Расширение раздела «Отчёты» вокруг единой модели `work_logs` (без параллельной
реализации):

- **Источник и номер задачи разделены** на два поля во всех формах УВР и отчётов:
  источник — выпадающий список (`task_source`), номер — обычное текстовое поле.
- **PNR чек-лист**: при источнике `PNR` вместо свободного описания показывается
  чек-лист из шести работ (поставить сервера, подключение питания, вставить
  трансиверы, промаркировать кабели, прокладка кабеля, коммутация кабельных
  систем) с кнопкой «Выбрать всё». Описание формируется автоматически из
  отмеченных пунктов; комментарий остаётся отдельным полем.
- **Авто-статус PNR**: все шесть пунктов → статус «Выполнено»; хотя бы один, но
  не все → «В работе». Генерация описания/статуса выполняется на сервере, поэтому
  API и импорт консистентны.
- **Ручной ввод в «Отчёт за смену»**: добавлена та же форма записи, что в УВР;
  запись пишется в общий `work_logs` и сразу видна на обеих вкладках. Кнопка
  «Экспорт в Excel» формирует XLSX с двумя листами — «Выполненные работы» и
  «Передача по смене» — средствами стандартной библиотеки (`inventory/shared/
  xlsx_writer.py`), без внешних зависимостей.
- **Новая вкладка «Передача по смене»**: автоматически показывает незавершённые
  задачи (статус ≠ «Выполнено», включая частично выполненный PNR). Полностью
  выполненные задачи не передаются, поэтому задачи не теряются между сменами.
  Поддержаны поиск, сортировка, фильтры и редактирование через общую модалку.
- **Срок выполнения**: в записи добавлено необязательное поле `due_date`,
  отображается на вкладке «Передача по смене».
- **БД**: идемпотентная миграция добавляет колонки `due_date` и `pnr_checklist`
  в `work_logs`; существующие данные не изменяются.
- **API**: `GET /api/handover` (незавершённые задачи),
  `GET /export/shift-report.xlsx` (двухлистовый экспорт); действия
  `WORK_LOG`/`UPDATE_WORK_LOG` принимают `due_date` и список `pnr_checklist`.
- **Тесты**: добавлен `tests/test_reports_handover.py` (11 тестов) — PNR
  генерация/статус, срок, фильтр передачи, двухлистовый XLSX.

## ODE 0.20.0 — equipment composition projection (2026-08-02)

### Full stabilization follow-up (2026-08-07)

- серийные оборудование и компоненты теперь на всех manual/batch/import
  путях принимаются только как `quantity=1`, `unit=шт`; один S/N больше нельзя
  превратить в несколько списаний;
- batch/import/delivery и Inventory Number lookup одинаково сопоставляют
  preservation-aware S/N с внешними пробелами, не переписывая raw значение;
  неоднозначная normalized-группа fail-closed до исправления дублей;
- malformed PBKDF2 hash больше не может аварийно оборвать login;
- неизвестный authenticated GET возвращает JSON 404, а scanner drafts разных
  ФИО в одном браузере физически разделены ключом session identity;
- устранены raw SQLite connection warnings и добавлен AST regression guard;
- добавлены отдельные operator/developer guides и датированный полный audit;
- полный gate: 649 тестов (`skipped=8`), headless Chrome и все repository/
  architecture/frontend/documentation/data проверки — PASS.

- карточка сервера, коммутатора и другого серийного оборудования показывает
  компоненты, ранее списанные на его S/N: тип, модель, исходный S/N,
  количество, hostname, дату, задачу/ИЗМ, инженера и комментарий;
- добавлена визуальная группировка по трансиверам, дискам, памяти,
  адаптерам/контроллерам, вычислительным модулям, питанию/охлаждению и прочим
  компонентам; наведение показывает краткую историю, клик фильтрует полный
  журнал операций;
- проекция намеренно не выдаётся за инвентаризацию: UI и API явно сообщают,
  что заводская комплектация, фактическое текущее наличие и физические слоты
  не подтверждены. Timeline использует доказуемое событие «Компонент списан
  на оборудование» вместо неточного «Установлен компонент»;
- read-path реализован через `WarehouseFacade → WarehouseDomainService →
  EquipmentCompositionService`; новые таблицы, зависимости и изменения
  production SQLite не требуются;
- добавлены backend/API/UI и headless Chrome regression-проверки. Релизный
  набор composition slice — 639 тестов (`skipped=8` на macOS/Linux);
- post-release documentation audit актуализировал living-документы и добавил
  исполняемые проверки Markdown/frontend controls;
- GitHub-visible PNG, интерактивный code graph и architecture SVG приведены к
  ODE 0.20.0 (248 узлов / 506 связей). Старый versioned PNG больше нельзя
  вывести как current: это проверяют graph/documentation contract tests;
- текущий полный набор после documentation/visual follow-up — 642 теста
  (`skipped=8` на macOS/Linux).

## ODE 0.19.1 — local runtime stabilization (2026-08-02)

- устранён fresh-process circular import в `app.py seed`: публичные symbols
  `inventory.core.ApplicationContext` и `create_application_context`
  загружаются лениво, а CLI seed снова стартует в чистом Python-процессе;
- карточка оборудования передаёт в форму расхода фактический остаток и единицу
  измерения; значение `не число undefined` больше не отображается;
- кнопка закрытия карточки оборудования закрывает modal мышью и очищает
  `history.state.card`, поэтому Back/Forward не восстанавливает уже закрытую
  карточку;
- Solar наследует `demo`-контур основного Warehouse runtime: тестовый launcher
  показывает оба защитных баннера и не принимает demo за production;
- macOS/Windows test launchers теперь создают и явно подключают три
  изолированные БД: demo IXcellerate, пустой Solar и пустой Vacations. Добавлен
  fail-closed builder `scripts/create_clean_vacations_test_db.py`;
- clean Warehouse builder удаляет candidate-only migration tables в корректном
  FK-порядке до promoted receipts/issues и поэтому работает на полном
  историческом контуре, не оставляя пустой marker повреждённого candidate;
- добавлены fresh-process CLI, Vacations builder, launcher/site/UI regression
  tests и расширен headless Chrome сценарий. Текущий полный набор — 635 тестов
  (`skipped=8`), headless Chrome smoke — PASS на macOS.

## ODE 0.19.0 — documentation alignment (2026-07-27)

Релиз без изменений runtime-кода. Единственная правка вне документации —
`inventory.__version__`. Вся функциональность унаследована от 0.18.1.

Причина релиза: после Multi-Warehouse (0.17.0), Vacations (0.18.0) и multi-DB
backup (0.18.1) три корневых документа продолжали описывать более ранний
контур и вводили в заблуждение и людей, и AI-агентов:

- `CLAUDE.md` описывал контур 0.16.0 и утверждал, что `data/warehouse.db` —
  «единственный активный продуктовый контур»: ни Solar, ни Vacations, ни
  multi-DB backup в нём не упоминались;
- `ARCHITECTURE.md` открывался разделом «ODE 0.14 initial-inventory boundary»
  и описывал одну runtime-БД;
- `ITOG.md` был озаглавлен «главная техническая документация ODE 0.16.0» и
  приводил устаревшее число тестов.

Что сделано:

- `CLAUDE.md`, `ARCHITECTURE.md` и `ITOG.md` приведены к фактическому контуру:
  три независимые runtime-БД, шесть публичных фасадов, `inventory/routes` и
  `inventory/templates`, `RuntimeDatabaseRegistry` и
  `MultiDatabaseBackupService`, fail-closed restore до ADR-013 и отсутствие
  сторнирующих операций до ADR-014;
- `AGENTS.md` дополнен разделом multi-DB backup и синхронизирован с
  `CLAUDE.md`, чтобы два набора правил не расходились;
- число автоматических тестов приведено к фактическим 628 везде, где оно
  упоминалось (`594`, `598`, «619» и незаполненное значение заменены);
- версия поднята до `0.19.0`, обновлены версионные указатели в `README.md`,
  `docs/README.md`, `docs/API_REFERENCE.md`, `docs/CODEBASE_GRAPH.md` и
  `docs/project/CURRENT_STATE.md`;
- добавлен `RELEASE_REPORT_ODE_0_19_0.md`; датированные отчёты 0.18.1 и
  раньше сохранены без изменений.

Датированные исторические отчёты, ADR и manual QA предыдущих версий не
переписывались.

## ODE 0.18.1 — stabilization and multi-DB backup slice (2026-07-27)

- Administration получил `RuntimeDatabaseRegistry` для трёх независимых
  файлов: IXcellerate, Solar и Vacations; registry описывает путь/профиль
  схемы и не владеет бизнес-таблицами.
- Новый профильный `MultiDatabaseBackupService` показывает read-only health и
  создаёт проверенные SQLite snapshots во внешнем каталоге: Backup API,
  integrity/FK/schema, SHA-256 manifest, atomic rename и Administration audit.
- UI больше не предлагает небезопасный частичный restore/upload: полный
  restore отложен до preview-token, cross-database guards, safety backup и
  атомарной публикации, описанных в ADR-013.
- длинные Windows-пути runtime-БД сохраняют читаемую ширину в прокручиваемой
  таблице и не сжимают соседние Administration-карточки.
- duplicate ФИО в Vacations по-прежнему возвращает HTTP 409, но больше не
  раскрывает внутренний текст SQLite `UNIQUE constraint`.
- генератор code graph использует POSIX repository paths на всех ОС; устранён
  ложный stale-result при проверке одного артефакта на Windows и Linux.
- добавлены regression-тесты трёх backup-профилей, read-only status, внешнего
  storage, ролей, alias guards, отключённого restore, friendly Vacations 409 и
  кроссплатформенной детерминированности графа и layout длинных DB-путей.

## ODE 0.18.0 — Vacations and UX stabilization (2026-07-27)

- добавлен общий для IXcellerate/Solar модуль `Отпуска`: календарь,
  список заявок, effective-dated справочник площадок/графиков и отдельная
  очередь конфликтов;
- зафиксирован цикл `1/3` от 26.07.2026, правила подменного,
  непересечение начальника/старших и обязательное покрытие дежурной смены;
- свежая Vacations DB не содержит данных компании; сотрудники и их начальные
  назначения создаются через отдельные UI/API/facade-компоненты;
- конфликт сохраняется как `Ожидает решения`; кнопки `Подтвердить исключение`
  и `Отклонить отпуск` работают с inline-комментарием без системных
  `confirm/prompt`, решение и автор пишутся в историю/audit;
- `vacation_*` и собственный `vacation_audit_log` физически вынесены в
  `data/vacations.db`; обычный запуск создаёт её отдельно, а
  `warehouse.db`/`warehouse_solar.db` не мигрируются и не содержат таблиц
  отпусков;
- складской интерфейс использует единый словарь операций: `Приход / принять`
  и `Расход / списать`; устаревшие пользовательские подписи
  `Выдать / Выдано` удалены из обзора и быстрых действий;
- способы прихода и расхода названы симметрично, а headless smoke проверяет
  точные подписи карточек и не допускает возврат смешанной терминологии;
- общий загрузчик UI больше не падает при переключении IXcellerate/Solar,
  если в уже открытой вкладке отсутствует устаревший необязательный select:
  обновление таких элементов выполняется null-safe, а headless smoke
  воспроизводит удаление legacy-контрола перед сменой склада;
- переключатель склада показывается только внутри Warehouse и больше не
  создаёт ложную связь самостоятельного модуля `Отпуска` с выбранной
  площадкой склада;
- CSS и JavaScript подключаются с версией продукта в URL: браузер не смешивает
  новый HTML со старыми закэшированными runtime-файлами после обновления;
- полный regression gate: 620 тестов (`skipped=8`), headless Chrome со
  вкладкой отпусков, module/frontend/data audits и clean-DB dry-run — PASS;
  code graph обновлён до 243 узлов / 494 связей, внешний Codebase Memory —
  до 7 067 узлов / 30 991 ребра; рабочие базы IXcellerate/Solar остались
  byte-identical.

## ODE 0.17.0 — Multi-Warehouse IXcellerate/Solar (2026-07-26)

- раздел `Склад` теперь открывается через явный выбор `IXcellerate` или
  `Solar`; выбранный склад хранится отдельно в каждой HTTP-сессии;
- существующая `data/warehouse.db` остаётся IXcellerate и общим application
  contour, а Solar использует ignored `data/warehouse_solar.db`;
- первый Solar bootstrap атомарно создаёт пустой operational Warehouse и
  переносит только одноразовый снимок legacy/v2 справочников IXcellerate;
  повторный startup не синхронизирует и не перезаписывает Solar;
- Warehouse reads, exports, imports, previews, mutations, posting policy,
  lock, audit, Full Inventory state и browser drafts изолированы по выбранной
  БД; авторизация, Reports, Monitoring и Knowledge остаются общими;
- добавлены `/api/warehouses`, `POST /api/warehouse/select`,
  `warehouse_site` в `/api/data`, UI-переключатель и isolation/bootstrap tests;
- рабочая `data/warehouse.db` не менялась; все mutation tests выполняются на
  disposable БД;
- полный gate содержит 598 тестов (`skipped=8`), headless Chrome smoke и
  module/frontend/data audits; file/import graph обновлён до 221 узла и
  455 связей, внешний Codebase Memory — до 6 949 узлов / 29 294 ребра.

## ODE 0.16.0 — modular extraction (2026-07-25)

### Verification and documentation follow-up (2026-07-26)

- upstream `main` fast-forwarded through all four 0.16.0 extraction commits
  only after a clean tree/data audit and a separate worktree gate on an exact
  copy of the current Warehouse database;
- schema/ownership remain unchanged; the working `data/warehouse.db` stayed
  byte-identical with SHA-256
  `8681f3c34c52d12e665ddae9f9f818a7635c1108aee353baa9fc63830955305b`;
- 593 upstream tests and headless Chrome smoke passed on the copied database;
  the local graph-version contract raises the current suite to 594 tests;
- current-state, repository map, documentation index, Codebase Memory snapshot,
  SVG and interactive code graph are synchronized with the extracted
  routes/templates and domain boundaries;
- `scripts/refresh_project_knowledge.py` is the single post-change command for
  committed graph regeneration and external Codebase Memory full reindex with
  `persistence=false`.
- headless Chrome polling now tolerates the short interval in which navigation
  has replaced the document but the new classic scripts are not yet defined;
  a persistent predicate error is still reported with its last exception.
- GitHub documentation now embeds a high-resolution PNG snapshot of the
  interactive ODE 0.16.0 file/import graph and links both PNG and HTML paths.

### Stage 4 — Web routes and templates

- `inventory/webapp.py` сокращён с 2415 до 921 строки и оставлен HTTP-shell:
  запуск сервера, auth/session middleware, общая валидация запросов, security
  headers и сериализация ответов;
- HTTP-логика физически разделена на
  `inventory/routes/{administration,reports,warehouse,monitoring,knowledge}.py`;
  общий неизменный `/api/action` делегирует действия профильным route-модулям;
- сборка `LOGIN_HTML` и `HTML` перенесена в
  `inventory/templates/webapp.py`; контрольные SHA-256 итоговых страниц
  совпадают с baseline до переноса;
- CSV presentation-контракты и защита от spreadsheet formula injection
  перенесены в `inventory/routes/csv.py` с сохранением старых импортов из
  `inventory.webapp`;
- module/frontend audits и source-contract тесты учитывают новую топологию;
  добавлен отдельный Stage 4 extraction contract;
- после каждого доменного переноса пройден headless Chrome smoke на временной
  копии БД; URL, JSON/CSV-контракты, подписи и порядок JavaScript не менялись.

### Stage 3 — Warehouse

- `WarehouseCore` сокращён с 3310 строк бизнес-логики до thin compatibility
  adapter без SQL; оставшиеся складские реализации физически перенесены в
  `inventory/warehouse/`;
- история, legacy equipment/operations, баланс/поиск/карточка, контроль
  качества и runtime-справочники разделены на
  `WarehouseHistoryService`, `LegacyInventoryService`,
  `WarehouseBalanceService`, `WarehouseMonitoringService` и
  `WarehouseReferenceService`;
- старые receipt/issue/delivery методы больше не имеют второй реализации:
  `WarehouseService` и `WarehouseFacade` используют общие экземпляры
  `ReceiptWriteService`, `IssueWriteService`, `CableService`,
  `DeliveryImportService`, `DeliveryReadService` и
  `DeliveryAcceptanceService`;
- прежние string-dispatch adapters для balance/history/inventory/monitoring/
  references заменены import aliases к реальным Warehouse-сервисам;
- сохранена совместимость публичных методов `WarehouseService`, включая
  legacy equipment/operations, preview/confirm и CSV export; схема SQLite и
  ownership таблиц не менялись;
- кабельная совместимость сохраняет учет целых штук и допускает дробный
  метраж для непоштучных единиц;
- добавлены Stage 3 architecture contracts и расширен module-boundary audit;
  полный discover-набор: **589 tests, OK (`skipped=15`)**.

### Stage 2 — Reports

- work logs, daily/weekly report assembly, uploaded daily reports, preview/
  confirm imports and work-log CSV export now have one implementation under
  `inventory/reports/`;
- `WarehouseService` composes one `ReportsFacade` with the Administration actor
  provider and one Warehouse-owned `WarehouseEventReader`;
  `ApplicationContext.reports` reuses that same instance;
- the obsolete `inventory/services/report_service.py` adapter was removed;
  compatibility methods in `WarehouseCore` and `WarehouseService` remain only
  as explicitly deprecated delegates;
- Reports-owned SQL for `work_logs`, `daily_report_uploads` and
  `daily_report_rows` is absent from `WarehouseCore`; the module audit enforces
  this boundary;
- full-day report filtering preserves timestamped rows through `23:59:59`;
  Warehouse event reads use the same inclusive day semantics;
- full discover suite: **584 tests, OK (`skipped=15`)**.

### Stage 1 — Administration

- пользователи, authentication/actor context, роли, аудит, диагностика,
  backup/restore и безопасная замена рабочей SQLite вынесены из
  `WarehouseCore` в `inventory/administration/`;
- `ApplicationContext.administration` теперь получает отдельный
  `AdministrationService`, а не общий `WarehouseService`;
- login, admin actions, session actor context и startup database check в
  `webapp.py` идут через `context.administration`;
- старые методы `WarehouseCore` и `WarehouseService` сохранены как явно
  помеченные `DEPRECATED` thin delegates; они используют тот же actor context и
  audit adapter, поэтому совместимость CLI и ещё не перенесённых модулей
  сохранена без второй реализации;
- схема БД и ownership таблиц не менялись; backup/restore/upload по-прежнему
  требуют admin role и явного подтверждения;
- добавлены архитектурные контракты физического отделения Administration;
  полный discover-набор: **579 tests, OK (`skipped=15`)**.

## ODE 0.15.0 warehouse history/export stabilization (2026-07-25)

- добавлен обязательный `scripts/audit_repository_data.py`: Git index не
  принимает runtime SQLite, monitoring/company JSON, backup/export/release/
  migration artifacts, Excel/CSV/ZIP и замаскированный SQLite; новый clone
  стартует без `data/warehouse.db`, а первый запуск создаёт пустые
  операционные таблицы;
- экран `Расход` получил постоянный блок последних 20 операций по аналогии с
  приходом; для каждой строки видны списанная позиция, задача, статус и целевая
  железка (название, модель, инв. №, S/N и hostname);
- расход переведён на единый operation-level read-model: один `stock_issues`
  всегда даёт одну строку UI/экспорта, даже если кабель распределён по
  нескольким FIFO-партиям; unmatched problem rows больше не теряются;
- кнопки полной истории явно подписаны `Выгрузить все приходы/расходы` и
  доступны вне import-сценария; прежние ссылки current-preview без Preview
  убраны из UI; пустой CSV сохраняет заголовки;
- пользовательское название `Остатки` заменено на `Баланс` в web UI, CLI и
  действующих инструкциях;
- read-only full-volume QA: 50 019 приходов / 18 798 расходов, CSV 10,8 / 5,1
  МБ, формирование 1,64 секунды; полный gate — 574 test (`skipped=8`),
  headless E2E, module/frontend audits PASS.

## ODE 0.15.0 balance-tree gate follow-up (2026-07-24)

- утверждён текущий ленивый экран остатков
  `категория → тип → вендор → модель`: сохранены независимое раскрытие ветвей,
  server-side поиск по всей базе, автоматическое раскрытие результата до
  50 позиций, cache и постраничная загрузка по 100 групп;
- headless Chrome E2E больше не ожидает удалённые построчные кнопки старой
  таблицы и проверяет нулевой/положительный остаток, четыре уровня дерева,
  сворачивание/повторное раскрытие и export query;
- frontend-contract audit получил документированный allowlist динамических
  controls группового выбора строк поставки;
- актуальный gate: 566 tests (`skipped=8`), оба audit-скрипта, headless E2E,
  clean-DB dry-run, code graph 205 узлов / 368 связей и `git diff --check` —
  PASS.

## ODE 0.15.0 release candidate (2026-07-19)

Предрелизная стабилизация: контроль качества данных стал рабочим инструментом
исправлений, сняты блокировки редактирования исторических карточек, исправлены
две несовместимости с Python 3.10, выполнен визуальный рефреш интерфейса.

### Контроль качества данных (экран «Проблемы»)

- «Неполные строки» показывают все колонки карточки (дата, S/N, наименование,
  инв. №, проект, полка, вендор, модель, количество); пустые поля заполняются
  прямо в таблице и сохраняются построчно. Fill-empty-only: уже заполненные
  значения никогда не перезаписываются, конфликт возвращается пользователю без
  применения. Новый audit-код `RECEIPT_FIELDS_FILLED`;
- пустая дата прихода исторической карточки заполняется вручную с валидацией
  формата (`ГГГГ-ММ-ДД`/`ДД.ММ.ГГГГ`/`ДД/ММ/ГГГГ`), нормализацией в ISO и
  отдельным audit-кодом `RECEIPT_DATE_FILLED` с пометкой `manual: true`;
  доказанная (заполненная) дата никогда не перезаписывается;
- «Дубли S/N» показывают полные строки обеих карточек группы (а не только
  serial+count): дата, наименование, вендор, модель, инв. №, количество;
  сохранена исходная семантика счётчика (число групп дублей);
- исправление дубля: новый S/N проверяется на непустоту, отличие от текущего и
  уникальность (`COLLATE NOCASE`) и записывается с audit-кодом
  `RECEIPT_SERIAL_CORRECTED` (старое значение сохраняется в аудите);
- удаление лишней дублирующей карточки с подтверждением в UI. Fail-closed
  защита: удалить можно только карточку, у которой остаётся вторая с тем же
  S/N; удаление блокируется при наличии списаний, связи с поставкой или
  миграционного provenance. Полный снимок удаляемой строки сохраняется в
  audit-коде `RECEIPT_DELETED`;
- все операции идут по существующему пути `web/API → WarehouseFacade →
  ReceiptWriteService → ReceiptRepository` с ролевой проверкой
  (`viewer` — read-only) и посадочным guard'ом; новые действия API:
  `FILL_RECEIPT_FIELDS`, `FILL_RECEIPT_DATE`, `CORRECT_DUPLICATE_SERIAL`,
  `DELETE_DUPLICATE_RECEIPT`.

### Редактирование карточки оборудования

- сняты жёсткие требования обязательности описательных полей («Поставщик»,
  «Объект», «ЦОД», «Единица») при редактировании карточки: у 99% исторических
  карточек «Объект» пуст, и прежнее требование блокировало любое сохранение.
  Обязательными остаются наименование и ровно один тип; проверка типа по
  активному справочнику сохранена.

### Совместимость с Python 3.10

- `ode/infrastructure/database.py`: снятие SQLite-авторизатора выполнялось
  через `set_authorizer(None)`, что поддерживается только с Python 3.11; на
  3.10 это превращалось в deny-all и COMMIT/ROLLBACK падали с «not
  authorized» (все 43 падения `tests/ode013` на 3.10). Заменено на
  разрешающий колбэк, работающий на всех версиях;
- (ранее в этой линии) `inventory/warehouse/baseline/models.py`: shim для
  `enum.StrEnum`.

### Интерфейс

- обзор склада: ряд операционных KPI (принято/выдано сегодня, изменение за
  смену, проблемные списания, активные поставки) — плитки кликабельны и ведут
  в соответствующие разделы; лента последних операций;
- удалён устаревший поясняющий текст про пересчёт баланса от baseline;
- счётчик вкладки «Кабели» показывает суммарное количество кабеля, а не число
  строк;
- убраны серые подписи на карточках сценариев расхода; исправлен значок
  поиска; обновлена палитра/типографика (радиусы, фокус-состояния, тени);
- Timeline: русские подписи для новых audit-кодов;
- убран дублирующий сценарий расхода: «Списать сканером» теперь
  является единой точкой входа для режимов «на одно оборудование» и
  «пары: компонент → оборудование»;
- обзор отделяет реальные блокеры учёта от исторических данных для
  уточнения; лента не выдаёт системные начальные остатки за операции и
  показывает бизнес-дату прихода/расхода вместо даты технической миграции;
  если бизнес-дата в истории отсутствует, UI так и сообщает; большие
  таблицы проблем показываются по одной группе с постраничной навигацией;
- формы прихода больше не создают пустой черновик при обычном переходе
  на экран, а модели в мастере ограничены выбранным вендором и типом;
- инженерский редактор справочников сокращён до операционных полей, а FULL
  Inventory получил ясную русскую последовательность от XLSX до будущей
  контролируемой активации;
- FULL Inventory XLSX стал scan-first: S/N находится в первой колонке, добавлены
  русская инструкция, категории/типы, активные полки, Excel dropdowns и
  исчерпывающая номенклатура всей Warehouse history. Все подсказки
  строятся read-only при скачивании и не меняют working DB.
- тяжёлые таблицы остатков, справочников и складской истории теперь
  отрисовываются только при открытии соответствующей вкладки; главная на
  проверенной рабочей копии сократилась примерно с 7,2 тыс. до 2,4 тыс. DOM-
  элементов без потери данных, а остатки продолжают догружаться блоками по 500;
- карточки прихода/расхода получили единый набор SVG-иконок, на стартовом
  экране расхода больше не видны формы невыбранных сценариев, а открытие нового
  раздела или вкладки всегда возвращает страницу к началу (включая mobile UI).

### Инфраструктура и релиз

- версия `0.15.0` задаётся только в `inventory/__init__.py`;
  `build_windows_package.py` теперь выводит имена пакетов из `__version__`
  (устранено дублирование захардкоженных имён);
- README реструктурирован для GitHub: титульная страница с возможностями,
  быстрым стартом, политикой данных (рабочая БД с серийниками и
  `data/monitoring/*.json` не коммитятся) и секцией для разработчиков;
  история этапов перенесена в `docs/STAGES_HISTORY.md` без изменений;
- новая документация: `ITOG.md` (главный технический документ для будущих
  патчей: как работает код, входы/выходы, инварианты, карта всей
  документации), `docs/API_REFERENCE.md` (полный справочник HTTP API),
  `docs/CODE_INVENTORY_0_15_0.md` (опись каждого исполняемого файла +
  трассировка Monitoring/Reports от main), `docs/DATA_QUALITY_OPERATIONS.md`
  (контракт операций контроля качества данных);
- интерактивный офлайн-граф связей кодовой базы
  `docs/assets/code_graph.html` (203 узла / 364 связи) и его генератор
  `scripts/generate_code_graph.py`; добавлен `--check`, который завершает
  release gate ошибкой при отсутствующем или устаревшем HTML;
- bootstrap compatibility runtime больше не печатает известные начальные
  учётные данные администратора в application/CI logs; отдельный regression-
  тест фиксирует запрет вывода credentials;
- 24 исторических отчёта версий 0.12–0.14 перенесены из корня в
  `docs/history/`; устаревшие diagram-доки и `FRONTEND_REFACTOR_PLAN.md`
  перенесены туда же; ссылки и Windows-сборщик обновлены;
- полный discover: **539 тестов, все зелёные** (включая новые UX/API/security-контракты),
  оба audit-скрипта
  и `git diff --check` — OK.

## ODE 0.14.0 integrated presentation candidate (2026-07-18)

- исправлена критическая несовместимость с Python 3.10: `SystemState` и
  `SessionStatus` (`inventory/warehouse/baseline/models.py`) использовали
  `enum.StrEnum`, доступный только с Python 3.11, хотя README заявляет
  «Python 3.10 или новее». На 3.10 это ломало импорт `inventory.core` и
  `inventory.webapp` целиком, то есть `python3 app.py` не запускался. Добавлен
  совместимый shim `class StrEnum(str, Enum)` с эквивалентным поведением
  `.value`/`str()`; полный набор тестов (456 тестов) и оба audit-скрипта
  перепройдены на исправленной версии — OK;
- Warehouse переведён из pre-baseline read-only в рабочий provisional-режим:
  production receipt/issue/scanner/delivery writes разрешены, неизвестная
  конфигурация и demo на рабочей БД остаются fail-closed;
- обзор склада показывает текущий расчётный остаток и marker
  `PROVISIONAL_HISTORICAL`; `authoritative=false` и
  `baseline_timestamp=null` сохраняются до утверждённой FULL inventory;
- FULL Inventory Preview продолжает работать внешне и не меняет рабочую БД;
  будущая activation должна заменить provisional-остаток initial baseline,
  а не прибавить инвентаризационные строки к историческим движениям;
- добавлен рабочий ручной Monitoring flow: hostname/problem validation,
  опциональный Edge/Selenium DCIM collector, ping/classification, безопасная
  hostname routing, Rooms/email preview и локальная история без автоотправки;
- добавлена Knowledge Base с категориями, поиском, тегами, пагинацией,
  безопасным Markdown, create/edit/soft-delete, private attachments и
  server-side ролями `viewer`/`engineer`/`admin`;
- добавлены идемпотентные runtime-таблицы Knowledge и миграционный скрипт;
- восстановлены byte-exact LF для утверждённых DDL checksums и исправлен
  Windows `fsync` для candidate/test database публикации;
- добавлены конфигурация, документация, API/frontend/security/migration tests;
  локальные routing rules, Edge profile, cookies, БД и вложения не публикуются.
- интегрирован отдельный Reports changeset: УВР с CRUD/фильтрами, CSV/XLSX
  import/export, отчёты за смену и неделю; Reports читает складские события
  только через `WarehouseEventReader`;
- устранено дублирование Reports JavaScript в монолитном `ui.js`; рабочие
  сценарии вынесены в `static/js/reports/*`, а Reports subnavigation снова
  доступна оператору;
- normal startup promoted historical DB снова byte-stable: установка новых
  Reports/Knowledge таблиц выполняется только явным backup-guarded скриптом
  `scripts/migrate_runtime_modules.py`;
- headless Chrome проходит Warehouse receipt/issue/scanner/balance/history,
  Monitoring, Knowledge, УВР/сменный отчёт, Profile и Administration без
  browser/resource/HTTP/API500 ошибок;
- на Главную GitHub добавлена поддерживаемая SVG/Mermaid карта связей; локальный
  Codebase Memory index, internal JSON, runtime DB и вложения не коммитятся.

## ODE 0.14.0 — Full Inventory safety workflow and baseline rehearsal

- добавлен первый изолированный Monitoring capability: fail-closed
  Salt/Digital/X5Tech routing по hostname, безопасная подготовка To/CC/темы и
  публичный `MonitoringFacade`; UI, collectors и отправка писем не включены;
- offline генератор Tech/Digital rules переведён с отсутствующего `openpyxl`
  на standard-library OOXML reader ODE, исправлено повреждение завершающего
  дефиса в hostname pattern, JSON пишется атомарно;
- внутренние hostname/recipient JSON установлены только локально и исключены
  из публичного Git; GitHub получает код, тесты, контракты и Mermaid-карту
  архитектурных связей без company infrastructure data;

- рабочий Warehouse переведён в fail-closed состояние `NOT_INITIALIZED`:
  импортированные receipts/issues остаются доступной историей, но рассчитанный
  по ним остаток явно помечен как исторический и не считается физическим;
- реальные receipt/issue/scanner/delivery/inventory-number mutations блокируются
  на backend и CLI стабильной ошибкой `WAREHOUSE_NOT_INITIALIZED`; тестовые
  операции разрешены только в явно настроенном disposable demo contour;
- добавлен внешний FULL Inventory workspace: строгий text-only XLSX template,
  безопасный OOXML parser, provenance/source SHA, reference fingerprint,
  paginated Preview rows/findings и неизменяемая activity history;
- реализованы durable append-only manual resolutions, actor/reason/timestamp,
  explicit supersede для конфликтов и deterministic revalidation; raw Excel
  остаётся неизменным, corrected value хранится отдельно, старые Preview runs
  сохраняются, а digest учитывает effective resolution set;
- добавлен isolated `baseline_rehearsal/` contour: admin может собрать
  отдельную ODE target DB по approved V001..V008, создать import commit,
  approved snapshot и balance projection и доказать их равенство. Candidate
  никогда не заменяет рабочую БД, а `publish_available=false`;
- Catalog/Equipment automatic matching не выполняется: каждая включённая
  строка требует явного `CHOOSE_CATALOG_ITEM`, serialized row — отдельного
  equipment resolution; `LINK_EXISTING_EQUIPMENT` закрыт до Query Port;
- Preview performance: 1 000 строк — 0.13 s, 10 000 — 1.28 s, 50 000 —
  6.70 s на текущем MacBook; прогоны использовали temporary DB, исходная
  fixture DB осталась byte-identical;
- post-release hardening перевёл Inventory rows с materialized tuple на
  повторно открываемый streaming reader; независимый Preview worker теперь
  обрабатывает 50 000 строк за 6.45 s при peak RSS около 69 MiB;
- stale/double-submit операции защищены `BEGIN IMMEDIATE` и повторной проверкой
  active session/run; отмена во время Preview fail-closed, UI-кнопки работают
  single-flight;
- существующий source-vault object теперь повторно проверяется по SHA-256, а
  candidate path и cold import защищены от symlink/circular-import edge cases;
- runtime metadata синхронизирована на `0.14.0`; Windows builder больше не
  включает `data/warehouse.db`, runtime/candidate DB или credentials. Новый
  Windows ZIP этой работой не создавался.

## Warehouse Stabilization Reconciliation — 2026-07-15

- устранены `ResourceWarning: unclosed database` полного regression gate:
  семь raw SQLite test handles теперь используют явный `contextlib.closing`
  при сохранении прежней commit/rollback семантики;
- полный `unittest discover` вырос до 392 тестов и проходит под
  `-W error::ResourceWarning` без SQLite ResourceWarning;
- Python/JavaScript syntax, module/frontend audits и `git diff --check`
  проходят;
- ordinary headless Chrome smoke на временной byte-copy рабочей БД проходит
  receipt/issue/balance/history/search/profile/administration и Inventory
  Number workflow без console/window/resource/HTTP/API500 errors;
- создан `docs/project/` как единый current-state hub; Warehouse source Stage
  отделён от Target/Platform ODE delivery Stage без переписывания исторических
  review/DDL evidence;
- подготовлены отдельные focused prompts для независимого Warehouse review и
  двухфазного repository cleanup audit; массовое удаление/`git clean` без
  утверждённого hash manifest запрещено;
- независимый Warehouse review завершён со статусом `PASS`; Phase 1 cleanup
  audit не нашла кандидатов на удаление исходного кода и отделила безопасную
  локальную гигиену от evidence/archive решений владельца;
- выполнена минимальная безопасная Phase 2 cleanup: удалены только
  регенерируемые `__pycache__` вне защищённых artifact-контуров, а 20
  исторических корневых QA/release/review документов добавлены в единый
  documentation index;
- после прямого owner approval удалены byte-identical test ZIP, распакованный
  дубль canonical RC1, disposable migration workspace DB/output и Platform
  dev DB; локальная stabilization DB удалена только после `cmp` с целостным
  внешним SQLite backup. Raw/provenance/reports, canonical RC1 ZIP и активная
  рабочая БД сохранены; working tree уменьшен примерно с 2.2 GiB до 711 MiB;
- post-cleanup regression повторно проходит 392 tests с восемью ожидаемыми
  skip только для отсутствующих ignored full/pilot candidate DB; module/
  frontend audits и clean-test-DB dry-run проходят;
- `data/warehouse.db` не изменялась: финальный SHA-256
  `73568a1c3eecbd4476473f064620d7f0a196b336ce8ea6d834c5b99359d4b010`,
  `integrity_check=ok`, FK violations и sidecars отсутствуют.

## ODE Warehouse Final Stabilization Pass — 2026-07-14

- исправлен ложный «проблемы» KPI на Главной/Мониторинге: `incomplete_rows`
  считал опциональное поле `project` обязательным, из-за чего после промоушна
  исторических карточек счетчик показывал 50160 «проблем» из 50001 карточки
  (100% данных, не имеющих смысла); теперь считаются только реально
  обязательные для формы поля (`shelf`, `vendor`, `model`);
- удалён подтвержденно мёртвый код `inventory/webapp.py`: константы
  `UX_SCRIPT`, `WIZARD_SCRIPT`, `DELIVERY_JS` (149 строк) никогда не достигали
  браузера (`_externalized_html()` вырезает инлайновые `<script>`/`<style>`) и
  дублировали устаревшей версией то, что реально исполняет `static/js/ui.js`;
  среди прочего убрал видимость hardcoded vendor/model списков, которые на
  деле никогда не рендерились;
- удалены неиспользуемые `renderWizard`/`renderHeader`/`renderSidebar` из
  `static/js/components.js` (0 вызовов в кодовой базе);
- Главная: карточки `Monitoring`/`Reports` переименованы в `Мониторинг`/
  `Отчеты` для согласованности с остальным русскоязычным интерфейсом;
- Главная: добавлена полноценная карточка `Профиль` в `.portal-grid` (рядом с
  `Мониторинг`); top bar `.profile-actions` больше не дублирует вход в
  профиль/смену пароля отдельными кнопками — `openShiftProfile()` остаётся
  единственной role-aware точкой входа; `.portal-grid` переведена на 3 колонки,
  чтобы 5–6 карточек не оставляли одинокую карточку на отдельной строке;
- исправлена доказанная стороннняя regression этой же сессии: удаление
  `renderToast` затронуло `static/js/components/notifications.js`
  (`ReferenceError` на каждой загрузке страницы) — функция восстановлена,
  проверено headless smoke;
- исправлено устаревшее утверждение в `CLAUDE.md`/
  `docs/REFERENCE_DATA_ARCHITECTURE.md`, что production `reference_values`
  «остаётся плоским и неизменным»: после promotion полного historical
  candidate `reference_domains_v2`/`reference_values_v2`/`reference_aliases_v2`
  реально заполнены (20 доменов, 931 значение) и являются live источником
  `ReferenceDataService` для форм UI;
- найдено, но НЕ исправлено (требует отдельного data-correction этапа с
  byte-copy/backup/provenance protocol): 291 карточка (0.58% от 50000
  промоутнутых) имеет `item_name = '#N/A'` — Excel-артефакт из исходника
  исторической миграции, не код-баг.

## ODE Warehouse Stabilization — 2026-07-14

- заменён runtime-источник dropdown на canonical `reference_*_v2`; добавлен
  permission-gated редактор с pending/deactivate/rename/merge preview/audit;
- active ЦОД ограничен `Ixcellerate`; shelf/supplier garbage исключён из форм
  без изменения исторических raw значений;
- vendors/models больше не hardcoded, модели ограничены выбранным вендором;
- возвращена компактная module-card навигация; Monitoring и Reports показывают
  только «В разработке»;
- убран отдельный UX «режима администратора», backend role checks сохранены;
- черновики прихода/расхода получили schema v3, user/DB isolation, TTL 14 дней
  и явный Continue/Start over/Delete;
- draft rows можно удалять по одной, выбранными или полностью до confirm;
- global search получил cancellation/stale-response protection, canonical name/
  source name/Part Number и быстрый exact-identifier short circuit;
- доказанный ручной test receipt exact S/N `1` удалён атомарно после двух
  внешних backup; создан audit `TEST_DATA_REMOVED_AFTER_MANUAL_REVIEW`.

## Local Full Warehouse Promotion and Runtime Simplification

Дата: 2026-07-14

- `data/warehouse.db` стала единственной обычной локальной рабочей БД ODE;
  full candidate опубликована через проверенную sibling `.next` и атомарный
  `os.replace`, а старая тестовая БД сохранена byte-copy и SQLite `.backup`
  вне репозитория;
- ordinary `python3 app.py` принимает promoted marker DB как рабочую, печатает
  путь/версию/число карточек/integrity и не включает read-only candidate landing;
- повторный startup уже инициализированной full-marker БД не продвигает
  `sqlite_sequence` no-op вставками и сохраняет SHA рабочей БД;
- dashboard и карточки используют существующий `WarehouseFacade` и актуальные
  `stock_receipts`/`stock_issues`/allocations; legacy 23-card source больше не
  формирует KPI;
- normal Equipment Card/Timeline скрывает migration-only события и показывает
  opening state понятным термином «Начальный остаток»; migration review сохранён
  только как административная диагностика;
- scanner draft получил schema version, TTL и scope по пользователю и
  fingerprint рабочей БД; несовместимый ODE draft старой тестовой БД безопасно
  удаляется, ошибки localStorage не ломают UI;
- browser/unit/contract проверки выполняются на временных копиях; candidate и
  raw не редактируются, DB/backup/reports не готовятся к commit;
- финальный gate: 309 unit tests, Python/JavaScript syntax, module/frontend
  audits, ordinary и admin-review headless Chrome smoke; browser/HTTP/API500
  error counters равны нулю, SQLite integrity/FK чисты;
- серверный deployment, Kafka, release ZIP, commit и push не выполнялись.

Процедуры эксплуатации и rollback:
`docs/LOCAL_WORKING_DATABASE_RUNBOOK.md`.

## Full Historical Warehouse Candidate Build (historical pre-promotion stage)

Дата: 2026-07-14

- весь staging прихода (51 003) и расхода (20 357) получил one-row/one-status
  reconciliation в отдельной disposable `warehouse_full_candidate.db`;
- S/N identity разделяет `TEXT_EXACT`, Decimal-expanded provisional numeric и
  corrupted quarantine; полка не входит в identity, `БАЛАНС` не используется;
- issue-only S/N получают explicit migration opening state, а source/target S/N,
  conflicts, duplicates, warnings и provenance не теряются;
- candidate строится атомарно из operationally-empty Stage A DB, сохраняет
  только security/system/reference/staging contour и не копирует test operations
  из `data/warehouse.db`;
- добавлены full XLSX/Markdown migration и cleanliness reports, marker-guarded
  read-only API/UI, Equipment Card/Timeline, macOS/Windows launchers и backend
  запрет Inventory Number для provisional numeric identity;
- focused candidate/contract tests и headless Chrome smoke подтверждают marker,
  exact/leading-zero/numeric/opening behavior, clean contour, unchanged DB SHA,
  нулевые browser/API errors и отсутствие SQLite sidecars;
- production replacement, release ZIP, commit/push и server deployment не
  выполнялись. Подробности: `docs/FULL_WAREHOUSE_MIGRATION.md`.

## ODE 0.13, Stage 0.13.3A.5 — Preservation-Aware Pilot Migration Review

Дата: 2026-07-14

### Новые возможности

- добавлен отдельный pilot-only путь исторического прихода, который сохраняет
  `source_serial_value` символ в символ и использует
  `normalized_match_value` только для группировки/поиска;
- детерминированный selector с seed
  `ODE-0.13.3A.5-PILOT-v1` выбирает ровно 200 реальных receipt staging rows и
  сохраняет причину включения каждой строки;
- фиксированное распределение решений: 130 `IMPORT`, 10 `QUARANTINE`,
  7 `MANUAL_REVIEW`, 6 `EXACT_DUPLICATE`, 35
  `CONFLICT_HISTORY_ONLY`, 10 `QUANTITY_POSITION_DEFERRED` и 2
  `SOURCE_CORRUPTED_REJECTED`;
- source-safe exact duplicate ограничен шестью группами: только у них literal
  raw-equivalent row имеет primary с доказанной датой и безопасными
  reference/alias решениями; седьмая группа заблокирована pending supplier
  alias. Остальное duplicate coverage состоит из 26 identity-conflict groups и
  9 date/shelf/order history-variation groups;
- создаётся отдельная ignored DB
  `migration_inputs/workspace/warehouse_pilot_candidate.db`; исходная
  Stage 0.13.3A candidate и `data/warehouse.db` не перезаписываются;
- selection публикуется в локальных ignored
  `PILOT_RECEIPT_SELECTION.xlsx`/`.md`; identifier-поля XLSX сохраняются как
  text и проходят round-trip check.

### S/N, identity и canonical naming

- migration writer обходит опасный обычный `strip().upper()` validator, но
  переиспользует `ReceiptRepository`, caller-owned transaction, audit и
  Equipment Card Timeline;
- карточки создаются только для сохранных `TEXT_EXACT` rows с quantity `1`,
  доказанной source date и решением `IMPORT`; numeric/unproven и
  `SOURCE_CORRUPTED` никогда не создают карточку;
- одна normalized identity создаёт не более одной pilot card; exact duplicates
  и конфликтующие source rows сохраняются как provenance/history;
- shelf остаётся необязательным placement attribute, не входит в identity и не
  дробит serialized balance;
- Stage 0.13.3A references/aliases и canonical-name proposals переиспользуются
  без silent production reference creation; Huawei/xFusion и разные модели не
  объединяются;
- **FACT:** в фактическом source есть Vegman R220, но нет Vegman R200. Selector
  фиксирует `VEGMAN_R200_UNAVAILABLE_FROM_SOURCE` и не создаёт синтетическую
  source row; раздельность R200/R220 остаётся unit contract.

### Pilot DB, audit и Timeline

- pilot-only schema хранит marker, selection, одну identity на imported S/N,
  provenance, quarantine и performance metrics;
- pilot receipts помечаются `is_opening_balance=1`: они видны в pilot balance
  и Equipment Card, но не выдаются Reports как текущие receipt events;
- существующий `audit_log` используется для действий
  `MIGRATION_RECEIPT_IMPORTED`, `MIGRATION_SOURCE_ROW_LINKED`,
  `MIGRATION_CONFLICT_RECORDED`, `MIGRATION_EXACT_DUPLICATE_SKIPPED` и
  `MIGRATION_SERIAL_QUARANTINED`; второй event store не создаётся;
- Timeline отделяет исторический source date от времени миграции, показывает
  logical source file/sheet/row, source/canonical names и warnings; абсолютные
  локальные пути отфильтровываются.

### API, UI и безопасность

- marker-guarded review runtime требует `ODE_MIGRATION_PILOT=1`, точное имя DB,
  stage/status/read-only marker, обязательные таблицы, integrity/FK и отсутствие
  WAL/SHM/journal;
- после guard pilot startup отключает обычный schema initializer сервиса;
  production/default startup остаётся без изменений, а headless smoke проверяет
  неизменность SHA runtime-копии pilot DB;
- добавлены read-only `GET /api/migration-pilot` и pilot-вариант Equipment Card
  по `pilot_selection_id`; доступ разрешён только `admin`/`engineer`;
- pilot UI показывает permanent banner, selection, фильтры
  `IMPORT`/`QUARANTINE`/`CONFLICT`/`CORRUPTED` и migration section карточки;
  imported values рендерятся как text DOM nodes;
- все operational POST mutations в pilot mode запрещены backend; browser не
  получает raw XML, password hashes или абсолютные пути;
- безопасные macOS/Windows launcher'ы валидируют уже существующую pilot DB,
  ничего не пересобирают и никогда не подменяют production DB.

### БД и миграции

- production schema и `data/warehouse.db` не изменяются;
- Stage 0.13.3A candidate-only reference/staging schema сохраняется, а шесть
  `migration_pilot_*` tables существуют только в disposable pilot DB;
- лист `БАЛАНС`, исторический расход и оставшиеся receipt rows не импортируются;
- case-distinct S/N остаются несовместимы с текущим production
  `COLLATE NOCASE`; тяжёлая schema migration намеренно отложена до отдельного
  ADR/Stage.

### Тесты и документация

- добавлены selector/date/raw-source, exact writer/rollback, duplicate/conflict,
  marker/schema/security, read-only API/UI, launcher, identifier/XLSX round-trip
  и headless pilot scenarios;
- полный regression gate включает обычный UI smoke и отдельный pilot smoke на
  временной копии candidate DB; `unittest discover` проходит 292 теста с
  `-W error::ResourceWarning`;
- добавлены architecture, reviewer guide и manual QA; актуализированы S/N,
  reference, naming, staging, database ownership, security, API, events и
  Mermaid diagrams.

### Breaking changes

- для production runtime отсутствуют: обычный receipt/API/UI flow не меняет
  поведение, пока process не запущен с pilot flag и marker DB.

### Известные ограничения

- это 200-row review pilot, а не Stage 0.13.3B и не массовый import 51 003
  receipt rows;
- numeric S/N, corrupted values, quantity positions и unresolved references
  остаются вне складских карточек;
- реальный Vegman R200 отсутствует в источнике и не может быть проверен на
  source-driven pilot card;
- approval pilot review не разрешает production DB reset/replacement;
- окончательная case-sensitive production identity schema, reference approval
  authority и обработка исторического расхода остаются open decisions.

## ODE 0.13, Stage 0.13.3A — Reference Data Foundation, Canonical Naming and Migration Staging

Дата: 2026-07-14

### Новые возможности

- добавлен отдельный offline migration-слой для справочников,
  aliases, канонических наименований, точного извлечения S/N и
  migration staging;
- формализованы controlled domains для классификации объекта,
  оборудования, компонентов, кабелей, catalog data, поставщиков,
  локаций и операционных атрибутов;
- для aliases введены provenance, normalized source key, confidence,
  resolution status и поля ручного утверждения;
- каноническое имя строится детерминированно из типа, vendor,
  model/Part Number и основной характеристики; имя не является
  identity и может быть пересчитано;
- создаётся disposable candidate DB в ignored migration workspace с
  чистой актуальной production-схемой, candidate-справочниками и
  staging-таблицами только для review;
- проверенный candidate snapshot содержит 71 360 staging rows
  (51 003 receipt-source и 20 357 issue-source), 91 717 S/N-role cells,
  893 reference values, 916 aliases и 358 catalog proposals; все production
  operational tables пусты;
- добавлен validation/reporting CLI для проверки source SHA,
  identifier preservation, candidate schema, foreign keys и счётчиков.

### S/N preservation

- source S/N хранится отдельно от normalized match key; match key
  никогда не подменяет исходный identifier;
- XLSX extraction сохраняет файл/лист/строку/колонку, coordinate,
  cell type, number format, raw XML token, display/source value, warning,
  preservation status и source hash;
- numeric cells не проходят как безусловно безопасные: raw token
  анализируется без float, leading zeros могут быть восстановлены
  только при однозначном custom number format;
- все непустые numeric S/N требуют manual review и получают пустой
  match key; exponent token сохраняется буквально, а decimal display
  служит только подсказкой review;
- потерявшие точность длинные numeric identifiers отмечаются
  `SOURCE_CORRUPTED` и не допускаются к созданию ложной карточки;
- на фактическом warehouse source exact extractor нашёл четыре
  `SOURCE_CORRUPTED` cells: `ПРИХОД!L19513`, `ПРИХОД!L19580`,
  `РАСХОД!J4826`, `РАСХОД!J4866`; это два повторяющихся
  повреждённых значения, их match key пуст;
- CSV/XLSX preview пинит identifiers как text; round-trip тесты
  покрывают leading zeros, Unicode, internal spaces, long text, custom
  zero format и exponent notation.

### API, UI и безопасность

- HTTP endpoints, runtime UI и роли ODE не изменялись;
- будущий receipt UX с dependent references зафиксирован как
  `FUTURE STAGE`, а не как текущее поведение;
- candidate/staging tooling не принимает production DB как output,
  не печатает password hashes и не создаёт production references;
- команда `report` применяет тот же path/inode guard ко всем output,
  полностью регенерирует allowlisted JSON из candidate и никогда не
  доверяет/не объединяет содержимое старого report-файла;
- raw sources, reports, normalized previews, workspace DB и SQLite sidecars
  считаются local-only artifacts и не входят в commit/release ZIP.

### БД и миграция

- production schema `data/warehouse.db` не изменена; staging-таблицы
  не добавлены в `inventory/db.py`;
- текущая `reference_values(kind, name, is_active)` в runtime ODE не
  заменена; candidate-модель не считается production integration;
- исходный `БАЛАНС` не загружается и не считается источником
  операций;
- исторические receipt/issue rows не загружены ни в production,
  ни в операционные таблицы candidate DB;
- план будущего reset описывает byte-copy + SQLite backup,
  сохранение security identity, проверку candidate и отдельное
  явное подтверждение перед заменой рабочей БД; reset на этом Stage
  не выполнялся.

### Тесты и документация

- добавлены unit/integration тесты serial preservation, XLSX raw-cell
  extraction, identifier round-trip, reference normalization, alias safety,
  canonical naming, candidate DB, source/working-DB immutability и
  schema/security boundaries;
- focused migration suite содержит 39 тестов, включая regression cases для
  secret-bearing stale report и report path equal/hardlinked с source DB;
- актуализированы source review и основная архитектура; добавлены
  отдельные reference, naming, S/N, staging, reset и manual-testing
  contracts;
- полный gate после Stage проходит: 266 тестов (`OK` под
  `-W error::ResourceWarning`); baseline до Stage составлял 227 тестов.
- syntax и Node checks, module/frontend audits и clean-test-DB dry-run
  проходят; headless smoke посетил все маршруты, включая Inventory Number,
  и подтвердил ноль console/window/unhandled/resource/HTTP/API-500 errors;
- raw hashes и рабочая БД остались неизменными; рабочая SHA-256 —
  `eaab698c0bb8fd5de1ebd86a5999ee29d2a89e96b59e7fbaa171b0d38a26e8db`.

### Breaking changes

- отсутствуют: production API, UI, schema и warehouse behavior не
  изменены.

### Известные ограничения

- candidate package есть предложение для review, а не утверждённый
  production master-data set;
- semantic aliases, legal supplier/vendor variants, неоднозначные
  models и locations требуют ручного решения;
- повреждённые Excel numeric S/N нельзя восстановить без независимого
  authoritative источника;
- DCIM source остаётся пустым, Inventory Number source отсутствует;
- Stage 0.13.3B historical receipt migration требует отдельного
  review/approval и не запускается автоматически.

## ODE 0.13, Stage 0.13.3 — УВР (учет выполненных работ) и текстовые отчеты смены

Дата: 2026-07-14

- раздел `Отчеты` получил три рабочие вкладки: `УВР`, `Отчет за смену`,
  `Отчет за неделю`;
- в `work_logs` добавлена колонка `section` («Раздел») и служебный флаг
  `needs_review` для мигрированных строк, требующих проверки;
- вкладка `УВР` — реестр работ смены с сортировкой по столбцам, поиском по всем
  полям, фильтрами (период, статус, раздел), созданием, редактированием через
  модальное окно и удалением строк без перезагрузки страницы;
- «Имя задачи» вводится единым combobox с шаблонами (PNR-, Заказ, Outlook:,
  ROOMS, Zabbix и т.д.); шаблон без номера (ROOMS, Time, Zabbix) допустим,
  полностью анонимная запись отклоняется;
- `Отчет за смену` показывает таблицу выполненных работ за выбранную дату,
  `Отчет за неделю` — за период; обе вкладки используют те же столбцы, что и
  `УВР` (Дата, Имя задачи, Описание работ, Статус, Раздел, Тип, Комментарий),
  показывают инженера, под которым выполнен вход, и выгружают именно список
  работ за период в CSV (не складскую агрегацию);
- `Раздел` в форме новой записи и в модальном окне редактирования — строгий
  выпадающий список фиксированных разделов; свободный ввод недоступен, но
  унаследованные из Excel значения сохраняются и остаются редактируемыми;
- `work_log_section` добавлен в набор редактируемых справочников
  (`Администрирование → Справочники`).

### Импорт из Excel

- добавлен временный импорт истории работ из XLSX (кнопка `Импорт из Excel` на
  вкладке `УВР`) для миграции из старого файла «Баланс»;
- XLSX читается средствами стандартной библиотеки (`zipfile` + `xml.etree`),
  внешние зависимости не добавлены; поддержаны shared/inline strings и
  Excel-даты;
- заголовки сопоставляются существующим механизмом синонимов; читается только
  первый блок листа «Логи»/«Отчет», складские блоки игнорируются;
- значения `Раздел`, отсутствующие в справочнике, сохраняются как есть и
  помечаются `needs_review`; данные не теряются; импорт проходит через
  существующий preview → confirm с атомарной транзакцией.

### API и безопасность

- `POST /api/action` поддерживает `UPDATE_WORK_LOG` и `DELETE_WORK_LOG`
  (роли `engineer/admin`, `viewer` отклоняется сервером);
- `POST /api/preview-xlsx?sheet=<лист>` принимает XLSX и строит preview логов
  работ; прямой импорт без preview недоступен;
- отчеты за смену и за неделю используют существующий `GET /api/work-logs` с
  фильтром по дате и экспортируются через `GET /export/work-logs.csv`;
- каждое реальное изменение фиксируется audit-действиями `WORK_LOG_UPDATE` и
  `WORK_LOG_DELETE`.

### Тесты и документация

- добавлен `tests/test_uvr_workflow.py` (19 тестов): миграция схемы, CRUD и
  аудит, права `viewer`, standalone-задачи, narrative-отчеты, XLSX preview/
  confirm, fuzzy-сопоставление разделов, флаг проверки, пропуск строк-
  разделителей;
- обновлены README, CHANGELOG, `docs/REPORTS_ARCHITECTURE.md`,
  `docs/DATA_MODEL_ODE_013.md`, `docs/FRONTEND_CONTRACTS.md`.

### БД и миграции

- идемпотентная миграция добавляет `section` и `needs_review` в существующую
  `work_logs` (`ALTER TABLE ADD COLUMN`), данные не изменяются;
- добавлен справочник `work_log_section` и расширены `task_source`/`task_type`
  значениями из рабочего процесса смены.

## ODE 0.13, Stage 0.13.2 — Bulk Inventory Number Import

Дата: 2026-07-14

### Новые возможности

- добавлено массовое назначение Inventory Number существующему оборудованию из
  CSV через обязательные Preview и Confirm;
- поиск выполняется исключительно по S/N; отсутствующий S/N получает
  `NOT_FOUND`, новая карточка не создаётся;
- публичные построчные статусы:
  `SUCCESS`, `UNCHANGED`, `NOT_FOUND`, `ALREADY_ASSIGNED`,
  `DUPLICATE_INVENTORY_NUMBER`, `VALIDATION_ERROR`;
- повтор S/N внутри CSV является blocking validation error; остальные
  конфликты пропускаются, а допустимые строки могут быть применены;

### UI

- добавлены UTF-8 BOM template, выбор CSV, таблица Preview, status counters,
  Confirm и итоговый Result в разделе `Склад -> Инвентаризация`;
- Equipment Card Timeline показывает существующее audit-событие для каждой
  реально изменённой позиции.

### API и безопасность

- добавлен шаблон `GET /import/inventory-numbers-template.csv`;
- существующий `POST /api/preview-csv` поддерживает
  `kind=inventory_numbers`;
- существующий `POST /api/action` поддерживает
  `CONFIRM_IMPORT_PREVIEW` с `kind=inventory_numbers`;
- прямой `/api/import-csv?kind=inventory_numbers` запрещён: обойти preview и
  confirm нельзя;
- preview/confirm разрешены только `engineer/admin`; `viewer` отклоняется
  сервером; preview одноразовый, author-bound и ограничен TTL.

### Бизнес-логика, audit и Timeline

- preview выполняет только чтение и не меняет БД/audit;
- confirm начинает `BEGIN IMMEDIATE`, повторно анализирует весь план и
  отклоняет stale preview;
- все строки `SUCCESS`, legacy sync и audit применяются одной SQLite-
  транзакцией; при любой ошибке выполняется полный rollback;
- на каждую реально изменённую позицию создаётся существующее audit-действие
  `EQUIPMENT_INVENTORY_NUMBER_ASSIGNED`, которое отображается в Timeline
  карточки; отдельная event subsystem не создана;
- заполненный другой номер не перезаписывается, занятый номер не передаётся
  другой позиции, повторный импорт становится `UNCHANGED`.

### Импорт, тесты и документация

- обязательны столбцы Serial Number и Inventory Number; parser поддерживает
  UTF-8/UTF-8 BOM, compatibility fallback CP1251 и разделители `;`, `,`, tab;
- лимиты общих импортов сохранены: 50 МБ и 40 000 непустых строк; preview
  возвращает до 100 строк и 200 validation errors;
- добавлены 16 unittest (2 unit, 7 contract/integration, 3 API,
  4 frontend-contract) и headless сценарий; полный набор содержит 227 тестов;
- добавлены нормативный архитектурный/API-контракт и руководство ручной
  проверки Stage 0.13.2; актуализированы README, module/security/data/event и
  diagram-документы.

### БД и миграции

- схема и модель хранения не менялись; migration не требуется;
- используются существующие `stock_receipts.inventory_number`, связанная
  legacy `equipment.inventory_number`, unique constraints и `audit_log`;
- runtime-метаданные исходников и target package builder остаются
  `0.12.17.1 RC2`, тогда как последний фактически собранный Windows ZIP
  содержит `ODE 0.12.17 RC1`; ZIP RC2/Stage 0.13.2 не собирался;
- перед следующим Windows-релизом metadata, builder, embedded release notes и
  test count требуется синхронизировать отдельным release change.

### Исправления

- отдельных исправлений вне нового bulk workflow нет; бизнес-логика
  Stage 0.13.1 и существующих import/export сценариев не изменялась.

### Breaking changes

- отсутствуют: существующие API, CSV kinds и схема БД обратно совместимы.

### Известные ограничения

- preview хранится в памяти процесса, теряется при restart/TTL/eviction и
  после неуспешного confirm требует нового Preview;
- отдельного persisted batch ID, batch audit-event и фонового progress нет;
- сохраняются ограничения single-process SQLite и необходимость отдельной
  приемки на целевом Windows-хосте.

## ODE 0.13.1 — Equipment Card Inventory Workflow

Дата: 2026-07-13

- существующая карточка оборудования получила workflow присвоения Inventory
  Number после появления S/N: обновляется та же строка `stock_receipts`, новая
  карточка не создаётся;
- запись проходит через `ApplicationContext -> WarehouseFacade ->
  ReceiptWriteService -> ReceiptRepository -> SQLite`; отдельный endpoint,
  глобальный сервис и параллельная бизнес-логика не добавлены;
- заполненный Inventory Number нельзя перезаписать из карточки; повтор того же
  запроса идемпотентен, дубли блокируются существующими unique constraints и
  проверкой legacy `equipment`;
- связанная через `legacy_equipment_id` карточка синхронизируется в той же
  транзакции; viewer не может выполнить запись;
- реальное изменение фиксируется audit-действием
  `EQUIPMENT_INVENTORY_NUMBER_ASSIGNED` и автоматически попадает в текущую
  Timeline карточки;
- форма показывается внутри существующего `openPositionCard` только для S/N без
  Inventory Number и ролей `engineer/admin`; DOM строится безопасными
  компонентами без HTML-интерполяции пользовательского значения;
- добавлены contract/API/query-plan тесты и headless Chrome сценарий. Схема БД
  не менялась, рабочая `data/warehouse.db` не использовалась для mutation-тестов,
  release не собирался.

## ODE 0.12.17.1 RC2 — Compact Navigation, Search Modal, Test Circuit

Дата: 2026-07-12

- шапка стала компактной: убран постоянный ряд крупных разделов
  (`.product-nav`, дублировавший навигацию), фактическую разметку строит
  `warehouseLanding()` — экран «Добро пожаловать в ODE» с четырьмя карточками
  (Склад, Отчеты, Мониторинг, Профиль) теперь всегда виден на «Главной» вместо
  KPI-дашборда, который его раньше перезаписывал при каждой загрузке данных;
- глобальный поиск переведен с постоянного поля в шапке на кнопку-лупу и
  модальное окно; автофокус, debounce (180 мс), клавиатурная навигация
  (стрелки/Escape), поиск через существующий `/api/global-search` и открытие
  существующей карточки оборудования — без изменений в логике, изменена
  только разметка/презентация;
- добавлен `scripts/create_clean_test_db.py`: собирает одноразовую тестовую
  копию БД из рабочей базы, очищает только операционные (складские/отчетные)
  таблицы и сохраняет пользователей, хеши паролей, категории, полки и
  справочники; поддерживает `--dry-run`, `--profile empty`, `--profile demo`,
  требует `--overwrite` для существующего файла и никогда не разрешает
  `--source == --output`; рабочая база открывается только на чтение;
- добавлены `start_test_macos.command` и `start_test_windows.bat` —
  запускают ODE только на пересобираемой тестовой базе
  `data/warehouse_test_clean.db`; интерфейс показывает баннер
  «ТЕСТОВЫЙ КОНТУР» (флаг `ODE_TEST_MODE=1`), обычные launcher'ы его не
  устанавливают;
- временные scanner-списки прихода и расхода получили колонку «Действие»,
  одиночное/выбранное/полное удаление, счетчик, duplicate highlight и защиту
  от гонок scan/confirm; canonical JS state, localStorage, DOM и confirm payload
  обновляются одним путем, подтвержденные складские записи не удаляются;
- `create_clean_test_db.py` усилен SQLite read-only + Backup API snapshot,
  учетом WAL, FK-проверкой и атомарной публикацией; 15 тестов генератора
  проверяют также точное сохранение пользователей, password hashes и
  справочников, изоляцию launcher-окружения и запрет test-режима на рабочей БД;
- серверный поиск баланса сразу скрывает прежние кликабельные строки на время
  debounce/запроса, поэтому нельзя случайно открыть или списать чужую позицию;
- добавлены `CLAUDE.md` и developer-only настройка `codebase-memory-mcp`;
  MCP/cache не входят в runtime и release ZIP;
- схема БД не менялась; все автоматические mutation-проверки выполняются на
  временных/test DB. Контрольный SHA рабочей БД фиксируется до и после gate и
  должен совпадать;
- полный набор содержит 206 тестов; Windows package builder синхронизирован с
  именем RC2 и test-contour support-файлами, но release ZIP в рамках патча не
  пересобирался.

## ODE 0.12.17 RC1 — Product Hardening

Дата: 2026-07-11

- добавлены Dashboard, быстрые действия, постоянная навигация и глобальный поиск;
- расширена карточка оборудования и единая хронология связанных операций;
- `Проблемы` и `События` перенесены в `Склад`, Monitoring оставлен заглушкой;
- ограничены bootstrap, баланс, поставки, inventory DOM, история и preview storage;
- ускорены exact S/N/inventory paths, batch uniqueness и агрегирование категорий/проблем;
- добавлены delivery pagination и серверный поиск усеченного баланса;
- закрыты повторное связывание receipt с поставками и неконтролируемые JSON 500;
- добавлены session TTL/limits, admin login rate limit, Host/Origin checks и security headers;
- инженерный HTTP-контекст принудительно работает с service-role `engineer`;
- обязательная смена начального admin-пароля блокирует остальные admin operations;
- server/client CSV exports защищены от spreadsheet formulas, wizard DOM — от найденного XSS sink;
- UI smoke расширен глобальным поиском, Back/reload, mobile 390 px и реальной проверкой `/api/admin`;
- полный набор содержит 185 тестов; схема таблиц и существующие HTTP actions сохранены.

## ODE 0.12.16 RC1 — Release Candidate

Дата: 2026-07-11

- зафиксирована проверенная версия после Stage 0.12.16A acceptance поставок;
- полный сценарий поставок пройден в headless Chrome: preview, confirm,
  карточка, scanner acceptance, existing S/N, conflicts, unplanned acceptance,
  batch acceptance, balance, history and reports;
- 158 тестов проходят, UI smoke проходит, JS/runtime/resource/API500 ошибок
  нет;
- рабочая БД и схема не менялись; `integrity_check = ok`,
  `foreign_key_check` пуст;
- close delivery остается compatibility/legacy;
- destructive override конфликтующих данных не реализован;
- версия предназначена для тестовой эксплуатации, не для production.

## Stage 0.12.16 — Delivery Acceptance Migration

Дата: 2026-07-11

- planned and unplanned delivery acceptance migrated to
  `ApplicationContext -> WarehouseFacade`;
- added inspect before accept, acceptance summary, conflict read, batch accept
  and safe delivery line metadata update facade methods;
- new planned S/N creates a receipt through the Warehouse receipt repository
  transaction contract and links `delivery_lines.receipt_id`;
- existing S/N does not create a receipt; only empty allowed fields are filled,
  and filled-field conflicts are reported without overwrite;
- unplanned acceptance requires explicit metadata, creates an unplanned
  delivery line and then creates a receipt;
- delivery status refresh moved behind WarehouseFacade; close delivery remains
  legacy;
- balance/history/reports continue to read source warehouse rows through current
  contracts;
- no DB migration; release ZIP not rebuilt.

## Stage 0.12.15 — Delivery Document Import and Matching

Дата: 2026-07-11

- документ поставки отделён от фактического складского прихода;
- delivery CSV preview, column mapping, S/N parsing, duplicate matching,
  stock matching, confirm document, list/card/search/export/template routes
  переведены на `ApplicationContext -> WarehouseFacade`;
- добавлен Warehouse-owned delivery import layer:
  `delivery_imports`, `delivery_repository`, `delivery_mapping`,
  `delivery_validators`, `delivery_previews`, `delivery_models`;
- confirm создаёт только `deliveries`, `delivery_lines` и audit
  `DELIVERY_UPLOAD`; `DELIVERY_IMPORTED` остаётся warehouse event contract;
- `stock_receipts`, `stock_issues`, allocations and balance не меняются при
  delivery import;
- acceptance scanner, planned/unplanned accept, close delivery and receipt
  creation from delivery remain legacy for Stage 0.12.16;
- новый пользовательский шаблон поставки зафиксирован без legacy-only колонок;
- БД и схема не менялись; release ZIP не пересобирался.

## Stage 0.12.14 — Warehouse Equipment and Component Issue Migration

Дата: 2026-07-11

- serialized equipment/component issue write/import routes migrated to
  `ApplicationContext -> WarehouseFacade`;
- migrated manual issue, issue scanner validation, scanned S/N confirm, generic
  issue CSV preview/confirm/import, and strict bulk S/N issue preview/confirm;
- issue allocations and computed balance contracts preserved;
- soft problem-row behavior preserved for scanned/CSV issue flows;
- Warehouse-owned issue preview storage is used for issue and bulk issue
  previews;
- cable issue remains separate in the cable module;
- deliveries, inventory write, Administration write, backup/restore, auth,
  Monitoring and legacy equipment/operations remain compatibility-backed;
- БД и схема не менялись; release ZIP не пересобирался.

## Stage 0.12.13 — Cable Warehouse Module

Дата: 2026-07-11

- кабели отделены от S/N-оборудования и компонентов на уровне
  `WarehouseFacade`;
- manual cable receipt and manual cable issue routes now go through
  `ApplicationContext -> WarehouseFacade -> inventory/warehouse/cables.py`;
- добавлены cable validators, repository and models;
- кабели не требуют S/N, учитываются положительным целым количеством and do not
  use scanner/S/N receipt validation;
- cable balance/history/Reports contracts сохранены через текущие
  `stock_receipts`, `stock_issues`, `stock_issue_allocations` and
  `WarehouseEventReader`;
- audit actions для новых cable writes: `CABLE_RECEIPT_CREATE`,
  `CABLE_ISSUE_CREATE`, `CABLE_RECEIPT_BATCH`;
- общий issue оборудования/компонентов, поставки, inventory write,
  Administration write, backup/restore and Monitoring remain compatibility;
- БД и схема не менялись; release ZIP не пересобирался.

## Stage 0.12.12 — Warehouse Receipt Write Facade Migration

Дата: 2026-07-11

- equipment/component receipt write/import routes переведены на
  `ApplicationContext -> WarehouseFacade`;
- мигрированы manual receipt, scanned S/N batch confirm, receipt serial
  validation, receipt CSV preview/confirm and direct receipt CSV import;
- добавлена Warehouse-owned receipt preview storage;
- добавлено системное наименование через `build_item_name(...)`;
- batch/import операции валидируют все строки до записи и пишутся атомарно;
- balance/history/Reports event contracts сохранены: receipt rows видны в
  balance, WarehouseEventReader and daily/weekly reports;
- добавлены receipt write contract/API tests, включая rollback, duplicate S/N,
  actor/audit, preview/confirm, 100-row batch and delivery regression;
- issue, cable receipt, deliveries, inventory write, Administration write,
  backup/restore and Monitoring remain compatibility-backed;
- БД и схема не менялись; release ZIP не пересобирался.

## Stage 0.12.11 — Reports Write and Import Facade Migration

Дата: 2026-07-11

- Reports write/import routes переведены на `ApplicationContext -> ReportsFacade`;
- мигрированы single work log, batch work logs, work-log CSV import,
  work-log CSV preview/confirm and uploaded daily report import;
- preview для Reports хранится отдельно от warehouse previews в Reports-owned
  in-memory storage;
- массовые операции валидируют все строки до записи и сохраняются атомарно;
- audit сохраняется через shared audit adapter с автором, count, filename/id;
- добавлены Reports write contract/API tests, включая rollback, роли, preview,
  кириллицу, даты, audit и проверку складских таблиц;
- architecture audit запрещает legacy Reports write calls из webapp и доступ
  Reports к warehouse-owned tables;
- API/CSV URL, action names, response keys and headers сохранены;
- БД, схема, Warehouse writes, Administration writes, Monitoring, frontend
  component migration и release ZIP не менялись.

## Stage 0.12.10 — Warehouse EventReader Contract

Дата: 2026-07-11

- создан публичный контракт `WarehouseEvent` и `WarehouseEventReader`;
- `ReportsFacade` получает складские события через `ApplicationContext`;
- daily report, weekly report, weekly rows and report CSV exports построены через WarehouseEventReader;
- work logs остаются собственными данными Reports;
- результаты отчетов и CSV byte/text contract сохранены относительно legacy;
- добавлены EventReader и Reports event contract tests, включая 1000 warehouse events на временной БД;
- architecture audit запрещает SQL по warehouse-owned таблицам внутри `inventory/reports`;
- БД, схема, write/import flows, Monitoring, frontend и release ZIP не менялись;
- EventReader пока compatibility-backed внутри Warehouse и может читать текущую SQLite-схему.

## Stage 0.12.9 — Administration Read API Facade Migration

Дата: 2026-07-11

- read-only Administration API routes переведены на `AdministrationFacade`;
- `/api/data` продолжает отдавать текущего пользователя без раскрытия секретов;
- `/api/admin` собирает `backups`, `audit` и `users` через AdministrationFacade;
- `/export/audit.csv` читает audit через AdministrationFacade;
- URL, JSON/CSV контракты, роли и существующие ограничения доступа сохранены;
- добавлены Administration API contract/security tests;
- `password_hash`, session token и пароли не возвращаются в read API;
- write/admin actions, login/logout и auth flow пока legacy;
- БД, Monitoring, frontend Administration components и release ZIP не менялись.

## Stage 0.12.8 — Reports Read API Facade Migration

Дата: 2026-07-11

- read-only Reports API routes переведены на `ReportsFacade`;
- `/api/data` продолжает отдавать тот же JSON, но reports-owned поля читаются через ReportsFacade;
- внешние JSON/CSV контракты, URL, имена файлов, BOM, разделители и заголовки сохранены;
- добавлены Reports API contract tests и semantic comparison old service vs facade;
- module boundary audit теперь запрещает прямые read-only reports `service.*` вызовы из `_do_GET`;
- Warehouse events остаются read-only входом для отчетов через публичный контракт/compatibility layer;
- write/import логов работ и готовых отчетов пока legacy;
- БД, SQL, Monitoring, frontend Reports components и release ZIP не менялись.

## Stage 0.12.7 — Warehouse Read API Facade Migration

Дата: 2026-07-11

- read-only Warehouse API routes переведены на `WarehouseFacade`;
- `/api/data` внутри разделен: складские данные идут через WarehouseFacade, отчеты через ReportsFacade, пользователь через AdministrationFacade;
- внешние JSON/CSV контракты, URL и имена файлов сохранены;
- добавлены API contract tests и semantic comparison old service vs facade;
- module boundary audit теперь запрещает прямые read-only warehouse `service.*` вызовы из `_do_GET`;
- write API, импорты, confirm-flow, scanner validation и WarehouseCore остаются legacy;
- БД, SQL, бизнес-логика и release ZIP не менялись.

## Stage 0.12.6 — Product Module Boundaries

Дата: 2026-07-11

- создан переходный каркас модулей `core`, `warehouse`, `reports`, `monitoring`, `administration`;
- добавлены публичные фасады `WarehouseFacade`, `ReportsFacade`, `MonitoringFacade`, `AdministrationFacade`;
- добавлен `ApplicationContext` с централизованными feature flags;
- Monitoring изолирован как заглушка без зависимостей от Warehouse и Reports;
- добавлены frontend entrypoints для Core/Warehouse/Reports/Monitoring/Administration и компонентных подпакетов;
- добавлен `EventReader`/`EventPublisher` контракт, временно читающий складские события из существующей истории;
- добавлены документы по модульной архитектуре, владельцам таблиц, Reports, Monitoring и миграции;
- добавлен архитектурный аудит `scripts/audit_module_boundaries.py`;
- БД, бизнес-логика, реальные складские операции и release ZIP не менялись.

## Stage 0.12.5 — History Components

Дата: 2026-07-11

- рабочий экран `История` перенесен на компонентный DOM-рендер;
- старый `renderOperations()` оставлен только как compatibility alias к `renderWarehouseHistory()`;
- действия истории получают человекочитаемые названия через единый словарь;
- `details` и комментарии разбираются безопасно, ошибочный JSON не ломает экран;
- фильтры периода, инженера, действия и поиска работают на клиенте без изменения API;
- таблица истории ограничена первыми 200 строками текущей выборки;
- БД, API, сервисный слой, бизнес-логика и release ZIP не менялись.

## Stage 0.12.4 — Balance Components

Дата: 2026-07-10

- рабочий экран `Баланс` перенесен на `components.js`;
- KPI-карточки баланса `Серверы`, `Диски`, `Память`, `Сеть`, `Кабели`, `Прочее` строятся DOM-компонентами;
- фильтр по KPI-карточкам, активная подсветка и `Сбросить фильтр` работают без inline `onclick`;
- таблица баланса и кнопки строк `Открыть карточку` / `Списать` строятся DOM-узлами без `innerHTML`;
- поиск и select-фильтры баланса применяются вместе с KPI-фильтром;
- legacy `renderBalance()` оставлен только как fallback раннего render-прохода;
- бизнес-логика, сервисный слой, БД, приход, расход, поставки, отчеты и release ZIP не менялись.

## Stage 0.12.3 — Home and Navigation Components

Дата: 2026-07-10

- экран «Добро пожаловать в ODE» перенесен на `components.js`;
- карточки Главной `Склад`, `Отчеты`, `Мониторинг`, `Профиль` теперь строятся DOM-компонентами без `innerHTML`;
- клик по ODE в верхней панели переведен на component-кнопку и `goHome`;
- базовая навигация разделов строится в `router.js` через `renderButton`;
- legacy-экраны склада, отчетов, поставок и профиля не переписывались;
- бизнес-логика, сервисный слой и БД не менялись;
- release ZIP не пересобирался.

## Stage 0.12.2 — Architecture Stabilization

Дата: 2026-07-10

- зафиксирован backend facade: `inventory.service.WarehouseService` остается публичной точкой входа;
- `WarehouseCore` явно признан временным compatibility core;
- создан и задокументирован слой `inventory/services/*`;
- новые сервисы пока являются делегатами, перенос бизнес-методов будет идти постепенно;
- добавлен документ `docs/SERVICE_MIGRATION_PLAN.md`;
- добавлен UI component layer `static/js/components.js`;
- `static/js/ui.js` зафиксирован как legacy UI на переходный период;
- добавлены документы `docs/UI_COMPONENTS.md` и `docs/FRONTEND_MIGRATION_PLAN.md`;
- добавлен frontend contract audit `scripts/audit_frontend_contracts.py`;
- добавлен документ `docs/FRONTEND_CONTRACTS.md`;
- smoke UI теперь явно отчитывается об отсутствии console/runtime/window errors и прохождении ключевых разделов;
- миграция БД не выполнялась;
- бизнес-логика не менялась;
- release ZIP не пересобирался.

## ODE 0.12 — стабилизационный патч

- исправлен переход из параметров партии к временному списку S/N;
- наименование партии строится из типа, вендора и модели;
- упрощены приход, расход, навигация и шаблон поставки;
- добавлены кликабельный ODE и раздел «История».
- добавлены фильтруемые карточки баланса и localStorage-черновики скан-листов;
- поставки получили preview новых/обновляемых строк и атомарный confirm;
- добавлен самозавершающийся headless Chrome smoke-test.

История развития рабочего инструмента «ODE учет работ и склада». Учебные материалы ведутся отдельно и не определяют этот файл.

## Приемка сканером и поставки — 1 июля 2026

- добавлены атомарные приемка и списание списков S/N со сканера, работающего как клавиатура;
- неизвестные S/N расхода сохраняются как проблемные строки;
- добавлены загрузка и проверка документов поставки, поиск дублей и уже имеющихся позиций;
- реализованы карточка поставки, групповое заполнение реквизитов, приемка по S/N, внеплановые позиции, закрытие и CSV-выгрузка результата;
- добавлены таблицы `deliveries` и `delivery_lines`;
- ежедневные и недельные отчеты учитывают операции приемки поставок;
- актуальный автоматический набор содержит 72 теста.

## Финальный рабочий проход и пакет Windows — 28 июня 2026

### Интерфейс

- приведены к рабочему виду названия разделов, вкладок, кнопок загрузки, резервного копирования и проверки базы;
- установлен рабочий порядок вкладок склада, отчетов и мониторинга;
- баланс сделан главным рабочим экраном и ограничен первыми 500 строками без ограничения скачиваемой выборки;
- добавлены отдельный поиск карточек, последние 20 приходов, проблемные списания и раздел загруженных отчетов;
- карточка позиции получила связанные проблемные строки, переход к списанию и скачивание истории;
- технические формулировки скрыты от пользователя.

### CSV и надежность

- все пользовательские CSV-шаблоны и отчеты используют `;` и UTF-8 BOM для Excel с русской локалью;
- сохранены проверка файла, атомарное подтверждение и обработка файлов до 40 000 строк;
- перед работами создана резервная копия `warehouse_before_windows_final_20260628_123926.db`;
- добавлены проверки шаблонов, интерфейсных подписей и состава переносимого архива.

### Windows

- добавлены `README_WINDOWS.md` и понятный `start_windows.bat`;
- добавлен сборщик `build_windows_package.py`;
- переносимый архив содержит программу, рабочую базу и одну актуальную проверенную резервную копию без кэшей Python.

## Текущее состояние

- название: ODE;
- расшифровка: Отдел дежурных инженеров;
- режим: локальное приложение Python + SQLite;
- запуск: `python3 app.py`;
- основная база: `data/warehouse.db`;
- внешние зависимости: отсутствуют;
- автоматические тесты: 72.

## Stage 4.3 — отказ от Excel как основной логики

Завершен 28 июня 2026 года.

### Добавлено

- двухэтапный preview/confirm для CSV прихода и расхода без записи и аудита на этапе просмотра;
- статистика preview, первые 50 строк и ошибки с номером строки;
- серверные одноразовые preview-сессии и повторная проверка перед подтверждением;
- карточка позиции из баланса с текущим остатком, приходами, расходами, аллокациями и аудитом;
- общий поиск баланса и поиск позиции для расхода по складским реквизитам;
- автозаполнение формы расхода из найденной позиции;
- строгое массовое списание S/N оборудования и компонентов одной транзакцией;
- рабочие действия «Открыть» и «Списать» в балансе и экспорт текущей выборки;
- базовый еженедельный отчет, разбивки по проектам/типам и CSV-экспорт;
- тесты preview, подтверждения, карточек, поиска, атомарного массового расхода и недельного отчета.

### Совместимость и границы

- старые сервисные методы импорта сохранены для служебных сценариев;
- импорт логов работ и готовых ежедневных отчетов не изменен;
- схема рабочих таблиц не переписывалась, миграция БД не потребовалась;
- справочники продолжают работать в мягком режиме;
- DCIM, Kaiten, Solar и мониторинг не изменялись;
- backup до изменений: `data/backups/stage4_3_20260628_114208`.

## Stage 4.2.1 — свободный тестовый режим справочников и CSV

Завершен 28 июня 2026 года.

### Добавлено

- `strict_reference_validation = false` по умолчанию для прихода и расхода;
- свободный текст в ручных формах и CSV с подсказками из справочников;
- автоматический сбор фактических значений в `reference_values`;
- справочники наименований, моделей, стеллажей/полок и ЦОД;
- алфавитная сортировка значений с активными выше отключенных;
- баланс и его фильтры по фактически введенным значениям;
- тесты мягкого режима, автосбора, строгого режима и баланса.

### Миграция

- SQL-ограничение единиц учета `шт/м` снято без удаления строк прихода;
- существующие значения прихода перенесены в соответствующие справочники;
- backup до изменений: `data/backups/stage4_2_1_20260628_110306`.

## Stage 4.2 — пользователи и административный контур

Завершен 27 июня 2026 года.

### Добавлено

- локальные профили, роли `admin` / `engineer` / `viewer` и cookie-сессии;
- PBKDF2-SHA256-хеширование паролей стандартной библиотекой Python;
- дефолтный администратор `lokolis` только для пустой таблицы пользователей;
- смена пароля и признак рекомендации смены начального пароля;
- реальный email автора в аудите;
- ролевые проверки операций записи и admin-only функций;
- безопасная загрузка `.db` в прод со страховочным backup, миграцией, проверкой и откатом;
- таблицы `daily_report_uploads` и `daily_report_rows`;
- атомарный импорт, просмотр и экспорт готового ежедневного CSV-отчета;
- группировка и фильтр справочников;
- настройка текущего ЦОД `CURRENT_DATACENTER = "Ixcellerate"`;
- новые названия навигации и заглушка учета поставок-отправок.

### Миграция

- складские таблицы и существующие данные не переписываются;
- новые таблицы и индексы создаются идемпотентно;
- backup до миграции: `data/backups/warehouse_before_stage4_2_20260627.db`;
- интеграции с DCIM, Kaiten, Solar и мониторинг не изменялись.

## Stage 4.1 — эксплуатационная надежность без ролей

Завершен 27 июня 2026 года.

### Добавлено

- таблица единого аудита `audit_log`;
- автор аудита `local_user` без системы ролей;
- backup рабочей SQLite-базы через SQLite Backup API;
- проверка созданной копии перед подтверждением успеха;
- список backup-файлов в интерфейсе;
- `PRAGMA integrity_check` и проверка ключевых таблиц;
- восстановление только после явного подтверждения;
- страховочный backup текущей базы перед восстановлением;
- откат на страховочную копию при ошибке восстановления;
- аудит приходов, расходов, логов, справочников, backup, restore и проверок;
- вкладка «Администрирование»;
- сериализация веб-запросов на время административных операций;
- тесты backup, integrity check, restore и аудита.

### Миграция

- `audit_log` добавляется без изменения существующих складских таблиц;
- backup перед миграцией: `data/backups/warehouse_before_stage4_1_20260627.db`;
- роли, авторизация и корректирующие операции не добавлялись.

## Stage 3 — новый баланс и показатели

Завершен 27 июня 2026 года.

### Добавлено

- расчет баланса по `stock_receipts` и `stock_issue_allocations`;
- агрегация одинаковых позиций без зависимости от полки;
- справочное отображение всех полок позиции;
- фильтры по проекту, объекту, типам, единице учета и ЦОД;
- поле `datacenter` в новой модели прихода;
- API и CSV-экспорт нового баланса;
- показатели обзора по новой модели;
- ежедневный отчет только по новым приходам и расходам;
- тесты независимости от `equipment/operations`.

### Миграция

- в `stock_receipts` добавлено поле `datacenter`;
- перенесенные позиции получили ЦОД из старой карточки либо `Ixcellerate`;
- существующие строки сохранены;
- backup: `data/backups/warehouse_before_stage3_20260627.db`.

## Stage 2 — расширенный приход, расход и справочники

Завершен 27 июня 2026 года.

### Добавлено

- таблицы `stock_receipts`, `stock_issues`, `stock_issue_allocations`;
- таблица `reference_values`;
- расширенные реквизиты прихода;
- расход оборудования и компонентов по S/N;
- обязательная задача для оборудования и компонентов;
- проверка целевого оборудования и запрет самосписания;
- кабельный учет по наименованию и типу в метрах;
- FIFO-распределение кабелей по партиям;
- автоматическое получение проекта и реквизитов из прихода;
- управление справочниками из интерфейса;
- новые CSV-шаблоны и атомарный импорт;
- синхронизация совместимых CLI-операций с новой моделью.

### Миграция

- положительные остатки старой модели перенесены как начальные позиции;
- связь со старой карточкой хранится в `legacy_equipment_id`;
- старые таблицы и операции не удалялись;
- backup: `data/backups/warehouse_before_stage2_20260627.db`.

## Stage 1 — интерфейс, логи работ и ежедневные отчеты

Завершен 27 июня 2026 года.

### Добавлено

- разделы «Склад», «Отчеты» и «Мониторинг»;
- вложенные вкладки и адаптивная навигация;
- таблица `work_logs`;
- ручной ввод, фильтрация, CSV-импорт и экспорт логов;
- отдельное хранение источника, типа и номера задачи;
- полный номер задачи вида `ПНР-123`;
- ежедневный отчет из логов, прихода и расхода;
- заглушки Kaiten, еженедельного отчета и мониторинга.

### Миграция

- таблица логов добавлена без изменения складских таблиц;
- backup: `data/backups/warehouse_before_stage1_20260627.db`.

## Совместимость

- `equipment`, `operations`, `categories` и `locations` сохранены для старого CLI и истории;
- новые складские функции развиваются через таблицы `stock_*`;
- миграции в `inventory/db.py` идемпотентны и выполняются при запуске;
- перед обновлением обязательна отдельная резервная копия базы.

## Возможные следующие этапы

- корректирующие операции без удаления истории;
- диагностика и автоматическое расписание backup;
- печать этикеток и централизованное многопользовательское развертывание;
- интеграции с DCIM, Kaiten и мониторингом.
