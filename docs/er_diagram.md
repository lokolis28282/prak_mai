# Модель данных ODE

Диаграмма показывает рабочую модель. Таблицы `equipment`, `operations`,
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

Stage 0.13.2 не меняет ER-схему. `stock_receipts.inventory_number` может быть
пуст при приходе и позже заполняется по S/N; partial unique index защищает
уникальность только непустых значений. При наличии `legacy_equipment_id`
пустой номер связанной legacy `equipment` синхронизируется той же транзакцией.
Audit action хранится в `audit_log` через generic `entity_type/entity_id`, а не
через новый foreign key или отдельную event-таблицу.
