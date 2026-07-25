# Stage 0.13.1 — Independent adversarial review

Статус: **REVIEW COMPLETE — CONDITIONAL ACCEPT (fixes required before Stage 0.13.2)**

Дата: 2026-07-15. Ревьюер: независимый adversarial review (роли Principal
Python Engineer / Senior SQLite Engineer / Security Reviewer / Operations
Engineer), без доверия отчёту исполнителя (Codex) и без subagents. Каждое
утверждение ниже подтверждено либо чтением фактического кода, либо
воспроизводимым скриптом, выполненным в этой сессии.

Ничего не исправлялось. `ode/`, `tests/`, продуктовый код и
`data/warehouse.db` не изменялись этим review.

## 1. Verdict

**CONDITIONAL ACCEPT.** Фундамент архитектурно корректен, path-safety и
manifest/migration integrity guards — сильные и адверсариально устойчивые
(см. §3–§5, все атаки заблокированы). Найдено 0 BLOCKER, 0 CRITICAL, но 3
MEDIUM finding (F1–F3) представляют реальный риск для Stage 0.13.2, потому что
именно они попадают в код, который 0.13.2 начнёт активно использовать
(`SqliteUnitOfWork` для domain writes, diagnostics при live-операции). Stage
0.13.1 **как staged foundation** можно принять — CLI, manifest, atomic create,
path policy готовы. Но перед стартом Stage 0.13.2 рекомендуется закрыть F1 и
F3 (UoW commit-exception wrapping и WAL-aware diagnostics warning), так как
0.13.2 — первый stage, где они становятся достижимы через реальные command
paths.

## 2. Findings table

| ID | Severity | Область | Файл:строки | Блокирует 0.13.2 | Блокирует deployment |
|---|---|---|---|---|---|
| F1 | MEDIUM (HIGH impact, LOW current reachability) | UoW error contract | `ode/infrastructure/database.py:218-221` | Да, до фикса | Да |
| F2 | MEDIUM | Migration runner error contract | `ode/infrastructure/migrations.py:212-213` | Рекомендуется | Да |
| F3 | MEDIUM | Diagnostics correctness/staleness | `ode/infrastructure/diagnostics.py:52,171` | Да, до фикса | Да |
| F4 | LOW-MEDIUM | CLI output sanitization | `ode/cli.py:58-67` | Нет | Рекомендуется |
| F5 | LOW | UoW misuse guard | `ode/infrastructure/database.py:176-190` | Нет | Нет |
| F6 | LOW (non-blocking) | UoW misuse guard | `ode/infrastructure/database.py:176-190` | Нет | Нет |
| F7 | LOW (informational) | Path normalization | `ode/infrastructure/paths.py:37-101` | Нет | Нет |

Ни один finding не является BLOCKER/CRITICAL: во всех случаях либо (a) данные
остаются корректными и rollback безопасен (подтверждено воспроизведением), либо
(b) путь неприменим в текущем Stage 0.13.1 CLI (ни одна команда пока не
вызывает `SqliteUnitOfWork`).

## 3. Preservation evidence

Baseline до review и после review идентичны:

```
branch: main
HEAD:        76afadd5355f4d379b19dcabf1f28850986d5300
origin/main:  76afadd5355f4d379b19dcabf1f28850986d5300  (равны — до и после)
```

`data/warehouse.db`:

- SHA-256 до и после review: `73568a1c3eecbd4476473f064620d7f0a196b336ce8ea6d834c5b99359d4b010`
  (идентичен на обоих концах сессии — сверено дважды).
- `PRAGMA integrity_check` → `ok`; `PRAGMA foreign_key_check` → 0 violations.
- Нет `-wal`/`-shm`/`-journal` sidecar файлов рядом с `data/warehouse.db`.
- Файл уже был помечен как `изменено` в `git status` **на момент старта этой
  сессии** (245 760 → 579 461 120 байт — это ранее выполненная promotion
  полного historical candidate, задокументированная в `CLAUDE.md` под
  «Текущий локальный контур (2026-07-14)»). Это состояние **предшествует**
  данному review и не связано со Stage 0.13.1 или с действиями в этой сессии;
  ни один байт файла не был записан мной — подтверждено идентичным SHA-256 до
  и после.

Product code (`app.py`, `inventory/`) не изменялся Stage 0.13.1: в текущем
`git status` нет модификаций `app.py`; модификации внутри `inventory/*`,
присутствующие в рабочем дереве, — это тоже pre-existing изменения с начала
сессии (часть незакоммиченной работы, предшествующей этому review), не
относящиеся к `ode/` и не тронутые мной. `ode/` не появляется в diff против
`origin/main` как модификация существующих файлов — весь пакет
untracked/новый, что соответствует side-by-side foundation.

Каждый adversarial/repro-скрипт этой сессии выполнялся только на temp DB под
`tempfile.gettempdir()` или в `TemporaryDirectory()`; ни один не писал в
`data/`. Итоговые временные файлы удалены.

## 4. Manifest review

`ode/schema_manifest.json` независимо сверен байт-в-байт с
`docs/architecture/ddl/V001..V008`:

```
946e17453d3926648caebca0e9287af2fffc56a0a3548c37289712ba0316570b V001
781ea0f8a1f7e0a45188132b383b6f9d3db5e0a26003566bb5004ce91566ff50 V002
a5e7a4e4f0dd20bbea163a0aa4204d8703653d352a49b963a22ec30896fa466f V003
e830e9a8d658f8528e57532ea71ea5dc2d66afa60fcab3ecebe6888a9e81d76f V004
1ec116d96c150a28d22a39fdde6ecdf3bdec3cb6c16d07715e52c4e3151c822a V005
e34ec3431786d6746b90d07ab69d0cc7222657da1f99c6784a5de51e97d4d2fb V006
c0fa68fe2d62fdd7929b38abd7184f7bc86e081b10dc6f5630723406d4fe28a5 V007
25e0beaae0f6ea1883f796938ff2eed6d3095ec0374c111b7d38bc37386d52b6 V008
```

Все 8 совпадают с `shasum -a 256` фактических DDL файлов и с manifest.
`approved_schema_hash` в manifest = `143bb0ae...f0cb`, совпадает с hash,
переданным в задании review, и с hash, независимо вычисленным двумя
раздельными clean builds (см. §5).

Adversarial mutation тесты на **временных копиях** manifest (не на
`ode/schema_manifest.json`):

| Мутация | Результат |
|---|---|
| Изменить checksum одного migration | `SCHEMA_MIGRATION_CHECKSUM_MISMATCH` (существующий unit test + независимо подтверждено) |
| Удалить последнюю запись из manifest (файл остаётся на диске) | `MANIFEST_CONTRACT_MISMATCH` (независимо подтверждено — `expected_migration_count` перестаёт совпадать с `schema_version`) |
| Добавить лишний DDL файл сверх manifest | `MIGRATION_SET_MISMATCH`, extra_count=1 (существующий unit test) |
| Переставить порядок двух записей | `MIGRATION_ORDER_MISMATCH` (существующий unit test) |
| Дублировать версию | `DUPLICATE_MIGRATION_VERSION` (существующий unit test) |
| sha256 в верхнем регистре (валидный hex, но не lowercase) | `INVALID_SCHEMA_MANIFEST` — независимо подтверждено, строгий regex `^[0-9a-f]{64}$` |
| Path traversal в поле `file` (`V001__../../../../etc/passwd.sql`, при этом сам regex `.+\.sql$` его пропускает) | `INVALID_SCHEMA_MANIFEST` — заблокировано отдельной проверкой `Path(migration.file).name != migration.file` в `_validate_manifest_contract`; независимо подтверждено |
| Symlink на migration-файл, указывающий на файл с ИДЕНТИЧНЫМ содержимым | Проходит (ожидаемо — верификация по содержимому, не по факту symlink) |
| Symlink на migration-файл, указывающий на **несуществующий** файл (dangling) | **Финдинг F2** — untyped `FileNotFoundError` вместо `MigrationError` (см. §17) |

Вывод: manifest verification — сильная сторона реализации; единственный gap —
обработка I/O-ошибок при чтении source файлов (F2), а не сама модель доверия.

## 5. Migration runner review

Create flow независимо воспроизведён (не через существующие тесты, а через
отдельные repro-скрипты в `/tmp`) для каждого сценария:

- **Clean create дважды** (`indep1.db`, `indep2.db`, независимо от
  `.local/ode013/ode013-dev.db`) → все три: `application_id=1329874225`,
  `user_version=8`, `schema_migrations`=8 rows, `users=0`, permissions `0600`,
  идентичные `tables=41/indexes=73/triggers=73/views=3` (после исключения
  `sqlite_%`), идентичный `approved_schema_hash`. Полная детерминированность
  подтверждена независимо от исполнителя.
- **Target уже существует** → `DATABASE_ALREADY_EXISTS`, файл не тронут
  (существующий unit test + независимо).
- **Конкурентное появление target непосредственно перед публикацией**
  (инструментировано monkeypatch вокруг `_publish_absent_target`, создающим
  target-файл прямо перед вызовом `os.link`) → `os.link` атомарно возвращает
  `EEXIST`, раннер конвертирует в `DATABASE_ALREADY_EXISTS`; **чужой** контент
  target сохранён без перезаписи; candidate и sidecar-файлы гарантированно
  удалены. **TOCTOU в точке публикации отсутствует** — это ключевое свойство
  hard-link no-clobber семантики, подтверждено эмпирически, а не только
  документацией.
- **Permission denied на родительской директории** (`chmod 0500` на parent,
  target внутри отсутствующей поддиректории) → `PermissionError` **не
  завёрнут** в `MigrationError` — см. **F2**.
- **Симуляция EXDEV** (`os.link` монки-патчен на `OSError(errno.EXDEV, ...)`,
  имитация недоступности hard link на другой файловой системе) →
  `DATABASE_CREATE_FAILED`, target не создан, candidate удалён. Runner
  корректно **fail-closed**, соответствует явной формулировке в
  `STAGE_0_13_1.md`: «atomic new-file publish требует local filesystem с
  hard-link support и иначе fail-closed». Никакого overclaim о cross-device
  support код не делает и ничего не «чинит» молча.
- **Middle-of-migration tampering**: V001 модифицирован так, чтобы выставлять
  другой `application_id` (`0x4F444531` → `999999`), manifest checksum
  синхронно обновлён под новый байт-контент (то есть checksum-guard сам по
  себе НЕ защищает от этой атаки — она моделирует легитимно
  checksummed-but-wrong DDL, например ошибку в approved DDL review, а не
  подмену файла). `_verify_applied_prefix` после первого же
  `connection.execute(script)` обнаруживает несовпадение `application_id` и
  бросает `INVALID_APPLICATION_ID` **до** любой публикации; candidate удалён,
  target не создан. Это подтверждает, что защита работает на двух
  независимых уровнях (checksum ДО применения + `PRAGMA`/registry-проверка
  ПОСЛЕ применения), а не полагается только на checksum.
- **KeyboardInterrupt** посреди `_verify_connection`: воспроизведено
  существующим unit test (`test_interrupted_migration_deletes_candidate_and_leaves_no_target`)
  и независимо прочитано в коде — `except BaseException` ветка в `create()`
  вызывает `_cleanup_candidate` и, если публикация уже случилась
  (`published_by_runner=True`), откатывает `target.unlink()`. Порядок
  корректен: candidate build/verify всегда предшествует publish, поэтому при
  KeyboardInterrupt **до** publish target гарантированно не создаётся.

### Оценка заявления «atomic no-overwrite hard-link publish»

Заявление **подтверждено** для целевого случая (local POSIX filesystem,
same-directory candidate/target, оба на одном volume по построению —
`candidate = target.with_name(...)` гарантирует общий parent, что исключает
EXDEV в нормальном режиме):

- `os.link` атомарен и no-clobber на уровне ядра ОС (в отличие от
  `os.replace`/`os.rename`, которые молча перезаписывают существующий файл на
  POSIX) — корректный выбор примитива для «никогда не перезаписывать target».
- После `os.link` inode candidate имеет 2 hard-link имени; `candidate.unlink()`
  сразу после `fsync(directory)` убирает временное имя, оставляя единственное
  publish-имя — inode остаётся ровно один, sidecar-имён не остаётся
  (подтверждено `_assert_no_sidecars`).
- Directory fsync после `os.link` присутствует (`_publish_absent_target`),
  что действительно нужно для durability directory entry на POSIX.

Ограничения, которые код и документация **честно** не скрывают (не blocker,
а зафиксированный non-goal):

- Не переносимо на файловые системы без hard link (некоторые FAT/exFAT
  volumes, отдельные network filesystems) — в этом случае fail-closed
  подтверждён (см. EXDEV-симуляцию выше), а не «работает частично».
  `STAGE_0_13_1.md` формулирует это явно, без overclaim.
  Windows не тестировался в этой сессии (среда — macOS); `os.link` на Windows
  маппится на `CreateHardLinkW` и работает на NTFS, но это не проверено здесь
  эмпирически — оставляю как непроверенное, а не как подтверждённый факт.
- Это НЕ operational replace-protocol для существующей БД — работает только
  для отсутствующего target. Отдельный replace/publish protocol для
  operational cutover (WAL checkpoint, ReplaceFileW и т.д.) описан в
  `docs/operations/database-lifecycle.md` как задача **будущего** stage и
  Stage 0.13.1 не реализует и не заявляет его — соответствие подтверждено.

## 6. Path-safety review

Все проверки выполнены на временных путях, не production DB, но включали
намеренные попытки алиасировать реальный `data/warehouse.db`:

| Сценарий | Результат |
|---|---|
| Прямой путь `data/warehouse.db` | `PRODUCTION_DATABASE_FORBIDDEN` (существующий тест) |
| Symlink внутри allowed dev root → `data/warehouse.db` | `PRODUCTION_DATABASE_FORBIDDEN` — **независимо подтверждено**; `.resolve()` разыменовывает symlink до сравнения с `PRODUCTION_DATABASE`, поэтому symlink-обход невозможен на уровне `canonical_database_path` |
| **Hard link** внутри allowed dev root → `data/warehouse.db` (тот же inode, без копирования 579 МБ) | `PRODUCTION_DATABASE_FORBIDDEN` — **независимо подтверждено**; ловится через `os.path.samefile(resolved, PRODUCTION_DATABASE)`, что специально устойчиво к hard link (в отличие от чистого path-сравнения) |
| Регистро-другой путь (`Data/warehouse.db`) | `PRODUCTION_DATABASE_FORBIDDEN` (macOS default case-insensitive FS резолвит его в тот же файл — платформенно-зависимо, но корректно на этой машине) |
| `migration_inputs/raw/...db` даже с `--allow-external-dev-path` | `SOURCE_PATH_FORBIDDEN` (существующий тест) |
| Symlink-directory эскейп из `LOCAL_DATABASE_ROOT` наружу | `SYMLINK_ESCAPE` (существующий тест) |
| Путь `/` | `INVALID_DATABASE_PATH` (нет `.db`-суффикса) |
| Директория вместо файла (`dir.db/` — существующая директория) | Config принимает путь (суффикс — чисто по имени), но `create()` видит `target.exists() == True` и корректно отказывает `DATABASE_ALREADY_EXISTS` до любой записи — fail-closed, хотя код ошибки не идеально описателен для этого конкретного случая (не blocker) |
| NUL-байт в пути | `INVALID_DATABASE_PATH` (существующий тест) |
| Control character (не NUL) в имени файла | Принимается — легально на POSIX-уровне пути, не является уязвимостью path policy как таковой, но см. **F4** (терминал/вывод) |
| NFC vs NFD Unicode-нормализация одного и того же видимого имени | Дают **разные** `resolved` Path (нет NFKC-нормализации на уровне `canonical_database_path`) — см. **F7**, informational, не демонстрирует security bypass, т.к. все protected paths ASCII-only |
| `--path -- ...` / `--path --allow-external-dev-path` (опция вместо значения) | argparse корректно требует значение → `INVALID_CLI_ARGUMENTS`, exit 2, без traceback |

TOCTOU между validation и открытием connection: `_open()` в
`SQLiteConnectionFactory` **повторно** вызывает `canonical_database_path` и
сравнивает результат с уже сохранённым `self._config.db_path`, отклоняя с
`DATABASE_PATH_CHANGED`, если путь между конфигурацией и открытием изменился
(например, кто-то подложил symlink после валидации, но до открытия). Это
защита в глубину сверх TOCTOU на уровне `create()`/`os.link`, подтверждена
чтением кода (`database.py:58-67`).

## 7. Connection/UoW review

Pragma-проверки подтверждены существующим тестом
(`test_connection_pragmas_and_close`) и независимо: `foreign_keys=1`,
`busy_timeout=10000`, `trusted_schema=0`, writer `journal_mode=wal`,
migration-candidate `journal_mode=delete`, read-only `query_only=on`.
Соединение действительно закрывается по выходу из context manager (проверено:
использование handle после `__exit__` бросает `sqlite3.ProgrammingError`).

Независимо воспроизведённые edge cases (все — на throwaway temp DB):

| Сценарий | Результат |
|---|---|
| Nested write UoW в одном execution context | `NESTED_WRITE_UNIT_OF_WORK` (существующий тест + подтверждено) |
| Nested-state после исключения — переиспользование UoW в том же потоке | Флаг корректно сброшен в `finally` (`_write_token` reset) — новый write UoW после падения предыдущего успешно открывается, не залипает |
| Read-only mutation | `READ_ONLY_MUTATION`, откатывается (существующий тест) |
| Double `uow.commit()` | Идемпотентно, одна запись, без ошибки |
| `uow.rollback()`, затем `uow.commit()` | Побеждает фактический rollback (данные не сохраняются) — `connection.commit()` в `__exit__` при отсутствии активной транзакции — безопасный no-op в sqlite3 module; **корректно**, не finding |
| Constraint failure на `execute()` (немедленный UNIQUE/NOT NULL и т.п.) | `UNIT_OF_WORK_SQL_FAILED`, без partial rows (существующий тест) |
| **Deferred FK violation, не пойманная на `execute()`, а всплывающая ровно на `connection.commit()`** (реальный `DEFERRABLE INITIALLY DEFERRED` FK есть в approved DDL — `inventory_snapshots.superseded_by_snapshot_id`, V005) | **F1** — сырое `sqlite3.IntegrityError` вместо `UnitOfWorkError`; данные корректно не сохраняются (0 rows), но контракт типизированных ошибок нарушен |
| Ручной `uow.execute("COMMIT")` внутри write UoW (обход `uow.commit()`) | **F5** — фиксирует commit в БД, при этом `_commit_requested` остаётся `False`; `__exit__` считает, что делает rollback, но данные уже сохранены — bookkeeping рассинхронизирован с реальным состоянием транзакции |
| DDL (`CREATE TABLE`) внутри write UoW | Проходит без ошибки — **F6**, non-blocking |
| Последовательные (не одновременные, `.join()`-сериализованные) write UoW в двух threads | Оба успешны; contextvar корректно изолирован по потокам — не демонстрирует настоящую concurrency (см. §12 ограничение), но подтверждает отсутствие state leakage между потоками |
| Закрытие write-соединения не оставляет `-wal`/`-shm` (single-shot open/close) | Подтверждено существующим тестом и диагностикой (§8) |

## 8. Diagnostics/health review

SHA-256 и nanosecond mtime до/после `diagnostics()` идентичны — подтверждено
существующим тестом и независимо повторено. Не создаются WAL/SHM/journal,
не создаются `sqlite_stat*`, audit или migration rows читающими операциями.
Отсутствующая БД не создаётся (`DATABASE_NOT_FOUND`, файл не появляется).
ODE 0.12-подобная БД (произвольная левая SQLite схема) отклоняется как
`INVALID_APPLICATION_ID` без мутации (существующий тест + независимо).
Truncated/corrupt DB отклоняется без мутации файла (существующий тест).

**F3 (главная находка этого раздела):** `IMMUTABLE_READ_ONLY` (`immutable=1`)
корректно не создаёт побочных файлов, но и не видит данные, которые writer
уже закоммитил в WAL, если WAL ещё не checkpoint-нут. Воспроизведено
буквально: открыт write-соединение в WAL-режиме, вставлена и закоммичена
строка, write-соединение НЕ закрыто (WAL остаётся на диске) → отдельное
`IMMUTABLE_READ_ONLY` соединение читает `count(*)=0` для только что
закоммиченной строки, при этом `diagnostics.wal_present=True` уже вычислен
корректно, но `diagnostics.warnings` не содержит никакого предупреждения об
этом — только статичный `NETWORK_FILESYSTEM_NOT_VERIFIED`. Для Stage 0.13.1
это не проблема (единственный writer — сам `create()`, closed до всякой
diagnostics), но при Stage 0.13.2+ live-операции `db status`/`system health`
могут молча показывать устаревшее состояние без единого warning-флага,
несмотря на то что вся необходимая информация (`wal_present`) уже собрана и
просто не используется для решения.

Health-приоритет подтверждён кодом и существующим property-тестом
(`test_health_policy_maps_all_critical_diagnostic_states`): при одновременном
наличии нескольких проблем порядок такой — `INTEGRITY_FAILED` >
`FOREIGN_KEY_FAILED` > `UNSUPPORTED_VERSION` > `INVALID_SCHEMA` >
`NOT_INITIALIZED` > `READY` > `DEGRADED` (fallback). Порядок логически
корректен (наиболее фундаментальные повреждения проверяются первыми), не
скрывает integrity/FK проблему за более «мягким» статусом.

Clean-DB baseline (NOT_INITIALIZED, schema_ready=true, posting disabled,
все домены = 0, exit 0) подтверждён и существующим тестом, и тремя
независимо построенными БД в этой сессии.

## 9. CLI review

Все реализованные команды (`db create/status/verify/migrations`,
`system health`) протестированы в human и JSON режимах, включая ошибочные
пути:

- Неизвестная подкоманда, отсутствующий `--path`, `--path` без значения
  (включая `--path --allow-external-dev-path` и `--path --`) →
  `INVALID_CLI_ARGUMENTS`, exit 2, ни одного traceback в stdout/stderr.
- `db create` на существующем target и `system health` на отсутствующей БД →
  стабильные `DATABASE_ALREADY_EXISTS` / `DATABASE_NOT_FOUND` (существующий
  subprocess-based тест + независимо).
- JSON envelope во всех случаях — валидный, парсибельный JSON, включая пути с
  кавычками/апострофом внутри (`ensure_ascii=False` + `json.dumps`
  корректно экранирует управляющие символы согласно спецификации JSON —
  подтверждено: ESC-байт НЕ просачивается в `--json` режим).
- **F4**: human-режим (`_human_success`, `ode/cli.py:58-67`) печатает
  строковые значения payload через `print(f"{key}: {value}")` без
  экранирования. Подтверждено: `--path` с встроенной ANSI-последовательностью
  (`\x1b[31mRED\x1b[0m`) приводит к тому, что сырой `0x1b` байт присутствует в
  stdout при `db create` без `--json`. Не эксплуатируется в текущем
  однопользовательском локальном CLI-контексте, но является реальным
  terminal-escape-injection примитивом, если путь когда-либо придёт из
  внешнего/непроверенного источника и результат будет показан в терминале.
- `--help` не создаёт файлов (`.local/` до/после идентичен) и не требует БД.
- Импорт `ode` и всех подмодулей не создаёт файлов и не открывает БД
  (независимо подтверждено snapshot-сравнением `.local/` до/после импорта).
- `python3 -m ode` без PYTHONPATH из директории вне репозитория даёт
  `ModuleNotFoundError` — ожидаемо, пакет не устанавливается через
  setup.py/pyproject (упаковка вне scope Stage 0.13.1, non-issue).

## 10. Test-quality review

Прочитаны все 38 тестов в `tests/ode013/` (4 файла). Наблюдения:

- Тесты в основном проверяют **поведение** (реальные вставки/чтения через
  публичный API, subprocess для CLI), а не совпадение строк с реализацией —
  хорошее качество. Исключение: `test_sql_migrations_are_not_duplicated_in_python`,
  `test_no_default_users_http_or_product_database_constant`,
  `test_context_build_does_not_create_or_migrate_database` в
  `test_cli_architecture.py` — это намеренные **текстовые/AST** проверки
  архитектурных инвариантов (нет embedded SQL/HTTP/default admin в `ode/`,
  `context.py` не вызывает `.create()`/`.migrate`). Для этого класса
  инвариантов (структурных, а не бизнес-логики) grep/AST-проверка —
  адекватный инструмент, не слабость.
- `test_cli_architecture.py`: CLI действительно тестируется через
  `subprocess.run([sys.executable, "-m", "ode", ...])`, не прямым вызовом
  Python-функций — соответствует требованию review.
- `test_module_boundary_audit_passes` запускает
  `scripts/audit_module_boundaries.py` как subprocess и проверяет exit code —
  корректно.
- `PYTHONWARNINGS=error::ResourceWarning` реально включён в CLI-тестах через
  `env` subprocess, и весь suite запускается под этим флагом в
  `STAGE_0_13_1.md` verification commands.
- Порядок независимости: suite независимо запущен в этой сессии (а) в
  нормальном порядке, (б) в полностью реверсированном порядке (кастомный
  loader), (в) дважды подряд в одном процессе, (г) из `cwd=/tmp` с абсолютными
  путями — во всех четырёх случаях 38/38 passed, без утечки временных
  директорий (`TemporaryDirectory` корректно самоочищается — подтверждено
  подсчётом файлов до/после).
- Тесты, специально проверяющие cleanup (`test_failed_migration_deletes_candidate_and_leaves_no_target`,
  `test_interrupted_migration_deletes_candidate_and_leaves_no_target`),
  действительно инструментируют сбой (`patch.object(..., side_effect=KeyboardInterrupt)`
  и повреждённый DDL с пересчитанным checksum) и проверяют реальное отсутствие
  файлов на диске, а не мокают файловую систему — сильная проверка.
- Windows/macOS-специфичные допущения нигде явно не помечены как
  platform-conditional (`os.link`, permissions `0o600`, `os.chmod`) — тесты
  корректны на POSIX (эта сессия — macOS), но не содержат explicit skip/mark
  для Windows-путей, где `chmod`-семантика иная. Не проверено эмпирически в
  этой сессии (нет доступа к Windows). Non-blocking naблюдение, не finding.
- Не найдено false-green моков, скрывающих реальную запись/чтение SQLite —
  все тесты бьют по настоящему `sqlite3`-файлу через реальный `MigrationRunner`
  или `SQLiteConnectionFactory`.

Вывод: test suite достаточен для заявленного scope Stage 0.13.1 и был
независимо перепройден в этой сессии с идентичным результатом (38/38, во всех
вариациях порядка/повторов/cwd).

## 11. Security review

- Path traversal, symlink/hardlink на production DB — заблокированы, см. §6
  (подтверждено адверсариально, включая реальный hard link на 579 МБ файл,
  без модификации оригинала).
- Malicious manifest (checksum/order/duplicate/traversal-in-filename/case)
  — заблокирован, см. §4.
- Malicious/replaced migration SQL source — заблокирован checksum-проверкой
  до применения И registry/pragma-проверкой после применения (двухслойная
  защита, см. §5 tampering-тест).
- Error leakage: типизированные `OdeError` никогда не включают traceback в
  вывод (подтверждено). Единственная утечка — F2/F1: **тип** исключения
  (`FileNotFoundError`/`PermissionError`/`sqlite3.IntegrityError`) вместо
  `code`, не содержимое/секреты.
- JSON injection: не воспроизведено — `json.dumps` корректно экранирует
  кавычки/backslash/control-chars (подтверждено путём с `"` и `'` внутри).
- Terminal escape characters: **воспроизведено** в human-режиме, см. F4.
- umask/permissions: candidate создаётся `touch(mode=0o600)` **и**
  дополнительно явным `os.chmod(candidate, 0o600)` сразу после — защита от
  restrictive umask, не полагающаяся только на `mode=` аргумент `touch()`
  (который сам подвержен umask). Подтверждено чтением кода и permissions
  проверкой на всех независимо построенных БД (`0o600` во всех трёх).
- Нет `eval`/`exec`/`shell=True`/`subprocess.*` вызовов внутри `ode/`
  (grep подтверждён, 0 совпадений).
- Нет hardcoded credentials/secrets/паролей (grep подтверждён; единственные
  совпадения — комментарий "non-secret error contract" и переменные
  `_write_token`/`Token` из `contextvars`, не относящиеся к security tokens).
- No default user/bootstrap credentials — подтверждено существующим тестом
  (`test_no_default_users_http_or_product_database_constant`) и независимо:
  clean DB имеет `users_count=0`.
- Predictable candidate name collision: candidate использует
  `uuid.uuid4().hex` — не предсказуемо, коллизия практически невозможна; не
  проверялось как атака (нецелесообразно, entropy достаточна).

## 12. Operations/portability review

- Crash/interrupt recovery: candidate всегда удаляется при любом сбое между
  началом записи и публикацией (подтверждено §5); target никогда не остаётся
  в частично-написанном состоянии, потому что target появляется только через
  один атомарный `os.link` в самом конце.
- Оператор отличает candidate от accepted DB по имени: `.{stem}.candidate-{uuid}{suffix}`,
  видимое отличие от целевого имени; candidate никогда не публикуется под
  собственным именем.
- Stale candidate cleanup: если процесс убит между `os.link` и
  `candidate.unlink()` (окно между строками 525 и 536 `migrations.py`),
  candidate-файл **может** остаться на диске рядом с уже опубликованным
  target (hard link на тот же inode, что и target — не мусорные данные,
  просто лишнее имя). Не воспроизведено принудительно (требует SIGKILL в
  точный момент, не тестировано в этой сессии), но логически возможно и не
  имеет автоматической cleanup-команды в Stage 0.13.1. Non-blocking для
  0.13.1 (candidate — валидный alias того же файла, не corruption), но стоит
  задокументировать как known manual-cleanup edge case для операторов.
- Process-owner lock отсутствует — явно и честно задокументировано как
  non-goal Stage 0.13.1 в `STAGE_0_13_1.md`; ADR-009 описывает его как
  целевую архитектуру для будущих stage. Приемлемо для текущего
  single-user/single-process контура ODE (см. `CLAUDE.md`), но станет
  необходимым, когда 0.13.2+ введёт параллельных читателей во время записи —
  зафиксировано как forward-looking risk, не blocker сейчас.
- Portability: hard-link fail-closed поведение подтверждено (§5); Windows не
  протестирован эмпирически в этой сессии (нет доступа к Windows-хосту) —
  оставляю как непроверенное, документация корректно не заявляет
  протестированную Windows-поддержку для этого конкретного create-flow.
- Логирование без секретов: подтверждено (§11) — ошибки не содержат
  password/session/token полей.

## 13. Documentation consistency

Сверка `STAGE_0_13_1.md`, `database-lifecycle.md`, `implementation-order.md`,
`transaction-model.md`, ADR-009 с фактическим кодом:

- Заявление «hard-link atomicity, no-overwrite» — подтверждено кодом и
  тестом (§5). Никакого overclaim не найдено.
- «Windows compatibility» — документация НЕ заявляет протестированную
  Windows-поддержку для этого create-flow; корректно не overclaim.
- «Network filesystem» — документация явно говорит «warning only, portable
  detector не заявлен»; код (`NETWORK_FILESYSTEM_NOT_VERIFIED`, всегда
  безусловно добавляется) в точности соответствует — не более и не менее.
- «Immutable diagnostics» — документация утверждает «не выполняет migration,
  repair, audit, WAL checkpoint» — верно, подтверждено. НО документация НЕ
  предупреждает явно, что immutable-чтение может быть **stale** относительно
  незакрытого writer'а с активным WAL — это единственный найденный gap между
  документацией и рискованным поведением кода (F3). Рекомендую добавить в
  `STAGE_0_13_1.md`/`database-lifecycle.md` explicit caveat.
- «No-overwrite / candidate cleanup» — подтверждено, с оговоркой §12 про
  теоретическое SIGKILL-окно между `os.link` и `candidate.unlink()`
  (документация не описывает этот edge case явно — non-blocking gap).
- «Schema hash method» (`.schema`-reproducing algorithm) — подтверждено
  байт-в-байт двумя независимыми clean builds, дающими идентичный
  `approved_schema_hash`.
- «NOT_INITIALIZED — успешный health результат с exit code 0» — подтверждено
  CLI-тестом в JSON-режиме (`health["status"] == "NOT_INITIALIZED"`,
  `returncode == 0`).
- «Automatic migration prohibition» (context build никогда не создаёт/не
  мигрирует БД) — подтверждено чтением `context.py` (нет вызовов `.create()`/
  `.migrate` в build-функции) и независимо: импорт и построение
  `ApplicationContext` не касаются файловой системы.

## 14. Confirmed strengths

- Manifest/checksum/registry/schema-hash защита — многослойная и
  адверсариально устойчивая (checksum до применения + PRAGMA/registry-сверка
  после каждого файла + финальный `.schema`-hash + `verify_schema.sql`/
  `verify_domain_invariants.sql`).
- Path policy надёжно ловит symlink- и **hard-link**-алиасы production DB —
  редкая и важная деталь (`os.path.samefile`, устойчивый к hard link, где
  чистое сравнение путей было бы обойдено).
- Атомарная publish-семантика (`os.link` + EEXIST) реально закрывает TOCTOU в
  точке публикации — подтверждено принудительной гонкой в этой сессии, а не
  только чтением кода.
- Fail-closed поведение при недоступности hard-link (EXDEV) — не пытается
  «подстраховаться» небезопасным fallback (например, `os.replace`), что было
  бы менее безопасно.
- Diagnostics действительно side-effect-free (SHA/mtime неизменны, sidecars
  не создаются) для «холодного» (closed, single-writer) случая.
- Явные типизированные ошибки (`OdeError`/подклассы) без traceback почти
  везде; JSON-контракт стабилен и валиден при экзотических входах.
- Композиция (`build_application_context`) не создаёт и не мигрирует БД —
  подтверждено и статически, и по факту отсутствия файловых операций при
  импорте/построении context.
- Module boundary audit (AST-based, не строковый grep) реально ловит
  cross-import между `ode` и `inventory` и подтверждён отдельным прогоном.
- Test suite полностью детерминирован (порядок/повтор/cwd-независимость
  подтверждены в этой сессии, не только заявлены).

## 15. Required fixes (перед Stage 0.13.2)

1. **F1** — обернуть `connection.commit()` (и, по симметрии, финальный
   `connection.rollback()`) в `SqliteUnitOfWork.__exit__` в try/except,
   транслируя `sqlite3.Error` в `UnitOfWorkError` с сохранением
   `sqlite_error` details, аналогично тому, как это уже сделано в
   `uow.execute()`.
2. **F3** — при `wal_present=True` в `DiagnosticsService.diagnostics()`
   добавлять явный warning (например `IMMUTABLE_READ_WITH_ACTIVE_WAL`) в
   `warnings`, чтобы оператор понимал, что immutable-снимок может быть
   устаревшим относительно активного writer'а.
3. **F2** — обернуть вызовы `self.validate_sources()` и
   `target.parent.mkdir(...)` в начале `MigrationRunner.create()` в тот же
   класс обработки ошибок (`MigrationError`/`DATABASE_CREATE_FAILED`), что и
   остальной create-flow, чтобы I/O-сбои (dangling symlink source,
   permission denied) получали стабильный код вместо `INTERNAL_ERROR`.

## 16. Non-blocking recommendations

- **F4** — экранировать/санитизировать non-printable символы в human-режиме
  CLI перед `print()`, либо задокументировать human-режим как
  trusted-local-only и не предназначенный для отображения untrusted путей.
- **F5/F6** — рассмотреть простую защиту в `SqliteUnitOfWork.execute()`,
  отклоняющую top-level `BEGIN`/`COMMIT`/`ROLLBACK`/`SAVEPOINT`/DDL-токены,
  либо явно задокументировать это как trust-boundary для будущих
  repository-авторов в `transaction-model.md`.
- **F7** — рассмотреть NFKC-нормализацию пути в `canonical_database_path`,
  если когда-либо появятся non-ASCII allowed roots; сейчас не требуется
  (все защищённые пути ASCII).
- Задокументировать теоретическое SIGKILL-окно между `os.link` и
  `candidate.unlink()` (§12) как known manual-cleanup edge case.
- Явно пометить в `STAGE_0_13_1.md`/тестах, какие проверки (permissions,
  hard link) POSIX-специфичны и не проверялись на Windows.

## 17. Stage 0.13.2 entry verdict

Разрешить старт Stage 0.13.2 **после** устранения F1 и F3 (оба напрямую
попадают в код, который 0.13.2 начнёт активно использовать — `SqliteUnitOfWork`
для domain writes и diagnostics при живой БД). F2 настоятельно рекомендуется
исправить одновременно, так как это тот же класс дефекта (untyped I/O
exception) и исправление тривиально. F4–F7 не блокируют старт 0.13.2, но
должны быть занесены в `TECH_DEBT.md` или аналогичный трекер, если не будут
исправлены сразу.

Этот review не исправлял код, не коммитил, не пушил и не начинал Stage
0.13.2.
