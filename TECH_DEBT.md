# Технический долг ODE 0.21.1

Актуализировано: 2026-08-13. Закрытые пункты не выдаются за текущие дефекты;
история их реализации остаётся в release reports.

## P1 — бизнес-целостность и восстановление

1. Нет компенсирующих correction/reversal для ошибочно проведённого прихода
   или расхода. Data Quality исправляет ограниченный набор полей и не заменяет
   бухгалтерски понятное сторно. Нормативный контракт — ADR-014.
2. Restore трёх runtime-БД не реализован. Status/create/verification работают,
   но UI/API restore fail-closed до полного ADR-013 protocol и drill.
3. Equipment Composition строится по issue-history. Он не подтверждает текущее
   физическое наличие, снятие, заводскую комплектацию и точный слот. Для
   current-state нужна отдельная модель подтверждения установки/снятия.
4. Реальный FULL baseline publish/cutover остаётся controlled change с внешним
   backup, остановкой writers, sibling candidate, atomic publish и rollback;
   review candidate/pilot не являются production.

## P2 — архитектура и эксплуатация

1. `inventory/templates/webapp.py` всё ещё собирает большой compatibility HTML
   цепочками `.replace(...)`. Фактические CSS/JS уже externalized, routes и
   domain facades выделены, но текстовые замены остаются риском разметки.
   Контроль: HTML hash, frontend/static-control audit и Chrome smoke.
2. Compatibility `WarehouseService`/`WarehouseCore` удаляются только
   постепенно. Новый code path обязан идти через `ApplicationContext → facade`
   и не создавать параллельный SQL/runtime.
3. SQLite/local-process контур не готов к активной многопользовательской
   серверной записи. Нужны owner/single-writer policy, locks, filesystem
   preflight, deployment, secrets и concurrent acceptance.
4. Backup пока без автоматического расписания, ротации, шифрования и измеренного
   disaster-recovery RTO/RPO.
5. Source-ZIP 0.21.1 проходит финальный gate, но физический Windows
   install/update/double-click sign-off ещё не выполнен. Архивы 0.21.0
   отозваны для повторного переноса и не являются fallback.
6. FULL Inventory Preview не имеет cooperative cancel/resume; для будущего
   1m-row контура нужны progress/checkpoint и ограниченное время остановки.
7. Delivery inspect/batch/conflict flows имеют backend и основное browser
   покрытие, но перед крупным UI rewrite нужен более глубокий accessibility и
   file-dialog E2E на Windows.
8. Внешний API и machine authentication отсутствуют. Текущая in-memory browser
   cookie не подходит как API key; server stage требует отдельные principals,
   scopes, hash-at-rest, expiry/rotation/revoke, audit, rate-limit, HTTPS и
   persistent session/credential lifecycle.

## Data-quality backlog

- 291 из 50 000 promoted карточек имеют `item_name = '#N/A'` из исторического
  Excel-источника. S/N сохранены, но имя нельзя угадывать. Исправление требует
  отдельного backup/provenance/transaction/audit/integrity/FK change.
- 1 030 promoted S/N содержат внешние пробелы; 160 normalized-key групп имеют
  более одной карточки. Read/write lookup удаляет только внешние пробелы без
  перезаписи raw S/N и fail-closed при неоднозначности. Удаление исторических
  дублей или expression unique index возможны только после отдельной
  доказательной data-correction процедуры.
- Monitoring cleanup Selenium-driver содержит намеренно подавленные ошибки;
  при развитии collector их нужно переводить в безопасное диагностическое
  логирование без утечки секретов.

## Reports scalability

- Реестр УВР показывает страницы по 25 строк поверх server-bounded окна в
  1000 совпадений. Date/search/status/section/review filters выполняются на
  сервере и UI явно показывает `truncated`, но полноценные server-side
  `offset/cursor + sort` нужны до длительной многолетней эксплуатации с более
  чем 1000 совпадающими записями.

## Обязательные защитные проверки

- `scripts/smoke_ui.py` остаётся release gate;
- `scripts/audit_module_boundaries.py` запрещает пересечение bounded contexts;
- `scripts/audit_frontend_contracts.py` проверяет ID и статические кнопки;
- `scripts/audit_documentation.py` проверяет living docs и локальные ссылки;
- mutation/file upload tests выполняются только на disposable DB;
- SHA-256/integrity/FK трёх рабочих DB сравниваются до/после read-only gate.
