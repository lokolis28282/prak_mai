# ODE 0.13 — Independent Adversarial Review (Architecture + DDL)

Статус этого документа: **REVIEW EVIDENCE — не нормативная спецификация**.
Дата: 2026-07-15. Ревьюер: независимый adversarial review (Principal
Architect / SQLite data engineer / warehouse domain / security / release
gatekeeper role), без доступа к частичному self-review автора и без
использования subagents, как того требовало задание.

Все выводы ниже получены заново: чтением docs/ADR/DDL и **независимым
выполнением** V001–V008 и adversarial SQL против временных БД вне репозитория
(`/private/tmp/.../ode013_review/`). Ни один DDL-файл, ни `data/warehouse.db`
не были изменены. Все read-only проверки против `data/warehouse.db`
выполнялись через `mode=ro&immutable=1` connection.

---

## 1. Главный вывод

**Нет.** Комплект ADR + DDL **нельзя** утвердить как безопасное основание
реализации ODE 0.13 в текущем виде. Обнаружено **2 CRITICAL** дефекта и
**1 HIGH** документационный разрыв, которые должны быть закрыты до
approval. BLOCKER-уровня дефектов (потеря данных, разрушение truth/ledger,
security bypass) не найдено. Крупная часть архитектуры — snapshot+ledger
truth model, immutability triggers, identity scoping, atomic publish
protocol, legacy/balance separation — **выдержала** adversarial проверку.

Зелёные результаты `REVIEW_RESULTS.md` (Codex self-review) в основном
воспроизводимы независимо, **за одним важным исключением**: заявленный
query-plan gate для «legacy history by serial» (Finding 1) не
воспроизводится — реальный план SQLite делает `SCAN`, а не `SEARCH`, что
прямо противоречит и заявленному результату, и требованию
`performance.md`.

---

## 2. Методология

- Прочитаны все перечисленные материалы (`docs/README.md`,
  `docs/architecture/*.md`, `docs/decisions/ADR-001..012`,
  `docs/architecture/ddl/V001..V008.sql`, `verify_schema.sql`,
  `verify_domain_invariants.sql`, `docs/migration/*`).
- `docs/architecture/SELF_REVIEW.md` и
  `docs/architecture/ODE_0_13_ARCHITECTURE_REVIEW.md` **намеренно не
  читались** до фиксации собственных findings (по прямому требованию
  задания — не использовать частичный анализ автора как источник).
- V001–V008 дважды собраны с нуля во временных БД
  (`/private/tmp/.../ode013_review/build1.db`, `fixture_base.db`,
  `perf.db`, `repro_check.db`) — результат идентичен заявленному:
  **41 таблица / 72 индекса / 67 триггеров / 3 view, integrity_check=ok,
  0 FK violations**.
- Independent negative/adversarial test suite: **36 сценариев**
  (`adversarial_tests.sh`, `adversarial_tests2.sh`, `adversarial_tests3.sh`),
  включая все обязательные сценарии из разделов 3–9 задания
  (UPDATE/DELETE approved snapshot, posted ledger, legacy event; duplicate
  identity; two active baselines; PARTIAL as snapshot; reversal-of-reversal;
  double supersede; orphan FK с `foreign_keys=OFF`; UOM scale mutation;
  negative projection row; equipment merge self-reference; и др.).
- Synthetic dataset (~20 тыс. equipment/identities, ~40 тыс. legacy events,
  ~20 тыс. ledger transactions+lines, ~20 тыс. projection rows,
  `ANALYZE` выполнен) для `EXPLAIN QUERY PLAN` — `gen_synth.py`, `perf.db`.
- Read-only проверка «71 360» арифметики против **текущей `data/warehouse.db`**
  через `mode=ro&immutable=1`.
- Итоговый воспроизводимый repro-набор: `independent-review-repro.sql`
  (публикуется рядом с этим отчётом).

---

## 3. Бизнес-модель (раздел «1» задания) — построчная проверка

| # | Утверждение | Вердикт | Доказательство |
|---|---|---|---|
| 1 | Legacy history никогда не влияет на баланс | **CONFIRMED** | `v_balance_truth_deltas`/`v_balance_truth` не читают `legacy_*`; `verify_domain_invariants.sql` содержит явные zero-row проверки `legacy_schema_balance_dependency`/`legacy_schema_ledger_dependency`; независимо вставлен legacy event поверх активного baseline — `v_active_balance` итог не изменился (1501→1501, воспроизведено). |
| 2 | Первый баланс создаётся только FULL approved inventory | **CONFIRMED** | `trg_snapshot_requires_full_session` требует `scope_type='FULL'`; независимая попытка создать snapshot из PARTIAL session отклонена (`snapshot requires approved FULL session`). |
| 3 | До baseline posting невозможен | **CONFIRMED** | Независимый тест на пустой схеме: INSERT в `warehouse_transactions` до какого-либо approved snapshot → `warehouse posting requires active baseline`. |
| 4 | Truth = active snapshot + immutable ledger after cutoff | **CONFIRMED** | `v_balance_truth` реализует ровно эту формулу; independent проверка `truth_projection_difference=0` после receipt/issue/reversal/transfer. |
| 5 | Projection можно полностью удалить и восстановить | **CONFIRMED** | `DELETE FROM balance_projection_rows` внутри транзакции с `ROLLBACK` работает (snapshot/ledger не затронуты); rebuild воспроизведён (`projection_rebuild_difference=0`). |
| 6 | PARTIAL inventory не может незаметно стать baseline | **CONFIRMED** | Независимая попытка `INSERT INTO inventory_snapshots` со `session.scope_type='PARTIAL'` отклонена тем же триггером, что и #2. |
| 7 | Reversal не переписывает исходную транзакцию | **CONFIRMED** | Posted `warehouse_transactions`/`_lines` полностью immutable (8/8 UPDATE/DELETE попыток отклонены); reversal — отдельная POSTED row. |
| 8 | Transfer не меняет общий остаток | **CONFIRMED** | `v_balance_truth_deltas` даёт `-Q`/`+Q` на разных ключах при одном `ledger_sequence`; глобальная сумма по catalog/uom не изменилась в proof-сценарии. |
| 9 | Старые `stock_receipts`/`stock_issues` не переходят в ledger | **CONFIRMED** | Ни один столбец/FK в V001–V008 не ссылается на legacy 0.12 таблицы; `source-to-target-field-mapping.md` явно помечает их `DO_NOT_MIGRATE_TO_LEDGER`; независимая read-only проверка `data/warehouse.db` показала **0** unlinked receipts/issues (см. §8). |
| 10 | История по S/N сохраняет ФИО/дату/качество/provenance | **CONFIRMED, с честной оговоркой** | Схема `legacy_history_events` хранит `performed_by_name_raw` (NOT NULL, допускает пустую строку) + `performed_by_quality`; независимая read-only проверка дала **48 451** missing и **22 909** code-like actor rows — совпадает с документом дословно. Оговорка не скрыта (`legacy-history-mapping.md` §«FIO limitation»). |

Все 10 бизнес-инвариантов раздела 1 задания **подтверждены** независимо,
включая косвенные (view/trigger) пути, не только прямые FK.

---

## 4. Классификация сложности схемы (раздел «2»)

41 таблица / 72 индекса / 67 триггеров — оправдано доменом (immutable
snapshot+ledger+legacy+audit+security+preview-adjacent+projection), но
структура заслуживает точечных правок.

**MUST KEEP**
- Все immutability-триггеры (`*_no_update`/`*_no_delete`/`*_immutable_*`,
  ~40 из 67). Независимо проверено: это **единственная** линия обороны против
  прямого SQL UPDATE/DELETE на posted/approved данных — 8/8 таких атак
  отражены исключительно триггерами, не application-слоем.
- `trg_ledger_requires_active_baseline`, `trg_snapshot_requires_full_session`,
  `trg_reversal_header_target`, `trg_reversal_line_exact_inverse`,
  `trg_location_parent_same_warehouse_*` — все независимо проверены как
  необходимые и работающие.

**NEEDS ADR** (см. Findings 2 и 4 ниже)
- Отсутствие anti-cycle защиты для `warehouse_locations.parent_location_id`
  и `reference_values.parent_value_id`.
- Отсутствие явной документации связки
  «rebaseline закрывает возможность reversal старых транзакций».

**MOVE TO APPLICATION (уже так, но не помечено явно в data-model.md)**
- Duplicate-subject line canonicalization внутри одной ledger transaction
  (warehouse-ledger.md сам называет это application validation, п.10, но
  DDL не имеет backstop — независимо подтверждено: 2 lines с идентичным
  stock key в одной transaction вставляются без ошибки).
- Equipment merge paired zero-net adjustment (ADR-006/domain-model.md
  описывают это как обязательное поведение correction workflow, но DDL это
  не требует — независимо подтверждено: merge проведён без paired
  adjustment, source equipment остаётся с активной projection-строкой).

**SIMPLIFY**
- `trg_uom_scale_immutable_after_use` (V008) проверяет использование UOM в
  5 таблицах, но пропускает `inventory_reconciliation_items.uom_id`
  (Finding 3) — нужно либо добавить 6-й `EXISTS`, либо — раз паттерн
  повторяется — рассмотреть единый generic backing view
  `v_uom_in_use` вместо перечисления таблиц вручную (снижает риск того же
  пропуска при добавлении новой uom_id-колонки в будущей миграции).

**REMOVE** — кандидатов на удаление не найдено; ни один триггер не
оказался избыточным dead-code при независимой проверке.

Trigger ordering / recursion: SQLite BEFORE-триггеры здесь не рекурсивны и
не создают cascade-цепочек между таблицами (каждый триггер работает на
«своей» таблице и читает соседние только через `SELECT EXISTS`, не через
INSERT/UPDATE), поэтому риска unbounded trigger recursion не обнаружено.
Единственный по-настоящему тонкий момент — предсказание PK для
`superseded_by_snapshot_id` (см. Finding 4b) — не trigger-recursion, а
transaction-ordering контракт, который DDL допускает (`DEFERRABLE INITIALLY
DEFERRED`), но нигде не описывает как обязательную технику реализации вне
одного комментария в `synthetic_rebaseline_proof.sql`.

Write amplification 67 триггеров + 72 индекса: для одного `RECEIPT` с одной
line независимая трассировка показывает единственный INSERT в
`warehouse_transactions`, единственный в `_lines`, срабатывание ~4 BEFORE
INSERT триггеров (все `SELECT EXISTS`, O(1) через индекс) — не найдено
квадратичной или table-scan стоимости per-write. Это не проверяет реальный
p95 на миллионах строк (см. §9 — «Performance»), но структурно amplification
разумна.

---

## 5. Equipment identity (раздел «3»)

Vendor-scoped active-uniqueness модель (ADR-006) **выдержала** все
предписанные сценарии:

- Дубль S/N в одном vendor scope → `UNIQUE constraint failed` (подтверждено).
- Два производителя, один и тот же физический S/N, разные `scope_key` →
  разрешено сосуществовать (разные partial-unique groups) — соответствует
  «Exact lookup может быть AMBIGUOUS между vendors», UI обязан показывать
  ambiguous result, а не выбирать одну карточку (это уже explicit contract
  в domain-model.md, не DDL blocker).
- UNKNOWN (`UNSCOPED`) vendor конфликт: первая identity `ACTIVE`, вторая
  вставлена напрямую со `status='CONFLICT'` — **успешно сосуществуют**,
  подтверждая, что partial unique index (`WHERE status='ACTIVE'`) корректно
  реализует «в UNSCOPED одновременно active может быть только один» без
  блокировки самого факта конфликта. Никакого автоматического merge при
  этом не происходит — корректно.
- Пустой S/N → `CHECK (length(raw_value) > 0)` блокирует. Confirmed.
- Case-only/пробелы/дефисы/leading zeros — это `normalized_key` policy
  (ADR-006 текст), DDL не проверяет саму нормализацию (это ответственность
  application `SerialKey` value object, вне DDL) — корректно разделено.
- Scientific notation / numeric identity — блокируется на уровне
  Excel-parser (import-preview-publish.md), не DDL; `raw_value` в DDL — это
  уже провалидированный текст. Не относится к DDL review.
- Merge: `equipment_merges.source_equipment_id <> survivor_equipment_id`
  проверено CHECK (self-merge отклонён). **НО**: DDL не требует
  `out_adjustment_sequence`/`in_adjustment_sequence` заполненными, даже
  если у source есть активный остаток — см. Finding 5 (MEDIUM).
- Split ошибочно объединённой карточки: `equipment_merges` не имеет
  UPDATE/DELETE (полностью immutable), поэтому «split» реализуется только
  новым forward-действием (новая identity/новое Equipment), не отменой
  merge-записи — соответствует «Merge rollback — explicit reverse
  correction, не history rewrite» в ADR-006.
- Повторный импорт того же Excel: `import_commits` UNIQUE
  `(import_kind, source_sha256, preview_digest)` + `idempotency_key` UNIQUE
  — двойной коммит того же файла отклонён (подтверждено).
- Legacy event до/после merge: `legacy_history_equipment_links` — отдельная
  additive-таблица с chain-триггером (`trg_legacy_link_chain`), не
  переписывает исходный legacy event — корректно.

**Вывод**: equipment identity model однозначна и не создаёт дублей одной
физической карточки при штатном использовании. Единственный настоящий
пробел — недостаточная DB-защита merge-with-active-balance (Finding 5,
MEDIUM, не CRITICAL, так как это existing app-level control по документу).

---

## 6. Inventory cutoff (раздел «4»)

ADR-010 сам честно признаёт операционную хрупкость полного freeze
(«Нужен operational owner freeze и процедура pending documents») и явно
относит это к **OPEN-003** («Operations blocker for first baseline/cutover;
not DDL»), а не скрывает проблему. Независимая проверка подтверждает: DDL
корректно реализует свою часть контракта —

- `late_operation_evidence` НЕ является ledger и НЕ влияет на баланс сама
  по себе (`resolution` CHECK разделяет `NO_BALANCE_EFFECT` от
  `ADJUSTMENT_POSTED`, второе требует отдельного posted
  `adjustment_ledger_sequence`) — двойной учёт технически невозможен без
  создания отдельной, явно audited posted-транзакции.
- Freeze token/state — намеренно **вне** operational DB (внешний workspace),
  соответствует принципу «до подтверждения рабочая база не меняется».
- Процесс упал во время `APPROVING`: candidate discard + operational DB
  остаётся byte-identical — структурно верно (SQLite Backup API +ATOMIC
  replace, см. §10).

**Ограничение, которое DDL не может закрыть и не должен**: «физическое
прекращение движений» — организационный, не технический факт. Docs
корректно признают это открытым пунктом (OPEN-003), не прячут за
формально «правильным» DDL. Я согласен с классификацией: это НЕ DDL
blocker, но это реальный operational risk, который нужно решить до
первого cutover — рекомендую явно требовать в runbook (не в DDL) второй
подтверждающий шаг «no pending documents» перед снятием freeze.

---

## 7. FULL/PARTIAL inventory (раздел «5»)

ADR-011 и DDL согласованы и независимо подтверждены:
- Первый baseline только FULL (§3, тест #2/#3 выше).
- PARTIAL никогда не создаёт Snapshot и не трогает `app_state` — независимо
  подтверждено (`trg_cycle_count_requires_partial_session` требует
  `scope_type='PARTIAL'`; symmetричный триггер требует `'FULL'` для
  snapshot — взаимоисключающие пути).
- Missing внутри PARTIAL scope → `inventory_reconciliation_items` с
  `classification` (`MISSING`/`NEW`/…), не создаёт adjustment сам по себе —
  подтверждено структурой (`import_resolution_id` — опциональная связь на
  отдельно поданную admin-команду, не автоматическая).
- Overlapping/parallel cycle counts — DDL допускает несколько
  `inventory_cycle_counts` со своими scope_json без взаимной блокировки;
  это by design (PARTIAL не мутирует global state), но нет UNIQUE-защиты
  от двух одновременно активных PARTIAL сессий на **пересекающийся**
  scope — это оставлено на application/organizational contract (документ
  явно не заявляет DDL-уровня защиты здесь), не считаю это finding, так
  как PARTIAL по определению balance-neutral и не может создать
  несогласованность truth.

**Вывод**: PARTIAL не бесполезна — она даёт controlled reconciliation
evidence + optional admin-initiated ADJUSTMENT, не нарушая immutable
ledger. Workflow корректен.

---

## 8. Quantity/UOM (раздел «6»)

- `quantity_minor INTEGER CHECK > 0` везде, `REAL` полностью отсутствует
  (`verify_schema.sql` подтверждает `real_quantity_columns=0`; независимо
  перепроверено — 0 REAL-колонок с `quantity`/`scale` в имени).
- Serialized quantity=1 COUNT/scale=0 enforced триггерами в 4 местах
  (snapshot item, cycle item, ledger line, projection row) — independent
  negative test (`quantity_minor=999999` для equipment line) отклонён.
- UOM scale immutable-after-use — **пробел** для
  `inventory_reconciliation_items` (Finding 3, MEDIUM, независимо
  воспроизведено — см. `FINDING_C` в repro-файле).
- Negative balance: нет отдельного DB-level "balance >= 0" CHECK на
  `warehouse_transaction_lines` (это ожидаемо — линия сама по себе не
  баланс), но есть defense-in-depth: попытка записать отрицательную
  `balance_projection_rows.quantity_minor` отклонена CHECK `>0` —
  независимо подтверждено. Полная корректность вычисления дельты остаётся
  application-enforced (см. §11 классификацию).
- Conversion/aggregation разных UOM: DDL не позволяет один stock key
  смешивать разные `uom_id` (партиция по `uom_id` — часть unique key),
  поэтому «сложение 5 EA + 3 M» структурно невозможно на уровне
  projection/snapshot — корректно.

---

## 9. Locations (раздел «7»)

- Same-warehouse parent check (`trg_location_parent_same_warehouse_*`) —
  подтверждён, работает при INSERT и UPDATE.
- **Cycle prevention отсутствует** — независимо воспроизведено (Finding 2,
  CRITICAL): двухузловой цикл `A→B→A` создан успешно в одном warehouse.
  Это прямое противоречие тексту data-model.md: «Unique code within
  warehouse; acyclic parent» и общей фразе «Parent graph must be acyclic»
  (там же, для `reference_values`, тот же паттерн, тот же дефект).
- Deactivated location / two identical codes / code rename — стандартные
  UNIQUE(warehouse_id, code) и `status` CHECK работают штатно, отдельно не
  выявлено проблем.
- Bulk item одновременно в нескольких locations — структурно возможно
  (разные stock key rows на разные `location_id`), это ожидаемо для bulk и
  не является дефектом.

---

## 10. Immutability и triggers (раздел «8»)

15 из 15 предписанных деструктивных попыток (плюс собственные вариации,
итого 20+ direct immutability/negative тестов) корректно отклонены:
UPDATE/DELETE approved snapshot и snapshot item, posted transaction и line,
legacy event, actor(user) delete, reference used by history (косвенно —
`users` защищён `trg_users_no_delete`, аналогично `legacy_source_files`),
identity после merge (identity rows immutable по `trg_equipment_identity_
immutable_fields`), reversal-of-reversal, reversal чужой transaction (через
`active_snapshot_id` match — см. Finding 4), duplicate idempotency key,
два активных baseline, activate projection от другого snapshot (partial
unique `ux_projection_active` тестирован структурно).

**Обход через отключение FK** — воспроизведён (`PRAGMA foreign_keys=OFF` +
insert orphan line → `pragma_foreign_key_check` находит нарушение). Это
**уже честно признано** в `docs/architecture/ddl/README.md`
(«Review negative test подтвердил, что connection без PRAGMA способен
вставить orphan; поэтому runtime connection factory и migration runner
имеют обязательный assertion `PRAGMA foreign_keys=1`») — я независимо
подтверждаю этот факт, не считаю его новым finding, но подчёркиваю: это
**application/operational-enforced** гарантия, не DDL-enforced (см. §11).
Immutability-триггеры сами по себе НЕ зависят от `foreign_keys` PRAGMA —
все `RAISE(ABORT,...)` триггеры сработали независимо от FK-статуса,
проверено отдельно.

Не найдено ни одного способа обойти immutability-триггеры через порядок
statements или каскад (нет ON DELETE CASCADE/ON UPDATE нигде в схеме —
все FK по умолчанию RESTRICT-подобны в SQLite при отсутствии явного
ON DELETE/ON UPDATE, что соответствует заявленному «Delete rule: RESTRICT»
в data-model.md).

---

## 11. Transaction/Audit/UoW (раздел «9»)

- Синтетический proof независимо воспроизведён «с нуля» (не скопирован
  бездумно — каждая транзакция receipt/issue/reversal/transfer
  перепроверена построчно на предмет отклонения при нарушении инвариантов
  до принятия как baseline для дальнейших тестов).
- Success audit находится в той же `BEGIN IMMEDIATE...COMMIT`, что и domain
  write — это **структурно проверяемо** (весь seed-скрипт использует одну
  транзакцию на use-case), но сама гарантия «audit ДОЛЖЕН быть в одной
  транзакции» — **application-enforced**, не DDL-enforced: DDL физически
  не может заставить приложение вставить audit-строку в ту же транзакцию,
  что и domain write; если приложение забудет — DDL это не поймает.
  Рекомендация: явно пометить это в transaction-model.md как
  application-layer инвариант (сейчас подразумевается, но не
  промаркировано отдельно от DB-enforced инвариантов).
- Audit hash chain (`previous_event_hash`/`event_hash`) детектирует
  accidental alteration, но не in-order insert violation на уровне DDL
  (никакой триггер не проверяет, что `previous_event_hash` нового ряда
  равен `event_hash` предыдущего) — это тоже честно оговорено в docs
  («hash chain обнаруживает accidental alteration, но не заявляется
  криптографически tamper-proof») — не новый finding, подтверждаю как
  correctly-scoped.

---

## 12. Atomic candidate publish (раздел «10»)

DDL-уровня здесь мало что можно проверить напрямую (это в основном
application/OS-уровень протокол), но связанные DDL-механизмы проверены:

- `superseded_by_snapshot_id ... DEFERRABLE INITIALLY DEFERRED` —
  единственный способ атомарно «переключить» active baseline без окна с
  двумя активными snapshot одновременно. Независимо воспроизведено: этот
  механизм **требует**, чтобы приложение заранее знало/резервировало PK
  нового snapshot (см. Finding 4b, HIGH) — иначе последовательность
  операций технически невозможна (protected unique index
  `ux_inventory_snapshot_active` не позволяет вставить новый active-ряд,
  пока старый ещё активен, а update старого требует ссылки на ещё не
  существующий ID нового).
- `application_id`/`user_version`/`schema_migrations` registry
  корректны, повторное применение V001 на существующей схеме корректно
  завершается ошибкой (проверено: `sqlite3 error, table schema_migrations
  already exists`).
- Windows/macOS-специфика (`os.replace` vs `ReplaceFileW`, antivirus/
  indexer lock, same-volume) — вне DDL, это application/ops-протокол;
  ADR-005 корректно относит platform acceptance к **OPEN-004**, не к DDL
  blocker — согласен с этой классификацией.
- «Два процесса approve одновременно» — SQLite `BEGIN IMMEDIATE` +
  `busy_timeout=10000` сериализует писателей на уровне файла; это
  стандартная, проверенная гарантия SQLite для single-writer модели
  (ADR-009), не требует дополнительного DDL-теста для подтверждения
  занятого замка.

**Вывод**: атомарность DDL-части протокола обоснована, но **предсказание
PK** (Finding 4b) должно быть explicit contract в ADR-002/transaction-
model.md, а не только в комментарии review-only proof файла.

---

## 13. Security (раздел «11»)

DB-enforced / application-enforced / operational-enforced классификация:

| Гарантия | Уровень | Проверено независимо |
|---|---|---|
| Argon2id-подобный **формат** пароля (`GLOB '$argon2id$*'`, `length>=30`) | DB (формат only) | **Подтверждено**: plaintext-подобная строка отклонена CHECK. Но CHECK **не может** проверить криптографическую корректность хеша (число итераций, соль, реальный Argon2id-алгоритм) — это правильно и без domain-owner claims в docs не заявлено иначе. Важно явно писать «DDL гарантирует только формат строки, не крипто-стойкость» — в security.md это не разведено явно (лёгкая формулировка «Password hash: Argon2id encoded string» может читаться как гарантия). |
| login/email uniqueness | DB | Подтверждено (`UNIQUE login_key`, partial unique `email_key`). |
| Default/known credentials | Operational (bootstrap) | `verify_schema.sql` проверяет `count(*)=0` в fresh `users` — корректно для fresh schema, но это НЕ проверяет, что bootstrap-процедура (вне DDL) не создаёт default пароль — operational, не DDL. |
| Session expiration/revocation | DB (CHECK) + application (актуальная проверка `now() < expiry`) | `absolute_expires_at_us >= idle_expires_at_us` CHECK подтверждён; фактическая проверка истечения — application read-path, не DDL. |
| CSRF hash | DB (столбец есть, NOT NULL, length=32) | Существование гарантировано, корректность генерации — application. |
| Role escalation | DB (`roles.code IN (...)`, `role_permissions` PK) | Unknown role отклонён CHECK — подтверждено. |
| Actor spoofing (display-name snapshot) | DB частично (`actor_display_name` NOT NULL) + application (кто на самом деле подставляет значение) | DDL не может проверить, что `actor_display_name` реально совпадает с текущим `actor_user_id.display_name` на момент записи — application responsibility, не DDL. |
| Storage key / path traversal | DB (CHECK `NOT LIKE '%..%'`, GLOB allowlist) | Подтверждено на 4 местах (`legacy_source_files`, `import_commits`, `report_jobs`, `backup_records`). |
| Audit access | Application (permission layer) | Вне DDL scope. |

Итог: ни одно utверждение "DDL гарантирует Argon2id" в буквальном смысле в
проверенных файлах не встречено — `security.md` формулирует аккуратно
(«Password hash: Argon2id encoded string»), но не содержит явной оговорки
«DDL проверяет только формат, не крипто-корректность». Рекомендую добавить
одну явную строку об этом в security.md — не блокер, MEDIUM
documentation-clarity item, включён в общий список ниже как Finding 6.

---

## 14. Performance (раздел «12»)

Независимый EXPLAIN QUERY PLAN прогон на synthetic dataset (~20–40 тыс. rows
на таблицу, `ANALYZE` выполнен) дал:

| Query | Ожидаемый path (docs) | Фактический path (независимо) |
|---|---|---|
| exact S/N | `ix_equipment_identity_exact` | **SEARCH** — совпадает |
| exact inventory number | `ix_equipment_identity_exact` | **SEARCH** — совпадает |
| equipment keyset page | `ix_equipment_lifecycle_page` | SEARCH на PK (rowid); для запроса с фильтром `lifecycle_status` без указания статуса в моём тесте план использовал PK-diapason, не ix_equipment_lifecycle_page — не считаю дефектом (зависит от точной формы запроса/selectivity, не gate-нарушение) |
| balance page (warehouse/location) | `ix_projection_balance_page` | **SEARCH** — совпадает |
| equipment balance | `ix_projection_equipment` | **SEARCH** — совпадает |
| **legacy history by serial** | `ix_legacy_history_serial` | **SCAN legacy_history_events — НЕ СОВПАДАЕТ** |
| ledger by equipment | `ix_ledger_lines_equipment` | **SEARCH** — совпадает |
| snapshot items by session | `ix_snapshot_items_page` | **SEARCH** — совпадает |
| audit feed keyset | `ix_audit_events_page` | **SEARCH/SCAN USING INDEX** (порядковый скан по индексу для keyset без WHERE — ожидаемо для полной keyset-страницы без фильтра, не дефект) |
| catalog item exact vendor+PN (доп. проверка, тот же root cause) | `ux_catalog_items_vendor_part` | **не используется**; планировщик выбирает `ix_catalog_items_browse` по одному `status=?` — менее селективно |

**Finding 1 (CRITICAL)** подробно: `ix_legacy_history_serial` определён как
`CREATE INDEX ... ON legacy_history_events(serial_key, occurred_at_us,
event_id) WHERE serial_key <> ''`. SQLite (проверено на 3.51.0) **не может
доказать**, что `serial_key = 'SN-0000001'` подразумевает
`serial_key <> ''`, и поэтому не применяет partial index для точного
запроса, который естественным образом напишет приложение
(`WHERE serial_key = ?`). Это воспроизводится даже на **пустой таблице**
(структурное решение планировщика, не следствие статистики) и **не
устраняется одним ANALYZE**. Обходной путь — дублировать
`AND serial_key <> ''` в каждом запросе — нигде не задокументирован (ни в
DDL-комментарии, ни в data-model.md, ни в performance.md).

При заявленном worst-case dataset (5 000 000 legacy events, до 10 000
повторов одного serial) это означает **полный table scan на 5 млн строк**
для одного из самых частых запросов (`LegacyHistoryQuery`, exact S/N
timeline) — прямое нарушение `performance.md`: «EXPLAIN QUERY PLAN gate
запрещает SCAN крупной operational table для exact lookup/page» и прямое
несовпадение с заявленным зелёным результатом в `REVIEW_RESULTS.md`
(«legacy history by serial | covering `ix_legacy_history_serial`»),
который **не воспроизводится**.

Redundant/missing indexes: не найдено явно избыточных индексов при первом
приближении (72 индекса примерно соответствуют перечисленным access paths
+ необходимые UNIQUE constraints); углублённый redundancy-аудит (например,
подмножества составных индексов) не входил в объём данного review при
текущем уровне effort и требует отдельного прохода с полным списком
запросов из UI/API DTO (вне предоставленных материалов).

Write cost 72 индекса + 67 триггеров — не измерялся как latency (для этого
нужна утверждённая машина, что явно запрещено performance.md
«Численные gates принимаются только на утвержденной машине»), но
структурно каждый триггер — O(1) `EXISTS`-проверка через индекс, не
table scan; серьёзной deep-OFFSET проблемы не обнаружено (все browse-пути
документированы как keyset, не OFFSET).

---

## 15. Source-to-target / 71 360 строк (раздел «13»)

Независимо перевыполнено **read-only** против текущей `data/warehouse.db`
(SHA-256 `73568a1c3ee...` не изменился до/после):

```
71 360 = 71 356 migrated + 4 quarantined (2 QUARANTINED + 2 SOURCE_CORRUPTED_REJECTED) + 0 excluded + 0 unclassified
```

**CONFIRMED, побитово совпадает** с `legacy-history-mapping.md` и
`REVIEW_RESULTS.md`. Дополнительно независимо перепроверено:

- Duplicate staging mappings: **0** — confirmed.
- Orphan reconciliation rows (missing staging/source file): **0** — confirmed.
- Date quality: `NUMERIC_DATE_EXACT_1900_EPOCH`=**49 094**,
  `SOURCE_DATE_UNPROVEN`=**22 266** — confirmed exactly.
- Missing raw actor total: **48 451**; code-like actor total: **22 909** —
  confirmed exactly (по operation_kind: RECEIPT missing=36 451/code=14 552,
  ISSUE missing=12 000/code=8 357).
- Unlinked `stock_receipts`/`stock_issues`: **0**/**0** — confirmed.
- Orphan `migration_serial_cells`: **0** — confirmed.

Восстановимость ФИО: подтверждаю честность формулировки —
почти половина receipt-строк (36 451 из 51 003, ≈71%) не имеет raw
ответственного вообще; UI не может и не обещает показать ФИО там, где
источник его не содержит. Это верно описано, не переоценено.

---

## 16. OPEN DECISIONS (раздел «14»)

Проверено: ни один из **новых** findings этого независимого review
(cycle-guard gap, partial-index scan, UOM-scale gap, reversal-after-
rebaseline coupling) **не входит** в существующий реестр OPEN-001..009.
Это значит, что реестр `OPEN_DECISIONS.md` **неполон относительно DDL**:
его собственное summary-утверждение «Архитектурных blocker, меняющих PK,
UNIQUE, FK, CHECK либо snapshot/ledger/history/identity/UoW model, не
осталось» **не выдерживает** независимую проверку — Finding 1 и Finding 2
ниже являются именно такими DDL-уровня дефектами (missing CHECK/trigger
coverage, broken index-usage contract), обнаруженными adversarial-тестами,
а не «self-review greenwashing». Существующие OPEN-001..009 сами по себе
корректно классифицированы как non-DDL (я согласен с их текущей
классификацией business/operational scope), но реестр должен получить
новые записи для DDL-специфичных находок этого отчёта.

---

## 17. Findings (раздел «16»)

### Finding 1 — CRITICAL — Performance / Query Plan
- **Область**: `docs/architecture/ddl/V004__legacy_history.sql:78-80`,
  `docs/architecture/ddl/V002__references_and_catalog.sql:128-130`.
- **Summary**: Partial index `WHERE col <> ''` не используется SQLite для
  обычного equality-запроса `col = ?`, вызывая полный table scan вместо
  index search на `legacy_history_events(serial_key)` и деградацию до
  менее селективного индекса на `catalog_items(vendor_scope_key,
  part_number_key)`.
- **Сценарий**: `EXPLAIN QUERY PLAN SELECT * FROM legacy_history_events
  WHERE serial_key = 'SN-0000001';` → `SCAN legacy_history_events`
  (воспроизведено на SQLite 3.51.0, даже на пустой таблице).
- **Expected**: `SEARCH ... USING INDEX ix_legacy_history_serial` (как
  заявлено в `performance.md` и `REVIEW_RESULTS.md`).
- **Actual**: `SCAN legacy_history_events`.
- **Доказательство**: `independent-review-repro.sql`, блок FINDING B.
- **Риск**: при 5 000 000 legacy events (заявленный worst-case dataset)
  — полный scan на каждый exact-S/N-timeline запрос; прямое нарушение
  заявленного performance gate и заявленного (но невоспроизводимого)
  зелёного query-plan review.
- **Рекомендация**: убрать partial-предикат `WHERE serial_key <> ''` из
  индекса (или переопределить с явным `serial_key IS NOT NULL AND
  serial_key <> ''` продублированным в каждом запросе как **обязательный**
  documented contract), аналогично для `ux_catalog_items_vendor_part`.
  Перепроверить query-plan review заново после фикса на той же машине.
- **Требует изменения ADR**: нет напрямую, но `performance.md`
  query-plan review результат должен быть аннулирован и переснят.
- **Требует изменения DDL**: да — V002, V004 (индексные определения).
- **Требует user decision**: нет, чисто техническая правка.

### Finding 2 — CRITICAL — Data Integrity / Missing Invariant
- **Область**: `docs/architecture/ddl/V002__references_and_catalog.sql`
  (`reference_values.parent_value_id`),
  `docs/architecture/ddl/V002__references_and_catalog.sql:170-190`
  (`warehouse_locations.parent_location_id`).
- **Summary**: Иерархии `parent_location_id` и `parent_value_id` не имеют
  anti-cycle защиты; существует только same-warehouse-membership check.
  `data-model.md` явно заявляет «acyclic parent» / «Parent graph must be
  acyclic» как нормативный инвариант.
- **Сценарий**: создать location A (parent=NULL), location B (parent=A),
  затем `UPDATE A SET parent_location_id=B` — независимо воспроизведено:
  цикл A↔B успешно создан. Идентичный сценарий воспроизведён для
  `reference_values`.
- **Expected**: UPDATE должен быть отклонён как нарушающий acyclic
  invariant.
- **Actual**: UPDATE выполнен без ошибки.
- **Доказательство**: `independent-review-repro.sql`, блоки FINDING A/A2.
- **Риск**: любой код, обходящий parent-chain (breadcrumbs, cascading
  deactivation, canonical-value resolution, будущие recursive CTE) может
  зациклиться; нарушает явно документированный MUST-инвариант без
  application-layer предупреждения в docs о том, что это НЕ enforced на
  уровне DB.
- **Рекомендация**: добавить BEFORE UPDATE/INSERT trigger с recursive CTE
  проверкой ancestor chain перед установкой `parent_location_id`/
  `parent_value_id` (глубина иерархии здесь мала — сотни/тысячи locations,
  recursive CTE by depth дёшева), либо явно перенести это в
  application-enforced с явной пометкой в data-model.md и покрытием в
  `verify_domain_invariants.sql` (сейчас там нет ни одной cycle-проверки).
- **Требует изменения ADR**: нет (не меняет PK/UNIQUE/FK/CHECK решения
  по сути, только добавляет trigger).
- **Требует изменения DDL**: да — V002 (оба места).
- **Требует user decision**: нет.

### Finding 3 — MEDIUM — Data Integrity
- **Область**: `docs/architecture/ddl/V008__audit_and_operations.sql:124-133`.
- **Summary**: `trg_uom_scale_immutable_after_use` проверяет использование
  UOM в 5 таблицах, но пропускает `inventory_reconciliation_items.uom_id`.
- **Сценарий**: создать UOM, использовать его только в одной
  `inventory_reconciliation_items` строке, затем `UPDATE uoms SET
  scale=... WHERE uom_id=...` — независимо воспроизведено: mutation прошла
  успешно.
- **Expected**: `RAISE(ABORT, 'used UOM dimension and scale are
  immutable')`, как для остальных 5 таблиц.
- **Actual**: UPDATE выполнен без ошибки.
- **Доказательство**: `independent-review-repro.sql`, блок FINDING C.
- **Риск**: `delta_quantity_minor = counted_quantity_minor -
  expected_quantity_minor` на immutable reconciliation evidence row теряет
  корректную интерпретацию, если scale соответствующего UOM тихо
  изменится после факта — нарушает retention PERMANENT/immutable claim
  для этой таблицы.
- **Рекомендация**: добавить 6-й `EXISTS`-check в триггер.
- **Требует изменения DDL**: да — V008.
- **Требует user decision**: нет.

### Finding 4 — HIGH — Documentation Gap (behavior plausibly correct)
- **Область**: `docs/architecture/ddl/V006__warehouse_ledger.sql:132-156`
  (`trg_ledger_requires_active_baseline`, `trg_reversal_header_target`);
  `docs/architecture/transaction-model.md`, `docs/architecture/
  warehouse-ledger.md`, `docs/decisions/ADR-002-snapshot-ledger-balance.md`,
  `docs/decisions/ADR-010-inventory-cutoff.md`.
- **Summary**: После supersession активного snapshot ни одна транзакция,
  посчитанная под старым (теперь неактивным) snapshot, больше никогда не
  может быть reversed — `trg_reversal_header_target` требует
  `original.active_snapshot_id = NEW.active_snapshot_id`, а
  `trg_ledger_requires_active_baseline` требует, чтобы
  `NEW.active_snapshot_id` был **текущим активным**. Это поведение
  логически объяснимо (дельта старой транзакции уже поглощена новым
  physical count), но **нигде не задокументировано** — ни в
  transaction-model.md, ни в warehouse-ledger.md, ни в ADR-002/ADR-010.
- **Сценарий**: post RECEIPT под snapshot 91 → approve successor FULL
  baseline (snapshot 92, superseding 91) → попытка REVERSAL транзакции,
  посчитанной под 91 (`active_snapshot_id=91`) — независимо воспроизведено:
  `warehouse posting requires active baseline`.
- **Expected**: явное поведение и explicit error code/сообщение,
  задокументированные как intended contract.
- **Actual**: неявная блокировка через generic trigger-сообщение, без
  explicit business-rule объяснения где-либо в prose docs.
- **Доказательство**: `independent-review-repro.sql`, блок FINDING D.
- **Риск**: администратор, обнаруживший ошибку в транзакции ПОСЛЕ того,
  как прошла новая инвентаризация, не сможет использовать REVERSAL и
  обязан использовать ADJUSTMENT — это в принципе предусмотрено
  документом («Если exact reversal невозможен... admin создает явные
  ADJUSTMENT/TRANSFER»), но конкретно ЭТА причина невозможности (rebaseline)
  нигде явно не связана с этим fallback-путём, что рискует непониманием
  и support-инцидентами при первом реальном случае.
- **Рекомендация**: добавить явный параграф в warehouse-ledger.md/ADR-010
  «Reversal доступен только в пределах текущего активного baseline; после
  supersession используется ADJUSTMENT», и рассмотреть отдельный,
  говорящий application-level error code (`REVERSAL_UNAVAILABLE_AFTER_
  REBASELINE`) вместо generic `INVENTORY_FREEZE`-подобного сообщения.
- **Требует изменения ADR**: да — ADR-010 (или новое short addendum).
- **Требует изменения DDL**: нет (текущее поведение корректно, только
  недокументировано).
- **Требует user decision**: да — подтвердить, что это **намеренное**
  поведение (я считаю его логически корректным, но это бизнес-решение,
  которое должно быть explicit, не emergent).

### Finding 4b — HIGH — Documentation Gap (implementation contract)
- **Область**: `docs/architecture/ddl/V005__imports_and_inventory.sql:129-132`
  (`superseded_by_snapshot_id ... DEFERRABLE INITIALLY DEFERRED`);
  `docs/architecture/transaction-model.md` (Approve inventory phase table);
  `docs/decisions/ADR-002-snapshot-ledger-balance.md`.
- **Summary**: Атомарная замена active baseline технически требует, чтобы
  приложение **заранее знало/зарезервировало** `snapshot_id` нового
  snapshot до его физической вставки (иначе `UPDATE` старого snapshot на
  `superseded_by_snapshot_id=<future-id>` невозможен без deferred FK, а
  вставка нового snapshot как active **до** деактивации старого нарушает
  partial unique index). Единственное место, где эта техника вообще
  описана — однострочный SQL-комментарий в review-only
  `synthetic_rebaseline_proof.sql`. Ни transaction-model.md, ни ADR-002 не
  формулируют это как обязательный implementation contract.
- **Риск**: разработчик, реализующий approve-flow «естественным» образом
  (сначала INSERT нового snapshot через `AUTOINCREMENT`, потом UPDATE
  старого) столкнётся либо с unique index violation (два active snapshot
  на мгновение), либо будет вынужден заново открывать эту же
  deferred-FK-технику самостоятельно, без единого источника истины.
- **Доказательство**: независимо воспроизведено в `adversarial_tests3.sh`
  test 30b и `synthetic_rebaseline_proof.sql` (комментарий на строке 55-56).
- **Рекомендация**: явно описать «predicted-PK atomic supersede» как
  normative implementation contract в ADR-002 или отдельном коротком
  разделе transaction-model.md «Approve inventory» — не оставлять только в
  proof-комментарии.
- **Требует изменения ADR**: да — ADR-002.
- **Требует изменения DDL**: нет.
- **Требует user decision**: нет.

### Finding 5 — MEDIUM — Data Integrity (app-enforced, undocumented as such)
- **Область**: `docs/architecture/ddl/V003__equipment_identity.sql:112-131`
  (`equipment_merges`); `docs/architecture/domain-model.md` («Merge...
  Если обе сущности имеют активный остаток, коррекция оформляет связанные
  ADJUSTMENT_OUT/ADJUSTMENT_IN с нулевым net total»).
- **Summary**: DDL не требует `out_adjustment_sequence`/
  `in_adjustment_sequence` заполненными, даже если source equipment имеет
  активную `balance_projection_rows` запись на момент merge — независимо
  воспроизведено: merge проведён, source equipment помечен `MERGED`, но
  его projection-строка (quantity>0) осталась нетронутой под старым
  `equipment_id`, что создаёт «осиротевший» баланс, невидимый обычным
  balance-запросам по survivor equipment.
- **Доказательство**: см. session transcript, тест «merge without paired
  adjustment» (репродуцирован до финализации отчёта; не включён в
  compact repro-файл ради краткости, воспроизводится аналогично FINDING C
  fixture-паттерну).
- **Рекомендация**: либо DB-level CHECK/trigger (сравнение суммы balance
  для source equipment перед разрешением lifecycle→MERGED), либо явная
  пометка в domain-model.md «DDL не проверяет это; enforced исключительно
  application use-case» рядом с существующим текстом.
- **Требует изменения DDL**: опционально (trigger добавление возможно, но
  недёшево — требует агрегирующего подзапроса по projection).
- **Требует user decision**: да — выбрать между DB enforcement (дороже,
  надёжнее) и явной документацией пробела (дешевле, требует
  дисциплины application-слоя).

### Finding 6 — LOW — Documentation Clarity
- **Область**: `docs/architecture/security.md` («Authentication» раздел).
- **Summary**: Формулировка «Password hash: Argon2id encoded string» может
  читаться как гарантия криптографической корректности. DDL CHECK
  (`GLOB '$argon2id$*' AND length>=30`) реально проверяет только **формат**
  строки, не то, что параметры (memory/iterations/salt) соответствуют
  actual Argon2id алгоритму или security-approved parameters.
- **Рекомендация**: добавить одну явную фразу «DDL проверяет только формат
  строки; фактическая крипто-корректность и параметры — ответственность
  application hashing library и security review, не DDL».
- **Требует изменения DDL**: нет.
- **Требует user decision**: нет.

### Finding 7 — LOW — Documentation/DDL mismatch
- **Область**: `docs/architecture/data-model.md` (import_commits раздел,
  «import_kind CHECK FULL_INVENTORY/LEGACY_MIGRATION/REFERENCE_IMPORT»);
  `docs/architecture/ddl/V005__imports_and_inventory.sql:8-10`.
- **Summary**: DDL реально включает 4-е значение `PARTIAL_INVENTORY`
  в CHECK, отсутствующее в прозе data-model.md.
- **Рекомендация**: обновить data-model.md, добавить `PARTIAL_INVENTORY` в
  перечисление.
- **Требует изменения DDL**: нет (DDL корректен, документация отстала).
- **Требует user decision**: нет.

### Finding 8 — LOW — Verification gate coverage
- **Область**: `docs/architecture/ddl/verify_schema.sql:62-70`
  (`immutability_triggers` check), `docs/architecture/ddl/
  verify_domain_invariants.sql` (полное отсутствие anti-cycle проверок).
- **Summary**: `immutability_triggers` gate — это только `count >= 12`, не
  per-table coverage list; при будущем добавлении новой mutable-по-ошибке
  таблицы gate не заметит регрессию, пока общее число триггеров ≥12.
  `verify_domain_invariants.sql` не содержит ни одной проверки cycle-
  freedom для `parent_location_id`/`parent_value_id` (что соответствует
  Finding 2 — отсутствию самой защиты).
- **Рекомендация**: заменить count-based gate на explicit table-list
  (по аналогии с `required_exact_indexes`), добавить recursive-CTE
  zero-row cycle-check queries в `verify_domain_invariants.sql` после
  фикса Finding 2.
- **Требует изменения DDL**: нет (только verify-скрипты).
- **Требует user decision**: нет.

---

## 18. Ответы на прямые вопросы (раздел «19» задания)

1. **Можно ли утвердить архитектурные ADR?** Частично — 10 из 12 ADR не
   имеют DDL-blocking проблем и подтверждены независимо. ADR-002 нуждается
   в addendum (Finding 4b), ADR-010 — в addendum (Finding 4). Ни один ADR
   не требует пересмотра PK/UNIQUE/FK/CHECK решения по существу.
2. **Можно ли утвердить DDL?** **Нет, не в текущем виде** — 2 CRITICAL
   находки (Finding 1, Finding 2) требуют исправления и повторной
   верификации перед approval.
3. **Число BLOCKER**: 0.
4. **Число CRITICAL**: 2 (Finding 1, Finding 2).
5. **Число HIGH**: 2 (Finding 4, Finding 4b).
6. **Число MEDIUM**: 2 (Finding 3, Finding 5).
7. **Число LOW**: 3 (Finding 6, Finding 7, Finding 8).
8. **Какие решения Codex подтверждены?** Все 10 бизнес-инвариантов §3
   задания; snapshot/ledger/legacy separation; equipment identity vendor-
   scoping; FULL/PARTIAL workflow; immutability triggers (20+ negative
   tests); atomic supersede mechanism (структурно, хоть и недокументирован
   как contract); 71 360-арифметика и все производные из неё числа
   (48 451/22 909/49 094/22 266); security format-level checks; отсутствие
   plaintext/default credentials в fresh schema.
9. **Какие решения опровергнуты?** Заявленный зелёный query-plan результат
   для «legacy history by serial» (Finding 1) — не воспроизводится.
   Implicit claim «Parent graph must be acyclic» для двух таблиц — не
   подтверждается DDL (Finding 2). Implicit claim «UOM scale immutable
   after use» — не полностью покрыт (Finding 3, один из 6 usage-путей
   пропущен).
10. **Оправданы ли 41 таблица?** Да, для заявленного домена (immutable
    ledger+snapshot+legacy+security+audit+projection+preview-adjacent
    provenance) без очевидно избыточных таблиц.
11. **Оправданы ли 67 triggers?** В основном да; один нуждается в
    дополнении (Finding 3), два места нуждаются в добавлении новых
    триггеров (Finding 2), остальные подтверждены как необходимые и
    эффективные защитные механизмы.
12. **Есть ли опасные или лишние triggers?** Опасных (создающих
    неконтролируемый recursion/cascade) — нет. Лишних — не найдено.
    Недостаточных — да (Finding 3, отсутствующие — Finding 2).
13. **Корректна ли equipment identity?** Да, включая edge cases (UNSCOPED
    conflict, vendor rename через новую identity row, alias preservation).
14. **Может ли vendor-scoped S/N создать дубли одной физической
    карточки?** Нет при штатном использовании; ambiguous-result UI path
    — explicit design decision, не дефект.
15. **Корректна ли модель FULL freeze?** Технически корректна в рамках
    того, что DDL способен гарантировать; операционная хрупкость честно
    признана как OPEN-003, не скрыта.
16. **Не теряются ли late operations?** Нет — `late_operation_evidence` +
    раздельный `ADJUSTMENT_POSTED` предотвращают двойной учёт математически;
    зависит от человеческого discovery process (не DDL-решаемо).
17. **Корректна ли PARTIAL inventory?** Да, balance-neutral по конструкции,
    подтверждено независимо.
18. **Корректны ли quantity/UOM?** В основном да; один пробел (Finding 3).
19. **Корректна ли location model?** Нет полностью — Finding 2 (cycle gap).
20. **Реально ли immutable ledger защищён?** Да, 8/8 direct attack
    сценариев отражены; обход возможен только через явное отключение FK
    (уже признанный, документированный, mitigated operational risk).
21. **Реально ли legacy history отделена от balance?** Да, подтверждено
    и структурно (views/triggers), и содержательно (71 360 арифметика).
22. **Корректна ли atomic publish на macOS и Windows?** DDL-часть
    (deferred FK supersede) корректна, но недокументирована как contract
    (Finding 4b); platform-specific часть вне DDL scope, корректно
    отнесена к OPEN-004.
23. **Какие guarantees только application-level?** Audit-в-той-же-
    транзакции; duplicate-line canonicalization; merge paired-adjustment;
    crypto-корректность password hash; достоверность actor_display_name;
    freeze token соблюдение; SerialKey/normalization policy — все
    перечислены в §11/§13 таблице выше.
24. **Есть ли security defects?** Не найдено security-специфичных
    дефектов уровня CRITICAL/BLOCKER; один LOW documentation-clarity item
    (Finding 6).
25. **Есть ли performance defects?** Да — Finding 1, CRITICAL, независимо
    воспроизведён и напрямую противоречит заявленному gate.
26. **Подтверждена ли арифметика 71 360 строк?** Да, полностью, включая
    все производные числа (§15 выше).
27. **Насколько восстановимы ФИО старых операций?** Ограниченно и честно
    задокументировано: 48 451 из ~71 360 (68%) не имеют raw ФИО вообще;
    ещё часть — только числовой код без approved personnel mapping
    (OPEN-001).
28. **Какие OPEN decisions оказались DDL blockers?** Ни один из
    существующих OPEN-001..009 не стал DDL blocker при независимой
    проверке (согласен с их текущей non-DDL классификацией); однако
    реестр должен получить новые записи под Finding 1/2/3 (см. §16 выше)
    — это НОВЫЕ находки, не превращение старых OPEN-пунктов в blocker.
29. **Какие ADR нужно изменить?** ADR-010 (Finding 4), ADR-002
    (Finding 4b) — addendum, не пересмотр решения по существу.
30. **Какие SQL-файлы нужно изменить?** `V002__references_and_catalog.sql`
    (Finding 2, 7), `V004__legacy_history.sql` (Finding 1, 2),
    `V008__audit_and_operations.sql` (Finding 3), `verify_schema.sql` и
    `verify_domain_invariants.sql` (Finding 8).
31. **Изменялся ли product code?** Нет. `git status`/`git diff --stat`
    до и после review идентичны для `inventory/`, `static/`, `app.py`,
    `scripts/`, `tests/` (тот же pre-existing worktree diff, к которому
    я не притрагивался).
32. **Изменялась ли production DB?** Нет.
33. **SHA-256 production DB до/после**:
    `73568a1c3eecbd4476473f064620d7f0a196b336ce8ea6d834c5b99359d4b010`
    (идентична, integrity_check=ok, foreign_key_check=0 violations,
    size/mtime не изменились, WAL/SHM/journal отсутствуют оба раза).
34. **Можно ли переходить к реализации Stage 0.13.1?** **Нет.** Наличие
    2 CRITICAL находок по правилам самого задания блокирует переход к
    реализации, независимо от общего высокого качества остальной
    архитектуры.
35. **Каков рекомендуемый следующий шаг?** (a) Исправить Finding 1
    (индексы) и Finding 2 (cycle guard) в V002/V004; (b) добавить Finding 3
    trigger-check в V008; (c) добавить explicit ADR addenda для Finding 4
    и 4b; (d) перезапустить `REVIEW_RESULTS.md` query-plan gate заново
    после фикса Finding 1 на той же процедуре; (e) только после этого —
    повторный независимый (или тот же) review конкретно по diff двух
    файлов, не полный review с нуля.

---

## 19. Проверки сохранности (раздел «18»)

| Проверка | До | После |
|---|---|---|
| Git HEAD | `76afadd5355f4d379b19dcabf1f28850986d5300` | `76afadd5355f4d379b19dcabf1f28850986d5300` (не менялся) |
| `data/warehouse.db` SHA-256 | `73568a1c3eecbd4476473f064620d7f0a196b336ce8ea6d834c5b99359d4b010` | идентична |
| size/mtime | 579461120 bytes / 2026-07-15 11:45:53 | идентичны |
| `PRAGMA integrity_check` | ok | ok |
| `PRAGMA foreign_key_check` | (пусто, 0 violations) | (пусто, 0 violations) |
| WAL/SHM/journal рядом с `data/warehouse.db` | отсутствуют | отсутствуют |
| product code diff (`inventory/`, `static/`, `app.py`, `scripts/`, `tests/`) | pre-existing unrelated worktree changes (не мои) | идентичен, не тронут |

Все temporary DB созданы вне `data/` —
`/private/tmp/claude-501/.../fc072bbf-.../scratchpad/ode013_review/`.
Ни один DDL-файл, ADR или review-artifact не изменялся кроме двух
разрешённых новых файлов: этот отчёт и
`docs/architecture/ddl/independent-review-repro.sql`.

Ни commit, ни push, ни release, ни deployment, ни DDL-миграция к
production/candidate DB не выполнялись.
