# ODE 0.21.0 — карта кода и зависимостей

![ODE 0.21.0 architecture graph](assets/ode-architecture-graph.svg)

## Граф файлов и импортов

[![ODE 0.21.0 — граф файлов и импортов](assets/ode-code-graph-0.21.0.png)](assets/code_graph.html)

- GitHub-friendly PNG:
  [`assets/ode-code-graph-0.21.0.png`](assets/ode-code-graph-0.21.0.png);
- интерактивный self-contained HTML:
  [`assets/code_graph.html`](assets/code_graph.html).

Детерминированный committed graph ODE 0.21.0 после полного system audit
содержит 252 файла/модуля и 512 import/serve edges. Статический PNG и
интерактивная карта построены из текущего `code_graph.html`.
Последний успешно зафиксированный внешний full-снимок Codebase Memory от
2026-08-11 содержит 7 774 узла и 33 376 рёбер (`skipped_count=0`). Он создан
для текущего дерева с `persistence=false`; `artifact_present=false` и
`.codebase-memory` в repository нет.

## Runtime path

```mermaid
flowchart LR
  App["app.py"] --> Web["inventory/webapp.py<br/>HTTP shell · auth · sessions"]
  Web --> Templates["inventory/templates/<br/>HTML assembly"]
  Web --> Routes["inventory/routes/<br/>domain HTTP handlers"]
  Web --> Static["static/css + static/js"]
  Web --> Context["ApplicationContext"]
  Web --> Sites["WarehouseSiteRegistry<br/>session site selection"]

  Routes --> Context
  Routes -. "legacy runtime metadata / lock / preview adapter" .-> Compat["WarehouseService<br/>compatibility only"]
  Context --> W["WarehouseFacade · IXcellerate"]
  Sites --> WS["WarehouseFacade · Solar"]
  Context --> R["ReportsFacade"]
  Context --> M["MonitoringFacade"]
  Context --> K["KnowledgeFacade"]
  Context --> V["VacationFacade"]
  Context --> A["AdministrationFacade"]

  W --> WD["Warehouse domain services<br/>receipt · issue · delivery · balance · history"]
  R --> RD["Reports services/repository<br/>work logs · daily · weekly"]
  A --> AD["AdministrationService<br/>users · audit · backup · diagnostics"]
  AD --> REG["RuntimeDatabaseRegistry<br/>IX · Solar · Vacations"]
  AD --> MDB["MultiDatabaseBackupService<br/>status · verified snapshot"]
  K --> KD["Knowledge repository<br/>articles · tags · attachments"]
  V --> VD["Vacations services/repository<br/>calendar · assignments · conflicts"]
  M --> MD["manual hostname/DCIM flow<br/>local ignored rules"]

  WD --> DB[("data/warehouse.db")]
  WS --> WDS["Warehouse domain services · Solar"]
  WDS --> SDB[("data/warehouse_solar.db")]
  Compat --> WD
  RD --> DB
  AD --> DB
  KD --> DB
  VD --> VDB[("data/vacations.db")]
  MDB --> EXT[("external backup root<br/>SQLite API · manifests")]
  WD --> Events["WarehouseEventReader"]
  Events --> R
```

Фактический web-path в 0.21.0:

`browser → webapp HTTP shell → session WarehouseSite → inventory/routes →
selected facade → domain service/repository → selected SQLite`.

Shared Administration, Reports, Monitoring, Knowledge и Vacations продолжают
получать primary `ApplicationContext`; Warehouse routes получают выбранный
site runtime.

`inventory/templates` отвечает только за детерминированную HTML-сборку.
Стили и браузерная логика реально загружаются из `static/`; SQL в
`inventory/routes` и `inventory/templates` отсутствует.

`RouteRuntime` пока также передаёт compatibility `WarehouseService`: route
handlers используют его для общего lock, пути/имени БД, старых констант и
одного preview adapter. Это не вторая реализация SQL, но реальная оставшаяся
связь, которую нельзя скрывать на карте. Новые business-вызовы через неё
добавлять запрещено.

## Границы модулей

| Контур | Вход | Реализация | Данные/зависимости |
|---|---|---|---|
| Warehouse | `WarehouseFacade` + `WarehouseSiteRegistry` | `inventory/warehouse/` | независимые `stock_*`, deliveries, balance/history в IXcellerate/Solar; публикует события |
| Reports | `ReportsFacade` | `inventory/reports/` | `work_logs`, `daily_report_*`; Warehouse читает только через `WarehouseEventReader` |
| Administration | `AdministrationFacade` | `AdministrationService` + runtime registry + multi-DB backup service | users, audit, diagnostics, status/create backup; restore disabled |
| Monitoring | `MonitoringFacade` | `inventory/monitoring/` | локальные ignored rules, hostname/project/ИС routing и optional DCIM; не импортирует Warehouse/Reports |
| Knowledge | `KnowledgeFacade` | `inventory/knowledge/` | `knowledge_*` и private attachments |
| Vacations | `VacationFacade` | `inventory/vacations/` | собственные `vacation_*` и audit в `data/vacations.db`; складские БД не используются |

`WarehouseService` и `WarehouseCore` сохранены как compatibility path для CLI,
старых тестов и ещё не перенесённых Python-вызовов. Они делегируют тем же
экземплярам domain-сервисов и не содержат второй реализации складского,
Reports или Administration SQL.

## Offline и target contours

```mermaid
flowchart LR
  Migration["scripts/migration_*"] --> Offline["inventory/migration<br/>offline only"]
  Offline --> Candidate[("ignored disposable candidate DB")]

  Warehouse["WarehouseFacade"] --> Full["FULL Inventory Preview"]
  Full --> Workspace["external ignored workspace"]
  Workspace --> Rehearsal["baseline_rehearsal"]
  Rehearsal --> Target[("disposable ODE target DB")]

  ODE["ode/ target platform"] -. "side-by-side; no cutover" .-> Target
  Candidate -. "never runtime DB" .- Working[("data/warehouse.db")]
```

Migration packages не импортируются runtime Web/API и не публикуют результат
в рабочую БД автоматически. `ode/` остаётся отдельным target-platform треком.

## Как поддерживать карту

- `python3 scripts/generate_code_graph.py` обновляет
  [`assets/code_graph.html`](assets/code_graph.html) из Python AST и
  static-layout; версия читается из `inventory.__version__`.
- PNG `assets/ode-code-graph-0.21.0.png` является GitHub-снимком текущего
  интерактивного графа. При каждом version bump он создаётся заново после
  стабилизации layout; старый versioned PNG запрещено показывать как current.
- `python3 scripts/generate_code_graph.py --check` завершает gate ошибкой, если
  committed HTML устарел или текущий versioned PNG отсутствует.
- `python3 scripts/refresh_project_knowledge.py` обновляет HTML-граф и делает
  внешний full Codebase Memory reindex с `persistence=false`.
- После каждого существенного изменения кода/топологии refresh обязателен;
  найденные связи нужно перепроверять через `rg`, source-read и тесты.

Codebase Memory cache и `.codebase-memory` artifact запрещено коммитить: они
могут содержать подробную структуру кода и быстро устаревают. Безопасная
процедура и исключения описаны в
[`CODEBASE_MEMORY_MCP.md`](CODEBASE_MEMORY_MCP.md).
