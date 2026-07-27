# Release Report — ODE 0.19.0 documentation alignment

Дата: 2026-07-27.

## Verdict

ODE 0.19.0 — релиз выравнивания документации. Runtime-код не менялся:
единственная правка вне документации — `inventory.__version__`
(`0.18.1` → `0.19.0`). Вся функциональность унаследована от 0.18.1.

Verdict: **READY FOR LOCAL DEMO / PILOT AND SOURCE DISTRIBUTION** —
без изменения статуса относительно 0.18.1.

Это не готовность к публичному многопользовательскому deployment. Release ZIP
не создавался; Git содержит только исходный код, тесты, документацию и
архитектурные схемы, без runtime-БД и данных компании.

## Исходная точка и Git

- upstream baseline: `cc663be` (`ODE 0.18.1`, ветка
  `codex/multidb-backup-0190`);
- рабочая ветка: `release/0.19.0`, создана от `origin/codex/multidb-backup-0190`;
- ветка коллеги не переписывалась, force push и history rewrite не
  выполнялись.

## Причина релиза

После Multi-Warehouse (0.17.0), Vacations (0.18.0) и multi-DB backup (0.18.1)
три корневых документа продолжали описывать более ранний контур. Расхождение
было не косметическим: это входные документы для людей и AI-агентов, и они
утверждали неверные архитектурные факты.

| Документ | Что утверждал | Факт на 0.18.1 |
|---|---|---|
| `CLAUDE.md` | контур 0.16.0; `data/warehouse.db` — «единственный активный продуктовый контур»; 594 теста | три runtime-БД, шесть фасадов, 628 тестов |
| `ARCHITECTURE.md` | «ODE 0.14 initial-inventory boundary»; одна runtime-БД | multi-warehouse + Vacations + multi-DB backup |
| `ITOG.md` | «главная техническая документация ODE 0.16.0»; 594 теста; 220 узлов графа | 0.18.1; 628 тестов; 245 узлов / 502 связи |

Ни один из трёх не упоминал Solar, Vacations и multi-DB backup. `AGENTS.md`
был обновлён до 0.18.0, но также не знал про backup-профиль Administration,
из-за чего два набора правил для агентов расходились между собой.

## Что сделано

- `CLAUDE.md`, `ARCHITECTURE.md`, `ITOG.md` приведены к фактическому контуру:
  три независимые runtime-БД и их владельцы, `inventory/routes` и
  `inventory/templates`, шесть публичных фасадов, `RuntimeDatabaseRegistry` и
  `MultiDatabaseBackupService`, fail-closed restore до ADR-013, отсутствие
  сторнирующих операций до ADR-014;
- `AGENTS.md` дополнен multi-DB backup и синхронизирован с `CLAUDE.md`:
  boundary, правила зависимостей, работа с БД и раздел ограничений теперь
  совпадают;
- число автоматических тестов приведено к фактическим 628 во всех местах, где
  оно упоминалось (`594`, `598`, `619` и незаполненное значение);
- версия поднята до `0.19.0`; обновлены версионные указатели в `README.md`,
  `docs/README.md`, `docs/API_REFERENCE.md`, `docs/CODEBASE_GRAPH.md` и
  `docs/project/CURRENT_STATE.md`;
- в `docs/project/CURRENT_STATE.md` добавлены раздел 0.19.0 и явные ссылки на
  ADR-013/ADR-014 как на ближайшие кандидаты с уже утверждённым контрактом;
- добавлен настоящий отчёт.

## Не вошло

- любые изменения runtime-кода, схемы SQLite, HTTP API и ownership таблиц;
- restore preview/token/safety backup/atomic replace (ADR-013);
- correction/reversal складских операций (ADR-014);
- расписание, retention и шифрование backup;
- новый Windows artifact и release ZIP.

Формулировки «реализовано» для этих пунктов в документации отсутствуют.

## Gate

Выполнен на Linux, Python 3.10.12, Node v22.22.3.

| Проверка | Результат |
|---|---|
| Python compile | OK |
| JavaScript syntax | 49 файлов, OK |
| module-boundary audit | OK |
| frontend-contract audit | OK, 162 html id / 317 static references |
| repository-data audit | OK, 576 tracked files, runtime/company artifacts отсутствуют |
| clean-test-DB dry-run | OK, source SHA не изменился |
| full `unittest discover` | 628 тестов, `OK (skipped=8)` под `-W error::ResourceWarning` |
| deterministic code graph | 245 узлов / 502 связи; `--check` current |
| `git diff --check` | OK |

Восемь skip относятся к отсутствующим ignored migration/pilot-артефактам.
Новых неожиданных skip нет.

### Что НЕ проверялось

- **headless Chrome smoke (`scripts/smoke_ui.py`) не запускался** в этой среде
  и не заявляется как выполненный. Для релиза без изменений кода и шаблонов
  это приемлемо, но перед операторской приёмкой его следует прогнать на macOS
  или Windows;
- Codebase Memory full reindex не выполнялся; метрики 0.18.0
  (7 067 узлов / 30 991 ребро / 550 файлов / 42 routes) сохранены как
  последний подтверждённый внешний снимок и не переименованы в 0.19.0.
  `artifact_present=false`.

## Сохранность рабочих БД

SHA-256 зафиксированы до начала работы и повторно после полного gate.

| Runtime DB | SHA-256 до и после | integrity | FK |
|---|---|---|---|
| IXcellerate | `8681f3c34c52d12e665ddae9f9f818a7635c1108aee353baa9fc63830955305b` | `ok` | 0 |
| Solar | `6eb930442fdc55bf5f460398eaa31afd0d302fc8f8081bc5787c295fca0eb257` | `ok` | 0 |
| Vacations | `41d226a96110e2233717ae002859f97912bc8b531da29b4f2f2fd083b9e28b4a` | `ok` | 0 |

Во всех трёх случаях SHA совпал, SQLite sidecars отсутствуют. Ни одна
runtime-БД не отслеживается Git.

## Evidence

- изменения: [`CHANGELOG.md`](CHANGELOG.md), раздел ODE 0.19.0;
- текущее состояние:
  [`docs/project/CURRENT_STATE.md`](docs/project/CURRENT_STATE.md);
- карта кода: [`docs/CODEBASE_GRAPH.md`](docs/CODEBASE_GRAPH.md);
- исторические отчёты 0.18.1 и раньше сохранены без изменений.
