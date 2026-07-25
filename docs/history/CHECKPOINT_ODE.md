# CHECKPOINT ODE 0.12.17.1 RC2

Контроль сохранности рабочей SQLite-базы во время финальной проверки RC2.
Этот файл фиксирует существующую рабочую базу, а не эталон из Git: в ней есть
пользовательские операции, появившиеся после текущего `HEAD`, поэтому заменять
её версией из репозитория нельзя.

## До финального gate

- проверено: `2026-07-13 09:49:24 +0300`;
- путь: `data/warehouse.db`;
- размер: `245760` байт;
- mtime: `2026-07-11 22:27:27 +0300`;
- SHA-256: `8e727bded75ad17bdd149f3e483fef8ea93ee649f8769fefa3f92c981079c99c`;
- `PRAGMA integrity_check`: `ok`;
- `PRAGMA foreign_key_check`: ошибок нет;
- SQLite sidecar (`-wal`, `-journal`): отсутствуют.

Контрольные количества строк:

| Таблица | Строк |
|---|---:|
| `stock_receipts` | 23 |
| `stock_issues` | 0 |
| `stock_issue_allocations` | 0 |
| `deliveries` | 1 |
| `delivery_lines` | 1 |
| `work_logs` | 0 |
| `audit_log` | 46 |
| `users` | 1 |
| `categories` | 6 |
| `locations` | 4 |
| `reference_values` | 56 |

## После финального gate

- проверено: `2026-07-13 09:55:16 +0300`;
- SHA-256: `8e727bded75ad17bdd149f3e483fef8ea93ee649f8769fefa3f92c981079c99c`;
- `PRAGMA integrity_check`: `ok`;
- `PRAGMA foreign_key_check`: ошибок нет;
- SQLite sidecar (`-wal`, `-journal`): отсутствуют;
- все контрольные количества строк совпадают с разделом «До финального gate».

Пройденный gate:

- 206 unit/contract/API тестов с `ResourceWarning` как error — `OK`;
- module-boundary audit — `OK`;
- frontend DOM contract audit — `OK`;
- Python и JavaScript syntax — `OK`;
- headless Chrome E2E — `OK`;
- реальная сборка `warehouse_test_clean.db` с profile `demo` — `OK`;
- console/window/unhandled/resource/HTTP/API 500 errors — `0`;
- `git diff --check` — `OK`.

Рабочая БД во время проверки не изменилась.
