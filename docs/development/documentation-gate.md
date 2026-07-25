# Documentation gate

Статус: **PROPOSED**

## Change traceability

Каждый behavior/schema/API/security change updates exactly one owner document,
relevant ADR if decision changes, tests and migration/rollback notes. Overview
не копирует детали.

## Required review

- Business: balance, inventory, ledger semantics.
- Data: DDL, identity, migration, retention.
- Security: accounts, permissions, audit, upload, release separation.
- Operations: SQLite, backup/restore/publish.
- UI/API: endpoint-action-screen traceability.
- Independent senior: contradictions and hidden assumptions.

## Automated audit

- Markdown headings and duplicate titles;
- relative links and anchors;
- Mermaid fenced blocks and parser where available;
- normative status/version terms;
- glossary term variants;
- endpoint → use case → transaction → UI action trace;
- table owner/retention coverage;
- OPEN decision references;
- git diff --check scoped to docs.

## Archive rule

Old document moves only when:

1. unique facts inventoried;
2. active destination linked;
3. code/release to which it applies tagged;
4. archive index records original path/date/status;
5. link audit updated.

Generated QA/performance reports are release evidence artifacts, not permanent
normative docs.
