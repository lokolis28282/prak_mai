# Integration Audit Report

Date: 2026-07-17
Target: `E:\prak_mai_integrated`
Read-only source: `E:\ODE v0.2\prak_mai-main`

## Architecture and boundaries

The target is a local Python 3.11/SQLite/vanilla-JS application. HTTP assembly
lives in `inventory/webapp.py`; business access is routed through
`ApplicationContext` and module facades. Warehouse, Reports, Administration,
Monitoring and Knowledge remain separate logical owners in one runtime DB.
The future `ode/` migration contour remains isolated from `inventory/`.

The source is an older revision of the same product. Whole-file replacement
would have reverted current Warehouse, navigation and migration safeguards, so
only domain-specific behavior was adapted. Source HEAD and dirty status were
recorded before work and are rechecked at completion.

## Reuse and rewrite decisions

- Reused: DCIM parsing/classification, Edge collector concept, safe Markdown,
  article/attachment repository structure and Knowledge UI interaction model.
- Preserved from target: secure hostname routing, current `ApplicationContext`,
  Full Inventory guards, shared API/DOM components, current navigation and DB.
- Extended: Monitoring configuration/error states/history; Knowledge search,
  tags, pagination, update, soft delete, roles, audit and Office validation.
- Not copied: databases, internal routing JSON, recipient addresses, Edge
  profiles, cookies, credentials, uploads, generated reports or source caches.

## Security review

- All new API routes require an authenticated session.
- Knowledge writes are enforced server-side for `admin`/`engineer`; `viewer`
  remains read-only. Monitoring is a diagnostic read operation for all roles.
- SQL uses parameters. JSON/file sizes are bounded. Stored attachment paths are
  generated, relative and containment-checked.
- Markdown escapes raw HTML and accepts links only for HTTP(S)/mailto.
- Attachment download uses authentication, safe content disposition,
  `Cache-Control: no-store`, `nosniff` and frame denial.
- Monitoring inputs reject unsafe hostnames/header injection. Development mock
  is explicit and marked. No automatic message transmission was introduced.
- Secret scan excludes internal configuration by design; local rule/profile,
  DB and upload paths are ignored or external.

## Data and migrations

New owner-scoped tables: `knowledge_articles`, `knowledge_attachments` and
`knowledge_article_tags`, with category/update, attachment and normalized tag
indexes. Migration is additive and idempotent. Promoted historical databases
receive Knowledge schema even when legacy `SCHEMA` replay is intentionally
skipped. Disposable migration tests pass integrity and FK checks.

No working or source database was migrated during integration. Attachment
bytes live outside public/static and must be backed up with SQLite.

## Cross-platform findings fixed

- Windows `core.autocrlf` changed byte-exact approved DDL checksums. A scoped
  `.gitattributes` now keeps canonical SQL at LF on every OS.
- Windows rejects `fsync` on read-only handles and has no POSIX directory
  descriptor. Candidate/test DB publication now uses writable file handles and
  directory fsync only when `O_DIRECTORY` exists.
- Tests that require POSIX mode bits, unlink-open semantics or unrestricted
  symlinks are explicitly skipped on Windows; functional equivalents remain.
- Frontend contract tests were updated from the retired Monitoring placeholder
  to the operational launcher, direct-route restoration was added, and lazy
  Monitoring IDs were documented.

## Performance and operational risk

- Knowledge list is bounded to 100 rows/request (default 20) and uses indexed
  category ordering. `LIKE` search is adequate for small corpora, not a large
  document archive.
- Attachments are streamed into memory by the current stdlib HTTP handler but
  capped at 1–50 MB (default 15 MB). A large shared deployment should stream.
- Selenium collection is external-I/O bound and runs in a dedicated
  `ThreadingHTTPServer` worker without taking the Warehouse mutation lock.
- SQLite remains unsuitable for heavy concurrent multi-user writes.

## Verification summary

- Monitoring + Knowledge focused tests: 36 passed.
- Module boundary audit: passed.
- Frontend static-ID audit: passed.
- Python/JavaScript syntax checks: passed.
- Full test suite after hardening: 480 passed, 15 platform-specific skips.
- Browser/API smoke used a disposable DB and covered Knowledge create/edit,
  Monitoring mock search/history, direct hash reload and a 390 px viewport;
  no production DB was opened for writes.

## Remaining limitations

- DCIM selectors depend on the external page and cannot be validated without a
  configured private session.
- Email/Rooms sending is intentionally absent.
- Knowledge attachment retention and antivirus scanning are not implemented.
- The monolithic `inventory/webapp.py` remains architectural debt.
- Live multi-user/server deployment needs a queue, stronger CSRF policy,
  external secret storage and a server-grade database decision.
