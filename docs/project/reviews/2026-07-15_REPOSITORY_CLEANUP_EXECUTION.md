# Repository Cleanup Execution — Phase 2

Статус: **COMPLETE**

Дата: 2026-07-15. Выполнение основано на Phase 1 audit и прямом разрешении
владельца удалить лишние версии и локальные артефакты при обязательном
сохранении активной рабочей БД. Исходный код, тесты, актуальная документация,
Git history, immutable migration raw и generated review reports не удалялись.

## Сохранённые authoritative объекты

- `data/warehouse.db` — единственная активная рабочая БД; post-cleanup SHA-256
  `73568a1c3eecbd4476473f064620d7f0a196b336ce8ea6d834c5b99359d4b010`;
- `release/ODE_0.12.17_RC1.zip` — последний фактический release ZIP; SHA-256
  `27cd04b36e09cd64f402e232f8d759be914ce961215a475ad712f97ac40a9501`;
- `migration_inputs/raw/`, `migration_inputs/normalized/` и
  `migration_inputs/reports/` — source/provenance/review contour;
- малые `.stabilization/` manifest и audit reports;
- внешний backup contour
  `/Users/lokolis/ODE_Backups/20260715-warehouse-full-audit-prechange/`.

## Удалённые объекты

| Объект | Размер, bytes | SHA-256 / доказательство | Основание |
|---|---:|---|---|
| `release/ODE_windows_test.zip` | 417493 | `27cd04b3...a9501` | Byte-identical duplicate canonical RC1 ZIP |
| `release/ODE_0.12.17_RC1/` | 1622873 file bytes, 184 files | `diff -qr` с распакованным canonical ZIP: no differences; ZIP `unzip -t`: PASS | Лишняя распакованная копия сохранённого ZIP |
| `.stabilization/20260715-warehouse-full-audit-prechange/warehouse.db` | 567816192 | `72408846...cb65`; `cmp` с внешним `warehouse.sqlite-backup.db`: equal; external integrity: `ok`, FK: 0 | Локальный дубль доказанного внешнего SQLite backup |
| `migration_inputs/workspace/candidate_validation.json` | 3617 | `ddac927a...d504` | Generated/disposable workspace output |
| `migration_inputs/workspace/reference_candidate_package.xlsx` | 178400 | `aa9a000e...8d92` | Generated/disposable workspace output |
| `migration_inputs/workspace/serial_preservation.csv` | 33700855 | `411f453a...9648` | Generated/disposable workspace output |
| `migration_inputs/workspace/warehouse_full_candidate.db` | 566059008 | `dd97fe6c...b53` | Generated candidate; active DB already promoted and independently verified |
| `migration_inputs/workspace/warehouse_migration_candidate.db` | 195825664 | `473d0e2d...de65` | Generated/disposable Stage A candidate |
| `migration_inputs/workspace/warehouse_pilot_candidate.db` | 196497408 | `b6ac005c...0ac` | Generated/disposable read-only pilot candidate |
| `.local/ode013/ode013-dev.db` | 811008 | `af2461f8...790f` | Regenerable Platform development DB |
| source-tree `__pycache__/` | 18 directories | Gitignored/regenerable | Cache hygiene |

Полные SHA удалённых workspace-файлов зафиксированы в командном evidence этой
сессии; сокращение в таблице используется только для читаемости. Workspace DB
воспроизводятся существующими migration builders из сохранённых raw sources.

## Результат

- размер working tree уменьшен примерно с 2.2 GiB до 711 MiB;
- `migration_inputs/` уменьшен до 49 MiB, `.stabilization/` — до 184 KiB,
  `release/` — до 408 KiB;
- в repository остались только две бинарные DB/ZIP позиции: активная
  `data/warehouse.db` и canonical release ZIP;
- Git-tracked исходники не удалялись, staging/commit/push не выполнялись.

## Post-cleanup verification

- full discovery: 392 tests, `OK (skipped=8)`, без ResourceWarning;
- восемь skip — только artifact-backed проверки удалённых ignored full/pilot
  candidate DB; temp/build/unit coverage продолжает выполняться;
- module-boundary audit: PASS;
- frontend-contract audit: PASS;
- clean-test-DB dry-run: PASS, source SHA unchanged;
- active DB: `integrity_check=ok`, FK violations 0, sidecars 0;
- `git diff --check`: PASS;
- codebase-memory fast reindex: 4398 nodes, 20044 edges,
  `artifact_present=false`.
