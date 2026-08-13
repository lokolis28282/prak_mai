# ODE Project Hub

Дата актуализации: 2026-08-13. Текущий source/runtime: ODE 0.21.1 release
candidate; физический Windows sign-off остаётся PENDING.

Это главная точка входа в текущее состояние проекта. Hub не копирует ADR,
DDL или stage evidence, а связывает их и явно разделяет два параллельных
трека разработки.

## Обязательный порядок чтения

1. [CURRENT_STATE.md](CURRENT_STATE.md) — что реально работает сейчас.
2. [MASTER_CONTEXT.md](MASTER_CONTEXT.md) — продуктовая цель и границы.
3. [SYSTEM_FUNCTION_MATRIX.md](SYSTEM_FUNCTION_MATRIX.md) — полный список
   функций, storage boundaries и проверок.
4. [ROADMAP.md](ROADMAP.md) — последовательность дальнейшей работы.
5. [ENGINEERING_WORKFLOW.md](ENGINEERING_WORKFLOW.md) — безопасный цикл изменений.
6. [REPOSITORY_MAP.md](REPOSITORY_MAP.md) — код, данные и артефакты.
7. [DECISIONS_INDEX.md](DECISIONS_INDEX.md) — нормативные ADR/DDL и контракты.
8. [DOCUMENTATION_INDEX.md](DOCUMENTATION_INDEX.md) — статус документации.
9. [RISKS_AND_BACKLOG.md](RISKS_AND_BACKLOG.md) — риски и отложенная работа.
10. [AGENT_HANDOFF.md](AGENT_HANDOFF.md) — минимальный handoff нового агента.
11. [USER_GUIDE.md](../USER_GUIDE.md) — рабочая инструкция оператора.
12. [DEVELOPER_GUIDE.md](../DEVELOPER_GUIDE.md) — вход для разработчика и
    code reviewer.
13. [Authentication/API access](../AUTHENTICATION_AND_API_ACCESS.md) — два
    режима входа, cookie session и отсутствие API-key auth.
14. [Runtime configuration](../RUNTIME_CONFIGURATION.md) — CLI/env, defaults и
    test/review flags.
15. [Multi-Warehouse](../MULTI_WAREHOUSE_ARCHITECTURE.md) — физическая
    изоляция IXcellerate/Solar и bootstrap Solar.
16. [Vacations](../VACATIONS_ARCHITECTURE.md) — самостоятельный календарь,
    графики и очередь конфликтов двух площадок.
17. [Multi-DB backup/restore](../decisions/ADR-013-multi-database-backup-restore.md)
    — реализованный status/create-backup slice и обязательный контракт будущего
    restore.
18. [Windows manual QA 0.21.1](../MANUAL_TESTING_0_21_1_WINDOWS.md) —
    обязательный double-click checklist и честный PENDING до физической
    приёмки.
19. [История версий](VERSION_HISTORY.md) и root
    [`CONTRIBUTORS.md`](../../CONTRIBUTORS.md) — lineage и нейтральное
    распределение направлений.
20. [Reports architecture](../REPORTS_ARCHITECTURE.md) — УВР, PNR, передача по
    смене, XLSX/CSV contracts и граница Warehouse events.

## Иерархия источников

1. Approved ADR/DDL и явно утверждённые бизнес-инварианты.
2. Фактический код и исполняемые tests.
3. `CURRENT_STATE.md` и действующие operational runbooks.
4. Профильные living architecture contracts.
5. `MASTER_CONTEXT.md` и roadmap.
6. Immutable review/migration evidence.
7. Исторические prompts, QA и release reports.

При конфликте нельзя молча выбирать удобный документ. Конфликт фиксируется в
`CURRENT_STATE.md` или `RISKS_AND_BACKLOG.md`, после чего изменение либо
сужается до безопасного scope, либо останавливается до решения владельца.
