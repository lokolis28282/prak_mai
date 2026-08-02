# Технический долг ODE 0.20.0

Актуализировано: 2026-08-02. Закрытые пункты не выдаются за текущие дефекты;
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
5. Новый Windows ZIP 0.20.0 не собран; последний фактический package — 0.12.17
   RC1. Builder/metadata/sign-off требуют отдельного release.
6. FULL Inventory Preview не имеет cooperative cancel/resume; для будущего
   1m-row контура нужны progress/checkpoint и ограниченное время остановки.
7. Delivery inspect/batch/conflict flows имеют backend и основное browser
   покрытие, но перед крупным UI rewrite нужен более глубокий accessibility и
   file-dialog E2E на Windows.

## Data-quality backlog

- 291 из 50 000 promoted карточек имеют `item_name = '#N/A'` из исторического
  Excel-источника. S/N сохранены, но имя нельзя угадывать. Исправление требует
  отдельного backup/provenance/transaction/audit/integrity/FK change.
- Monitoring cleanup Selenium-driver содержит намеренно подавленные ошибки;
  при развитии collector их нужно переводить в безопасное диагностическое
  логирование без утечки секретов.

## Обязательные защитные проверки

- `scripts/smoke_ui.py` остаётся release gate;
- `scripts/audit_module_boundaries.py` запрещает пересечение bounded contexts;
- `scripts/audit_frontend_contracts.py` проверяет ID и статические кнопки;
- `scripts/audit_documentation.py` проверяет living docs и локальные ссылки;
- mutation/file upload tests выполняются только на disposable DB;
- SHA-256/integrity/FK трёх рабочих DB сравниваются до/после read-only gate.
