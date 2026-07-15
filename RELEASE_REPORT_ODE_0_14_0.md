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

## Security и данные

- production mutations возвращают `WAREHOUSE_NOT_INITIALIZED`;
- demo writes разрешены только для явной disposable DB и заметно маркированы;
- candidate rehearsal — admin-only;
- исходное raw identifier значение не перезаписывается;
- upload ограничен размером, проверяет OOXML traversal/macros/external payload;
- source SHA и reference fingerprint проверяются повторно;
- runtime DB, candidate и credentials не входят в Windows/source package;
- реальный publish отсутствует и не может заменить `data/warehouse.db`.

## Performance evidence

Disposable MacBook benchmark (`scripts/benchmark_full_inventory.py`):

| Rows | Preview | Throughput | Peak RSS |
|---:|---:|---:|---:|
| 1 000 | 0.132 s | 7 594 rows/s | 56 MiB |
| 10 000 | 1.280 s | 7 813 rows/s | 175 MiB |
| 50 000 | 6.695 s | 7 469 rows/s | 708 MiB |

Во всех прогонах session стала `READY_FOR_APPROVAL`, fixture operational DB
осталась byte-identical.

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
- full warning-clean suite — **436 tests PASS, 8 expected skips**;
- focused ODE target suite входит в full gate (60 tests);
- headless Chrome smoke — PASS: receipt/issue/balance/history/search/profile/
  administration/monitoring, console/window/resource/HTTP/API500 errors = 0;
- performance 1k/10k/50k — PASS;
- `git diff --check` — PASS;
- production DB SHA before gate:
  `73568a1c3eecbd4476473f064620d7f0a196b336ce8ea6d834c5b99359d4b010`,
  integrity=ok, FK=0, sidecars=0. Финальная повторная проверка обязательна
  непосредственно перед commit.
