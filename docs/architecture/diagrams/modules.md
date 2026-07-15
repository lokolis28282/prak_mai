# Module dependencies

Статус: **APPROVED — ODE 0.13 architecture baseline**

~~~mermaid
flowchart TB
    UI --> API
    API --> APP["bootstrap/application"]

    APP --> EQ[equipment]
    APP --> INV[inventory]
    APP --> WH[warehouse]
    APP --> BAL[balance]
    APP --> HIST[legacy history]
    APP --> IMP[imports]
    APP --> REF[references/catalog]
    APP --> USR[users]
    APP --> SEC[security]
    APP --> AUD[audit]
    APP --> REP[reports]

    INV -->|public ports| EQ
    INV -->|ledger head| WH
    INV -->|activate projection| BAL
    INV -->|resolve approved refs| REF
    WH -->|identity/catalog/location queries| EQ
    WH --> REF
    WH -->|availability query| BAL
    BAL -->|snapshot and ledger queries| INV
    BAL --> WH
    HIST -->|optional identity resolution| EQ
    IMP -->|read-only matching| EQ
    IMP --> REF
    REP -->|public query contracts| EQ
    REP --> INV
    REP --> WH
    REP --> BAL
    REP --> HIST

    SEC --> USR
    APP --> INFRA[infrastructure]
    INFRA -.->|implements repository/UoW ports| EQ
    INFRA -.-> INV
    INFRA -.-> WH
    INFRA -.-> BAL
    INFRA -.-> HIST
    INFRA -.-> IMP
    INFRA -.-> REF
    INFRA -.-> USR
    INFRA -.-> SEC
    INFRA -.-> AUD
~~~

Стрелка не разрешает direct repository access. Циклы query ports между balance
и ledger/inventory разрешаются constructor injection и не являются Python
import cycles domain models.
