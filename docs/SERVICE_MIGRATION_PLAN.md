# SERVICE_MIGRATION_PLAN

Дата: 2026-07-10

## Статус

Stage 0.12.2 фиксирует переходное состояние: `WarehouseService` уже является facade, профильные сервисы созданы, но большинство методов пока делегируют в `WarehouseCore`. Это допустимое состояние для стабилизации. В этом этапе методы не переносятся.

Общие правила переноса:

- один доменный блок за один pull/change;
- публичные методы `WarehouseService` и HTTP API не меняются;
- схема БД не меняется;
- рабочая БД не трогается;
- после каждого блока проходят unittest, smoke UI, SQLite integrity и frontend contract audit.

## ReceiptService

Методы для переноса:

- `add_stock_receipt`
- `preview_stock_receipt_rows`
- `confirm_stock_receipt_preview`
- `scan_receipt_serial`
- `confirm_scanned_receipts`
- `import_stock_receipt_rows`
- `stock_receipts`
- legacy `receipt`
- приватные helpers: `_prepare_receipt`, `_receipt_values`, `_sync_legacy_stock_receipt`, `_positive_number`, `_collect_references`

Тесты:

- `test_receipt_and_issue_update_balance_and_log`
- `test_receipt_preview_does_not_change_database_and_confirm_imports`
- `test_scanned_receipt_checks_serial_and_confirms_atomically`
- `test_cable_receipt_does_not_require_serial_number`
- `test_equipment_and_component_receipts_still_require_serial_number`
- `test_receipt_category_maps_to_legacy_type_fields`
- CSV/import/reference tests around receipt.

Риски:

- нарушение атомарности preview/confirm;
- рассинхронизация legacy stock;
- неверная классификация оборудования, компонентов и кабелей;
- потеря audit/history записи.

Таблицы:

- `stock_receipts`
- `equipment`
- `current_stock`
- `reference_values`
- `audit_log`
- legacy operation/current stock tables.

## IssueService

Методы для переноса:

- `add_stock_issue`
- `scan_issue_serial`
- `confirm_scanned_issues`
- `import_stock_issue_rows`
- `preview_stock_issue_rows`
- `confirm_stock_issue_preview`
- `preview_bulk_issue_serials`
- `confirm_bulk_issue_preview`
- `stock_issue_rows`
- legacy `issue`
- helpers: `_prepare_issue`, `_available_receipts`, `_create_stock_issue`, `_create_unmatched_stock_issue`, `_is_unmatched_issue`

Тесты:

- `test_issue_cannot_make_negative_balance`
- `test_issue_preview_and_confirm_use_same_validation`
- `test_bulk_issue_import_is_atomic`
- `test_bulk_serial_issue_is_strict_and_atomic`
- `test_scanned_issue_rolls_back_whole_list_on_invalid_position`
- `test_scanned_issue_saves_unknown_as_problem`
- cable issue and component target tests.

Риски:

- отрицательные остатки;
- частичная запись при bulk/scanned issue;
- некорректные allocations;
- потеря проблемных строк.

Таблицы:

- `stock_issues`
- `stock_issue_allocations`
- `stock_receipts`
- `problem_rows`
- `audit_log`
- legacy stock tables.

## DeliveryService

Методы для переноса:

- `preview_delivery_rows`
- `confirm_delivery_preview`
- `deliveries`
- `delivery`
- `update_delivery_lines`
- `accept_delivery_serial`
- `close_delivery`
- helpers: `_delivery_serials`, `_refresh_delivery_status`

Тесты:

- `test_delivery_upload_splits_serials_and_detects_duplicates_and_stock`
- `test_delivery_web_confirm_adds_new_and_fills_only_empty_existing_fields`
- `test_delivery_acceptance_creates_receipt_blocks_repeat_and_updates_status`
- `test_unplanned_delivery_acceptance_and_bulk_fill`
- report tests that include delivery activity.

Риски:

- повторная приемка S/N;
- неверный статус поставки;
- приемка внеплановой строки без обязательных реквизитов;
- расхождение поставок с приходом.

Таблицы:

- `deliveries`
- `delivery_lines`
- `stock_receipts`
- `reference_values`
- `audit_log`

## BalanceService

Методы для переноса:

- `dashboard_stats`
- `balance_by_category`
- `warehouse_categories`
- `stock_balance`
- `search_stock_positions`
- `position_card`

Тесты:

- `test_dashboard_stats_show_flow_and_current_balance`
- `test_balance_exposes_supplier_type_and_category`
- `test_balance_filters_all_new_dimensions`
- `test_balance_allows_empty_project_and_shelf`
- `test_position_search_card_and_balance_query`
- `test_balance_and_overview_do_not_read_legacy_tables`

Риски:

- медленные запросы на большой БД;
- неверное агрегирование кабелей;
- путаница серийных и количественных позиций;
- карточка позиции показывает неполную историю.

Таблицы:

- `stock_receipts`
- `stock_issues`
- `stock_issue_allocations`
- `deliveries`
- `delivery_lines`

## ReportService

Методы для переноса:

- `add_work_log`
- `add_work_logs`
- `work_logs`
- `import_work_log_rows`
- `preview_work_log_rows`
- `confirm_work_log_preview`
- `daily_report`
- `weekly_report`
- `weekly_report_rows`
- `import_daily_report_rows`
- `daily_report_uploads`
- `uploaded_daily_report`
- `export_work_logs_csv`

Тесты:

- work log import/preview tests;
- daily report tests;
- weekly report tests;
- uploaded daily report isolation tests;
- Excel-friendly CSV tests.

Риски:

- потеря атомарности импорта логов;
- смешивание uploaded daily report с work logs;
- неверные периоды дня/недели;
- несовместимый CSV формат.

Таблицы:

- `work_logs`
- `daily_report_uploads`
- `daily_report_rows`
- `stock_receipts`
- `stock_issues`
- `deliveries`
- `delivery_lines`

## ReferenceService

Методы для переноса:

- `references`
- `reference_groups`
- `add_reference`
- `set_reference_active`
- `reference_data`
- legacy `add_category`
- legacy `add_location`
- helpers: `_reference_sets`, `_reference`, `_collect_references`

Тесты:

- reference grouping tests;
- strict/soft reference validation tests;
- disabled reference tests;
- import tests that collect references.

Риски:

- strict mode начинает ошибочно пропускать неизвестные значения;
- soft mode перестает собирать фактические значения;
- отключенные значения используются в новых операциях.

Таблицы:

- `reference_values`
- `categories`
- `locations`

## ProfileService

Методы для переноса:

- `authenticate`
- `user_by_email`
- `current_user`
- `user_context`
- `users`
- `create_user`
- `change_password`
- `update_profile`
- helpers: `_public_user`, `_require_role`, `_require_write`

Тесты:

- `test_login_and_password_change`
- `test_default_admin_is_created_once_with_hashed_password`
- role restriction tests;
- profile update tests.

Риски:

- обход ролей;
- потеря текущего user context в audit;
- изменение формата публичного пользователя;
- нарушение дефолтного admin bootstrap.

Таблицы:

- `users`
- `audit_log`

## HistoryService

Методы для переноса:

- `audit_entries`
- `warehouse_history`
- legacy `operation_log`
- helper `_audit`

Тесты:

- `test_business_actions_are_written_to_unified_audit`
- `test_warehouse_history_uses_human_labels`
- backup/integrity audit tests;
- legacy operation log tests.

Риски:

- пропуск операций в единой истории;
- несовместимые подписи действий;
- потеря автора операции;
- разъезд legacy history и нового audit.

Таблицы:

- `audit_log`
- `operations`
- `stock_receipts`
- `stock_issues`
- `deliveries`

## MonitoringService

Методы для переноса:

- `check_integrity`
- `data_quality_problems`
- helper `_database_check`

Тесты:

- `test_integrity_check_validates_tables_and_writes_audit`
- problem rows/data-quality tests;
- SQLite integrity and foreign key checks.

Риски:

- false OK при поврежденной схеме;
- тяжелые проверки блокируют UI;
- неверные problem counters.

Таблицы:

- `sqlite_master`
- `stock_receipts`
- `stock_issues`
- `problem_rows`
- `audit_log`

## InventoryService

Методы для переноса:

- `list_backups`
- `create_backup`
- `restore_backup`
- `replace_production_database`
- legacy `add_equipment`
- legacy `move`
- legacy `equipment`
- `inventory_compare`
- `import_operation_rows`
- `import_equipment_rows`
- `import_preview_rows`
- `export_csv`

Тесты:

- backup/restore tests;
- production DB replace tests;
- inventory compare tests;
- legacy CLI sync tests;
- export CSV tests.

Риски:

- потеря safety backup;
- запись в рабочую БД во время тестов;
- несовместимость legacy CLI;
- повреждение export CSV.

Таблицы:

- `equipment`
- `operations`
- `current_stock`
- `stock_receipts`
- `stock_issues`
- `audit_log`
