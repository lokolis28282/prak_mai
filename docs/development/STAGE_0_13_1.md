# Stage 0.13.1 — Foundation, versioned database and application core

Статус: **REVIEW_READY — ожидает независимый review и пользовательское approval**

Stage реализует минимальный runtime-фундамент ODE 0.13 параллельно ODE 0.12.
Он не меняет `app.py`, `inventory/` или `data/warehouse.db` и не запускает
Stage 0.13.2.

## Scope

- immutable typed database configuration and path policy;
- manifest-verified V001–V008 clean database creation;
- SQLite connection factory and `SqliteUnitOfWork`;
- explicit composition root;
- typed read-only diagnostics and health policy;
- CLI for create/status/verify/migrations/health;
- infrastructure, CLI and architecture regression tests.

## Package layout

```text
ode/
├── __init__.py
├── __main__.py
├── cli.py
├── schema_manifest.json
├── application/
│   ├── __init__.py
│   ├── config.py
│   ├── context.py
│   └── errors.py
├── infrastructure/
│   ├── __init__.py
│   ├── database.py
│   ├── diagnostics.py
│   ├── migrations.py
│   └── paths.py
└── system/
    ├── __init__.py
    ├── models.py
    ├── queries.py
    └── service.py
```

`SqliteUnitOfWork` находится рядом с единственной connection policy в
`infrastructure/database.py`: отдельный forwarding module не создавался, потому
что не добавлял бы contract или ownership. Future bounded-context packages и
пустые ports отсутствуют.

## CLI

Все команды требуют явный `--path`; `--json` допустим в любой позиции.

```console
python3 -m ode db create --path .local/ode013/ode013-dev.db
python3 -m ode db status --path .local/ode013/ode013-dev.db
python3 -m ode db verify --path .local/ode013/ode013-dev.db
python3 -m ode db migrations --path .local/ode013/ode013-dev.db
python3 -m ode system health --path .local/ode013/ode013-dev.db
```

Ожидаемые operational ошибки имеют stable envelope
`{"ok":false,"error":{"code":"...","message":"...","details":{}}}`.
Traceback не является частью CLI contract. `NOT_INITIALIZED` — успешный health
результат с exit code 0.

## Database path and security policy

Development DB: `.local/ode013/ode013-dev.db`; весь `.local/` исключён из Git.
Разрешены только canonical paths внутри `.local/ode013` и системного temporary
root. Другой development/test path требует `--allow-external-dev-path`, который
отражается в diagnostics. `data/warehouse.db`, `migration_inputs/raw`, path
traversal через symlink и malformed SQLite filenames отклоняются до open.

Надёжное определение network filesystem не переносимо в stdlib, поэтому
diagnostics честно возвращает warning `NETWORK_FILESYSTEM_NOT_VERIFIED` вместо
ложной гарантии. Operational deployment на network/cloud-synced filesystem
остаётся запрещён.

## Manifest and canonical DDL

Source of truth — только
`docs/architecture/ddl/V001__system_and_security.sql` …
`V008__audit_and_operations.sql`. Python не содержит копии DDL.
`ode/schema_manifest.json` фиксирует version 8, application ID `1329874225`,
ordered filenames, exact file SHA-256, registry count 8 и approved schema hash
`143bb0ae16c68c1fcd653ecc94adc62464746fed738ebfa47749057380f7f0cb`.

Approved schema hash воспроизводит exact bytes команды SQLite `.schema`:

1. прочитать все rows `sqlite_schema` с non-NULL `sql` в `rowid` order, включая
   internal `sqlite_sequence`;
2. вывести stored SQL каждого object;
3. для view перед `;` вывести newline и CLI comment
   `/* view_name(column1,column2,...) */`, где columns идут по `cid` из
   `pragma_table_info`;
4. завершить каждый object bytes `;\n`, кодировать UTF-8 и вычислить SHA-256.

Этот representation закреплён тестом двух независимых builds и не зависит от
installed `sqlite3` shell binary.

## Atomic creation flow

`db create` работает только для отсутствующего target:

1. проверяет manifest, exact file set/order/version/checksum;
2. создаёт temporary sibling candidate с permission `0600`;
3. применяет self-transactional migrations строго V001 → V008;
4. после каждого файла записывает и сверяет registry prefix, application ID и
   `user_version`;
5. запускает `verify_schema.sql`, `verify_domain_invariants.sql`, approved schema
   hash, `integrity_check` и `foreign_key_check`;
6. закрывает SQLite, требует отсутствие WAL/SHM/journal и fsync candidate;
7. atomically publishes новый inode через same-directory hard link, который не
   может перезаписать существующий target, затем удаляет candidate name.

Любой failure удаляет candidate и sidecars. Existing target возвращает
`DATABASE_ALREADY_EXISTS`. Upgrade/migrate существующей DB отсутствует и никогда
не вызывается application startup.

## Connection and Unit of Work

Factory владеет режимами write, read-only, immutable diagnostics и migration.
Каждый connection включает foreign keys, busy timeout, row factory и
`trusted_schema=OFF`; read-only включает `query_only=ON`, runtime writer —
WAL/`synchronous=FULL`, migration candidate — single-file DELETE journal.
Connections всегда context-managed и закрываются.

Write UoW использует `BEGIN IMMEDIATE`; отсутствие явного `uow.commit()` и любое
исключение приводят к rollback. Read-only mutation блокирует SQLite и получает
typed error. Nested write UoW в одном execution context запрещён. Runtime UoW
не является произвольной SQL-консолью: допускаются только обычные
`SELECT`/`INSERT`/`UPDATE`/`DELETE` и соответствующие `WITH`-операции. Запрещены
multiple statements, transaction-control, DDL, `ATTACH`/`DETACH`, произвольные
`PRAGMA` и прямые записи в `sqlite_schema`/`sqlite_master` (включая TEMP-алиасы).
Лексическая allowlist проверяется до execute, а SQLite authorizer даёт
defense-in-depth для runtime connection. Transaction boundary принадлежит UoW,
schema changes — только approved migration runner; migration connection не
использует runtime authorizer.

SQLite failures на begin/body/commit/rollback/close имеют typed contract:
`UnitOfWorkBeginError`, `UnitOfWorkCommitError`, `UnitOfWorkRollbackError`,
`UnitOfWorkCloseError`, `ReadOnlyMutationError` и `NestedUnitOfWorkError`
наследуют `UnitOfWorkError`. Deferred FK из V005 проверяется SQLite только при
commit; неуспешный commit возвращает `UNIT_OF_WORK_COMMIT_FAILED`, выполняет
rollback, если transaction ещё active, всегда закрывает connection и очищает
execution-context state. Исходная SQLite error доступна как `__cause__`; cleanup
failure не скрывает commit/body cause. Программистские ошибки без SQLite cause
не преобразуются. Domain logic, repository commit и неиспользуемый audit hook
отсутствуют.

## Diagnostics and health

Diagnostics открывает существующий файл immutable read-only только для закрытой
published DB без exact SQLite sidecars. Наличие `-wal`, `-shm` или `-journal`,
включая stale/zero-byte файл, до или после чтения даёт typed
`IMMUTABLE_SNAPSHOT_UNSAFE`; status/verify/health не возвращают authoritative
state по main file. Никакого автоматического WAL-aware fallback нет. Diagnostics
не выполняет migration, repair, audit, sidecar delete или WAL checkpoint. Для
безопасного closed snapshot она возвращает versions/registry, integrity/FK,
object and empty-domain counts, sidecars, schema hash, baseline, ledger head,
projection and legacy state. Tests фиксируют SHA и nanosecond mtime main DB и
sidecars до/после; unrelated похожие имена не считаются SQLite sidecars.

Human CLI экранирует C0/C1 и bidi controls в display values (`\\xNN`,
`\\uNNNN`), сохраняя обычные Unicode paths. Реальный canonical path не меняется.
JSON mode использует исходные значения и стандартное JSON escaping, остаётся
parseable и не получает terminal-specific transformation.

После clean create:

- `schema_ready=true`;
- `baseline_state=NOT_INITIALIZED`;
- `warehouse_posting_enabled=false`;
- `active_snapshot_id=null`, `ledger_head=0`;
- `projection_state=UNAVAILABLE`;
- `legacy_history_state=NOT_IMPORTED`;
- users/equipment/legacy/snapshots/ledger/projections = 0;
- общий status `NOT_INITIALIZED`, exit code 0.

## Verification commands

```console
python3 -m compileall -q ode
PYTHONWARNINGS='error::ResourceWarning' \
  python3 -m unittest discover -s tests/ode013 -t . -v
python3 scripts/audit_module_boundaries.py
git diff --check
```

Focused suite строит disposable DB; production DB используется только через
read-only immutable checks в final gate.

## Non-goals and known limitations

- нет HTTP endpoint/API/UI и test entity;
- нет users/security/reference/equipment/inventory/warehouse business behavior;
- нет default credentials или bootstrap data;
- нет upgrade existing DB, backup/restore, process-owner lock или runtime startup;
- нет automatic migration, dual-write, real-data migration или production open;
- network filesystem только предупреждается: portable detector не заявлен;
- atomic new-file publish требует local filesystem с hard-link support и иначе
  fail-closed; это не operational replace protocol существующей DB;
- immutable diagnostics fail-closed при любом exact SQLite sidecar; online
  WAL-aware operational diagnostics/checkpoint policy и process-owner lock
  относятся к последующему lifecycle stage;
- POSIX hard-link/permission behavior проверено на macOS; Windows host в этом
  correction stage не проверялся;
- SIGKILL между successful `os.link(candidate, target)` и удалением candidate
  name может оставить второй hard-link на тот же валидный inode; это manual
  cleanup edge case, не partial/corrupt target;
- NFC/NFD Unicode filenames остаются разными filesystem path identities.
  Protected production/source roots сейчас ASCII-only; normalization не
  вводится без отдельного cross-platform path ADR.

## Independent review checklist

- manifest/source mutation and candidate cleanup tests;
- exact `.schema` hash representation and two-build equality;
- atomic no-overwrite create, `0600`, no sidecars;
- path/symlink/production/raw/external override policy;
- connection PRAGMAs and UoW commit/rollback/nesting/query-only behavior;
- diagnostics SHA/mtime immutability and wrong-ID/version/FK/corruption cases;
- JSON/human CLI and exit/error contracts;
- ODE 0.12 ↔ ODE 0.13 import isolation and no embedded DDL/default user/HTTP.

## Stage 0.13.2 entry criteria

Stage 0.13.2 нельзя начинать автоматически. Entry требует успешного независимого
review Stage 0.13.1, устранения его blocking findings и отдельного явного
пользовательского подтверждения.
