# Основные процессы ODE

Диаграммы актуальны для source Stage 0.13.3A.5; runtime metadata остаётся
`0.12.17.1 RC2`. Первые три процесса — production runtime. Последние два —
offline migration staging и marker-guarded read-only pilot.

## Приход и расход со сканером

```mermaid
flowchart TD
    A[Заполнить общие поля операции] --> B[Сканировать S/N]
    B --> C{Проверка S/N}
    C -->|Допустим| D[Добавить в список]
    C -->|Ошибка или дубль| E[Показать причину]
    D --> F{Есть еще позиции?}
    E --> F
    F -->|Да| B
    F -->|Нет| G[Подтвердить весь список]
    G --> H{Повторная проверка}
    H -->|Успех| I[Записать одной транзакцией]
    H -->|Ошибка| J[Откатить весь список]
    I --> K[Обновить баланс, аудит и отчеты]
```

При списании неизвестный S/N допускается как проблемная строка. Остальные ошибки подтверждения отменяют всю транзакцию.

## Приемка поставки

```mermaid
flowchart TD
    A[Загрузить CSV снабжения] --> B[Проверить строки]
    B --> C[Подтвердить создание поставки]
    C --> D[Заполнить недостающие реквизиты]
    D --> E[Сканировать S/N]
    E --> F{S/N есть в поставке?}
    F -->|Да| G[Создать приход и связать строку]
    F -->|Нет| H{Принять внепланово?}
    H -->|Да| G
    H -->|Нет| E
    G --> I[Обновить статус поставки]
    I --> J{Приемка завершена?}
    J -->|Нет| E
    J -->|Да| K[Закрыть поставку и выгрузить результат]
```

## Массовое назначение Inventory Number — Stage 0.13.2

```mermaid
flowchart TD
    A[Скачать шаблон и заполнить Serial Number + Inventory Number] --> B[Загрузить CSV]
    B --> C[Read-only Preview: lookup только по S/N]
    C --> D{Есть VALIDATION_ERROR?}
    D -->|Да| E[Заблокировать Confirm; исправить CSV]
    D -->|Нет| F[Показать SUCCESS / UNCHANGED / NOT_FOUND / conflicts]
    F --> G[Пользователь подтверждает]
    G --> H[Consume one-shot preview и BEGIN IMMEDIATE]
    H --> I[Повторно проанализировать весь план]
    I --> J{План совпадает?}
    J -->|Нет| K[ROLLBACK; потребовать новый Preview]
    J -->|Да| L[Обновить все SUCCESS + legacy sync + audit]
    L --> M{Все writes успешны?}
    M -->|Нет| K
    M -->|Да| N[COMMIT и показать Result]
    N --> O[Timeline показывает событие каждой изменённой карточки]
```

Новые карточки не создаются, конфликтные строки не изменяются. Каноническая
sequence diagram и API-контракт:
[INVENTORY_NUMBER_IMPORT_ARCHITECTURE.md](INVENTORY_NUMBER_IMPORT_ARCHITECTURE.md).

## Reference Data Foundation и migration staging — Stage 0.13.3A

```mermaid
flowchart TD
    A[Проверить все 4 output paths] --> B{Есть alias с source DB/sidecar/raw/normalized либо outputs совпадают?}
    B -->|Да| C[Fail до чтения/сборки]
    B -->|Нет| D[Зафиксировать SHA immutable raw и working DB]
    D --> E[inspect-sources: manifest + read-only DB]
    E --> F[Прочитать OOXML tokens без float]
    F --> G[Сохранить source S/N + provenance]
    G --> H{Тип source cell}
    H -->|Text| I[Match key: NFKC + только внешние ignorable + casefold]
    H -->|Numeric ≤15 digits| J[Manual review; raw token; match key пуст]
    H -->|Numeric >15 digits| K[SOURCE_CORRUPTED; match key пуст]
    I --> L[Собрать reference/alias/catalog proposals]
    J --> L
    K --> L
    L --> M[Создать candidate DB в temporary bundle]
    M --> N[Security snapshot; operation tables пусты; 9 candidate-only tables]
    N --> O[На POSIX chmod candidate 0600]
    O --> P[Validate candidate + registered source SHA/size]
    P --> Q[Создать и round-trip проверить XLSX + CSV]
    Q --> R[Повторно проверить raw и working DB SHA]
    R --> S[Создать secret-free JSON report и fsync bundle]
    S --> T{Полный bundle gate пройден?}
    T -->|Нет| U[Удалить temporary bundle; published candidate не менять]
    T -->|Да| V[Опубликовать ancillary XLSX и CSV]
    V --> W[Опубликовать JSON report]
    W --> X[Заменить candidate DB последним как publication marker; fsync outputs]
    X --> Y[Ручной review; production не меняется]
```

**IMPLEMENTED:** CLI предоставляет `inspect-sources`, `build-candidate`,
`validate-candidate`, `report`. Автоматически подтверждаются только
синтаксически безопасные aliases; canonical name — пересчитываемый display,
S/N — identity.

Все четыре output (`candidate DB`, reference XLSX, serial CSV и JSON report)
должны быть разными файлами. Path guard запрещает совпадение путей и
symlink-/hardlink-equivalence с working DB и её sidecars, любым raw source или
normalized review input, а также запись внутрь `raw/` и `normalized/`.
Default outputs находятся в ignored `migration_inputs/workspace`.
Standalone `report` повторно применяет тот же guard и полностью строит
allowlisted JSON из candidate/source checks, не читая и не объединяя старый
report-файл.

**FACT:** Stage 0.13.3A не создаёт приходы/расходы, не импортирует лист БАЛАНС,
не изменяет runtime `reference_values`, не сбрасывает и не заменяет
`data/warehouse.db`.

**FUTURE STAGE / OPEN DECISION:** approved staging может стать входом Stage
0.13.3B только после ручного решения по конфликтам и отдельного import/reset
contract.

## Preservation-aware receipt pilot — Stage 0.13.3A.5

```mermaid
flowchart TD
    A[Проверить SHA Stage A candidate, raw workbook и serial review] --> B[Re-read receipt dates from OOXML]
    B --> C[Stable rank: SHA256 seed + source row hash]
    C --> D[Select exactly 200 real receipt rows]
    D --> E{Classify row}
    E -->|IMPORT, 130| F[Require TEXT_EXACT + quantity 1 + proven date + canonical proposal]
    E -->|QUARANTINE / MANUAL_REVIEW| G[Store review row; no receipt]
    E -->|EXACT_DUPLICATE / CONFLICT_HISTORY_ONLY| H[Link provenance to one identity; no second receipt]
    E -->|QUANTITY_POSITION_DEFERRED / SOURCE_CORRUPTED_REJECTED| I[Reject serialized receipt]
    F --> J[Write exact source S/N through ReceiptRepository in caller transaction]
    J --> K[Verify SQLite text and exact equality]
    K --> L[Mark historical opening balance; write migration audit]
    G --> M[(Pilot-only selection/quarantine/provenance)]
    H --> M
    I --> M
    L --> M
    M --> N{Marker/count/integrity/FK/no-sidecar/round-trip gate}
    N -->|fail| O[ROLLBACK / do not publish]
    N -->|pass| P[(warehouse_pilot_candidate.db)]
    P --> Q[Explicit launcher validates marker before ApplicationContext]
    Q --> R[Admin/engineer read-only review UI]
    R --> S[Exact S/N + source/canonical fields + Timeline]
    S --> T{Manual pilot decision}
    T -->|changes required| U[Fix rule in separate review; regenerate disposable artifacts]
    T -->|accepted| V[May plan FUTURE 0.13.3B only]
```

The selector records the unavailable-source fact
`VEGMAN_R200_UNAVAILABLE_FROM_SOURCE`; it does not fabricate a row. Shelf is
history/placement and never branches identity. All operational POST mutations
are denied in pilot mode. No arrow from this process writes or replaces
`data/warehouse.db`.
