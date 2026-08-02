# Roadmap после ODE 0.20.0

## Что уже в рабочем runtime

- S/N-first Warehouse с transaction-safe приходом/расходом, scanner/CSV,
  балансом, поставками, инвентаризацией и справочниками;
- физически отдельные IXcellerate и Solar Warehouse;
- Reports, ручной Monitoring/DCIM routing, Knowledge и отдельный Vacations
  bounded context;
- topology/health трёх runtime-БД и проверенный внешний backup;
- поиск целевой железки и Equipment Composition по доказанным issue-history
  операциям без выдумывания слотов/заводской комплектации;
- FULL Inventory Preview/resolution и disposable migration rehearsal/pilot.

Исторические Stage и их исходные test counts сохранены в датированных release-
отчётах. Они не являются текущим roadmap status.

## Ближайший эксплуатационный цикл

1. Провести owner walkthrough по матрице функций на рабочем ноутбуке.
2. Накопить реальные примеры `компонент → целевой S/N/hostname` и уточнить
   группировку типов без изменения raw history.
3. Спроектировать обратную/подтверждающую операцию установки/снятия, если
   бизнесу нужен именно current-state состава, а не история списаний.
4. Реализовать warehouse correction/reversal только по ADR-014.
5. Реализовать restore protocol только полностью по ADR-013, затем отдельный
   disaster-recovery drill на копиях.

## Server readiness

- process owner и single-writer/concurrency policy;
- service account, filesystem permissions, secrets/bootstrap/reset;
- backup retention, rotation, encryption и restore acceptance;
- maintenance/migration и network/filesystem preflight;
- deployment runbook без runtime/test/candidate DB в code release.

## Отдельные направления

- Monitoring: acceptance с реальным DCIM-сеансом, bounded background execution,
  затем отдельное решение о message transports;
- Reports/Knowledge/Vacations: retention, backup drill и operator acceptance
  внутри собственных boundaries;
- Windows: отдельный package bump/build/sign-off; последний фактический ZIP
  пока 0.12.17 RC1;
- target Platform/DDL: продолжать side-by-side и публиковать только после
  отдельного rehearsal/cutover решения, не поверх рабочего Warehouse.
