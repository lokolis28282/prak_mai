# Порядок реализации ODE 0.13

Статус: **APPROVED ORDER — Stage 0.13.1 реализован до REVIEW_READY**

Номера ниже — **Platform/Target ODE delivery stages**, не Warehouse source
Stage и не опубликованная версия приложения. Warehouse source Stage 0.13.2
означает Bulk Inventory Number Import и не связан с Platform Stage 0.13.2
ниже. Каждый stage вертикальный: минимальный domain + storage +
API/UI/operations proof, никаких сотен пустых файлов.

## 0.13.0 — Specification freeze

- Entry: этот documentation gate завершен.
- Scope: ADR freeze, executable review-only DDL, threat/data review, OPEN decisions.
- Deliverables: APPROVED docs, exact migration SQL proposal, traceability.
- Tests: two clean temporary DB builds, negative constraints, domain proof,
  EXPLAIN, link/Mermaid/term review.
- DB impact: none.
- Rollback: revert documentation change only.
- Exit: business/data/security/technical signatures; no BLOCKER.
- Commit: documentation-only reviewable commits; no version bump.

## 0.13.1 — Platform foundation

- Status: REVIEW_READY; Stage 0.13.2 remains blocked pending independent review
  and explicit user approval.
- Entry: approved DDL/ADR and explicit Stage 0.13.1 authorization.
- Scope: composition root, typed config, explicit clean-create migration runner,
  connection/UoW, empty DB, architecture CI and typed health/diagnostics service.
- Deliverables: CLI and schema/system-state proofs on temporary DB; no HTTP
  endpoint and no test entity at this Stage.
- Tests: exact manifest and two clean builds, mismatch fail, path safety, UoW
  rollback, handles closed, read-only diagnostics and CLI contracts.
- DB impact: new disposable 0.13 DB only; old DB read-only.
- Rollback: delete disposable DB/build.
- Exit: no startup migration; schema manifest reproducible; independent review
  and explicit user approval still required.
- Evidence: [STAGE_0_13_1.md](STAGE_0_13_1.md).

## 0.13.2 — Personal security, audit and references

- Entry: stable UoW.
- Scope: users/sessions/roles/permissions, append audit, reference/catalog/UOM,
  warehouse/location, minimal admin/read UI/API.
- Tests: role matrix, CSRF/session/revoke/default credential, alias lifecycle,
  audit rollback.
- DB impact: new 0.13 tables/migrations; no 0.12 write.
- Rollback: restore disposable prior schema backup.
- Exit: personal login and no canonical-on-read.
- Docs: API/security/reference contracts updated from implementation evidence.

## 0.13.3 — Equipment identity and legacy history vertical

- Entry: references and security stable.
- Scope: Equipment/Identity/Merge contracts, source vault, deterministic legacy
  mapper, exact S/N history query and UI.
- Tests: 71 360-row rehearsal copy, leading zeros, ambiguity, date/actor
  quality, idempotency, no balance tables touched.
- DB impact: candidate/archive DB only.
- Rollback: discard/rebuild candidate.
- Exit: signed history sample/count/hash gates; source-to-target complete.
- Docs: migration evidence report.

## 0.13.4 — XLSX Preview vertical

- Entry: identity/reference exact matching available.
- Scope: template parser, workspace schema, upload vault, findings/resolutions,
  progress/resume/cancel, Preview API/UI.
- Tests: malformed XLSX, 1m bounded-memory, crash resume, stale digest,
  operational DB before/after hash.
- DB impact: external workspace/source only.
- Rollback: cleanup session workspace under retention; operational unchanged.
- Exit: no blocking finding bypass and deterministic digest.

## 0.13.5 — Snapshot, balance core and candidate publish

- Entry: Preview READY contract stable; platform replace drills pass.
- Scope: inventory lifecycle/freeze, snapshot/reconciliation, deterministic
  balance math, projection build/rebuild, candidate approval and atomic replace,
  NOT_INITIALIZED/ACTIVE UI.
- Tests: atomic approval, candidate failures, projection properties, cutoff,
  new baseline supersession, restore.
- DB impact: first authoritative 0.13 candidate; no legacy ledger.
- Rollback: whole pre-publish DB.
- Exit: physical fixture baseline publishes and rebuild checksum matches.
- Docs: publish and recovery actual runbook.

## 0.13.6 — Warehouse ledger verticals

- Entry: active snapshot/projection.
- Scope in order: RECEIPT, ISSUE, TRANSFER, ADJUSTMENT, REVERSAL; each includes
  domain, repository, projection, audit, API and UI before next kind.
- Tests: idempotency, stale state, negative prevention, reversal math,
  concurrent readers/single writer, posted immutability.
- DB impact: ledger migrations in disposable/rehearsal 0.13 only.
- Rollback: DB backup per migration; no in-place row compensation.
- Exit: all transaction sequence diagrams executable as contracts.

## 0.13.7 — Reports, operations and integrated UI/API

- Entry: all core write verticals stable.
- Scope: reports through query ports, audit UI, backup/restore/diagnostics,
  accessibility/mobile read, remove remaining new-stack temporary adapters.
- Tests: API contract/E2E/security, release denylist, disaster restore.
- DB impact: report job metadata only.
- Rollback: disable optional reports; core unaffected.
- Exit: complete operator/admin/auditor journeys.

## 0.13.8 — Full migration rehearsal

- Entry: feature-complete release candidate.
- Scope: frozen-copy rehearsal, full mapping, 1m performance dataset, Windows
  and POSIX publish/rollback drills, independent acceptance.
- Tests: all verification gates; no uncontrolled unittest dependence on live DB.
- DB impact: rehearsal artifacts only.
- Rollback: discard artifacts, preserve evidence.
- Exit: signed go/no-go, known data quarantine accepted.
- Docs: final manifests, RTO/RPO, release checklist.

## 0.13.9 — Cutover and cleanup

- Entry: signed business/data/security/technical go.
- Scope: freeze, backups, migrate archive, deploy NOT_INITIALIZED, approve first
  physical baseline, controlled writes, observation, then cleanup after window.
- Tests: production read-only smoke, baseline/projection, backup restore,
  package/data separation.
- DB impact: new operational DB and active baseline.
- Rollback: [rollback-plan.md](../migration/rollback-plan.md).
- Exit: signed acceptance and expired rollback window.
- Docs: release notes, archived old specification index.
- Version: only here application becomes ODE 0.13.

## Commit policy

No commit in this documentation task. During implementation:

- one cohesive vertical change per reviewed PR/commit series;
- schema migration + repository + tests + rollback/docs together;
- no mixed cleanup and behavior change;
- no generated DB/ZIP/source data;
- migration irreversible step requires signed evidence before merge;
- stage tag only after exit criteria.
