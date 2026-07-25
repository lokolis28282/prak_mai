# Migration Database Reset Plan

Дата: 2026-07-14.

## Status

**LOCAL EXECUTION COMPLETED UNDER EXPLICIT APPROVAL ON 2026-07-14.** The plan
was not run during Stage 0.13.3A or the Stage 0.13.3A.5 pilot. It was executed
later for the single local ODE contour: the validated full candidate was copied
to `data/warehouse.db.next`, checked with the ordinary runtime, and published
to `data/warehouse.db` by atomic `os.replace` only after the old DB had two
verified external backups and no writers/sidecars.

This record does not authorize or claim a server production deployment.
Future replacements still require a new explicit approval. Never run mutation
or stress tests directly against `data/warehouse.db`.

Execution evidence is retained at
`~/ODE_Backups/20260714T171002+0300/`; old working SHA-256 was
`49020e71e764d3a05ecd18d4baa406c1c359bf6470b7c60eca38d716665f17fb`
and post-startup/no-user-operation SHA-256 was
`aad540d26c89b79b0da9f7c2881b78e03717371a9bf627e157f5acc3c9278f57`
(`170729d1555c8eafd65bdc6caea53395b2ff04a82d200b8f7b25d615d9518a51`
was the atomically published pre-launch `.next` SHA). The live handoff SHA
after one ordinary `LOGIN` audit at `2026-07-14 20:19:30` was
`4ede3a74b1efdc56fcc8a689e652cf8f7511c4293a45bd509e51db8101794c65`.
Later legitimate warehouse/audit writes will naturally change the working SHA.
See [LOCAL_WORKING_DATABASE_RUNBOOK.md](LOCAL_WORKING_DATABASE_RUNBOOK.md) for
verification and rollback commands/constraints.

The ignored `warehouse_pilot_candidate.db` is a 200-row preservation review
artifact, not the future installation candidate: it intentionally contains
only 130 receipt cards, no historical issues and no approved bulk reference
decision. Pilot review may inform Stage 0.13.3B design but cannot satisfy any
reset precondition or authorize a swap.

## Goal

After all migration stages and acceptance, replace development/test warehouse
operations with authoritative inventory data while retaining the required
administrative/security identity and a verified rollback path.

## Preconditions

- Approved reference set and all manual alias/S/N decisions.
- Approved receipt/issue migration plans and reconciliations.
- Maintenance window with ODE stopped and no SQLite sidecars/writers.
- Explicit production replacement approval naming the exact candidate SHA.
- Sufficient disk space for two independent backups, candidate and manifests.
- Named operator/reviewer and rollback owner.

## Required workflow

1. Resolve the canonical working-DB path and reject symlinks/hardlinks or a path
   outside the configured ODE data boundary.
2. Record SHA-256, size, SQLite page metadata, `integrity_check`,
   `foreign_key_check` and sidecar state of the working DB.
3. Create a byte-for-byte backup in external `~/ODE_Backups/<timestamp>/`.
4. Create an independent SQLite Backup API snapshot that includes committed WAL
   state without mutating the source.
5. Verify both backups independently: SHA/size, open read-only, integrity/FK,
   user/security row counts and a manifest containing source/copy identity.
6. Create a new candidate DB from the current clean schema. Do not clear and
   reuse the old file.
7. Transfer only approved security state: administrator/user identities,
   `password_hash` byte-for-byte without printing it, roles, active and
   password-change flags, and explicitly enumerated security settings.
8. Do not transfer development/test receipts, issues, allocations, deliveries,
   reports, legacy operations/equipment or audit rows as authoritative stock.
9. Load the approved reference package.
10. Load approved historical receipts through the separately reviewed migration
    workflow.
11. Load approved issues/allocations only after receipt identity is fixed.
12. Run complete source-to-target counts, S/N/inventory uniqueness, staging
    provenance, balance-from-operations, audit/event, integrity/FK, security and
    UI/API checks.
13. Present the candidate DB path, SHA, manifest, validation report and known
    unresolved rows to the user; do not replace production automatically.
14. After a separate explicit approval, stop ODE, recheck current/candidate SHA
    and sidecars, atomically swap the candidate into the working path, start and
    execute post-swap smoke/read checks.
15. Retain the former working DB and both backups under
    `~/ODE_Backups/<timestamp>/` with immutable manifest/SHA and documented
    retention; never delete them as part of the swap.

## Security transfer allowlist

Candidate security migration may read/write only explicitly listed columns of
`users`: identity/profile fields, email, exact password hash, role,
`must_change_password`, active flag and creation metadata. It must not log,
export to Markdown/CSV or compare password hashes in visible diagnostics.

Unknown security tables/settings block the reset until the allowlist and
documentation are updated. Security transfer and warehouse-data import are
separate transactions/steps.

## Atomic publication

Build and validate the DB at a sibling temporary path. Before `os.replace` or
equivalent atomic rename:

- ensure source/candidate are on the intended filesystem;
- ensure ODE is stopped;
- reject `-wal`, `-journal` and active `-shm` state;
- recheck old and candidate hashes against the approved manifest;
- fsync files/directories where supported;
- never overwrite the rollback backups.

If any pre-swap or post-swap check fails, stop and restore the verified SQLite
backup according to a recorded rollback decision. Never attempt to repair a
partially accepted migration in place through ad-hoc DELETE/UPDATE.

## Validation after local or future swap

- working DB SHA equals approved candidate SHA;
- `integrity_check = ok`; `foreign_key_check` is empty;
- required administrator can authenticate without password reset or disclosure;
- role boundaries remain enforced;
- all operational counts equal the approved manifest;
- S/N/inventory identifiers round-trip exactly;
- balance is computed from receipts minus allocations; no balance snapshot was
  imported as operations;
- no HTTP 500, JS/unhandled/resource error or unexpected audit event;
- backups and manifest remain readable and outside the runtime package.

## Rollback triggers

- hash/schema/integrity/FK mismatch;
- missing administrator or role/security mismatch;
- identifier corruption or unexpected duplicate;
- operation/reference counts differ from the approved plan;
- unapproved row entered operational tables;
- ODE fails startup/auth/smoke or produces HTTP 500;
- candidate/working sidecars indicate an uncoordinated writer.

## OPEN DECISIONS FOR A FUTURE SERVER DEPLOYMENT

- Maintenance window, backup retention and named approval roles.
- Final candidate schema after receipt/issue stages.
- Required audit migration events and how migration-batch identity is exposed.
- Whether legacy compatibility tables are empty, rebuilt or retired.
- Exact server/Windows atomic-swap and filesystem durability procedure.
