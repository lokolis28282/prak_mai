# Full Historical Warehouse Candidate and Local Promotion

## Post-promotion Warehouse stabilization

Повторный historical build/replacement не выполнялся. Все 50 000 imported
identities и migration provenance сохранены character-exact. Reference cleanup
изменяет только canonical `reference_*_v2`/audit и не переписывает historical
receipt datacenter/shelf/supplier или S/N.

Ручная запись receipt 1050001 с exact S/N `1` была создана 2026-07-14 20:28:22
после full build, не имела строк в staging/serial cells/reconciliation/identity,
delivery, issue или allocation. После отдельного byte-copy и SQLite `.backup`
она удалена SHA-guarded transaction скриптом `scripts/remove_test_serial.py`.
Сохранён audit `TEST_DATA_REMOVED_AFTER_MANUAL_REVIEW`; 50 000 migration
identities и digest всех оставшихся S/N не изменились.

## Статус и граница

**CANDIDATE BUILT, VALIDATED AND PROMOTED TO LOCAL WORKING DB.** Этот контур
строит с нуля disposable БД
`migration_inputs/workspace/warehouse_full_candidate.db` с marker
`FULL_WAREHOUSE_CANDIDATE`. Он обработал весь доступный staging:
51 003 строки прихода и 20 357 строк расхода. Каждая из 71 360 строк имеет ровно
один финальный статус в `migration_full_reconciliation` и в XLSX-отчёте.

Builder не изменяет `data/warehouse.db`, не использует лист `БАЛАНС` и не
продолжает тестовые складские операции. После отдельной проверки и явного
разрешения байтовая копия этого candidate была проверена как sibling `.next` и
атомарно опубликована в локальную `data/warehouse.db`. Исходный full candidate,
pilot и Stage 0.13.3A candidate сохраняются отдельно. Это не серверный
production deployment.

Обычный `python3 app.py` открывает promoted `data/warehouse.db` без специальной
переменной окружения. Точное candidate-имя остаётся специальным read-only
review artifact; marker и provenance внутри рабочей копии доступны только
административной диагностике и не меняют обычный складской UI.

Нормативные entrypoints:

- builder/validator: `scripts/migration_full_candidate.py`;
- candidate-only schema: `inventory/migration/full_schema.py`;
- классификация и orchestration: `inventory/migration/full_builder.py`;
- запись в актуальные ODE warehouse tables и существующий `audit_log`:
  `inventory/warehouse/migration_full.py`;
- marker-guarded review: `inventory/warehouse/migration_full_review.py`;
- macOS/Windows launchers: `start_full_migration_candidate_macos.command` и
  `start_full_migration_candidate_windows.bat`.

## Воспроизводимая сборка

Предпосылка — проверенный Stage 0.13.3A candidate
`migration_inputs/workspace/warehouse_migration_candidate.db`, immutable raw
sources и их SHA manifest. Полная сборка запускается только явно:

```bash
python3 scripts/migration_full_candidate.py build --overwrite
python3 scripts/migration_full_candidate.py validate
```

Без `--overwrite` существующие full DB/reports не заменяются. Builder запрещает
совпадение любого source/output path или inode, сначала сверяет raw, Stage A и
production SHA, строит DB и четыре отчёта во временном каталоге, выполняет
validation и только затем публикует их через `os.replace`. На POSIX файлы имеют
mode `0600`; после публикации не должно быть `-wal`, `-shm` или `-journal`.

Детерминированы identity/status decisions, current-attribute rule, ID ranges,
event/provenance content, ordering и build key. Замеренные durations и размер
являются наблюдениями конкретного прогона и естественно могут отличаться при
повторе. Generated DB не редактируется вручную: исправляется source rule,
approved alias либо код классификации, после чего весь candidate пересобирается
этой командой.

Текущий проверенный build:

| Метрика | Значение |
|---|---:|
| Source rows | 71 360 |
| Identity/card states | 50 000 |
| Реальные historical receipt states | 49 709 |
| Technical opening states | 291 |
| Imported issues/allocations | 18 798 / 18 798 |
| Provisional numeric identities | 6 689 |
| Quarantine rows | 4 |
| Audit/Timeline rows | 146 632 |
| DB size | 566 059 008 bytes |

## Чистый операционный контур

Full candidate копируется из operationally-empty Stage A candidate, а не из
операционного содержимого `data/warehouse.db`. До исторического импорта builder
обязан получить нули для `stock_receipts`, `stock_issues`,
`stock_issue_allocations`, `deliveries`, `delivery_lines`, `equipment`,
`operations`, `work_logs`, `daily_report_uploads`, `daily_report_rows` и
`audit_log`.

Сохраняются только актуальная схема, один активный admin/user security contour,
системные/reference tables Stage A и migration staging. После импорта остаются
пустыми deliveries, legacy equipment/operations, work logs и daily reports.
Ненулевыми становятся только historical receipt/opening states, issues,
allocations и allowlisted migration audit events.

Новые ID находятся в отделённых диапазонах:

- receipt/opening state: больше 1 000 000;
- issue: больше 2 000 000;
- allocation: больше 3 000 000.

`migration_full_cleanliness` хранит before/after counts, сохранённые system
tables, исходные operational IDs и проверку каждого исключённого test S/N.
Текущий build доказал отсутствие 24 уникальных старых test S/N (31 source-table
occurrence). Каждый candidate receipt связан ровно с одной
`migration_full_identities` row; каждый issue — с reconciliation и одной
неосиротевшей allocation.

Подробное доказательство:
`migration_inputs/reports/FULL_WAREHOUSE_OPERATIONAL_CLEANLINESS.xlsx` и `.md`.

## Preservation-aware identity

Identity key всегда включает preservation domain; полка в него не входит.

### `TEXT_EXACT`

`source_serial_value` сохраняется как текст символ в символ, включая ведущие
нули, регистр и внутренние символы. Нормализованное значение хранится отдельно
и применяется только как match key. На один proven S/N создаётся одна карточка;
повторная source row становится linked/duplicate/conflict history и не создаёт
второй receipt.

### `NUMERIC_FORMAT_UNPROVEN`

Raw OOXML token остаётся literal в `raw_xml_value`. Display S/N раскрывается в
целое только через `Decimal`, без `float`, например
`3.000221521238E12 → 3000221521238`. Identity имеет
`identity_confidence=PROVISIONAL`, `authoritative=0`,
`requires_manual_review=1`; предупреждение явно сообщает о возможной потере
ведущих нулей. Ключ строится как отдельный numeric domain плюс raw token, поэтому
такая карточка не merge-ится с `TEXT_EXACT`. Inventory Number пуст и запрещён
backend guard до ручного подтверждения формата.

### `SOURCE_CORRUPTED`

Карточка/receipt/issue не создаются. Raw token, logical source file, sheet/row,
reason и final status сохраняются в reconciliation/quarantine. Никакого
предположительного восстановления нет; quarantine имеет `affects_balance=0`.

### Атрибуты и canonical naming

Stage 0.13.3A reference domains, approved aliases, catalog proposals и naming
переиспользуются без redesign. Pending alias добавляет warning и не останавливает
batch. Опасный semantic merge не выполняется: vendor/model остаются отдельными
полями, Huawei/xFusion и разные модели не объявляются взаимозаменяемыми.

Для identity с несколькими строками текущие атрибуты выбираются
детерминированно: последняя доказанная historical date, затем наибольший source
row и staging ID. Все альтернативные vendor/model/item-name/shelf значения
остаются в provenance/conflicts. `source_item_name` и `canonical_item_name`
хранятся отдельно. Полка сохраняется как placement/provenance; несколько полок
не дробят serialized balance.

## Приход

Финальная сверка 51 003 строк:

| Status | Rows |
|---|---:|
| `IMPORTED` | 43 027 |
| `NUMERIC_PROVISIONAL_IMPORTED` | 6 682 |
| `LINKED_TO_EXISTING_IDENTITY` | 65 |
| `EXACT_DUPLICATE` | 611 |
| `CONFLICT_HISTORY_ONLY` | 532 |
| `QUANTITY_DEFERRED` | 84 |
| `SOURCE_CORRUPTED_REJECTED` | 2 |

Serialized unit rows создают одну identity/receipt state. Exact duplicate не
создаёт второй receipt. Conflicting attributes остаются history/warnings.
Quantity/cable-like rows не превращаются в serialized equipment.

## Расход и opening state

Финальная сверка 20 357 строк:

| Status | Rows |
|---|---:|
| `IMPORTED` | 15 359 |
| `NUMERIC_PROVISIONAL_LINKED` | 3 155 |
| `OPENING_STATE_CREATED` | 284 |
| `CONFLICT_HISTORY_ONLY` | 283 |
| `QUANTITY_DEFERRED` | 1 274 |
| `QUARANTINED` | 2 |

Расход связывается с тем же preservation-aware key. Для S/N, встреченного
только в расходе, создаётся technical `MIGRATION_OPENING_STATE_CREATED` без
supplier/order/request/PLU. Это не поставка и не исторический приход. Timeline
показывает:

> Исходный приход отсутствует в доступной выгрузке; начальное состояние
> восстановлено для сохранения исторического расхода

Всего opening identities 291: 284 exact issue rows имеют status
`OPENING_STATE_CREATED`, ещё 7 issue-only numeric identities остаются в более
строгом status `NUMERIC_PROVISIONAL_LINKED`, но также имеют `opening_state=1`.
Повторный/противоречивый расход записывается history-only и не создаёт
отрицательный serialized balance. Target equipment S/N хранится в 13 058
`INSTALLED_IN` relationships; 1 979 target references не нашли preservation-
compatible identity и явно помечены warning, не теряя исходное значение.

## Audit, Timeline и read-only UI

Новая event-система не создаётся. Используется существующий `audit_log` и
только восемь migration actions:

- `MIGRATION_RECEIPT_IMPORTED`;
- `MIGRATION_SOURCE_ROW_LINKED`;
- `MIGRATION_EXACT_DUPLICATE_SKIPPED`;
- `MIGRATION_CONFLICT_RECORDED`;
- `MIGRATION_NUMERIC_IDENTITY_PROVISIONAL`;
- `MIGRATION_OPENING_STATE_CREATED`;
- `MIGRATION_ISSUE_IMPORTED`;
- `MIGRATION_SERIAL_QUARANTINED`.

`GET /api/migration-full` и full-вариант Equipment Card доступны только после
marker guard и только admin/engineer. UI показывает permanent banner
«ПОЛНАЯ КАНДИДАТНАЯ БАЗА СКЛАДА», counters, все требуемые filters, source и
canonical names, historical date, preservation/confidence, warnings,
conflicts/opening state и target relationships. Absolute local paths и
`password_hash` не проектируются. Все POST, кроме logout, отвергаются backend.

Запуск на macOS:

```bash
./start_full_migration_candidate_macos.command
```

Windows: `start_full_migration_candidate_windows.bat`. Launcher не строит и не
изменяет DB, использует только фиксированный full path, требует marker, точное
имя, mode/health/no-sidecars и отвергает production path. Остановка — `Ctrl+C`.

## Как читать отчёт

Основные artifacts:

- `FULL_WAREHOUSE_MIGRATION_REPORT.xlsx` / `.md` — totals, reconciliation,
  receipts/issues/identities, provisional/corrupted/duplicates/conflicts,
  opening/unresolved/quarantine/deferred, references, performance, validation и
  manual checklist;
- `FULL_WAREHOUSE_OPERATIONAL_CLEANLINESS.xlsx` / `.md` — сохранённые/очищенные
  tables, before/after counts, исключённые test S/N и provenance proof.

`SOURCE_ROW_RECONCILIATION` является главным ledger: ровно 71 360 data rows,
по одной на source row. Идентификаторы записаны как text с number format `@`.
Для расследования сначала фильтруют `final_status`, затем используют
source file/sheet/row/hash и target identity/receipt/issue ID. Generated reports
— evidence конкретной сборки, не вход для следующей.

## Известные ограничения текущей candidate

- 22 266 receipt rows не имеют доказанной historical date; они импортированы с
  `SOURCE_DATE_UNPROVEN`, а не отброшены.
- 6 689 numeric identities требуют ручного решения; формат до Excel и возможные
  ведущие нули не доказаны.
- 16 567 canonical names используют documented fallback; pending supplier,
  vendor/model aliases сохранены warnings.
- 31 755 rows имеют numeric part-number warning и требуют предметной проверки.
- 1 979 target-equipment relationships не нашли compatible target identity.
- `UNRESOLVED_ISSUE` сейчас равен нулю; deferred quantity/cable rows — 1 358.
- Source Inventory Number сохраняется только как provenance и не назначается
  автоматически ни exact, ни provisional карточкам.
- Candidate предназначена для review; корректирующих production migration
  операций, rollback deployment и multi-user write режима здесь нет.

## Local promotion record and future server boundary

Для локальной promotion проверены marker, SHA, integrity/FK, sidecars,
пользователи/роли/password hashes, operational counts, исключение старых test
S/N, exact/leading-zero/long/vendor/component/opening карточки, баланс,
Timeline, обычный `WarehouseFacade` и browser/API smoke на временной копии.
Старая БД сохранена двумя независимо проверенными способами вне Git. Точная
процедура и rollback описаны в
[LOCAL_WORKING_DATABASE_RUNBOOK.md](LOCAL_WORKING_DATABASE_RUNBOOK.md).

Ручные решения по provisional/canonical/pending-alias остаются сохранёнными в
provenance; обычный интерфейс не выдаёт технический статус за пользовательский
термин. Raw и generated candidate не исправляются вручную: меняется исходное
правило/approved decision, затем candidate воспроизводится и заново проходит
gate.

В будущем на сервер переносятся versioned application code и schema migrations,
после чего full candidate воспроизводится из approved immutable sources либо
публикуется по отдельно утверждённому migration runbook. Текущая тестовая
БД никогда не переносится как основа production и никакая DB не должна
попадать на сервер как побочный файл обычного code release. Server path,
permissions, maintenance window, backup retention и deployment gate пока не
реализованы. Existing audit
architecture допускает будущую outbox boundary, но outbox/Kafka в candidate не
добавлены.
