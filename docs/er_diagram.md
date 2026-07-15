# Модель данных ODE

Первая диаграмма показывает production-модель source Stage 0.13.3A.5; runtime
metadata остаётся `0.12.17.1 RC2`. Таблицы `equipment`, `operations`,
`categories` и `locations` сохранены как legacy compatibility layer. Они не
являются источником современного баланса, но связанная `equipment` всё ещё
участвует в проверке/синхронизации Inventory Number.

```mermaid
erDiagram
    DAILY_REPORT_UPLOADS ||--o{ DAILY_REPORT_ROWS : contains
    STOCK_RECEIPTS ||--o{ STOCK_ISSUE_ALLOCATIONS : supplies
    STOCK_ISSUES ||--o{ STOCK_ISSUE_ALLOCATIONS : allocates
    DELIVERIES ||--o{ DELIVERY_LINES : contains
    STOCK_RECEIPTS o|--o| DELIVERY_LINES : accepts_as

    USERS {
        integer id PK
        text email UK
        text password_hash
        text role
        integer is_active
    }
    STOCK_RECEIPTS {
        integer id PK
        text receipt_date
        text item_name
        text serial_number UK
        text inventory_number UK
        text project
        text datacenter
        text unit
        real quantity
    }
    STOCK_ISSUES {
        integer id PK
        text issue_date
        text source_serial_number
        text task_type
        text task_number
        real quantity
    }
    STOCK_ISSUE_ALLOCATIONS {
        integer id PK
        integer issue_id FK
        integer receipt_id FK
        real quantity
    }
    DELIVERIES {
        integer id PK
        text source_filename
        text delivery_number
        text supplier
        text status
    }
    DELIVERY_LINES {
        integer id PK
        integer delivery_id FK
        text serial_number
        text state
        integer receipt_id FK
        integer is_unplanned
    }
    REFERENCE_VALUES {
        integer id PK
        text kind
        text name
        integer is_active
    }
    WORK_LOGS {
        integer id PK
        text work_date
        text task_source
        text task_type
        text task_number
        text status
    }
    AUDIT_LOG {
        integer id PK
        text event_date
        text action
        text entity_type
        text entity_id
        text author
    }
    DAILY_REPORT_UPLOADS {
        integer id PK
        text filename
        text uploaded_by
        integer row_count
    }
    DAILY_REPORT_ROWS {
        integer id PK
        integer upload_id FK
        text report_date
        text report_block
    }
```

Баланс вычисляется как сумма `stock_receipts.quantity` минус связанные `stock_issue_allocations.quantity`. Поставка создает обычную запись прихода и связывает ее со строкой через `delivery_lines.receipt_id`.

Stages 0.13.2, 0.13.3A и 0.13.3A.5 не меняют production ER-схему.
`stock_receipts.inventory_number` может быть
пуст при приходе и позже заполняется по S/N; partial unique index защищает
уникальность только непустых значений. При наличии `legacy_equipment_id`
пустой номер связанной legacy `equipment` синхронизируется той же транзакцией.
Audit action хранится в `audit_log` через generic `entity_type/entity_id`, а не
через новый foreign key или отдельную event-таблицу.

## Disposable candidate ER — IMPLEMENTED, не production

Следующие девять таблиц создаются только в ignored
`migration_inputs/workspace/warehouse_migration_candidate.db`. Они намеренно
не входят в `inventory/db.py` и не должны появляться в `data/warehouse.db`.

```mermaid
erDiagram
    MIGRATION_BATCHES ||--o{ MIGRATION_SOURCE_FILES : records
    MIGRATION_BATCHES ||--o{ MIGRATION_STAGING_ROWS : contains
    MIGRATION_BATCHES ||--o{ MIGRATION_VALIDATION_RESULTS : validates
    MIGRATION_SOURCE_FILES ||--o{ MIGRATION_STAGING_ROWS : sources
    REFERENCE_DOMAINS_V2 ||--o{ REFERENCE_VALUES_V2 : contains
    REFERENCE_DOMAINS_V2 ||--o{ REFERENCE_ALIASES_V2 : scopes
    REFERENCE_VALUES_V2 ||--o{ REFERENCE_ALIASES_V2 : resolves_to
    REFERENCE_VALUES_V2 ||--o| CATALOG_ITEMS_V2 : describes
    REFERENCE_VALUES_V2 ||--o{ CATALOG_ITEMS_V2 : structured_fields
    CATALOG_ITEMS_V2 o|--o{ MIGRATION_STAGING_ROWS : proposed_for
    MIGRATION_STAGING_ROWS ||--o{ MIGRATION_SERIAL_CELLS : preserves

    MIGRATION_BATCHES {
        integer id PK
        text batch_key UK
        text stage
        text status
        text source_manifest_sha256
    }
    MIGRATION_SOURCE_FILES {
        integer id PK
        integer batch_id FK
        text source_path
        text sha256
        integer immutable
    }
    REFERENCE_DOMAINS_V2 {
        integer id PK
        text domain_key UK
        text display_name
        integer active
    }
    REFERENCE_VALUES_V2 {
        integer id PK
        integer domain_id FK
        text canonical_value
        text normalized_key
        text scope_key
        text approval_status
    }
    REFERENCE_ALIASES_V2 {
        integer id PK
        integer domain_id FK
        integer canonical_id FK
        text source_value
        text normalized_source_key
        text resolution_status
    }
    CATALOG_ITEMS_V2 {
        integer id PK
        integer reference_value_id FK
        text canonical_item_name
        text part_number
        text resolution_status
    }
    MIGRATION_STAGING_ROWS {
        integer id PK
        integer batch_id FK
        integer source_file_id FK
        text source_row_hash
        text operation_kind
        text source_serial_value
        text normalized_matching_serial
        text resolution_status
        text target_entity_id
    }
    MIGRATION_SERIAL_CELLS {
        integer id PK
        integer staging_row_id FK
        text raw_xml_value
        text source_serial_value
        text normalized_match_value
        text preservation_status
        text source_hash
    }
    MIGRATION_VALIDATION_RESULTS {
        integer id PK
        integer batch_id FK
        text severity
        text code
        text details
    }
```

**FACT:** candidate также содержит clean production schema и security snapshot,
но все operational/audit tables проходят проверку на нулевое количество строк.
Production `reference_values` не заменяется `reference_values_v2`.

**PROPOSED/FUTURE STAGE:** перенос approved reference/staging data в рабочую
модель и возможная production reference migration требуют отдельного ADR и
reset/import workflow. **OPEN DECISION:** окончательная runtime ER для richer
references пока не утверждена.

## Disposable pilot ER — IMPLEMENTED / PILOT ONLY

Stage 0.13.3A.5 copies the validated Stage A candidate into a separate
`warehouse_pilot_candidate.db`, retains the nine candidate tables above and adds
six `migration_pilot_*` tables. They are forbidden in production
`inventory/db.py`.

```mermaid
erDiagram
    MIGRATION_BATCHES ||--o{ MIGRATION_STAGING_ROWS : owns
    MIGRATION_STAGING_ROWS ||--o| MIGRATION_PILOT_SELECTION : selected_from
    MIGRATION_PILOT_MARKER ||--o{ MIGRATION_PILOT_SELECTION : describes
    MIGRATION_PILOT_SELECTION ||--o| MIGRATION_PILOT_IDENTITIES : primary
    STOCK_RECEIPTS ||--o| MIGRATION_PILOT_IDENTITIES : target
    MIGRATION_PILOT_SELECTION ||--|| MIGRATION_PILOT_PROVENANCE : evidence
    STOCK_RECEIPTS o|--o{ MIGRATION_PILOT_PROVENANCE : links
    MIGRATION_PILOT_SELECTION ||--o| MIGRATION_PILOT_QUARANTINE : holds
    MIGRATION_PILOT_MARKER ||--o{ MIGRATION_PILOT_PERFORMANCE : measures

    MIGRATION_PILOT_MARKER {
        integer id PK
        text marker UK
        text stage
        integer pilot_only
        integer review_read_only
        text status
        text selection_sha256
        integer selected_count
        integer imported_count
    }
    MIGRATION_PILOT_SELECTION {
        integer id PK
        integer staging_row_id FK
        text source_serial_value
        text normalized_match_value
        text serial_preservation_status
        text canonical_item_name
        text import_decision
        integer target_receipt_id FK
    }
    MIGRATION_PILOT_IDENTITIES {
        integer id PK
        text normalized_match_value UK
        text preserved_serial_value
        integer primary_selection_id FK
        integer target_receipt_id FK
    }
    MIGRATION_PILOT_PROVENANCE {
        integer id PK
        integer selection_id FK
        integer identity_id FK
        integer target_receipt_id FK
        text source_row_hash
        text source_serial_value
        text import_decision
    }
    MIGRATION_PILOT_QUARANTINE {
        integer id PK
        integer selection_id FK
        text reason_code
        text resolution_status
    }
    MIGRATION_PILOT_PERFORMANCE {
        integer id PK
        text metric UK
        text duration_ms
    }
```

The 130 `IMPORT` primaries and 41 linked duplicate/conflict source rows have
`target_receipt_id`; only the 130 primaries create stock. The other 29 rows are
quarantined/deferred/rejected and have no target. Duplicate/conflict source
rows link provenance to a primary identity but do not create a second receipt.
Pilot receipts have
quantity `1`, exact text S/N and `is_opening_balance=1`; shelf is not a key.

**NOT PRODUCTION / FUTURE 0.13.3B:** this ER is a disposable review result.
Production case-sensitive identity, richer references and historical event
storage remain separate ADR decisions.
