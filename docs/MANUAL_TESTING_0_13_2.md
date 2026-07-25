# Ручная проверка Stage 0.13.2

Дата: 2026-07-14.

Проверка массового назначения Inventory Number выполняется только на
одноразовой тестовой БД. Запрещено использовать `data/warehouse.db` для
mutation-сценариев.

## Подготовка

1. Зафиксировать SHA-256 рабочей БД и убедиться, что у неё нет WAL/journal.
2. Запустить `start_test_macos.command` или `start_test_windows.bat`. Launcher
   должен создать `data/warehouse_test_clean.db` и показать баннер
   `ТЕСТОВЫЙ КОНТУР`.
3. Создать на тестовом контуре несколько существующих receipt-позиций:
   - `MT-0132-SUCCESS` без Inventory Number;
   - `MT-0132-SAME` с `INV-MT-SAME`;
   - `MT-0132-ASSIGNED` с `INV-MT-OLD`;
   - `MT-0132-OWNER` с `INV-MT-TAKEN`;
   - `MT-0132-DUPLICATE` без Inventory Number;
   - `MT-0132-FREE-A` и `MT-0132-FREE-B` без Inventory Number.
4. Создать backup тестовой БД либо сохранить её SHA/копию для сравнения.

## Базовый CSV

Скачать шаблон в `Склад -> Инвентаризация -> Массовое назначение Inventory
Number` и сохранить заполненный файл в UTF-8:

```csv
Serial Number;Inventory Number
MT-0132-SUCCESS;INV-MT-NEW
MT-0132-SAME;INV-MT-SAME
MT-0132-MISSING;INV-MT-MISSING
MT-0132-ASSIGNED;INV-MT-OTHER
MT-0132-DUPLICATE;INV-MT-TAKEN
```

## Preview

1. Выбрать CSV и дождаться таблицы.
2. Проверить по одной строке каждого результата:
   - `SUCCESS` для `MT-0132-SUCCESS`;
   - `UNCHANGED` для `MT-0132-SAME`;
   - `NOT_FOUND` для `MT-0132-MISSING`;
   - `ALREADY_ASSIGNED` для `MT-0132-ASSIGNED`;
   - `DUPLICATE_INVENTORY_NUMBER` для `MT-0132-DUPLICATE`.
3. До confirm открыть карточки/SQLite-копию и убедиться, что значения и число
   audit-записей не изменились.
4. Убедиться, что кнопка confirm доступна: перечисленные конфликты не являются
   `VALIDATION_ERROR`, примениться должна только строка `SUCCESS`.

## Confirm и повторный импорт

1. Нажать `Подтвердить импорт` один раз.
2. Проверить видимый counter/toast `SUCCESS = 1` / «Назначено Inventory Number:
   1»; в API response этому соответствует `changed_count = 1`. У
   `MT-0132-SUCCESS` должен быть записан `INV-MT-NEW`, остальные позиции не
   изменены, новая карточка для `MT-0132-MISSING` не появилась.
3. Открыть карточку `MT-0132-SUCCESS` и найти одну Timeline-запись
   `EQUIPMENT_INVENTORY_NUMBER_ASSIGNED` с текущим инженером.
4. Загрузить тот же CSV повторно. Первая строка должна стать `UNCHANGED`,
   confirm не должен создать второй audit event.

## Blocking validation

Загрузить файл:

```csv
Serial Number,Inventory Number
MT-0132-SUCCESS,INV-FIRST
mt-0132-success,INV-SECOND
```

Оба вхождения должны получить `VALIDATION_ERROR`, а confirm должен быть
недоступен. Регистр и пробелы не делают S/N различными.

Отдельно проверить пустые S/N/Inventory Number и значения длиннее 255 символов:
они также дают `VALIDATION_ERROR` и не меняют БД.

## Duplicate Inventory Number внутри CSV

Для двух существующих позиций без номера назначить один свободный номер:

```csv
Serial Number;Inventory Number
MT-0132-FREE-A;INV-MT-INFILE
MT-0132-FREE-B;inv-mt-infile
```

Обе строки должны получить `DUPLICATE_INVENTORY_NUMBER`. Confirm разрешён при
отсутствии validation errors, но `changed_count` должен быть 0.

## Права и lifecycle preview

- `viewer` может читать карточки и скачать шаблон; после загрузки user state
  видимый label выбора CSV удаляется, скрытый file input не должен запускать
  импорт, а прямые preview/confirm API-вызовы должны быть отклонены;
- confirm с чужим author возвращает ошибку;
- повторный confirm того же `preview_id` возвращает
  `Предпросмотр не найден или устарел`;
- после restart/TTL/eviction или stale-plan необходимо выполнить новый Preview;
- прямой `POST /api/import-csv?kind=inventory_numbers` должен отклоняться.

## Атомарность

Искусственный failure в середине batch нельзя создавать на рабочей БД. Он
покрыт автоматическим тестом
`test_confirm_rolls_back_all_updates_and_audits_on_mid_batch_failure`, который
создаёт trigger только во временной SQLite БД. После failure обе позиции,
legacy sync и audit остаются без изменений.

## Обязательный gate

Команды ниже являются каноническим release gate для POSIX/zsh development-
окружения. На Windows пользовательскую проверку выполняют test launcher и
version-specific release instructions; production DB для gate не используется.

```bash
python3 -m py_compile app.py inventory/**/*.py scripts/*.py tests/*.py
for file in static/js/**/*.js tests/headless_smoke.js; do
  node --check "$file" || exit 1
done
python3 scripts/audit_module_boundaries.py
python3 scripts/audit_frontend_contracts.py
python3 -W error::ResourceWarning -m unittest discover -s tests -v
python3 scripts/create_clean_test_db.py --dry-run
python3 scripts/smoke_ui.py
git diff --check
```

В финале проверить рабочую БД: SHA до/после совпадает,
`PRAGMA integrity_check` возвращает `ok`, `PRAGMA foreign_key_check` пуст,
WAL/journal отсутствуют. Headless должен показать `inventoryNumbers=true` и
нулевые console/window/unhandled/resource/HTTP/API500 errors.
