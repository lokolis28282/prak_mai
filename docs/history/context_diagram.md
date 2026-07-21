# Контекстная диаграмма ODE

Диаграмма отражает source Stage 0.13.3A.5; runtime metadata остаётся
`0.12.17.1 RC2`. Внешние интеграции с DCIM, Kaiten и мониторингом не
реализованы.

```mermaid
flowchart LR
    Supply[Снабжение / поставщик] -->|CSV поставки и оборудование| ODE((ODE))
    Admin[Администратор] -->|Пользователи, backup, восстановление| ODE
    Engineer[Инженер] -->|Приход, расход, сканирование, логи, CSV Inventory Number| ODE
    Viewer[Наблюдатель] -->|Поиск, баланс и отчеты| ODE
    Scanner[USB/Bluetooth-сканер] -->|S/N или QR как клавиатурный ввод| ODE
    ODE -->|Статус приемки и CSV-результат| Supply
    ODE -->|Баланс, карточки, аудит и отчеты| Admin
    ODE -->|Preview/результаты операций, Timeline и проблемные строки| Engineer
    DB[(data/warehouse.db)] <--> ODE
    Backups[(data/backups)] <--> ODE

    Analyst[Migration engineer] -->|offline CLI| Migration[Reference/Staging tooling]
    Raw[(immutable migration_inputs/raw)] -->|read-only OOXML/TXT| Migration
    DB -.->|mode=ro + query_only; SHA/security snapshot| Migration
    Migration -->|generated, ignored| Candidate[(migration_inputs/workspace/candidate DB)]
    Migration -.->|forbidden: production write| DB

    Reviewer[Migration reviewer] -->|explicit pilot launcher; admin/engineer| PilotUI[Read-only pilot UI]
    Candidate -->|deterministic 200-row selection| PilotBuild[Pilot builder]
    Raw -->|SHA-pinned source evidence| PilotBuild
    PilotBuild -->|130 IMPORT primaries; ignored| PilotDB[(warehouse_pilot_candidate.db)]
    PilotDB -->|marker-guarded read only| PilotUI
    PilotBuild -.->|forbidden| DB
    PilotUI -.->|operational POST denied| DB
```

ODE слушает `127.0.0.1:8765` по умолчанию. Состояние хранится в локальной SQLite-базе; сервер приложения не обращается к интернету.

**IMPLEMENTED:** `inventory/migration` и
`scripts/migration_reference_data.py` изолированы от Web/API runtime. Candidate
содержит 16 reference domains и девять staging/reference tables только для
review; historical receipt/issue не импортируется.

**FUTURE STAGE / OPEN DECISION:** перенос утверждённых candidate data и замена
рабочей БД отсутствуют на диаграмме как действующие потоки, потому что требуют
отдельного stage, backup/reset gate и явного подтверждения.

**IMPLEMENTED / PILOT ONLY (0.13.3A.5):** reviewer sees a fixed 200-row sample,
source/canonical names, exact S/N, provenance and audit-backed Timeline. The
pilot DB is neither the Stage A candidate nor the production DB; launch requires
an exact marker and environment opt-in. The source contains R220 but no R200,
and the pilot does not synthesize missing source data.
