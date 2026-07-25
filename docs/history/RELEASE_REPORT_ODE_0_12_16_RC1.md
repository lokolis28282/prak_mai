# ODE 0.12.16 RC1 Release Report

Date/time: 2026-07-11 04:17 MSK
Version: ODE 0.12.16 RC1
Commit: 739faf7
Decision: Passed for transfer to a Windows laptop for test operation.

## Artifacts

- Release folder: `release/ODE_0.12.16_RC1/`
- Main ZIP: `release/ODE_0.12.16_RC1.zip`
- Compatible ZIP: `release/ODE_windows_test.zip`
- Pre-release backup: `release_backups/pre_ode_0_12_16_rc1_20260711_041707/`

## Hashes

- Working DB SHA-256: `5eb98ea10824d92bc1ddbcbee2cdde92b630b7c9cc1c324af6ea40d5a66396f1`
- Release DB SHA-256: `5eb98ea10824d92bc1ddbcbee2cdde92b630b7c9cc1c324af6ea40d5a66396f1`
- Main ZIP SHA-256: `9eb3f20bb60fa65ec9d987551e16555323e9271e303a3e3865e4fa9e11d9a23e`
- Compatible ZIP SHA-256: `9eb3f20bb60fa65ec9d987551e16555323e9271e303a3e3865e4fa9e11d9a23e`
- Release `app.py`: `9d7b7b34e9b1dc9a5800f74ca5750cf66215346bf2f74bbc56474ac171a2df87`
- Release `inventory/webapp.py`: `508280a6f88cdc736671cf781c46c25c1b73dc8020fd8993be6e0b942ce1bfbe`
- Release `static/js/ui.js`: `bddf2553353badb6338e01bd6061e666004c7d91cbf3a4b7a2abafba909698ff`
- Release `VERSION`: `1462ed5a189c2a34a5bee493e4e416f05e5a92841d8a7e7b481d0554689e2c5f`

## Package Stats

- Release files: 136
- Main ZIP size: 253,160 bytes
- Compatible ZIP size: 253,160 bytes
- Archive root: `ODE/`
- `unzip -t release/ODE_0.12.16_RC1.zip`: passed
- `unzip -t release/ODE_windows_test.zip`: passed
- Forbidden files: none found for tests, scripts, docs architecture, backups, release, exports, screenshots, `.git`, `__pycache__`, `*.pyc`, `.DS_Store`.

## Pre-Build Checks

- `python3 -m py_compile app.py inventory/**/*.py scripts/*.py tests/*.py`: passed
- `node --check static/js/**/*.js tests/headless_smoke.js`: passed
- `python3 scripts/audit_module_boundaries.py`: passed
- `python3 scripts/audit_frontend_contracts.py`: passed
- `python3 scripts/smoke_ui.py`: passed
- `python3 -W error::ResourceWarning -m unittest discover -s tests -v`: 158 tests passed
- `sqlite3 data/warehouse.db "PRAGMA integrity_check;"`: `ok`
- `sqlite3 data/warehouse.db "PRAGMA foreign_key_check;"`: empty
- Acceptance reports present:
  - `ACCEPTANCE_DELIVERIES_0_12_16.md`
  - `BUGS_DELIVERIES_0_12_16.md`

## Isolated Package Validation

ZIP was extracted to a new temporary directory:

- `/var/folders/69/0blt65cn5v11xdxs75zyvcs40000gn/T/ode_rc1_isolated_final_des9svgk/ODE`

Validation results:

- Python compile from extracted folder: 91 runtime Python files compiled.
- JS syntax from extracted folder: 33 runtime JS files checked.
- Release DB `PRAGMA integrity_check`: `ok`
- Release DB `PRAGMA foreign_key_check`: empty
- Absolute source project path references: none
- Server launched from extracted folder with a copy of release DB.
- HTTP `/`: 200
- HTTP `/static/css/main.css`: 200
- HTTP `/static/js/ui.js`: 200
- Headless Chrome smoke against extracted release:
  - title: `Начало смены — ODE 0.12.16 RC1`
  - `/api/data`: 200
  - runtime errors: 0
  - resource errors: 0
  - API 500: 0

## Windows Static Validation

- `start_windows.bat` uses `chcp 65001`.
- Starts from its own directory via `cd /d "%~dp0"`.
- Uses `py -3 app.py`, with fallback to `python app.py`.
- Shows a clear message when Python is missing.
- Contains no bash commands.
- Contains no macOS-only absolute paths.
- Runtime paths are relative to the package folder.

Physical Windows launch: Pending. No Windows host was available in this environment.

## Git State

Git was available. No commit was created. The worktree already contains many unrelated modified/deleted/untracked files from prior stages. The RC backup includes `GIT_STATUS.txt` with the full status snapshot at backup time.

## Known Limitations

- `close_delivery` remains compatibility/legacy.
- Destructive override of conflicting existing data is not implemented.
- Monitoring is a placeholder.
- Part of the frontend remains legacy `ui.js`.
- WarehouseCore remains a compatibility core.
- Physical Windows launch must be confirmed on the target laptop.
- Scheduled automatic backup is not implemented.
- Server deployment is not implemented.

## Recommendation

ODE 0.12.16 RC1 can be transferred to the working Windows laptop for test operation. This is not a production release.
