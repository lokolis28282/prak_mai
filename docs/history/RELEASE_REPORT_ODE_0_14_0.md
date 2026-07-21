# ODE 0.14.0 — Full Inventory Safety Release Report

Дата: 2026-07-16. Статус: **SOURCE READY FOR TARGETED OPERATOR REVIEW**.

## Результат

ODE 0.14 переводит текущий импортированный склад в честный режим legacy
history: исторический расчёт можно искать и анализировать, но он не выдаётся
за физический остаток. До initial baseline backend fail-closed блокирует
складские записи.

Реализован законченный внешний контур FULL Inventory:

`NOT_INITIALIZED → session → XLSX → Preview/findings → manual resolutions
→ revalidation → READY_FOR_APPROVAL → disposable baseline rehearsal`.

Raw XLSX и рабочая БД не изменяются. Resolution evidence append-only, actor и
reason обязательны, старые runs сохраняются. Candidate строится на approved
target DDL V001..V008 и доказывает snapshot/projection equivalence.

Follow-up этой же версии добавляет изолированный Monitoring hostname routing:
локальные Tech/Digital rules определяют Salt/Digital/X5Tech и подготовленные
адресаты через `MonitoringFacade`. Operator UI, collectors и email transport
не включены; внутренние rules не публикуются в GitHub.

## Security и данные

- production mutations возвращают `WAREHOUSE_NOT_INITIALIZED`;
- demo writes разрешены только для явной disposable DB и заметно маркированы;
- candidate rehearsal — admin-only;
- исходное raw identifier значение не перезаписывается;
- upload ограничен размером, проверяет OOXML traversal/macros/external payload;
- source SHA проверяется до и после потокового Preview, существующий vault
  object повторно хешируется; reference index и fingerprint читаются одним
  согласованным snapshot;
- stale/double-submit Preview/resolution requests закрыты транзакционным
  `BEGIN IMMEDIATE`, отмена работающего Preview запрещена;
- candidate path не может быть symlink, SHA candidate считается потоково;
- runtime DB, candidate и credentials не входят в Windows/source package;
- реальный publish отсутствует и не может заменить `data/warehouse.db`.

## Performance evidence

Disposable MacBook benchmark (`scripts/benchmark_full_inventory.py`):

| Rows | Preview | Throughput | Peak RSS |
|---:|---:|---:|---:|
| 1 000 | 0.130 s | 7 673 rows/s | 41 MiB |
| 10 000 | 1.295 s | 7 723 rows/s | 49 MiB |
| 50 000 | 6.448 s | 7 755 rows/s | 69 MiB |

Каждый Preview выполнялся в отдельном subprocess после отдельной генерации
XLSX, поэтому RSS не включает synthetic writer и предыдущие размеры. Во всех
прогонах session стала `READY_FOR_APPROVAL`, fixture operational DB осталась
byte-identical.

## Ограничения / stop conditions

- реальный approval/publish/cutover feature-disabled;
- автоматическое Catalog/Model matching запрещено;
- target Equipment Query Port отсутствует, поэтому
  `LINK_EXISTING_EQUIPMENT` не применяется;
- candidate rehearsal требует явных per-row Catalog/Equipment decisions и
  предназначен для небольшого acceptance input, не для ручного кликанья 50k;
- correction/reversal для будущих posted операций остаётся отдельной задачей;
- серверный multi-user deployment, backup rotation и Windows acceptance не
  реализованы;
- новый Windows ZIP не создавался; последний физический ZIP — 0.12.17 RC1.

## Verification gate

- Python/JavaScript syntax — PASS;
- module boundaries — PASS, включая restricted rehearsal bridge;
- frontend contracts — PASS;
- clean-test DB dry-run — PASS, source SHA unchanged;
- full warning-clean suite — **464 tests PASS, 8 expected skips**;
- focused Monitoring routing/generator suite — **20 tests PASS**; 33 локальных
  Tech rules и 530 Digital hostname проходят runtime validation;
- focused ODE target suite входит в full gate (60 tests);
- headless Chrome smoke — PASS: receipt/issue/balance/history/search/profile/
  administration/monitoring, console/window/resource/HTTP/API500 errors = 0;
- performance 1k/10k/50k — PASS;
- `git diff --check` — PASS;
- production DB SHA before gate:
  `73568a1c3eecbd4476473f064620d7f0a196b336ce8ea6d834c5b99359d4b010`,
  integrity=ok, FK=0, sidecars=0. Финальная повторная проверка обязательна
  непосредственно перед commit.
