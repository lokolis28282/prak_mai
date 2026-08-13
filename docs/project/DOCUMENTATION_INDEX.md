# Индекс документации ODE 0.21.1

Актуализировано: 2026-08-13.

Документы разделены по статусу. Только раздел «Текущий продукт» описывает
поведение установленного source/runtime ODE 0.21.1 целиком. Версионные release-
отчёты и датированные reviews остаются неизменяемыми доказательствами своего
этапа и не должны восприниматься как текущая инструкция.

## Текущий продукт

| Что нужно узнать | Основной документ |
|---|---|
| Понятная инструкция для инженера | [`ODE_USER_GUIDE.md`](../../ODE_USER_GUIDE.md), offline [`HTML`](../../ODE_USER_GUIDE.html) |
| Текущая презентация для руководителя | [`ODE_PRESENTATION.html`](../../ODE_PRESENTATION.html) — автономный обзор возможностей и планов |
| Установка, запуск, функции пользователя | [`README.md`](../../README.md) |
| Пошаговая рабочая инструкция оператора | [`USER_GUIDE.md`](../USER_GUIDE.md) |
| Вход для разработчика и code reviewer | [`DEVELOPER_GUIDE.md`](../DEVELOPER_GUIDE.md) |
| Вход, cookie API и статус API keys | [`AUTHENTICATION_AND_API_ACCESS.md`](../AUTHENTICATION_AND_API_ACCESS.md) |
| CLI/env и runtime paths | [`RUNTIME_CONFIGURATION.md`](../RUNTIME_CONFIGURATION.md) |
| Текущий status snapshot | [`CURRENT_STATE.md`](CURRENT_STATE.md) |
| Архитектура и границы модулей | [`ARCHITECTURE.md`](../../ARCHITECTURE.md) |
| API и permissions | [`API_REFERENCE.md`](../API_REFERENCE.md) |
| Полная матрица экранов, функций и проверок | [`SYSTEM_FUNCTION_MATRIX.md`](SYSTEM_FUNCTION_MATRIX.md) |
| Frontend/кнопочные контракты | [`FRONTEND_CONTRACTS.md`](../FRONTEND_CONTRACTS.md) |
| Рабочие IXcellerate/Solar/Vacations DB | [`LOCAL_WORKING_DATABASE_RUNBOOK.md`](../LOCAL_WORKING_DATABASE_RUNBOOK.md) |
| Windows source/runtime | [`README_WINDOWS.md`](../../README_WINDOWS.md) |
| Windows release procedure | [`WINDOWS_RELEASE.md`](../../WINDOWS_RELEASE.md) |
| Windows double-click QA | [`MANUAL_TESTING_0_21_1_WINDOWS.md`](../MANUAL_TESTING_0_21_1_WINDOWS.md) — PENDING до физической проверки |
| Текущий release gate | [`RELEASE_REPORT_ODE_0_21_1.md`](../../RELEASE_REPORT_ODE_0_21_1.md) |
| Версии и участники | [`VERSION_HISTORY.md`](VERSION_HISTORY.md), [`CONTRIBUTORS.md`](../../CONTRIBUTORS.md) |
| Риски и открытый технический долг | [`RISKS_AND_BACKLOG.md`](RISKS_AND_BACKLOG.md), [`TECH_DEBT.md`](../../TECH_DEBT.md) |

Дополнительные living-контракты:

- [`DATABASE_OWNERSHIP.md`](../DATABASE_OWNERSHIP.md) — владельцы таблиц и
  допустимые направления зависимостей;
- [`MODULE_ARCHITECTURE.md`](../MODULE_ARCHITECTURE.md) — фасады и постепенное
  извлечение из compatibility core;
- [`REPORTS_ARCHITECTURE.md`](../REPORTS_ARCHITECTURE.md) — УВР/PNR, передача,
  фильтры, импорт и экспортные контракты Reports;
- [`SECURITY_BOUNDARIES.md`](../SECURITY_BOUNDARIES.md) — session/role,
  permissions и fail-closed границы;
- [`AUTHENTICATION_AND_API_ACCESS.md`](../AUTHENTICATION_AND_API_ACCESS.md) —
  фактические login payloads, session lifecycle, отсутствие API-key auth и
  future machine-auth gate;
- [`RUNTIME_CONFIGURATION.md`](../RUNTIME_CONFIGURATION.md) — поддержанные
  аргументы, env, defaults и test/review flags;
- [`VACATIONS_ARCHITECTURE.md`](../VACATIONS_ARCHITECTURE.md) — отдельная
  Vacations DB;
- [`MONITORING_HOSTNAME_ROUTING.md`](../MONITORING_HOSTNAME_ROUTING.md) и
  [`MONITORING_KNOWLEDGE_GUIDE.md`](../MONITORING_KNOWLEDGE_GUIDE.md) —
  Monitoring/Knowledge;
- [`reviews/2026-08-11_ODE_0_21_0_MONITORING_INTEGRATION_AUDIT.md`](reviews/2026-08-11_ODE_0_21_0_MONITORING_INTEGRATION_AUDIT.md)
  — текущий Monitoring integration/release evidence;
- [`reviews/2026-08-11_ODE_0_21_0_DOCUMENTATION_AND_API_ACCESS_AUDIT.md`](reviews/2026-08-11_ODE_0_21_0_DOCUMENTATION_AND_API_ACCESS_AUDIT.md)
  — полный semantic documentation/auth/API/configuration follow-up;
- [`operations/backup-restore.md`](../operations/backup-restore.md) —
  реализованный multi-database backup и отключённый restore;
- [`CODEBASE_GRAPH.md`](../CODEBASE_GRAPH.md) и
  [`assets/code_graph.html`](../assets/code_graph.html) — текущая карта кода.

Текущий release evidence:

- [`RELEASE_REPORT_ODE_0_21_1.md`](../../RELEASE_REPORT_ODE_0_21_1.md) —
  patch prerelease исправления Windows package/launcher и runtime path guards;
- [`MANUAL_TESTING_0_21_1_WINDOWS.md`](../MANUAL_TESTING_0_21_1_WINDOWS.md) —
  физический Windows checklist со статусом PENDING до исполнения;

- [`RELEASE_REPORT_ODE_0_20_0.md`](../../RELEASE_REPORT_ODE_0_20_0.md) —
  выпуск поиска по целевой железке и состава оборудования;
- [`2026-08-02_ODE_0_20_0_FULL_SYSTEM_AUDIT.md`](reviews/2026-08-02_ODE_0_20_0_FULL_SYSTEM_AUDIT.md)
  — полный Documentation/System/UI gate этой ревизии.
- [`2026-08-02_ODE_0_20_0_CURRENT_VISUALS_FIX.md`](reviews/2026-08-02_ODE_0_20_0_CURRENT_VISUALS_FIX.md)
  — исправление GitHub-visible PNG/SVG и защита от показа старого графа.
- [`2026-08-07_ODE_0_20_0_FULL_STABILIZATION_AUDIT.md`](reviews/2026-08-07_ODE_0_20_0_FULL_STABILIZATION_AUDIT.md)
  — полный code/backend/frontend/data/documentation gate и исправления
  подтверждённых дефектов.
- [`2026-08-07_ODE_0_20_0_REPORTS_INTEGRATION_AUDIT.md`](reviews/2026-08-07_ODE_0_20_0_REPORTS_INTEGRATION_AUDIT.md)
  — ancestry review ветки `reports`, интеграция УВР/PNR/XLSX и повторный
  полный release gate.

## Нормативная целевая архитектура

Эти документы определяют утверждённое будущее направление, но сами по себе не
доказывают наличие функции в runtime:

- [`decisions/`](../decisions/) — ADR, включая restore ADR-013 и складские
  коррекции ADR-014;
- [`architecture/`](../architecture/) — документы со статусом `APPROVED` и DDL
  V001..V008;
- [`development/implementation-order.md`](../development/implementation-order.md)
  — Platform delivery track.

[`docs/README.md`](../README.md) индексирует этот target track. Для ответа на
вопрос «что работает сейчас» сначала используйте `CURRENT_STATE.md` и матрицу
функций.

## Исторические и scoped-документы

Следующие материалы остаются в Git намеренно: они сохраняют ход решений,
миграций и независимой приёмки. Они не являются старой копией текущей
инструкции и не переписываются задним числом.

- `RELEASE_REPORT_ODE_0_12_*` … `RELEASE_REPORT_ODE_0_19_1.md` — evidence
  соответствующих версий;
- `docs/MANUAL_TESTING_*` — чек-лист конкретной версии, а не текущий общий
  runbook;
- `docs/development/STAGE_*`, migration plans/reports и DDL review — scoped
  implementation evidence;
- `docs/history/` — перенесённые ранние QA, product, security, performance и
  architecture snapshots;
- `.stabilization/` — локальные, некоммитируемые доказательства, если каталог
  присутствует.

Ключевая цепочка датированных reviews:

- [`2026-07-15_WAREHOUSE_STABILIZATION_REVIEW.md`](reviews/2026-07-15_WAREHOUSE_STABILIZATION_REVIEW.md);
- [`2026-07-26_FULL_PROJECT_UX_REGRESSION.md`](reviews/2026-07-26_FULL_PROJECT_UX_REGRESSION.md);
- [`2026-07-27_VACATIONS_MODULE_REVIEW.md`](reviews/2026-07-27_VACATIONS_MODULE_REVIEW.md);
- [`2026-07-27_ODE_0_18_1_MULTI_DB_BACKUP.md`](reviews/2026-07-27_ODE_0_18_1_MULTI_DB_BACKUP.md).
- [`2026-08-11_ODE_0_21_0_MONITORING_INTEGRATION_AUDIT.md`](reviews/2026-08-11_ODE_0_21_0_MONITORING_INTEGRATION_AUDIT.md).
- [`2026-08-11_ODE_0_21_0_DOCUMENTATION_AND_API_ACCESS_AUDIT.md`](reviews/2026-08-11_ODE_0_21_0_DOCUMENTATION_AND_API_ACCESS_AUDIT.md).

## Правило актуальности

1. Новое поведение сначала обновляет living-документы, API/ownership/security
   контракты и тесты.
2. Release получает новый датированный report; старый report не редактируется.
3. `python3 scripts/audit_documentation.py` проверяет локальные ссылки,
   обязательную версию 0.21.1 в текущих документах, текущий release report и
   запрет устаревших Windows backup/restore инструкций.
4. Prompts не являются архитектурным решением или evidence реализации; у них
   должен быть явный статус `ACTIVE` либо `SUPERSEDED`.
