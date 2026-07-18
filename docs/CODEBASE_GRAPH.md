# ODE code relationships

![ODE 0.14 architecture graph](assets/ode-architecture-graph.svg)

Снимок Codebase Memory от 2026-07-18 содержит 6 184 nodes, 26 241 edges,
470 files и 26 распознанных HTTP routes. В Git публикуется только эта
обобщённая карта; локальный индекс и внутренние данные не публикуются.

GitHub отображает эту Mermaid-диаграмму прямо на странице документа. Она
показывает поддерживаемые архитектурные связи, а не пытается публиковать
внутреннюю базу Codebase Memory.

```mermaid
flowchart TB
  App["app.py"] --> Web["inventory/webapp.py"]
  App --> CLI["inventory/cli.py"]
  Web --> Context["ApplicationContext"]
  CLI --> Context

  Context --> Warehouse["WarehouseFacade"]
  Context --> Reports["ReportsFacade"]
  Context --> Monitoring["MonitoringFacade"]
  Context --> Knowledge["KnowledgeFacade"]
  Context --> Admin["AdministrationFacade"]

  Warehouse --> Stock["receipts / issues / allocations / balance / history"]
  Stock --> DB[("data/warehouse.db")]
  Reports --> Events["WarehouseEventReader"]
  Events --> Warehouse
  Reports --> ReportTables["work logs / daily reports"]
  ReportTables --> DB
  Admin --> Security["users / audit / backup / diagnostics"]
  Security --> DB
  Knowledge --> KnowledgeTables["articles / tags / attachment metadata"]
  KnowledgeTables --> DB

  Monitoring --> Routing["hostname_routing.py"]
  Rules["local ignored Tech/Digital JSON"] --> Routing
  Generator["offline XLSX generator"] --> Rules

  Warehouse --> FullInventory["FULL Inventory workspace"]
  FullInventory --> Rehearsal["isolated baseline rehearsal"]
  Rehearsal --> Candidate[("disposable target candidate")]

  Migration["inventory/migration offline"] -. "candidate tooling only" .-> Candidate
```

Отсутствие стрелок Monitoring → Warehouse/Reports является обязательной
границей, а не пропущенной связью.

Интерактивный граф уровня функций/классов из Codebase Memory, похожий на
трёхмерный скриншот, является локальным developer UI и не является встроенной
функцией GitHub. Его cache и `.codebase-memory` artifact запрещено коммитить:
они могут содержать структуру внутреннего кода и быстро устаревают. Текущая
проверенная процедура локальной индексации описана в
[`CODEBASE_MEMORY_MCP.md`](CODEBASE_MEMORY_MCP.md).
