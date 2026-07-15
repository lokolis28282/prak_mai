# Risks and Backlog

## P0 — всегда блокирует

- mutation/replace `data/warehouse.db` без утверждённой backup/publish procedure;
- потеря S/N raw value, leading zeros или provenance;
- нарушение receipt/issue/allocation balance;
- authorization bypass или раскрытие password hashes;
- прямое применение target V001..V008 к working Warehouse DB;
- смешивание candidate/test DB с production code release.
- повторное добавление installation-owned `data/warehouse.db` в Git, source
  archive или release;
- включение runtime `data/warehouse.db` в Windows/source artifact. Закрыто в
  0.14: builder включает только `data/README.md`, regression запрещает DB в ZIP.

## P1 — текущая стабилизация

- Большой dirty worktree не воспроизводится из HEAD.
- Platform Stage и Warehouse source используют одинаковые номера Stage.
- Формальный post-fix PASS Platform Stage 0.13.1 отсутствует.
- Автоматизированная операторская Warehouse acceptance пройдена; остаётся
  финальный owner walkthrough на рабочем ноутбуке.
- Legacy clean-DB bootstrap создаёт default admin; для будущего сервера нужен
  explicit personal bootstrap/recovery contract без default credentials.
- Correction/reversal для ошибочных posted operations ограничен и требует
  отдельного бизнес-контракта.
- Initial-baseline candidate rehearsal реализован, но реальный publish
  отключён до отдельного cutover approval, backup и writer-stop gate.
- `LINK_EXISTING_EQUIPMENT` не применяется до target Equipment Query Port;
  автоматическое Vendor/Model matching запрещено.

Закрыто 2026-07-15: тестовые raw `sqlite3.Connection` handles теперь явно
закрываются; full suite 392/392 проходит без ResourceWarning.

Закрыто 2026-07-15: permission-gated и scenario elements больше не протекают
визуально из-за CSS `display`; placeholder values не дублируются; списание с
нулевого остатка недоступно в UI. Backend validation оставлена как второй слой
защиты. Full suite после изменений: 394 tests, `OK (skipped=8)`.

## P2 — server readiness

- process-owner/single-writer lifecycle;
- service account, secrets и filesystem permissions;
- backup rotation/retention и restore drills;
- deployment/update/rollback runbook;
- Windows/server validation;
- network filesystem rejection;
- concurrent operator acceptance;
- release metadata/ZIP synchronization.
- explicit empty-install bootstrap and schema-migration gate without shipping
  a runtime/production DB in the code release;
- optional coordinated Git history cleanup: old small DB blobs remain in main
  history, а локальные Codex capture refs могут удерживать большой runtime blob;
  не удалять refs и не переписывать историю без maintenance window.

## Отдельные направления

- Monitoring colleague-code inventory and integration plan.
- Reports application contracts.
- Wiki branch integration policy.
- DCIM/ITSM/Zabbix integration после стабильных Equipment query ports.
