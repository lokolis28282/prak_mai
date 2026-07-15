# Security и Audit

Статус: **APPROVED — ODE 0.13 architecture baseline**

## Principals и роли

- operator: inventory workflow и штатные receipt/issue/transfer.
- admin: управление accounts/references, adjustment/reversal, backup/restore.
- auditor: read-only operational, history, reports и audit.

Каждое современное действие выполняет персональный User. Произвольное ФИО не
создает session и не подменяется общим аккаунтом. Legacy ФИО — raw historical
text, не User.

## Permission matrix

| Action / permission | Operator | Admin | Auditor | Audit |
|---|:---:|:---:|:---:|---|
| Login/profile | ✓ | ✓ | ✓ | LOGIN/LOGOUT/FAILED |
| Inventory upload | ✓ | ✓ | — | INVENTORY_SOURCE_UPLOADED external |
| Preview/read findings | ✓ | ✓ | read | PREVIEW_STARTED/COMPLETED |
| Resolve finding | ✓ | ✓ | — | INVENTORY_FINDING_RESOLVED |
| Approve/reject inventory | ✓ | ✓ | — | INVENTORY_APPROVED/REJECTED |
| Receipt | ✓ | ✓ | — | RECEIPT_POSTED |
| Issue | ✓ | ✓ | — | ISSUE_POSTED |
| Transfer | ✓ | ✓ | — | TRANSFER_POSTED |
| Adjustment in/out | — | ✓ + reauth | — | ADJUSTMENT_POSTED |
| Reversal | — | ✓ + reauth | — | REVERSAL_POSTED |
| Equipment read/history | ✓ | ✓ | ✓ | Read не логируется построчно |
| Identity correction/merge | — | ✓ + reauth | — | IDENTITY_CORRECTED/MERGED |
| Reference browse | ✓ | ✓ | ✓ | — |
| Reference create/approve/merge | — | ✓ | — | REFERENCE_* |
| User/role administration | — | ✓ + reauth | — | USER_*/ROLE_* |
| Audit read/export | — | ✓ | ✓ | AUDIT_EXPORTED |
| Backup create/list | — | ✓ + reauth | read list optional | BACKUP_* |
| Restore | — | ✓ + second confirmation | — | RESTORE_* |
| Diagnostics read | — | ✓ | ✓ limited | DIAGNOSTICS_READ |
| Report request/read | ✓ | ✓ | ✓ | REPORT_* |

Operator может approve собственный upload: персональная ответственность
сохраняется, а обязательный four-eyes rule заблокировал бы однопользовательский
склад. Deployment MAY добавить stricter policy, но не ослабить permissions.

## Authentication

- DB-level: `password_hash` обязателен, не пуст, не имеет default и проходит
  только format check `$argon2id$...`; SQLite не проверяет, что строка является
  криптографически корректным Argon2id hash.
- Application-level: утвержденная password library выполняет реальную Argon2id
  verification constant-time API. Version, memory, time и parallelism задаются
  versioned security profile после deployment-hardware test; login выполняет
  rehash при устаревшем или ослабленном profile.
- Operational-level: interactive bootstrap не создает default credential;
  rotation/recovery аудируются, backups защищаются как credential material,
  plaintext password и hashing secrets не попадают в DB, logs или artifacts.
- Минимум 12 символов; запрещены known default/product/user-name passwords.
- Initial account создается interactive bootstrap, не hardcoded.
- Must-change-password блокирует business writes.
- Rate limit login по account+IP hash; exponential delay без account existence
  disclosure.
- После 10 неуспешных попыток account получает timed LOCKED; admin unlock
  audited.
- Credential change увеличивает credential_version и инвалидирует sessions.

## Session

- 256-bit random bearer token; в DB только SHA-256 token hash.
- Cookie HttpOnly, SameSite=Strict, Path=/, no Domain.
- Secure обязателен под HTTPS. Loopback-only HTTP development profile явно
  маркируется и не слушает внешний interface.
- Idle timeout 30 minutes, absolute 12 hours.
- Rotation после login/reauth и privilege change.
- Logout/revocation effective на следующем request.
- Session list/revoke доступны самому user; admin может revoke all.

## CSRF, Origin и Host

Все cookie-authenticated unsafe methods требуют synchronizer CSRF token,
совпадающий с session secret. API дополнительно проверяет exact allowlisted
Origin и Host. Отсутствующий Origin допускается только для same-host native CLI
с отдельным token authentication profile, не browser cookie.

## Upload security

- allowlist XLSX MIME/signature, no extension trust;
- compressed/expanded size, row, XML depth/entity/ratio limits;
- reject macros, external links, DDE and path traversal;
- random temp names outside web root;
- source file name никогда не используется как path;
- parse worker имеет минимальные filesystem permissions;
- source/workspace/candidate не раздаются static server;
- upload and preview rate/concurrency limits per user;
- content hash before reuse.

## Audit contract

Critical event содержит:

- personal user ID или SYSTEM;
- display-name snapshot;
- role and permission snapshot;
- session ID where applicable;
- UTC timestamp;
- correlation ID;
- action/outcome;
- subject public ID;
- reason and safe structured details;
- IP hash/user-agent family where lawful and configured.

Пароли, tokens, raw auth headers, full XLSX payload и sensitive comments в audit
не записываются. Source provenance хранится в domain tables.

Success audit входит в domain UoW. Denied attempt записывается отдельно и не
выдает sensitive details. Hash chain обнаруживает accidental alteration;
tamper-proof claim требует external signed anchor и не входит в 0.13.

## Release/data separation

Release не содержит live/default DB, user/password hash, source Excel, Preview,
candidate, backup или operations logs. См.
[release-data-separation.md](../operations/release-data-separation.md).

## Network exposure

Default binding — loopback. Remote/server deployment не входит в 0.13 и требует
отдельных TLS, reverse proxy, secret management, threat model и operations ADR.
Нельзя считать текущий local profile безопасным для LAN.

## Security failure mode

Fail closed: unknown role/permission, stale session, unavailable audit write,
active inventory freeze или inconsistent projection блокируют write. Audit read
failure не открывает direct DB access.

Решение персональных accounts закреплено в
[ADR-008](../decisions/ADR-008-personal-accounts-and-audit.md).
