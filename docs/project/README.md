# ODE Project Hub

Дата актуализации: 2026-07-19.

Это главная точка входа в текущее состояние проекта. Hub не копирует ADR,
DDL или stage evidence, а связывает их и явно разделяет два параллельных
трека разработки.

## Обязательный порядок чтения

1. [CURRENT_STATE.md](CURRENT_STATE.md) — что реально работает сейчас.
2. [MASTER_CONTEXT.md](MASTER_CONTEXT.md) — продуктовая цель и границы.
3. [ROADMAP.md](ROADMAP.md) — последовательность дальнейшей работы.
4. [ENGINEERING_WORKFLOW.md](ENGINEERING_WORKFLOW.md) — безопасный цикл изменений.
5. [REPOSITORY_MAP.md](REPOSITORY_MAP.md) — код, данные и артефакты.
6. [DECISIONS_INDEX.md](DECISIONS_INDEX.md) — нормативные ADR/DDL и контракты.
7. [DOCUMENTATION_INDEX.md](DOCUMENTATION_INDEX.md) — статус документации.
8. [RISKS_AND_BACKLOG.md](RISKS_AND_BACKLOG.md) — риски и отложенная работа.
9. [AGENT_HANDOFF.md](AGENT_HANDOFF.md) — минимальный handoff нового агента.

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
