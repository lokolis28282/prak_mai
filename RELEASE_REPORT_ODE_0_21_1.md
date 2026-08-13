# ODE 0.21.1 — Windows portability pre-release report

Дата: 2026-08-13
Исходная база patch: `main` / `ccbec75`
RC anchor: `v0.21.1-rc.1` на release commit
Статус: **release candidate; physical Windows sign-off pending**

## Причина patch-релиза

Физический перенос приватного ODE 0.21.0 на рабочий Windows-ноутбук обнаружил
две независимые блокирующие регрессии:

1. `cmd.exe` разбирал UTF-8 `.bat` с Unix LF-окончаниями строк как повреждённые
   команды, поэтому появлялись сообщения `'3'`, `'cho'` и `'DE' is not
   recognized`.
2. Windows ZIP включал `inventory/warehouse/baseline/service.py` с обязательным
   импортом `baseline_rehearsal`, но не включал сам bridge, зависимый `ode/`,
   schema manifest, target DDL и SQL схемы FULL Inventory workspace. Запуск
   завершался `ModuleNotFoundError: No module named 'baseline_rehearsal'`.

Архив и его `SHA256SUMS.txt` не были повреждены при копировании: прежняя сборка
изначально имела неполный allowlist. Это дефект release tooling 0.21.0.

## Исправление

- все tracked Windows launcher-файлы закреплены как CRLF через
  `.gitattributes`;
- builder дополнительно нормализует `.bat`/`.cmd` в CRLF независимо от ОС
  сборки;
- source package включает полный runtime closure:
  `inventory` Python/SQL, `baseline_rehearsal`, `ode`, schema manifest,
  V001–V008, verification SQL и оба clean-test builder;
- extracted-package regression выполняет cold import `inventory.webapp`,
  создаёт FULL target schema через `MigrationRunner` и проверяет workspace SQL;
- test проверяет отсутствие UTF-8 BOM и одиноких LF во всех Windows launcher;
- test launcher создаёт новые `*_test_disposable_v1.db`; старые unmarked
  `*_test_clean.db` не используются и не блокируют patch-upgrade;
- test runtime принимает только три явные DB с marker
  `ODE_DISPOSABLE_TEST_DB_V1` и ролями
  `warehouse`/`warehouse`/`vacations`; ordinary startup marked test DB
  отвергает;
- builders перезаписывают только marked target той же роли, а любой selected
  SQLite sidecar блокирует startup до writes;
- выбранные IX/Solar/Vacations DB должны быть попарно различны и не могут
  менять installation-owned роли; malformed marker, non-regular path,
  case-insensitive collision и target race отклоняются до публикации;
- test/review FULL Inventory, Knowledge, Monitoring и backup auxiliary state
  размещается только во временном owned root; live DCIM отключён;
- idle persistent-WAL source без sidecar открывается immutable; существующий
  committed WAL попадает в согласованный snapshot через SQLite Backup API при
  неизменных main DB/WAL/journal;
- pre-write runtime validation/composition вынесены в
  `inventory/core/web_runtime.py`, сохранив публичные facade/API contracts;
- добавлены ясная история версий, нейтральная атрибуция участников и автономная
  HTML-презентация для руководителя.

## Safety boundary

Кодовый patch не меняет business schema или runtime data; marker существует
только в disposable test DB. Все mutation/UI smoke выполняются на временных
копиях. `data/warehouse.db`,
`data/warehouse_solar.db` и `data/vacations.db` остались byte-identical; их
итоговые SHA-256, integrity/FK и результаты полного gate зафиксированы ниже.

## Финальный gate и артефакты

Автоматический gate на macOS завершён успешно:

- `python3 -W error::ResourceWarning -m unittest discover -s tests -v` —
  **754 теста**, `OK (skipped=8)`, без failure/error/ResourceWarning;
- Python compile и JavaScript `node --check` — PASS;
- module boundaries, frontend contracts и repository-data audit — PASS;
- documentation audit — **218 Markdown-файлов**, current version и локальные
  ссылки проверены;
- headless Chrome smoke — все основные разделы, без Console/HTTP/API 500,
  resource и unhandled ошибок;
- clean-test builder `--dry-run` — PASS, source main/WAL/journal неизменны;
- committed code graph — **254 узла / 527 связей**; внешний непубликуемый
  Codebase Memory snapshot — 7 959 узлов / 34 472 связи,
  `skipped_count=0`, `persistence=false`, repository artifact отсутствует;
- Windows package regression — versioned root, cold import
  `inventory.webapp`, FULL target schema, workspace SQL, локальные ссылки,
  CRLF/no-BOM launcher и atomic/recovery сценарии — PASS.

Три рабочие runtime-БД до и после gate:

| Контур | SHA-256 | Integrity | FK | Sidecars |
|---|---|---|---:|---|
| IXcellerate | `8681f3c34c52d12e665ddae9f9f818a7635c1108aee353baa9fc63830955305b` | `ok` | 0 | отсутствуют |
| Solar | `6eb930442fdc55bf5f460398eaa31afd0d302fc8f8081bc5787c295fca0eb257` | `ok` | 0 | отсутствуют |
| Vacations | `41d226a96110e2233717ae002859f97912bc8b531da29b4f2f2fd083b9e28b4a` | `ok` | 0 | отсутствуют |

Публичный артефакт — `ODE_0.21.1_windows_source.zip`; canonical alias —
`ODE_0.21.1.zip`. Оба архива должны быть byte-identical, иметь один корень
`ODE_0.21.1/`, полный internal `SHA256SUMS.txt` и собственный внешний
`.zip.sha256`. Публичный пакет не содержит `.db`, SQLite sidecars, приватные
Monitoring JSON, секреты и private-transfer README. Закрытый переносимый
артефакт — `ODE_0.21.1_FULL_PRIVATE_WORK_LAPTOP_TRANSFER.zip`; он собирается
отдельно из публичного дерева, SQLite Backup API snapshots и локальных
Monitoring rules, имеет `TRANSFER_MANIFEST.md` и не публикуется в Git/GitHub.

Точные SHA публичного и закрытого ZIP фиксируются соседними внешними
`.zip.sha256` после последней воспроизводимой сборки. Старые архивы 0.21.0
отозваны для повторного переноса.

Физический double-click запуск на целевом Windows остаётся обязательным и не
подменяется проверкой на macOS.

## Участники

- Юра Устинов — Monitoring;
- Никита Боронев — Reports;
- Александр Мерненко — остальные части ODE, интеграция и сопровождение проекта.
