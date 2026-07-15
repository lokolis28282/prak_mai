# ER-модель ODE 0.13

Статус: **APPROVED**. Диаграмма показывает ownership и основные связи; полный
набор колонок находится в [data-model.md](../data-model.md).

~~~mermaid
erDiagram
    USERS ||--o{ USER_ROLES : assigned
    ROLES ||--o{ USER_ROLES : grants
    ROLES ||--o{ ROLE_PERMISSIONS : contains
    PERMISSIONS ||--o{ ROLE_PERMISSIONS : grants
    USERS ||--o{ SESSIONS : authenticates
    REFERENCE_DOMAINS ||--o{ REFERENCE_VALUES : contains
    REFERENCE_VALUES ||--o{ REFERENCE_ALIASES : resolves
    REFERENCE_VALUES ||--o{ CATALOG_ITEMS : classifies
    UOMS ||--o{ CATALOG_ITEMS : measures
    WAREHOUSES ||--o{ WAREHOUSE_LOCATIONS : contains

    CATALOG_ITEMS ||--o{ EQUIPMENT : describes
    EQUIPMENT ||--o{ EQUIPMENT_IDENTITIES : identifies
    EQUIPMENT ||--o| EQUIPMENT_MERGES : source

    IMPORT_COMMITS ||--o{ IMPORT_ROW_LINKS : proves
    IMPORT_COMMITS ||--o{ IMPORT_FINDINGS : records
    IMPORT_COMMITS ||--o{ IMPORT_RESOLUTIONS : records
    IMPORT_FINDINGS o|--o{ IMPORT_RESOLUTIONS : resolved_by
    IMPORT_COMMITS ||--|| INVENTORY_SESSIONS : publishes
    INVENTORY_SESSIONS ||--|| INVENTORY_SNAPSHOTS : approves
    INVENTORY_SNAPSHOTS ||--o{ INVENTORY_SNAPSHOT_ITEMS : contains
    INVENTORY_SNAPSHOTS ||--o{ INVENTORY_RECONCILIATION_ITEMS : explains
    IMPORT_ROW_LINKS ||--o| INVENTORY_SNAPSHOT_ITEMS : sources

    INVENTORY_SNAPSHOTS ||--o{ WAREHOUSE_TRANSACTIONS : baseline
    WAREHOUSE_TRANSACTIONS ||--|{ WAREHOUSE_TRANSACTION_LINES : contains
    WAREHOUSE_TRANSACTIONS o|--o| WAREHOUSE_TRANSACTIONS : reverses

    INVENTORY_SNAPSHOTS ||--o{ BALANCE_PROJECTION_VERSIONS : derives
    BALANCE_PROJECTION_VERSIONS ||--o{ BALANCE_PROJECTION_ROWS : contains

    LEGACY_SOURCE_FILES ||--o{ LEGACY_HISTORY_EVENTS : contains
    LEGACY_HISTORY_EVENTS ||--o{ LEGACY_HISTORY_WARNINGS : warns
    LEGACY_HISTORY_EVENTS ||--o{ LEGACY_HISTORY_EQUIPMENT_LINKS : resolves
    EQUIPMENT ||--o{ LEGACY_HISTORY_EQUIPMENT_LINKS : optionally_links

    USERS o|--o{ AUDIT_EVENTS : acts
    USERS ||--o{ REPORT_JOBS : requests
~~~

Запрещенная связь отсутствует намеренно: LEGACY_HISTORY_EVENTS не связана с
BALANCE_PROJECTION_ROWS и не является источником WAREHOUSE_TRANSACTIONS.
