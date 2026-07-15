# Stage 0.13.1 — Targeted re-review of F1–F7 corrections

Статус: **RE-REVIEW COMPLETE — NOT YET FINAL ACCEPT (new findings in F6 scope)**

Дата: 2026-07-15. Ревьюер: независимый targeted re-review (без subagents),
той же ролевой дисциплины (Principal Python Engineer / Senior SQLite Engineer
/ Security Reviewer), выполненный в новой сессии без доверия
`STAGE_0_13_1_REVIEW_RESPONSE.md` на слово — каждое утверждение re-review
подтверждено либо независимым чтением кода, либо воспроизводимым скриптом,
выполненным в этой сессии на disposable temp DB.

Это **targeted** re-review, не повтор полного первоначального аудита: объём
ограничен исправлениями F1–F7, их regression-тестами и отсутствием новых
регрессий, как и запрошено в задании. `ode/`, `tests/`, approved DDL, `app.py`,
`inventory/`, `data/warehouse.db` не изменялись. Изменён только этот документ.

## 1. Preservation

| | До re-review | После re-review |
|---|---|---|
| branch | `main` | `main` |
| HEAD | `76afadd5355f4d379b19dcabf1f28850986d5300` | `76afadd5355f4d379b19dcabf1f28850986d5300` (без изменений) |
| origin/main | `76afadd5355f4d379b19dcabf1f28850986d5300` | `76afadd5355f4d379b19dcabf1f28850986d5300` |
| `data/warehouse.db` size | 579 461 120 bytes | 579 461 120 bytes |
| `data/warehouse.db` mtime | 15 июля 11:45 | 15 июля 11:45 (не менялся) |
| `data/warehouse.db` SHA-256 | `73568a1c3eecbd4476473f064620d7f0a196b336ce8ea6d834c5b99359d4b010` | `73568a1c3eecbd4476473f064620d7f0a196b336ce8ea6d834c5b99359d4b010` (идентичен) |
| `PRAGMA integrity_check` | `ok` | `ok` |
| `PRAGMA foreign_key_check` | 0 violations | 0 violations |
| WAL/SHM/journal | отсутствуют | отсутствуют |
| `STAGE_0_13_1_INDEPENDENT_REVIEW.md` SHA-256 | `7a1b48739bea1db3d263539aa9976cc2a941b6bee314aa82c6f5ec9079a8cad8` | не менялся (сверено) |
| `STAGE_0_13_1_REVIEW_RESPONSE.md` SHA-256 | `c6ffd4ac6a198a1b9b2ca2d328831b55a2b081d3a8d8be5a273dc1b1b82aa5ca` | не менялся (сверено) |

Production DB открывалась в этой сессии только `mode=ro&immutable=1` (baseline
и final checks). Все repro-скрипты этой сессии выполнялись исключительно на
`TemporaryDirectory()`-based disposable DB под `/private/tmp/...`; ни один не
писал в `data/`, `.local/`, `ode/`, `tests/`.

## 2. F1 — UoW deferred FK

**Verdict: CLOSED.**

Подтверждено чтением `ode/infrastructure/database.py` и независимым
выполнением (не только чтением) существующего теста
`test_real_v005_deferred_fk_commit_is_typed_and_fully_rolled_back`, плюс
собственными repro на отдельной disposable DB:

- Реальный `DEFERRABLE INITIALLY DEFERRED` FK (`inventory_snapshots.
  superseded_by_snapshot_id`, V005), не пойманный на `execute()`, срабатывает
  ровно на `connection.commit()` в `__exit__` → наружу выходит
  `UnitOfWorkCommitError`, `code == "UNIT_OF_WORK_COMMIT_FAILED"`,
  `__cause__` — реальный `sqlite3.IntegrityError`, `body.details
  ["sqlite_error"] == "IntegrityError"`.
- После этого: `connection.in_transaction` → rollback выполнен внутри
  `__exit__`; `inventory_snapshots` содержит 0 строк; handle закрыт
  (`sqlite3.ProgrammingError` при повторном использовании); ContextVar
  (`_active_write_uow`) корректно сброшен — подтверждено тем, что немедленно
  после этого новый `SqliteUnitOfWork` на том же factory открывается и
  коммитит без `NESTED_WRITE_UNIT_OF_WORK`.
- **Независимо воспроизведено сверх существующего теста**: реальный
  `BEGIN failure` через настоящую блокировку (`SQLITE_BUSY`, не
  fake-инъекция) — второе соединение держит `BEGIN IMMEDIATE` без commit,
  `busy_timeout=200ms` истекает → `UnitOfWorkBeginError`,
  `code == "UNIT_OF_WORK_BEGIN_FAILED"`. **Нюанс**: `__cause__` в этом
  сценарии — не сам `sqlite3.OperationalError`, а промежуточный
  `DatabaseError("SQLite operation failed")`, который сам оборачивает
  `sqlite3.OperationalError` (потому что реальная блокировка проявляется
  раньше — на `PRAGMA journal_mode = WAL` внутри `SQLiteConnectionFactory.
  _open()`, до `BEGIN IMMEDIATE`, и уже там ловится общим `except
  sqlite3.Error` в `connect()`). Тип ошибки при этом **не теряется** —
  `_database_failure_type()` корректно проходит по цепочке `__cause__` и
  возвращает `"OperationalError"` в `body.details["sqlite_error"]`, но прямой
  `.__cause__` на один уровень глубже, чем в сценарии fake-инъекции (где
  существующий тест `test_begin_and_close_failures_are_typed_and_state_is_
  cleared` подставляет ошибку прямо в `execute("BEGIN...")`). Это **LOW,
  non-blocking observation**, не regression: контракт «типизированная ошибка
  + сохранённый тип причины» выполнен в обоих случаях, просто существующий
  fake-based тест не покрывает именно эту (более реалистичную) форму BEGIN
  failure. Не требует исправления для CLOSED-статуса F1.
- `rollback failure precedence`, `close failure precedence`,
  `unrelated Python exception не маскируется` — подтверждены чтением и
  выполнением `UnitOfWorkFailurePrecedenceTests` (fake connection/manager,
  детерминированные инъекции): commit failure → `__cause__` = commit's
  `IntegrityError`, rollback/close failures той же цепочки — только в
  `details` (не теряются, но не становятся `__cause__`); rollback-only
  failure с body exception → `__cause__` = body exception (`RuntimeError`),
  rollback's `OperationalError` — в `details["sqlite_error"]`; close-only
  failure после успешного commit → `UnitOfWorkCloseError`, `__cause__` =
  close's `OperationalError`. Независимо подтверждено: обычный `ValueError`
  без какой-либо SQL-ошибки проходит через `__exit__` **без оборачивания**
  (`_is_database_failure` возвращает `False` для не-SQL/не-`DatabaseError`
  исключений) — не маскируется.

## 3. F2 — Migration I/O errors

**Verdict: CLOSED.**

Независимо воспроизведено на собственных disposable fixtures (не только
прочитаны существующие тесты, но и повторены с независимыми путями/параметрами):

- Dangling symlink migration source (`V003` → несуществующий файл) →
  `validate_sources()` бросает `MigrationError("MIGRATION_SOURCE_READ_FAILED")`,
  `__cause__` — `FileNotFoundError`, `details["version"]` корректен.
- `chmod 0500` на parent-директории перед `target.parent.mkdir(...)` →
  `MigrationError("DATABASE_CREATE_FAILED")`, `__cause__` — `PermissionError`;
  target не создаётся.
- Существующий target **никогда не перезаписывается** повторным `create()` —
  подтверждено байт-в-байт сравнением SHA-256 до/после неудачной попытки.
- Candidate-файл после ошибки отсутствует (`.{stem}.candidate-*` glob пуст).
- **Раздельно проверено через реальный subprocess CLI** (не только Python
  API): `python3 -m ode db create --path <under-chmod-0500-parent> --json` →
  валидный JSON envelope, `error.code == "DATABASE_CREATE_FAILED"`, **ноль**
  `Traceback` в stdout/stderr — сырой `PermissionError`/`OSError` не
  просачивается через CLI.

## 4. F3 — Active sidecars

**Verdict: CLOSED.**

Независимо воспроизведено сверх существующей тестовой матрицы:

- Active WAL с committed uncheckpointed data (второе `sqlite3.connect`,
  `wal_autocheckpoint=0`, commit без close) → `require_immutable_snapshot_safe`
  и все read-паттерны (`diagnostics()`, `migration_status()`, `system.health()`,
  `MigrationRunner.verify()`) бросают `DatabaseError("IMMUTABLE_SNAPSHOT_
  UNSAFE")`; ни READY, ни NOT_INITIALIZED не возвращаются как authoritative.
- Stale WAL (subprocess `os._exit(0)` без close, симулирующий crash) — та же
  ошибка, файл-состояние (SHA/size/mtime каждого файла и sidecar) идентично
  до/после проверки.
- Zero-byte WAL/SHM/journal по отдельности — fail closed.
- **Независимо добавлено**: одновременно zero-byte `-wal` **и** `-journal`
  (комбинация, не покрытая существующим тестом, который проверяет каждый
  suffix изолированно) → корректно `IMMUTABLE_SNAPSHOT_UNSAFE`,
  `details == {"wal": true, "shm": false, "journal": true}`.
- **Независимо добавлено**: директория (не файл), буквально названная
  `<path>-wal` — тоже fail-closed, потому что guard проверяет только
  `Path.exists()`, не тип файла; ожидаемо консервативно, не false-negative.
- Unrelated similarly-named files (`-wal-backup`, `-shm.old`) корректно **не**
  триггерят guard (подтверждено существующим тестом, независимо перечитано).
- Checkpoint/delete/truncate/create sidecar со стороны diagnostics не
  происходит ни в одном сценарии — подтверждено file-state сравнением
  (SHA/size/mtime каждого файла) до/после.

## 5. F4 — Terminal output

**Verdict: CLOSED.**

Через реальный `subprocess.run([sys.executable, "-m", "ode", ...])` (не
прямой вызов Python-функций):

- ESC (`\x1b`), BEL (`\x07`), CR (`\r`), LF-injection (`\n` внутри значения),
  C0 controls, C1 (`\x85` NEL), bidi override (`‮`) — все дают safe
  `\xNN`/`\uNNNN` representation в human-режиме; ни один сырой control byte не
  просачивается в stdout/stderr (подтверждено `assertNotIn` на raw bytes).
- **Независимо добавлено** сверх существующего перечня: DEL (`\x7f`),
  vertical tab (`\x0b`), form feed (`\x0c`) — тоже корректно санитизируются,
  ни один не просачивается raw.
- Обычный Cyrillic/CJK путь (`кириллица-設備.db`) отображается **без**
  экранирования — Unicode не повреждён.
- JSON-режим: тот же путь с ESC/LF/CR/BEL/bidi внутри имени файла даёт
  валидный, парсибельный JSON через `json.dumps(..., ensure_ascii=False)`;
  `database_path` в JSON — точный canonical resolved path (не изменённое
  представление), корректно JSON-escaped стандартным механизмом.
- Активный WAL через CLI (`system health`, `db status`) в обоих режимах
  (human/JSON) корректно fail-closed с `IMMUTABLE_SNAPSHOT_UNSAFE`, без
  traceback.

## 6. F5/F6 — SQL policy

**Verdict: F5 CLOSED. F6 PARTIALLY_CLOSED — два новых finding (см. §7).**

Подтверждено (существующие тесты + независимые обфускационные repro):

- `BEGIN`/`COMMIT`/`END`/`ROLLBACK`/`SAVEPOINT`/`RELEASE` и
  `ALTER`/`CREATE`/`DROP`/`REINDEX`/`VACUUM` как top-level statement —
  отклоняются с `UNIT_OF_WORK_TRANSACTION_CONTROL_FORBIDDEN` /
  `UNIT_OF_WORK_DDL_FORBIDDEN`, без partial writes.
- Обход **leading whitespace** (`"   \n\t COMMIT"`), **mixed case**
  (`"CoMmIt"`, `"CrEaTe TABLE..."`), **leading line comment**
  (`"-- x\nSAVEPOINT sp1"`), **leading block comment**
  (`"/* x */ RELEASE sp1"`) — все корректно распознаются и отклоняются
  regex'ом `_LEADING_SQL_KEYWORD`.
- **Multiple statements** (`"CREATE TABLE evil2(id INTEGER); SELECT 1"`) —
  отклонён на первом keyword до того, как `sqlite3` вообще успел бы
  пожаловаться на multi-statement `execute()`.
- **False-positive проверка**: строковые литералы-**данные**, содержащие
  слова `COMMIT`/`CREATE`/`DROP` внутри обычного `INSERT ... VALUES (...)`
  (не как SQL-синтаксис, а как текстовое значение параметра) — **не**
  отклоняются, проходят и коммитятся нормально. Guard анализирует только
  leading keyword, не содержимое строковых литералов — корректно.
- Обычный parameterized DML работает без изменений.

**Обнаруженный gap (независимо, не описанный в исходном review или
correction)**: `_TRANSACTION_CONTROL` и `_DDL_CONTROL` — это два **фиксированных
списка** ключевых слов
(`{BEGIN,COMMIT,END,ROLLBACK,SAVEPOINT,RELEASE}` и
`{ALTER,CREATE,DROP,REINDEX,VACUUM}`). `PRAGMA` и `ATTACH`/`DETACH` **не
входят ни в один из них** и полностью проходят через `SqliteUnitOfWork.
execute()` без отказа. См. §7 — это два конкретных, воспроизведённых finding,
а не гипотетический риск.

## 7. Новые findings (за пределами F1–F7)

### NF-1 — `ATTACH DATABASE` полностью обходит SQL policy guard и все path-safety гарантии

**Severity: HIGH** (impact — полный, silent bypass главного защищённого
свойства всего Stage 0.13.1 foundation; reachability — сейчас LOW, ни один
существующий caller не открывает write UoW с произвольным/внешним SQL).

Независимо воспроизведено на паре disposable temp DB (production DB **не
использовалась** в этом repro — намеренно, чтобы не рисковать `data/
warehouse.db`, использован отдельный "victim" `.sqlite3` файл):

```python
with SqliteUnitOfWork(factory) as uow:
    uow.execute(f"ATTACH DATABASE '{victim_path}' AS victim")
    uow.execute("INSERT INTO victim.untouched VALUES (999)")
    uow.commit()
# -> completes WITHOUT error; victim DB now contains the injected row
```

`ATTACH` не совпадает ни с одним словом ни в `_TRANSACTION_CONTROL`, ни в
`_DDL_CONTROL`, поэтому `_sql_keyword()`-guard его пропускает целиком. Это
значит, что **любой** код, открывший `SqliteUnitOfWork` (или любой будущий баг,
из-за которого внешние данные попадут в `sql`-параметр `execute()`), может
одной строкой прикрепить **произвольный файл файловой системы** — включая, в
принципе, `data/warehouse.db` — и читать/писать его напрямую через SQL,
полностью в обход:

- `canonical_database_path`/`PRODUCTION_DATABASE_FORBIDDEN` (весь §6
  независимого review, отдельно отмеченный как «confirmed strength» за
  устойчивость к symlink/hard-link алиасингу);
- read-only/immutable connection policy (ATTACH внутри write-соединения даёт
  write-доступ к attached файлу независимо от режима основного соединения);
- любых будущих repository-level permission checks, если они не продублированы
  на уровне каждого SQL-statement.

Это не гипотетическая атака: `ATTACH` — стандартная, документированная
возможность `sqlite3`, доступная любому коду с доступом к открытому
соединению, и единственная причина, по которой она сейчас не эксплуатируется
— это то, что ни один компонент Stage 0.13.1 ещё не вызывает
`SqliteUnitOfWork.execute()` с чем-либо, кроме статичных литеральных SQL-строк.
Как только 0.13.2 введёт repository-код, эта гарантия перестаёт быть архитектурной
и становится вопросом дисциплины каждого отдельного repository-автора — то
есть ровно тот класс риска, ради которого создавался сам keyword-guard.

**Рекомендация**: расширить guard, отклоняя top-level `ATTACH`/`DETACH` тем же
способом, что и текущие списки; в идеале — перейти от denylist к allowlist
(`SELECT`/`INSERT`/`UPDATE`/`DELETE`/`WITH` как единственные разрешённые
top-level keyword), потому что denylist по конструкции неполон — это
наглядно показывает и сам факт, что `ATTACH` был пропущен при исходной F5/F6
коррекции.

### NF-2 — `PRAGMA writable_schema=ON` + прямой `INSERT INTO sqlite_master` обходит F6 и повреждает БД

**Severity: MEDIUM** (impact — реальное повреждение файла БД, но blast radius
ограничен уже открытой БД, не произвольным внешним файлом, как в NF-1;
reachability — LOW, аналогично NF-1).

Независимо воспроизведено на disposable temp DB:

```python
with SqliteUnitOfWork(factory) as uow:
    uow.execute("PRAGMA writable_schema=ON")
    uow.execute(
        "INSERT INTO sqlite_master (type,name,tbl_name,rootpage,sql) "
        "VALUES ('table','evil_bypass','evil_bypass',0,"
        "'CREATE TABLE evil_bypass(id INTEGER)')"
    )
    uow.commit()
# -> completes WITHOUT error
```

После commit: `sqlite_schema` действительно содержит новую строку
`evil_bypass` — то есть DDL-подобное изменение схемы, совершённое **без**
единого запрещённого keyword (ни `CREATE`, ни `ALTER`, ни `DROP` — только
`PRAGMA` и `INSERT`, оба разрешены текущим guard). Хуже: последующий
`PRAGMA integrity_check` на этом файле возвращает **`database disk image is
malformed`** — то есть это не просто «фантомная» строка каталога, а реальное
повреждение файла (из-за `rootpage=0`, синтетически вставленного в обход
нормального DDL-пути, который обычно сам выделяет валидный rootpage).

Это прямо и полностью противоречит заявленному контракту F6-коррекции —
«Reject top-level CREATE/ALTER/DROP/REINDEX/VACUUM; **migrations remain sole
DDL owner**» (`STAGE_0_13_1_REVIEW_RESPONSE.md`, «Corrected contracts»). Guard
действительно отклоняет прямые DDL-ключевые слова, но `PRAGMA
writable_schema` — стандартный, документированный SQLite-способ обойти именно
это ограничение, и он не был учтён.

Дополнительно проверено: остальные security/runtime-policy-влияющие PRAGMA
(`trusted_schema=ON`, `foreign_keys=OFF`, `case_sensitive_like=ON`,
`query_only=ON`) тоже проходят без отказа внутри write UoW — единственный
PRAGMA, случайно отклонённый в этом тестовом прогоне
(`journal_mode=DELETE`), был отклонён **самим SQLite** («cannot change into
wal mode from within a transaction»), не guard'ом ODE — то есть это
случайное совпадение, не защита.

**Рекомендация**: то же расширение guard, что для NF-1 — включить `PRAGMA` в
отклоняемые top-level keyword (runtime repository код не должен вообще
выполнять PRAGMA — все нужные PRAGMA уже выставлены `SQLiteConnectionFactory.
_open()` при открытии соединения), либо полный переход на allowlist.

### Влияние NF-1/NF-2 на итоговый вердикт

Задание требует для финального accept: «F1–F6 CLOSED... новых
BLOCKER/CRITICAL/HIGH нет». NF-1 классифицирован как **HIGH** — это
**напрямую нарушает** условие финального accept. F6 поэтому помечен
**PARTIALLY_CLOSED**, а не CLOSED: заявленные в review/correction сценарии
(CREATE/ALTER/DROP/REINDEX/VACUUM, включая comment/case-обфускацию)
корректно закрыты и независимо переподтверждены; но сам инвариант «migrations
remain sole DDL owner», ради которого F6 создавался, всё ещё нарушаем другим
путём.

## 8. F7 — NFC/NFD

**Verdict: CLOSED as documented non-blocking limitation** (соответствует
заявленному в задании контракту — «finding корректно оставлен limitation, а
не скрыт», без требования новой Unicode-normalization policy).

Независимо подтверждено:

- `unicodedata.normalize("NFC", "café.db")` и `normalize("NFD", ...)`
  действительно дают разные byte-последовательности, и
  `canonical_database_path`/`DatabaseConfig.create()` резолвит их в два
  **разных** `Path`-объекта — код **не** реализует NFKC/NFC-нормализацию
  (подтверждено чтением `paths.py` — нет `unicodedata` импорта вообще — и
  выполнением существующего теста
  `test_unicode_normalization_remains_filesystem_path_identity`).
- Security bypass **не воспроизводится**: `PRODUCTION_DATABASE` и все
  `FORBIDDEN_SOURCE_ROOTS`/allowed roots — чистый ASCII, а ASCII-строки по
  определению NFC/NFD-инвариантны (`unicodedata.normalize("NFC", ascii) ==
  unicodedata.normalize("NFD", ascii) == ascii`), независимо подтверждено
  прямым вычислением на `PRODUCTION_DATABASE`. Нет способа алиасировать
  защищённый путь через NFC/NFD-эквивалент, потому что защищённые пути не
  содержат ни одного non-ASCII символа, который мог бы иметь два разных
  normalization form.
- Документация (`STAGE_0_13_1_REVIEW_RESPONSE.md`) не заявляет ложную
  эквивалентность — прямо говорит «No code change. Documented as accepted
  cross-platform limitation pending path ADR» — соответствует
  фактическому коду.

Не реализовывался и не предлагается новый normalization код (в соответствии
с прямым запретом задания).

## 9. Regression gate

Все проверки выполнены независимо в этой сессии (не переиспользован вывод
предыдущих review):

| Проверка | Результат |
|---|---|
| `python3 -m compileall ode tests/ode013` | PASS |
| `tests/ode013`, normal order, `PYTHONWARNINGS=error::ResourceWarning` | **55/55 PASS** |
| `tests/ode013`, полностью реверсированный порядок | **55/55 PASS** |
| `tests/ode013`, дважды подряд в одном процессе | **55/55 PASS** × 2 |
| `tests/ode013`, из `cwd=/tmp`, discovery через `-t` | **55/55 PASS** |
| ResourceWarnings за весь прогон (все варианты) | **0** |
| `scripts/audit_module_boundaries.py` | `module-boundaries: OK`, exit 0 |
| `git diff --check` | exit 0, без warnings |
| `ode` ⟷ `inventory`/`app.py` cross-import | Ни один найден (grep обеих сторон) |
| Independent clean build #1 (`db create`, temp path вне репозитория) | `application_id=1329874225`, `user_version=8`, `tables=41/indexes=73/triggers=73/views=3`, permissions `0600`, `integrity_check=ok`, `foreign_key_violations=0`, все 23 domain invariant = 0 |
| Independent clean build #2 | Идентичные значения build #1 |
| `approved_schema_hash` обоих builds (`db create` + `db verify`, JSON) | `143bb0ae16c68c1fcd653ecc94adc62464746fed738ebfa47749057380f7f0cb` — совпадает с hash, переданным в задании, во всех 4 замерах (create×2, verify×2) |
| `verify_schema.sql` (оба builds) | Все проверки `PASS`/`ok`/`0`, `schema_counts` совпадает |
| `verify_domain_invariants.sql` (оба builds) | Все 23 инварианта = 0 |
| `app.py` парсится, не импортирует `ode` | PASS |
| `data/warehouse.db` до/после всей сессии | SHA-256 идентичен, integrity `ok`, FK 0, sidecars отсутствуют |

## 10. Verdict table

| ID | Verdict | Severity |
|---|---|---|
| F1 | **CLOSED** | — (было MEDIUM, закрыто; один LOW observational nuance, не blocking) |
| F2 | **CLOSED** | — |
| F3 | **CLOSED** | — |
| F4 | **CLOSED** | — |
| F5 | **CLOSED** | — |
| F6 | **PARTIALLY_CLOSED** | Заявленный scope (CREATE/ALTER/DROP/REINDEX/VACUUM) закрыт; см. NF-1/NF-2 |
| F7 | **CLOSED as documented limitation** | LOW, informational (без изменений — соответствует заданию) |
| NF-1 (new) | **NOT_CLOSED** | **HIGH** |
| NF-2 (new) | **NOT_CLOSED** | **MEDIUM** |

Regression gate: **без regression**, 55/55 во всех вариациях, production DB
неизменна, schema hash подтверждён.

## 11. Итоговый вердикт по критериям задания

Условие финального accept: «F1–F6 CLOSED; F7 корректно документирован как
non-blocking limitation; новых BLOCKER/CRITICAL/HIGH нет; production DB
неизменна.»

- F1–F5 — CLOSED. ✔
- F6 — **PARTIALLY_CLOSED**, не полностью CLOSED. ✘
- F7 — корректно документирован как non-blocking limitation. ✔
- Новых BLOCKER/CRITICAL — нет. Новый **HIGH** (NF-1) — есть. ✘
- Production DB неизменна. ✔

**Итог: Stage 0.13.1 нельзя окончательно принять по буквальным критериям
задания** — не из-за F1–F5 (они реально закрыты и независимо
переподтверждены), а из-за двух новых findings в точном scope F6
(`ATTACH`/`PRAGMA writable_schema` обходят «migrations remain sole DDL
owner»), обнаруженных именно тем целевым SQL-policy тестированием, которое
задание явно запросило («PRAGMA, изменяющий schema/runtime policy» было
прямо указано в задании как то, что нужно проверить).

Fix минимален и симметричен уже существующему коду: добавить `PRAGMA` и
`ATTACH`/`DETACH` в keyword-guard `ode/infrastructure/database.py`
(`_TRANSACTION_CONTROL`/`_DDL_CONTROL` или отдельный третий set), тем же
способом, каким уже отклоняются `BEGIN`/`CREATE`/etc., включая
comment/whitespace/case-обфускацию, которая уже корректно обрабатывается
существующим `_LEADING_SQL_KEYWORD`-regex для всех остальных keyword.

Stage 0.13.2 остаётся запрещённым до отдельного явного пользовательского
подтверждения — это верно независимо от вердикта NF-1/NF-2, и этот re-review
его не начинал, не исправлял код и не коммитил.
