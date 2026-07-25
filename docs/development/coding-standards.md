# Coding standards ODE 0.13

Статус: **PROPOSED**

## Structure

- File exists only for cohesive responsibility and used code.
- Recommended production file <=400 lines, function <=50 lines; exception needs
  review rationale.
- Domain models import no infrastructure/API/UI.
- Public ports and DTO fully typed; Any prohibited.
- No dynamic method dispatch by string/getattr for use cases.
- No service locator/global mutable application service.
- No empty facade/models/legacy marker modules.

## Functions

Excel read, normalization, match, validation, persistence, audit and rendering
are separate phases. Side effects explicit in name/port. Clock/UUID/filesystem
injected. Exceptions use stable domain codes, not text matching.

## Persistence

- Repository stages reads/writes only; no commit/rollback.
- SQL lives in infrastructure adapter owned by one context.
- Parameterized SQL only.
- Query contracts return immutable DTO.
- Explicit transaction in application command.
- No schema/data mutation on startup.
- Resource handles use context managers and leak tests.

## Data

- Raw and normalized identifiers separate.
- No float quantities.
- No local-time implicit conversion.
- No guessed identity/reference/date.
- Posted/snapshot/history/audit immutable by API and DB authorization.
- JSON schemas versioned and canonicalized for hashes.

## API/UI

- Resource endpoints and stable errors; no action switch.
- Server permissions authoritative.
- Idempotency on create/post.
- Keyset pagination.
- ES modules, no window global domain state or inline handlers.
- textContent/safe DOM by default.

## Tool gates

Formatter, Ruff, type checker, dependency boundary audit, complexity/size gate,
SQL ownership audit, secret/data artifact scan, tests appropriate to slice and
git diff --check. Suppression requires code and reason, not blanket file ignore.
