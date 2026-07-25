# Manual Testing — Stage 0.13.3A.5 Migration Pilot

Дата: 2026-07-14. Статус: **PILOT ONLY / NOT PRODUCTION**.

## Scope

Проверяется только preservation-aware выборка из 200 receipt staging rows,
disposable pilot DB, read-only review UI, Equipment Card provenance и
audit-backed Timeline. Массовый Stage 0.13.3B, расход, лист `БАЛАНС`, reset и
замена `data/warehouse.db` не выполняются.

## 1. Baseline and immutability

Сохранить до проверки:

```bash
pwd
git status --short
git rev-parse HEAD
shasum -a 256 migration_inputs/raw/*
shasum -a 256 migration_inputs/normalized/serial_review.xlsx
shasum -a 256 data/warehouse.db
sqlite3 -readonly data/warehouse.db 'PRAGMA integrity_check; PRAGMA foreign_key_check;'
```

Ожидание: raw manifest сходится, рабочая БД имеет `integrity_check=ok`, FK output
пуст и рядом нет `warehouse.db-wal`, `warehouse.db-shm`, `warehouse.db-journal`.

## 2. Deterministic selection

```bash
python3 scripts/migration_pilot.py select
```

Проверить:

- output только в `migration_inputs/reports/`;
- 200 строк и seed `ODE-0.13.3A.5-PILOT-v1`;
- распределение `130/10/7/6/35/10/2` по семи решениям;
- минимум 50 ordinary text, 20 leading-zero, 20 long text, 20 server,
  20 component, 10 vendor, 20 duplicate group и 20 conflict group;
- exact duplicates ровно 6; seventh raw-exact candidate остаётся history из-за
  pending supplier alias. Duplicate/history coverage включает 26 identity
  conflicts и 9 date/shelf/order variations;
- Dell, Huawei, xFusion, Vegman R220, no-shelf и multi-shelf coverage;
- `VEGMAN_R200_UNAVAILABLE_FROM_SOURCE` присутствует, синтетической source row
  нет;
- повторный запуск на тех же hashes даёт тот же selection SHA.

Открыть `PILOT_RECEIPT_SELECTION.xlsx`, не сохранять его поверх raw. Убедиться,
что S/N, Part Number и identifier-поля имеют type text/format `@` и повторное
чтение сохраняет ведущие нули.

## 3. Build and validate pilot DB

```bash
python3 scripts/migration_pilot.py build
python3 scripts/migration_pilot.py validate
```

Проверить:

- DB создана только как
  `migration_inputs/workspace/warehouse_pilot_candidate.db`;
- marker `ODE_MIGRATION_PILOT`, stage `0.13.3A.5`, status
  `READY_FOR_REVIEW`, `pilot_only=1`, `review_read_only=1`;
- 200 selection rows и 130 imported receipts/identities;
- остальные решения не создают `stock_receipts`;
- на S/N одна карточка; duplicate/conflict rows связаны provenance;
- shelf не входит в identity;
- все pilot receipt quantities равны 1 и `is_opening_balance=1`;
- legacy `equipment` не создаётся;
- `integrity_check=ok`, FK output пуст, sidecars отсутствуют;
- POSIX mode DB — `0600`;
- SHA production DB не изменился.

## 4. Marker and launcher negative cases

На временных копиях, не на реальной pilot DB, проверить:

- `ODE_MIGRATION_PILOT=1` + обычная DB -> fail before service startup;
- marker DB без `ODE_MIGRATION_PILOT=1` -> fail;
- неверные filename/stage/status/pilot flags -> fail;
- hardlink/same file с `data/warehouse.db` -> fail;
- наличие `-wal`, `-shm` или `-journal` -> fail;
- launcher при отсутствии DB только сообщает ошибку и ничего не создаёт;
- launcher не перезаписывает существующий pilot artifact.

## 5. Role and read-only HTTP boundary

Запустить пилот:

```bash
./start_migration_pilot_macos.command
```

Проверить:

- баннер `МИГРАЦИОННЫЙ ПИЛОТ` виден до и после login;
- browser payload содержит только логический DB path;
- `viewer` не читает pilot selection/card;
- `engineer` и `admin` читают review;
- `GET /api/migration-pilot` поддерживает фильтры `IMPORT`, `QUARANTINE`,
  `CONFLICT`, `CORRUPTED` и search;
- card endpoint принимает `pilot_selection_id` для `IMPORT` и связанных
  `EXACT_DUPLICATE`/`CONFLICT_HISTORY_ONLY`; все они открывают одну primary
  card, а quarantine/manual/corrupted/quantity rows карточку не открывают;
- operational POST action/import/backup/restore отклоняется backend;
- UI не показывает destructive controls;
- raw XML, password hash, absolute path и traceback не попадают в response.

## 6. Exact S/N and Equipment Card

Для каждой leading-zero строки из generated report:

1. найти S/N в pilot review;
2. сравнить точное число/порядок code points с `source_serial_value`;
3. открыть Equipment Card;
4. подтвердить тот же S/N без trim/upper/leading-zero loss;
5. проверить Source, Original Item Name, Canonical Item Name, Preservation
   Status, Warnings и Source Rows;
6. проверить `Исторический приход (миграция)` и migration audit actions в
   Timeline.

Повторить для long text, mixed case, Cyrillic, internal-space и hyphen
fixtures. Ни один numeric/corrupted row не должен иметь кнопку рабочей карточки.

## 7. Naming, model and vendor separation

Проверить:

- Vegman R220 отображается как отдельная модель;
- реального R200 нет и UI/отчёт не создаёт его искусственно;
- synthetic unit contract сохраняет R200/R220 раздельно;
- Huawei и xFusion не объединены ни в vendor, ни в canonical name;
- unknown vendor/model остаётся source text + warning/manual review;
- canonical name не используется как identity.

## 8. Duplicate, conflict and shelf behavior

Проверить не менее одного примера каждого вида:

- exact duplicate: одна карточка, второй receipt отсутствует, provenance и
  `MIGRATION_EXACT_DUPLICATE_SKIPPED` сохранены;
- vendor/model/item conflict: одна карточка, conflicting source row находится
  в history, есть `MIGRATION_CONFLICT_RECORDED`;
- разные shelves одного S/N: одна identity/card; обе source locations видны;
- quarantine/corrupted/quantity-deferred: складской баланс не меняют.

## 9. Browser/headless smoke

Запустить проектный pilot headless scenario на временной копии pilot DB. Он
должен:

1. открыть pilot review;
2. найти leading-zero S/N;
3. открыть карточку;
4. проверить exact S/N, source/canonical names и Timeline;
5. проверить conflict/quarantine filters;
6. подтвердить `console.error=0`, `window.onerror=0`,
   `unhandledrejection=0`, resource errors `=0`, HTTP/API 500 `=0`.

Smoke также обязан сравнить SHA своей pilot DB copy до/после runtime: schema
initialization в pilot mode отключена, поэтому SHA должен совпасть.

Отдельно запустить обычный `python3 scripts/smoke_ui.py`, чтобы доказать
отсутствие regression production UI.

## 10. Final checks

```bash
python3 -m py_compile app.py inventory/**/*.py scripts/*.py tests/*.py
for file in static/js/**/*.js tests/headless_smoke.js tests/headless_migration_pilot_smoke.js; do node --check "$file" || exit 1; done
python3 scripts/audit_module_boundaries.py
python3 scripts/audit_frontend_contracts.py
python3 -W error::ResourceWarning -m unittest discover -s tests -v
python3 scripts/create_clean_test_db.py --dry-run
python3 scripts/smoke_ui.py
python3 scripts/smoke_migration_pilot_ui.py
git diff --check
```

Ожидаемый результат текущего Stage: `Ran 292 tests`, `OK`; оба smoke завершаются
без console/window/unhandled/resource/HTTP/API500 errors.

Повторить raw/normalized/production hashes и SQLite checks из baseline. Они
должны совпасть; pilot DB должна снова пройти integrity/FK и не иметь sidecars.
Убедиться, что raw/generated DB/reports не staged, commit/push/ZIP не созданы.

## Acceptance result

Результат ручной проверки должен быть одним из:

- `PILOT_ACCEPTED_FOR_0_13_3B_DESIGN` — разрешает только начать отдельное
  проектирование/Stage;
- `PILOT_CHANGES_REQUIRED` — перечисляет rejected rows/rules;
- `PILOT_BLOCKED_BY_SOURCE` — требует authoritative S/N/reference source.

Ни один результат не разрешает автоматически заменить production DB.
