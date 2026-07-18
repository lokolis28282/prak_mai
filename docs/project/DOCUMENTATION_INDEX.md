# Documentation Index

## Current

- `docs/project/CURRENT_STATE.md` — единый status snapshot.
- root `README.md` — пользовательская инструкция текущего Warehouse.
- root `CHANGELOG.md` — living change history.
- `AGENTS.md` — обязательные repository guardrails.
- `docs/LOCAL_WORKING_DATABASE_RUNBOOK.md` — operational DB procedure.
- Warehouse living architecture contracts из `DECISIONS_INDEX.md`.
- `docs/MANUAL_TESTING_0_14_FULL_INVENTORY.md` — операторская приёмка 0.14.
- `RELEASE_REPORT_ODE_0_14_0.md` — readiness evidence и ограничения.
- `docs/MONITORING_HOSTNAME_ROUTING.md` — реализованный изолированный routing
  contract и правила локальных данных.
- `docs/CODEBASE_GRAPH.md` — GitHub-rendered карта поддерживаемых зависимостей.
- `docs/MONITORING_KNOWLEDGE_GUIDE.md` — настройка Monitoring/Knowledge и
  backup-guarded runtime module migration.
- `RELEASE_REPORT_ODE_0_14_INTEGRATION.md` — integration/release evidence от
  2026-07-18.

## Normative target

- `docs/decisions/ADR-*`.
- `docs/architecture/*.md` со статусом APPROVED.
- `docs/architecture/ddl/V001..V008` и DDL review results.
- `docs/development/implementation-order.md` — только Platform delivery track.

`docs/README.md` остаётся индексом target ODE architecture, а не единственным
current-state документом всего repository.

## Immutable/datestamped evidence

- `docs/development/STAGE_0_13_1_*REVIEW*.md`;
- `docs/architecture/ddl/*REVIEW*.md`;
- migration review reports;
- root release/QA/security/UX reports;
- `.stabilization/` local evidence.

Evidence не переписывается задним числом. Новый verdict получает новый
датированный файл.

Актуальная цепочка независимой проверки и cleanup:

- `docs/project/reviews/2026-07-15_WAREHOUSE_STABILIZATION_REVIEW.md`;
- `docs/project/reviews/2026-07-15_REPOSITORY_CLEANUP_AUDIT.md`;
- `docs/project/reviews/2026-07-15_REPOSITORY_CLEANUP_EXECUTION.md`.
- `docs/project/reviews/2026-07-15_WAREHOUSE_OPERATIONAL_ACCEPTANCE.md`.
- `docs/project/reviews/2026-07-15_SCANNER_OPERATIONS_0_13_4.md`.

## Historical or scoped

- старые `MANUAL_TESTING_*`, release reports и migration plans действуют только
  в указанном scope;
- старый Monitoring integration review анализирует исторический placeholder;
  текущий hostname-routing slice описан отдельным living contract выше.

Root-level evidence сохранён как датированные снимки и не переписывается
задним числом:

| Документ | Scope |
|---|---|
| [`ACCEPTANCE_ODE_0_12.md`](../../ACCEPTANCE_ODE_0_12.md) | Общая приёмка ODE 0.12 |
| [`ACCEPTANCE_DELIVERIES_0_12_16.md`](../../ACCEPTANCE_DELIVERIES_0_12_16.md) | Приёмка поставок 0.12.16 |
| [`ARCHITECT_REVIEW.md`](../../ARCHITECT_REVIEW.md) | Исторический architecture review |
| [`CODE_REVIEW.md`](../../CODE_REVIEW.md) | Исторический code review |
| [`PRODUCT_REVIEW.md`](../../PRODUCT_REVIEW.md) | Исторический product review |
| [`PERFORMANCE_REVIEW.md`](../../PERFORMANCE_REVIEW.md) | Исторический performance review |
| [`SECURITY_REVIEW.md`](../../SECURITY_REVIEW.md) | Исторический security review |
| [`UX_REVIEW.md`](../../UX_REVIEW.md) | Исторический UX review |
| [`BUG_REPORT.md`](../../BUG_REPORT.md) | Ранний общий bug report |
| [`BUGS_0_12.md`](../../BUGS_0_12.md) | Known bugs ODE 0.12 |
| [`BUGS_DELIVERIES_0_12_16.md`](../../BUGS_DELIVERIES_0_12_16.md) | Bugs поставок 0.12.16 |
| [`BUGS_STAGE_0_12_17.md`](../../BUGS_STAGE_0_12_17.md) | Bugs Stage 0.12.17 |
| [`QA_REPORT.md`](../../QA_REPORT.md) | Ранний общий QA snapshot |
| [`QA_STAGE_0_12_17.md`](../../QA_STAGE_0_12_17.md) | QA Stage 0.12.17 |
| [`RELEASE_REPORT.md`](../../RELEASE_REPORT.md) | Ранний release snapshot |
| [`RELEASE_REPORT_ODE_0_12_16_RC1.md`](../../RELEASE_REPORT_ODE_0_12_16_RC1.md) | Release 0.12.16 RC1 |
| [`RELEASE_REPORT_ODE_0_12_17_RC1.md`](../../RELEASE_REPORT_ODE_0_12_17_RC1.md) | Release 0.12.17 RC1 |
| [`RELEASE_REPORT_ODE_0_13_2.md`](../../RELEASE_REPORT_ODE_0_13_2.md) | Warehouse Stage 0.13.2, не Platform Stage 0.13.2 |
| [`RELEASE_REPORT_ODE_0_14_0.md`](../../RELEASE_REPORT_ODE_0_14_0.md) | FULL Inventory safety workflow и candidate rehearsal |
| [`CHECKPOINT_ODE.md`](../../CHECKPOINT_ODE.md) | Маленькая DB до full promotion; не current DB status |
| [`WINDOWS_RELEASE.md`](../../WINDOWS_RELEASE.md) | Текущая release-инструкция Windows, не фактический новый ZIP |

## Prompts

Prompts не являются архитектурным решением или evidence реализации. Они
хранятся только с датой, scope и статусом `ACTIVE`/`SUPERSEDED`.
