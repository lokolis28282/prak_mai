# Warehouse Stabilization — Focused Independent Review

Статус: **PASS**

Дата: 2026-07-15. Ревьюер: независимый focused review (без subagents), без
доверия отчёту исполнителя на слово — каждое утверждение ниже подтверждено
либо чтением фактического diff/кода, либо выполненной командой в этой сессии.
Ревьюер не вносил исправлений; единственный write этой сессии — данный файл.

## Scope

Точный reviewed change, как указано в задании:

- явное закрытие raw SQLite test-соединений в `tests/test_stage_0_12_17.py`,
  `tests/test_warehouse_api_contract.py`, `tests/test_warehouse_stabilization.py`;
- новый canonical project hub `docs/project/`;
- разделение Warehouse source track и Target/Platform track;
- живое обновление счётчика тестов с устаревшего 292/301 на текущий 392.

Полный diff двух модифицированных файлов и содержимое нового
`test_warehouse_stabilization.py` шире объявленного scope (новые тестовые
случаи для `warehouse_type_summary`, комбинированных `balance` фильтров,
опциональности поля `project` и т.д.). Эти дополнительные тесты не входят в
заявленный reviewed change и не проверялись по существу их бизнес-логики —
см. §7 «Вне scope» ниже. Раскрытие этого несоответствия — не блокирующая
находка, а прозрачность объёма проверки.

## 1. Preservation evidence

| | До review | После review |
|---|---|---|
| branch | `main` | `main` |
| HEAD | `76afadd5355f4d379b19dcabf1f28850986d5300` | не изменился |
| `data/warehouse.db` size | 579 461 120 bytes | 579 461 120 bytes |
| `data/warehouse.db` permissions | `-rw-------` (0600) | `-rw-------` (0600) |
| `data/warehouse.db` SHA-256 | `73568a1c3eecbd4476473f064620d7f0a196b336ce8ea6d834c5b99359d4b010` | идентичен |
| WAL/SHM/journal | отсутствуют | отсутствуют |
| `PRAGMA integrity_check` (immutable ro) | `ok` | `ok` |
| `PRAGMA foreign_key_check` (immutable ro) | 0 violations | 0 violations |
| git index (staged) | пусто | пусто |

`data/warehouse.db` открывалась в этой сессии исключительно
`mode=ro&immutable=1`; ни разу не использовалась как fixture для мутаций.
Все тестовые прогоны используют собственные `tempfile`-based БД (подтверждено
чтением `setUp`/`tearDown` во всех трёх файлов — каждый тест создаёт БД в
`TemporaryDirectory()`, не в `data/`).

## 2. Files reviewed

- `tests/test_stage_0_12_17.py` (git diff против HEAD);
- `tests/test_warehouse_api_contract.py` (git diff против HEAD);
- `tests/test_warehouse_stabilization.py` (полностью, новый файл);
- `docs/project/README.md`, `CURRENT_STATE.md`, `MASTER_CONTEXT.md`,
  `DECISIONS_INDEX.md`, `ROADMAP.md`, `REPOSITORY_MAP.md`,
  `RISKS_AND_BACKLOG.md`, `DOCUMENTATION_INDEX.md`;
- `AGENTS.md` (grep на заявления о test count/Stage);
- root `README.md` (grep на заявления о test count/Stage);
- `docs/LOCAL_WORKING_DATABASE_RUNBOOK.md` (проверка отсутствия hardcoded
  устаревшего SHA как «текущей константы»).

## 3. Connection-closing verification (Required §1)

Полный перечень `sqlite3.connect(` в трёх файлах и подтверждение, что каждый
обёрнут в `contextlib.closing`:

```
tests/test_warehouse_api_contract.py:157   closing(sqlite3.connect(...)) as db, db:
tests/test_stage_0_12_17.py:125            closing(sqlite3.connect(...)) as db, db:
tests/test_stage_0_12_17.py:297            closing(sqlite3.connect(...)) as db, db:
tests/test_stage_0_12_17.py:315            closing(sqlite3.connect(...)) as db:
tests/test_stage_0_12_17.py:322            closing(sqlite3.connect(...)) as db, db:
tests/test_warehouse_stabilization.py:21,82,87,99,110   closing(sqlite3.connect(...)) as db, db:
```

**0 из 10** вызовов остаются raw/незакрытыми — 100% покрытие в этих трёх
файлах.

Паттерн `with closing(sqlite3.connect(path)) as db, db:` корректно сохраняет
прежнее commit/rollback-поведение и добавляет фактическое закрытие handle:
`sqlite3.Connection.__exit__` сам по себе управляет только
commit-on-success/rollback-on-exception и **не закрывает** соединение (частая
ловушка) — второй context manager в составном `with` (сам `db`) даёт
транзакционную семантику, а внешний `closing(...)` гарантирует `.close()` при
выходе из блока независимо от исхода.

Единственное исключение — `test_stage_0_12_17.py:315`, где используется
**только** `closing(...) as db:` без второго `db`. Проверено по коду
(`tests/test_stage_0_12_17.py:315-319`): блок содержит один `SELECT`, без
мутаций — отсутствие commit/rollback-семантики здесь корректно и не является
регрессией, поскольку читающему запросу нечего коммитить.

**Вывод**: закрытие соединений реализовано полно и корректно во всех трёх
заявленных файлах; предыдущее commit/rollback-поведение не изменено.

## 4. Commands and exact results (Required §2–5, §7)

| Команда | Результат |
|---|---|
| `python3 -W error::ResourceWarning -m unittest tests.test_stage_0_12_17 tests.test_warehouse_api_contract tests.test_warehouse_stabilization -v` (с `PYTHONTRACEMALLOC=25`) | **33/33 OK**, ноль `ResourceWarning`, ноль unclosed-database сообщений |
| `python3 -W error::ResourceWarning -m unittest discover -s tests -q` | **392/392 tests, OK** — совпадает с заявленным живым счётчиком; ноль вхождений строки `ResourceWarning` во всём выводе (проверено `grep -ci`) |
| `python3 scripts/audit_module_boundaries.py` | `module-boundaries: OK`, exit 0 |
| `python3 scripts/audit_frontend_contracts.py` | `frontend-contracts: OK, no missing static ids`, exit 0 |
| `git diff --check` | exit 0, без предупреждений о trailing whitespace/conflict markers |
| `python3 -m py_compile app.py inventory/**/*.py scripts/*.py tests/*.py` | без ошибок |
| `node --check` на затронутых JS (`router.js`, `ui.js`, `product.js`, `administration/references.js`) | все OK |

Полный лог full-discover сохранён во временный файл сессии и проверен
дважды: (а) хвост на `Ran 392 tests ... OK`; (б) отдельный `grep -ci
resourcewarning` по всему выводу → `0`.

## 5. Documentation consistency (Required §5–6)

- `docs/project/DECISIONS_INDEX.md` только **ссылается** на
  `../decisions/ADR-*` и `../architecture/*` — не копирует и не переопределяет
  их содержимое; явно формулирует «Interpretation rule»: target ADR/DDL не
  объявляется уже реализованным поведением текущего Warehouse.
- `docs/project/CURRENT_STATE.md` и `ROADMAP.md` явно пишут «Platform Stage
  0.13.2 (security/audit/references) не начинался» — **ложного заявления о
  реализации Platform Stage 0.13.2 не найдено**.
- `docs/project/REPOSITORY_MAP.md` корректно описывает `ode/` как
  side-by-side foundation, не применяемый к `data/warehouse.db`.
- Test-count согласован во всех трёх независимых источниках:
  `AGENTS.md:319` («Current full discover result is 392 tests»), root
  `README.md:630` («Полный discover-набор... содержит **392 теста**»),
  `docs/project/CURRENT_STATE.md:44` («392/392 PASS») — совпадает с фактически
  измеренным результатом (§4).
- Stage-номенклатура согласована: `AGENTS.md` и root `README.md` оба называют
  Warehouse source `Stage 0.13.3A.5` с runtime/package metadata
  `0.12.17.1 RC2` и последним собранным ZIP `0.12.17 RC1`; `CURRENT_STATE.md`
  повторяет то же самое дословно.
- `docs/LOCAL_WORKING_DATABASE_RUNBOOK.md` не фиксирует текущий SHA как
  версионную константу — прямо документирует, что легитимные операции меняют
  SHA; согласуется с явной оговоркой в `CURRENT_STATE.md` («SHA меняется
  после легитимных операционных writes и не является константой версии»).

Несоответствий между `docs/project/`, `AGENTS.md`, root `README.md` и
`LOCAL_WORKING_DATABASE_RUNBOOK.md` не найдено.

## 6. Findings

Blocking-категории (data loss/mutation, balance/identity invariant,
authorization/secret exposure, schema corruption, regression, false
current-state claim) — **не найдено ни одной**.

Non-blocking наблюдение (не расширяет scope, зафиксировано отдельно):

- `docs/project/CURRENT_STATE.md` строка 30–32 упоминает «Platform Stage
  0.13.1 реализован, NF-1/NF-2 исправлены... Формальный post-fix independent
  targeted PASS ещё не сохранён» — документ сам честно отмечает отсутствие
  формального подтверждения; это корректно сформулированная открытая задача,
  не false claim, но фиксируется здесь как задача вне scope этого review
  (проверка исправления NF-1/NF-2 требует отдельного targeted re-review,
  аналогичного `docs/development/STAGE_0_13_1_TARGETED_REREVIEW.md`).

## 7. Вне scope (не проверялось по существу)

Diff `tests/test_stage_0_12_17.py` и `tests/test_warehouse_api_contract.py`
содержит тестовые случаи за пределами заявленного «closing raw connections»
scope: `test_warehouse_type_summary_and_balance_type_filter_use_full_dataset`,
`test_missing_project_alone_is_not_an_incomplete_row`,
`test_balance_combined_filters_sort_and_pagination`,
`test_exact_serial_search_uses_an_identifier_index`. Эти тесты **выполняются
и проходят** (см. §4, входят в 33/33 и 392/392), но их бизнес-логика
(SQL-фильтрация до LIMIT, семантика `project` как optional tag, index usage
для exact S/N lookup) не подвергалась отдельному independent review в этой
сессии — задание прямо ограничивает scope closing-паттерном и запрещает
расширение до full-system audit. Рекомендация: если эта функциональность
считается частью stabilization gate, она заслуживает отдельного targeted
review с тем же уровнем строгости.

## 8. Verdict

**PASS.**

- Connection-closing изменение корректно, полно, не меняет прежнюю
  commit/rollback-семантику.
- 392/392 tests, `OK`, без единого `ResourceWarning` — подтверждено
  независимо, не только по отчёту исполнителя.
- Module-boundary и frontend-contract audits — PASS.
- `git diff --check` — PASS, ничего не staged.
- `docs/project/` не переопределяет approved ADR/DDL и не заявляет
  преждевременную реализацию Platform Stage 0.13.2.
- `data/warehouse.db` — байт-в-байт неизменна (SHA, размер, permissions,
  integrity, FK, отсутствие sidecars) до и после всей сессии.

**Warehouse stabilization может переходить к manual operator acceptance**
(`docs/MANUAL_TESTING_WAREHOUSE_STABILIZATION.md`) по результатам этого
review. Это не отменяет отдельно необходимый formal post-fix independent
targeted PASS для Platform Stage 0.13.1 NF-1/NF-2 (§6) — тот трек не блокирует
Warehouse operator acceptance, так как это независимые lanes (см.
`docs/project/ROADMAP.md`, Lane W vs Lane T).
