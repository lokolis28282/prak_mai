# Risks and Backlog — ODE 0.21.0

Актуализировано: 2026-08-11.

## P0 — всегда блокирует выпуск

- mutation/replace любой runtime-БД без утверждённой backup/publish procedure;
- потеря raw S/N, leading zeros, provenance или text round-trip;
- нарушение receipt/issue/allocation balance либо частичный Confirm;
- authorization bypass, grant по ФИО или раскрытие password hash/secret/path;
- прямой business SQL из routes/templates или чтение чужих таблиц модулем;
- применение target DDL/candidate/test DB к рабочему runtime;
- runtime DB, backup, raw, exports, secrets или ZIP в Git/code release;
- включённый частичный restore либо correction без полного контракта.

## P1 — текущая эксплуатация

- owner walkthrough всех функций на рабочем Windows-ноутбуке ещё требуется;
- issue-history composition нельзя интерпретировать как подтверждённый
  current-state или точный slot map;
- correction/reversal требует ADR-014;
- restore и disaster-recovery drill требуют ADR-013;
- default/bootstrap credentials неприемлемы для будущего сервера;
- FULL baseline publish отключён до отдельного cutover approval;
- `LINK_EXISTING_EQUIPMENT` нельзя автоматически применять без доказанного
  Equipment Query Port; Vendor/Model matching не заменяет S/N identity;
- 291 `#N/A` names требуют отдельной доказательной data-correction процедуры.
- В IXcellerate остаются 160 исторических групп S/N, совпадающих после удаления
  только внешних пробелов. Runtime не создаёт новые normalized-дубли и
  Inventory Number assignment для неоднозначной группы fail-closed, но сами
  строки требуют отдельной backup/provenance/audit data-correction процедуры.

## P2 — server/release readiness

- process owner, single-writer/concurrency lifecycle;
- service account, secrets и filesystem permissions;
- отдельный machine principal/API-key contract со scopes, hash-at-rest,
  expiry/rotation/revoke, audit, rate-limit и TLS; session cookie не должна
  использоваться как integration token;
- backup schedule/rotation/retention/encryption и restore acceptance;
- deployment/update/rollback и network filesystem rejection;
- concurrent operator acceptance;
- Windows package metadata/build/sign-off;
- explicit empty-install bootstrap без runtime DB в code release;
- optional coordinated Git history cleanup старых data blobs — только в
  maintenance window, без force rewrite в обычной разработке.

## Отдельные направления

- Monitoring: реальный DCIM acceptance и будущие transports;
- Reports/Knowledge/Vacations: retention, content acceptance и backup drill;
  для Reports — cursor/offset pagination после текущего bounded окна 1000;
- target Platform: independent gates и отдельный rehearsal/cutover;
- точный installed-component current-state — отдельное бизнес-решение, не
  косметическое расширение текущей схемы карточки.

Закрытые исторические дефекты и их прежние test counts находятся в датированных
reviews/release reports; этот файл содержит только открытый риск текущего
runtime.
