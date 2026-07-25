# System context

Статус: **APPROVED — ODE 0.13 architecture baseline**

~~~mermaid
flowchart LR
    Engineer["Инженер ЦОД<br/>физическое сканирование"] -->|Approved XLSX| Operator
    Operator["Operator"] -->|HTTPS / local browser| UI
    Admin["Admin"] -->|HTTPS / local browser| UI
    Auditor["Auditor"] -->|Read-only UI/API| UI

    subgraph ODE["Trust boundary: ODE 0.13 modular monolith"]
        UI["UI"]
        API["API v1"]
        APP["Application + domain modules"]
        UI --> API --> APP
    end

    APP -->|Operational state| SQLite[("SQLite ODE 0.13")]
    APP -->|Immutable sources| Vault[("Filesystem source vault")]
    APP -->|Untrusted pre-approval data| Workspace[("Preview workspace DB")]
    APP -->|Candidate / backup / restore| Storage[("Protected filesystem storage")]

    Legacy["Legacy Excel files"] -->|Archive import only| Vault
    DCIM["Future DCIM<br/>out of scope"] -.->|Versioned API, future| API

    Attacker["Untrusted browser/file/network input"] -.-> UI
    Attacker -.-> API
~~~

SQLite и filesystem находятся на local filesystem. Future DCIM не получает
direct DB access. Kafka и микросервисы отсутствуют.
