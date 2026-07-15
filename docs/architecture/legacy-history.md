# Legacy History

Статус: **APPROVED — ODE 0.13 architecture baseline**

## Назначение и запреты

LegacyHistoryEvent отвечает только на вопрос «что было записано в старом
источнике». Он:

- не является warehouse ledger;
- не создает opening state;
- не создает Equipment автоматически;
- не входит в snapshot или projection;
- не редактируется пользователем;
- может получить additive link на Equipment без изменения баланса;
- сохраняется вместе с immutable source file и raw payload.

## Поля события

Нормативная схема находится в [data-model.md](data-model.md#legacy-archive).
Timeline показывает:

- event type RECEIPT/ISSUE/UNKNOWN;
- performed_by_name_raw и его quality;
- accepted_by_name_raw, если источник действительно содержит получателя;
- occurred_at и date quality;
- comment, source item name, vendor/model/PN;
- S/N и Inventory Number raw;
- quantity/location raw;
- file name, SHA-256, sheet, one-based row;
- raw payload;
- warnings/conflicts;
- optional reviewed Equipment link и confidence.

## ФИО

ФИО нельзя получить предположением. performed_by_name_raw хранится NOT NULL как
точная строка source, включая пустую строку. Дополнительный quality:

- EXACT — source содержит проверяемое ФИО;
- CODE_ONLY — source содержит код/номер, но нет утвержденного personnel mapping;
- MISSING — source cell пуст;
- CORRUPTED — source не может быть интерпретирован как имя или код.

UI показывает «не указано» или «код без расшифровки», а не выдуманное имя.
Если позднее появится authoritative personnel mapping, создается отдельная
reviewed resolution; raw не изменяется и связь с User не создается
автоматически.

Фактическая 0.12 reconciliation содержит пустой responsible в 36 451 receipt и
12 000 issue rows. Значительная часть остальных значений числовая. Поэтому
требование сохранить ФИО реализуется как lossless raw + quality, а не ложное
NOT NULL имя.

## Date quality

| Quality | occurred_at | raw | Дополнительное правило |
|---|---|---|---|
| EXACT | required | required | Однозначно доказан парсинг и epoch/timezone |
| MISSING | null | empty | Source действительно пуст |
| ESTIMATED | required | required | estimation_basis required; UI помечает оценку |
| CORRUPTED | null | required | Значение есть, но надежная дата не доказана |

ESTIMATED не используется для удобства сортировки. Сортировка unknown dates
идет по source coordinates, а не по искусственной дате.

Текущие 49 094 NUMERIC_DATE_EXACT_1900_EPOCH могут стать EXACT только после
повторной проверки workbook date system и raw cell. 22 266
SOURCE_DATE_UNPROVEN имеют raw numeric value, но пустую parsed date; они
переходят в CORRUPTED, не ESTIMATED.

## Import identity

Идемпотентный ключ:

    source file SHA-256 + sheet + row number + operation kind + source row SHA

Одна source row создает ровно один LegacyHistoryEvent. Exact duplicate в
старом operational contour все равно остается отдельным source event, если это
отдельная Excel row; duplicate classification сохраняется warning.

## Equipment linking

Link допустим только:

- EXACT по active identity namespace;
- REVIEWED по explicit resolution;
- UNRESOLVED;
- CONFLICT.

Link хранится отдельной additive LegacyHistoryEquipmentLink с confidence.
Изменение создает новую link row, supersedes предыдущую и пишет audit, но не
переписывает event. Exact lookup может показывать unresolved legacy events по
serial_key рядом с Equipment timeline.

## Query

Exact S/N query использует conservative SerialKey и keyset:

    WHERE serial_key = ?
      AND (occurred_at_us, event_id) after cursor
    ORDER BY occurred_at_us IS NULL, occurred_at_us, event_id

Если разные vendor scopes имеют один S/N, UI показывает все groups и не
сливает их. Fuzzy search только помогает найти кандидатов и всегда помечается.

Unified timeline объединяет DTO из:

1. LegacyHistoryQuery;
2. InventoryQuery snapshot evidence;
3. LedgerQuery current transactions;
4. AuditQuery identity/admin actions.

Union выполняет history application query, не SQL join между repositories.
Каждый DTO содержит source_type.

См. [history search sequence](diagrams/history-search-sequence.md) и
[legacy mapping](../migration/legacy-history-mapping.md).
