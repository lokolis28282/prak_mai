# ODE 0.21.0 — Monitoring integration release report

Дата: 2026-08-11
База: `release/0.20.0` / `26a48a1`
Статус: **release candidate; Windows sign-off pending**

## Результат

Monitoring-изменения из `ODE_0.21.0_new_monitor` интегрированы выборочно через
существующие `MonitoringFacade`, HTTP route и frontend entrypoint. Warehouse,
Reports, Vacations и Administration storage boundaries не изменены. Реальные
DCIM/Zabbix запросы и ping в приёмке не запускались.

## Включено

- нормализация вставленного hostname до внешнего запроса;
- DCIM project/ИС/ITSM/criticality enrichment;
- routing по hostname/project/ИС, `global_cc` и learned Digital rules;
- единый девятипунктовый Rooms/email template;
- frontend copy/validation flow и расширенные unit/contracts;
- универсальный stdlib XLSX rule generator;
- public source ZIP без данных и private transfer ZIP с ignored Monitoring
  rules, но без SQLite-БД.

## Исключено

- рабочие и тестовые БД;
- corporate JSON/analysis reports из Git;
- одноразовый generator с персональными Windows-путями;
- automatic email/Rooms transport;
- живой DCIM/hostname поиск в локальном release gate.

## Проверки

Public source ZIP:
`ODE_0.21.0_windows_source.zip`, SHA-256
`f6eafd759128f4546593239bb046b84e3ae62a1ac54f5b070e14f1fa2a0a60fb`.

Private Monitoring transfer ZIP (не публиковать):
`ODE_0.21.0_PRIVATE_MONITORING_TRANSFER.zip`, SHA-256
`f353499cd5c7596045d8905a29cdcb6c7a9e493e3ee83ed4fe82310b61e79854`.

Финальные команды, количество тестов, SHA БД и состав ZIP фиксируются в
[`docs/project/reviews/2026-08-11_ODE_0_21_0_MONITORING_INTEGRATION_AUDIT.md`](docs/project/reviews/2026-08-11_ODE_0_21_0_MONITORING_INTEGRATION_AUDIT.md).

Физическая проверка на целевом Windows-ноутбуке остаётся обязательной до
рабочего rollout.
