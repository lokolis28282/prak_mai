# Разделение release и данных

Статус: **APPROVED; Stage 0.13.1 controls REVIEW_READY**

Stage 0.13.1 development DB находится в `.local/ode013/`, а `/.local/` входит
в Git ignore. `ode/schema_manifest.json` и canonical DDL входят в source;
`.local`, candidate DB и SQLite sidecars — generated data и не входят в release.

## Release allowlist

Release contains:

- application code/binary and static assets;
- dependency/license manifests;
- versioned empty schema migrations;
- public templates only after separate approval;
- minimal active docs/runbooks;
- build manifest and checksums.

## Absolute denylist

- data/warehouse.db и любые .db/.sqlite with user data;
- WAL/SHM/journal;
- Preview workspace/candidate;
- source/legacy Excel;
- backups and manifests containing paths/users;
- password hashes, sessions, tokens, secrets;
- migration_inputs and generated reports;
- local logs/audit exports;
- .stabilization artifacts;
- old release ZIP nested in new ZIP.

Build fails if denylist path or SQLite magic header appears outside explicitly
approved empty bootstrap fixture. Empty DB лучше создавать installer command,
а не shipping file.

## Git

Live DB and generated release ZIP must cease being tracked after verified
archive/cutover. Removing from current tree is not historical purge; any Git
history data-removal operation requires separate security decision and backup.

## Installation and upgrade

Installer creates code directories only. First-run admin command selects data
root and creates versioned empty DB. Upgrade preflight backs up data, applies
explicit migration and never replaces data with release content.

## Build gate

Machine-readable allowlist, archive listing, secret scan, SQLite-header scan,
size anomaly scan and reproducible hash report. Human reviewer confirms release
can be copied publicly without revealing warehouse facts.
