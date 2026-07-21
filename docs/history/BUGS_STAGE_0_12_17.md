# Bugs ODE, Stage 0.12.17

Дата актуализации: 11 июля 2026 года.

## 1. Правила реестра

В таблицу включены только дефекты, которые были воспроизведены аудитом,
подтверждены кодом или зафиксированы автоматическим тестом. Статус `Fixed`
означает, что исправление присутствует в текущем worktree и покрыто указанной
проверкой. Он не означает, что связанная функциональная область полностью готова
к промышленной эксплуатации.

Шкала severity:

- `Critical` — возможна потеря/подмена рабочей БД или обход административной
  границы;
- `High` — нарушается основной рабочий сценарий, возможен HTTP 500, неконтролируемое
  потребление ресурсов или существенный security-риск;
- `Medium` — заметная ошибка UX, навигации или обработки данных без прямой потери
  базы;
- `Low` — локальная косметическая или диагностическая ошибка.

## 2. Найденные и исправленные дефекты

| ID | Severity | Проявление до исправления | Исправление Stage 0.12.17 | Проверка | Статус |
|---|---|---|---|---|---|
| BUG-17-001 | Critical | Обычная engineer-session технически использовала admin-пользователя `lokolis`; `/api/upload-prod-db` не требовал отдельный admin-mode. Инженер мог заменить рабочую БД. Export аудита также не имел route guard. | До чтения upload добавлена `_require_admin_session`; audit export защищен тем же guard; сервис замены БД повторно проверяет роль `admin`. Дополнительно web handler запускает обычную смену с `role_override="engineer"`, поэтому service-level admin checks запрещают backup/integrity/upload даже при ошибочно пропущенном route guard. | `test_engineer_session_cannot_upload_production_database`, `test_engineer_session_is_downgraded_inside_service_context`, `test_engineer_http_context_keeps_defense_in_depth_if_route_guard_is_missed`, `test_audit_export_requires_admin_session`, `test_admin_can_replace_production_database_with_safety_backup`. | Fixed, включая defense in depth |
| BUG-17-002 | High | На новой базе известный начальный пароль позволял выполнять административные операции без обязательной смены. | При `must_change_password=1` admin-session допускает только `CHANGE_PASSWORD`; остальные admin-действия блокируются сервером. | `test_initial_admin_password_allows_only_password_change`. | Fixed; известный bootstrap-пароль остается открытым ограничением OL-005. |
| BUG-17-003 | High | Admin login не имел защиты от перебора; сессии не имели TTL и общего лимита, поэтому могли жить до перезапуска и неограниченно расти в памяти. | После 5 ошибок за 5 минут login блокируется на 15 минут; состояние rate limit ограничено 2 000 ключами. Session inactivity TTL — 12 часов, общий лимит — 500 сессий, logout удаляет token. | `test_admin_login_is_blocked_after_five_failures`, `test_session_expires_after_twelve_hours_of_inactivity`, `test_session_store_is_bounded_and_evicts_oldest_session`. | Fixed для одного процесса; ограничения распределенного deployment перечислены в OL-006. |
| BUG-17-004 | High | POST не имел достаточной границы Host/Origin, а ответы не содержали базовых anti-sniff/frame headers. Для локального сервера сохранялся риск browser DNS-rebinding/CSRF-сценария. | Для browser POST с `Origin` проверяются совпадение `Origin.netloc` и `Host` и разрешенный host; DNS-имена вне allowlist отклоняются. Добавлены `nosniff`, `DENY`, `no-referrer` и ограниченный `Permissions-Policy`. | `test_host_allowlist_rejects_dns_names_and_accepts_private_addresses`; security contract review. | Fixed для локального контура; TLS, CSRF token и reverse proxy profile не реализованы, см. OL-006. |
| BUG-17-005 | High | `id=abc`, JSON-массив вместо объекта, `dict/list/null/bool` в scalar-полях и неверные collection-типы приводили к HTTP 500 либо необработанному исключению login. Строка `"false"` интерпретировалась через `bool()` как `True`. Текст внутренних исключений попадал в 500-response. | Добавлены `_query_int`, `_read_json_object`, shape/type validation action payload и строгий parser совместимых boolean-значений. Неожиданный 500 теперь возвращает нейтральное сообщение без деталей исключения. | `test_invalid_numeric_queries_are_400_and_never_leak_trace_details`, `test_json_root_must_be_object_for_action_and_login`, `test_invalid_field_types_are_user_errors`, `test_action_collection_and_scalar_types_never_reach_http_500`, `test_boolean_compatibility_and_large_csv_fail_cleanly`. | Fixed |
| BUG-17-006 | High | Один складской receipt можно было попытаться связать со второй поставкой. UNIQUE constraint `delivery_lines.receipt_id` выбрасывал необработанный `IntegrityError`, что превращалось в HTTP 500. | Перед связыванием выполняется явная проверка другой поставки; возвращается понятный `WarehouseError`, а вторая строка остается в состоянии `Ожидается` без частичной записи. | `test_existing_receipt_cannot_be_linked_to_two_deliveries`. | Fixed |
| BUG-17-007 | High | Проверка backup/upload могла получить `integrity_check=ok`, но не обнаружить осиротевшие foreign keys. | `_database_check` включает `PRAGMA foreign_key_check`; результат влияет на `ok` для backup, restore и production upload. | `test_database_check_rejects_foreign_key_corruption`; текущая рабочая БД: `integrity_check=ok`, `foreign_key_check` пуст. | Fixed |
| BUG-17-008 | High | Warehouse/Reports preview не имели TTL, row budget и thread synchronization. Несколько больших preview удерживали значительный объем памяти. Delivery preview обычных смен разделяли owner `lokolis` и могли вытеснять друг друга; пустой session не обеспечивал изоляцию. | Все preview stores получили `RLock`, TTL, лимит одного preview, общий row budget и лимит на автора/сессию. Web handler передает session token при preview и confirm поставки; проверка session стала строгой. | 7 тестов в `test_preview_limits.py`, включая concurrent stores, TTL, oversized preview и owner/session isolation; delivery import contract tests. | Fixed в пределах лимита 40 000 строк; transient memory CSV остается в OL-002. |
| BUG-17-009 | High | `/api/data` материализовал полный баланс, все приходы, поставки и проблемы. На больших БД ответ и память браузера росли линейно; проекция старого JSON на 1 млн строк составляла около 450 МиБ. | Bootstrap ограничен: баланс 5 000 строк, приходы 20, поставки 100, проблемы 200 на группу; примеры и exact counts проблем строятся общими SQL-проходами; добавлен `balance_truncated`. | Замеры в `PERFORMANCE_REVIEW.md`: итоговый ответ остается примерно 2,3–2,7 МиБ на 100 тыс. и 1 млн записей; API contract suite. | Fixed для размера ответа; CPU bootstrap на 1 млн остается OL-001. |
| BUG-17-010 | High | Карточка поставки могла возвращать все строки документа; inventory result пытался отрисовать весь результат; поиск баланса работал только по уже загруженной клиентской выборке. | Для поставки добавлены `limit/offset`, summary и pager по 500 строк. Inventory UI показывает первые 1 000 строк с полным export. При усеченном bootstrap поиск баланса выполняется сервером по всей БД. | `tests/headless_smoke.js`, frontend contracts, delivery API/contract tests. | Fixed для DOM и перечисленных списков; полный inventory compare response и большие exports остаются OL-004/OL-011. |
| BUG-17-011 | High | Точные проверки S/N и инвентарного номера не повторяли predicate partial index и могли делать full scan. Batch-приход загружал в память все существующие идентификаторы склада. | Exact queries содержат `trim(...) <> ''` и используют partial unique indexes; batch uniqueness загружает только запрошенные значения чанками. | `EXPLAIN QUERY PLAN` и замеры в `PERFORMANCE_REVIEW.md`; receipt/issue/delivery regression tests. На 100 тыс. строк batch-приход 1 000 позиций — 0,047 с. | Fixed |
| BUG-17-012 | High | Значения, начинающиеся с `=`, `+`, `-`, `@`, могли попасть в CSV и интерпретироваться Excel как формула. | Server-side и client-side CSV helpers нейтрализуют опасные текстовые значения апострофом и сохраняют корректное quoting. | `test_csv_download_neutralizes_spreadsheet_formulas`; проверка `csvQuotedCell` в `tests/headless_smoke.js`. | Fixed |
| BUG-17-013 | Medium | Wizard создавал кнопку выбора через `innerHTML` с динамической подписью; специально сформированная подпись могла стать HTML, а не текстом. | Wizard choice переведен на DOM-компоненты `renderButton`/`renderElement` с `textContent`. | XSS-negative assertion в `tests/headless_smoke.js`; `audit_frontend_contracts.py`. | Fixed для найденного sink; полный stored-XSS fuzz остается OL-010. |
| BUG-17-014 | High | Быстрый двойной submit или повторный одинаковый mutation request мог отправить операцию дважды до завершения первого запроса. | На клиенте одинаковые pending mutations объединяются; submitter блокируется на время отправки формы. | Код `static/js/product.js`, расширенный headless сценарий и существующие duplicate/atomicity service tests. | Fixed для немедленного UI double-click; server idempotency key отсутствует, см. OL-009. |
| BUG-17-015 | High | Не было единого глобального поиска; карточка позиции не содержала обязательные эксплуатационные поля и связную историю. Инженер вынужден был искать объект в разных экранах. | Добавлен ограниченный global search по позиции, S/N, инвентарному номеру, hostname, поставке, заказу, проекту, ЦОД, полке и инженеру. Карточка дополнена типом, категорией, поставщиком, поставкой, заказом, датой, hostname, ответственным и хронологией. | `test_global_search_and_equipment_card_cover_operational_fields`; global search/card path в `tests/headless_smoke.js`. | Fixed в текущей модели данных; корректирующие события отсутствуют, см. OL-003. |
| BUG-17-016 | High | Главная не давала требуемую оперативную сводку и быстрые действия; начало смены требовало лишних переходов. | Добавлен Dashboard: оборудование, кабели, приход/расход за сегодня, проблемы, поставки, последние действия и четыре быстрых сценария. | `test_dashboard_stats_show_flow_and_current_balance`; headless переходы через новую Главную. | Fixed |
| BUG-17-017 | Medium | «Проблемы» и «События» находились в Monitoring, хотя относятся к складу. Monitoring выглядел как рабочий модуль. Кнопка ODE, browser Back и reload не всегда возвращали/восстанавливали ожидаемый экран. | Проблемы и события перенесены в навигацию Склада; Monitoring заменен явной заглушкой «В разработке». Добавлены единая product navigation, ODE → Главная и history state/hash для Back/reload и карточки. | Проверки warehouse/monitoring navigation, ODE home, reload и Back в `tests/headless_smoke.js`; frontend contracts. | Fixed |
| BUG-17-018 | Medium | Значение «сегодня» формировалось через UTC (`toISOString`), поэтому около локальной полуночи формы могли получать соседнюю дату. | Дата строится из локальных `getFullYear/getMonth/getDate`. | Local-date assertion в `tests/headless_smoke.js`; JS syntax check. | Fixed |
| BUG-17-019 | Medium | Профиль инженера заменял содержимое общей секции через `innerHTML`; административная форма смены пароля могла быть уничтожена в DOM, а smoke проверял только открытие раздела. | Профиль смены создается отдельным DOM-блоком, исходная admin-форма сохраняется; режим выбирается по роли без HTML-инъекции. | Headless smoke отдельно проверяет видимую карточку инженера и реальную форму пароля администратора; frontend contracts и JS syntax check. | Fixed |

## 3. Открытые ограничения

Ниже перечислены ограничения, которые **не считаются исправленными** этим Stage.

| ID | Severity | Ограничение и фактическое состояние | Требуемое решение |
|---|---|---|---|
| OL-001 | High | Bootstrap на 1 000 000 записей имеет ограниченный ответ 2,658 МиБ, но выполняет несколько полных SQL-агрегаций и занимает 7,482 с после оптимизации (исходно 9,742 с). Итоговый mixed load test 50 инженеров не выполнен. | До 1.0 согласовать SLO, устранить оставшиеся полные агрегации и провести нагрузочный тест 50 инженеров с p50/p95/p99, RSS, `database is locked`, HTTP 500 и rollback. |
| OL-002 | High | Один CSV принимает максимум 40 000 непустых строк. Файл на 100 000 строк корректно отклоняется, а не импортируется. HTTP handler сначала читает и декодирует body целиком; миллион коротких строк в замере дал около 66,6 МиБ peak до отказа. | Для 1.0 документировать и проверять лимит и сценарий деления файла. Поддержку 100 тыс.+ строк реализовывать отдельным потоковым/фоновым импортом с progress, cancel и журналом ошибок, вероятно в 1.1. |
| OL-003 | Critical для эксплуатации | Нет штатных компенсирующих операций для ошибочного прихода/расхода: отмены, возврата, корректировки количества, исправления реквизитов с полной историей и подтвержденного списания. Прямое редактирование SQLite недопустимо. | До 1.0 определить бизнес-правила и добавить auditable correction/reversal workflows без удаления исходного события. |
| OL-004 | High | Большие exports по-прежнему получают полный Python list и формируют весь CSV в `StringIO`. Экспорт сотен тысяч или миллиона строк может исчерпать память. | До 1.0 ограничить объем или формировать export потоково/во временный файл с проверкой свободного диска. |
| OL-005 | Critical | Новая база все еще получает известный bootstrap `lokolis/lokolis`. Guard заставляет сменить пароль до admin-действий, но сам секрет публичен и может быть использован для захвата первичной admin-session. | До 1.0 убрать фиксированный пароль и реализовать безопасную первичную настройку администратора. Technical identity обычной смены больше не является blocker: `role_override="engineer"` ограничивает ее внутри service context. |
| OL-006 | Critical для сети | Встроенный сервер не реализует TLS, SSO, MFA, полноценный CSRF token, trusted-proxy profile или централизованные sessions/rate limits. Текущий контур рассчитан на локальный `127.0.0.1`, а не на готовый server deployment для 50 инженеров. | Не публиковать приложение напрямую в сеть. До сетевой эксплуатации спроектировать HTTPS reverse proxy, строгий Host allowlist, `Secure` cookie, CSRF, identity provider и модель отказоустойчивости. SSO/MFA могут быть отдельным этапом, но не должны заявляться как готовые. |
| OL-007 | High | Финальная hardware acceptance на Windows не выполнена. Не проверены текущий ZIP на целевом Windows-хосте, `start_windows.bat`, реальный USB/QR-сканер, раскладка/суффикс Enter, Excel CSV, антивирус и корпоративные filesystem policies. | Обязательный sign-off до 1.0 на реальном ноутбуке инженера и минимум одной целевой Windows-конфигурации. Результат зафиксировать отдельно, не заменять macOS/headless smoke. |
| OL-008 | High | После снятия глобального read-lock не выполнен смешанный concurrency test. SQLite работает в `journal_mode=delete`; решение по WAL не проверено crash-тестом на целевой Windows FS. | До 1.0 выполнить read/write load и crash/restart test. WAL включать только после измерений и проверки backup/restore/Windows semantics. |
| OL-009 | High | Client guard защищает от немедленного двойного клика, но API не принимает idempotency key. Повтор запроса после timeout/retry может создать две допустимые несерийные операции. | До 1.0 добавить request id/idempotency contract для критичных write/batch endpoints и тест повторной отправки после потерянного ответа. |
| OL-010 | Medium | Найденный XSS sink исправлен, но строгого CSP и полного stored-XSS fuzz всех импортируемых полей нет. Сессии/rate limits живут только в памяти и не отзываются централизованно после смены роли/пароля. БД и backup не зашифрованы at rest. | До 1.0 выполнить security acceptance для выбранной модели deployment. CSP, централизованные sessions/audit и encryption at rest планировать по утвержденной инфраструктуре, часть работ допустимо перенести на 1.1. |
| OL-011 | High на больших БД | Inventory compare может вернуть полный список отсутствующих складских S/N, а legacy-массив `equipment` в bootstrap не имеет отдельной pagination. Ограничение DOM до 1 000 строк не ограничивает размер соответствующего API payload. | До 1.0 добавить серверный summary/pagination или отдельный потоковый export и нагрузочный тест инвентаризации на согласованном максимуме записей. |

## 4. Проверки текущего состояния

Выполнено на текущем worktree:

- `python3 -m unittest discover -s tests` — `185` тестов, `OK`;
- focused Stage/security/preview наборы — `OK`;
- `node --check static/js/product.js` — `OK`;
- `node --check static/js/ui.js` — `OK`;
- `node --check tests/headless_smoke.js` — `OK`;
- `python3 scripts/audit_module_boundaries.py` — `OK`;
- `python3 scripts/audit_frontend_contracts.py` — `OK`, отсутствующих static IDs нет;
- `python3 scripts/smoke_ui.py` — `OK` после role-override и security-изменений;
- рабочая SQLite-БД: `PRAGMA integrity_check = ok`, `PRAGMA foreign_key_check` — ошибок нет.

Headless-сценарий расширен проверками глобального поиска, карточки, Back/reload,
новой навигации, Monitoring placeholder, локальной даты, XSS-safe wizard label и
CSV formula neutralization. Chrome UI smoke выполнен успешно, но не заменяет
Windows hardware acceptance, которая остается OL-007.

## 5. Release verdict по дефектам

Найденные Stage 0.12.17 дефекты из таблицы исправлены и имеют regression coverage.
При этом открытые ограничения OL-001, OL-003, OL-005, OL-006, OL-007, OL-008 и
OL-009 не позволяют честно назвать текущий build полностью готовым к промышленной
эксплуатации для 50 инженеров и миллионной базы. Они должны быть либо закрыты до
1.0, либо формально исключены из release scope с утвержденными эксплуатационными
ограничениями.
