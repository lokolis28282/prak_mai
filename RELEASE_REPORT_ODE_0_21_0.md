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
`65534a63a4302544d92e6dbd681ea4d9589bc31295c49ac4007aabbbd8c6299e`.

Private Monitoring transfer ZIP (не публиковать):
`ODE_0.21.0_PRIVATE_MONITORING_TRANSFER.zip`, SHA-256
`1da522788f7cf3c89ee0ab891fd4dae0ce148d329aeb2212e8dfc14397d141ca`.

Финальные команды, количество тестов, SHA БД и состав ZIP фиксируются в
[`docs/project/reviews/2026-08-11_ODE_0_21_0_MONITORING_INTEGRATION_AUDIT.md`](docs/project/reviews/2026-08-11_ODE_0_21_0_MONITORING_INTEGRATION_AUDIT.md).

Физическая проверка на целевом Windows-ноутбуке остаётся обязательной до
рабочего rollout.

Post-release documentation follow-up проверил весь living-комплект и добавил
точные current-контракты входа, cookie API, отсутствия API-key auth и runtime-
конфигурации. Evidence:
[`docs/project/reviews/2026-08-11_ODE_0_21_0_DOCUMENTATION_AND_API_ACCESS_AUDIT.md`](docs/project/reviews/2026-08-11_ODE_0_21_0_DOCUMENTATION_AND_API_ACCESS_AUDIT.md).
