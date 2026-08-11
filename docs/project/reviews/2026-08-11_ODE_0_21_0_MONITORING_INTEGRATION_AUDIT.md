# ODE 0.21.0 — Monitoring integration audit

Дата: 2026-08-11
Исходный commit: `26a48a1`
Вердикт: **PASS локального release gate; Windows sign-off pending**

## Scope

Проверяется выборочный перенос Monitoring-кода коллеги, защита корпоративных
данных, документация 0.21.0, ручной UI smoke без запуска live DCIM и два ZIP:
public source без runtime data и private transfer с ignored Monitoring rules,
но без SQLite.

## Data boundary

Исходные SHA-256 рабочих БД:

- IXcellerate: `8681f3c34c52d12e665ddae9f9f818a7635c1108aee353baa9fc63830955305b`;
- Solar: `6eb930442fdc55bf5f460398eaa31afd0d302fc8f8081bc5787c295fca0eb257`;
- Vacations: `41d226a96110e2233717ae002859f97912bc8b531da29b4f2f2fd083b9e28b4a`.

Все три исходно: `PRAGMA integrity_check=ok`, `foreign_key_check` пуст.

## Verification

- Python compile — PASS;
- JavaScript syntax — PASS;
- module/frontend/repository-data/documentation audits — PASS;
- current code graph — `252 nodes / 512 edges`, PASS;
- Codebase Memory refresh — `7 727 nodes / 33 325 edges`,
  `skipped_count=0`, `persistence=false`;
- warning-clean unittest discover — `703 tests`, `OK (skipped=8)`;
- targeted Monitoring/API/frontend/generator contracts — PASS;
- `scripts/create_clean_test_db.py --dry-run` — PASS, production source SHA
  unchanged;
- headless Chrome smoke — PASS по Warehouse, Reports, Monitoring, Knowledge,
  Profile, Administration, Vacations, search; console/window/unhandled/
  resource/HTTP/API500 errors — 0;
- local Monitoring rule corpus — schema PASS, `278/278` non-regex rules routed
  однозначно, ambiguous/unmatched/error — 0;
- `git diff --check` и final data-boundary scan — PASS.

## Manual UI

На disposable demo DB вручную проверены вход, главная, IXcellerate overview,
навигация Warehouse, Reports, Knowledge, Vacations, Profile и глобальный поиск.
В Monitoring открыта ручная форма; ввод ` MSK-DPRO- ESX158<Tab>` нормализован
до `MSK-DPRO-ESX158`. Кнопка запуска сбора не нажималась, live DCIM и ping не
выполнялись. Browser console warnings/errors — 0.

## Package verification

Public source:

- `release/ODE_0.21.0_windows_source.zip`;
- 413 файлов, Monitoring JSON — 0, DB-like files — 0.

Private Monitoring transfer (только корпоративный канал):

- `release/ODE_0.21.0_PRIVATE_MONITORING_TRANSFER.zip`;
- 416 файлов, ровно два Monitoring JSON, DB-like files — 0.

Оба архива прошли `unzip -t` и внутренний `SHA256SUMS.txt`. Персональные source
paths и одноразовый corporate generator отсутствуют. Финальные внешние SHA-256
хранятся в sidecar-файлах рядом с ZIP и в корневом release report, потому что
архив не может содержать собственный хэш без изменения этого хэша.

## Final runtime data evidence

Финальные SHA трёх рабочих БД совпадают с исходными. Для каждой
`integrity_check=ok`, `foreign_key_check` пуст, production sidecars отсутствуют.
Локальные правила Monitoring имеют SHA:

- Digital: `f1b2eb57fe72138c3ebe7fc5d464de6f9578be9f4b5edb47b95995363b9437c7`;
- Tech: `9ad7ac30dea080015661cf38a5879cad488eb62a65700f8dacee85a7c802de9e`.

Правила остаются ignored/local и не входят в Git. Физическая приёмка private
ZIP и разрешённый live DCIM scenario выполняются только на рабочем Windows-
ноутбуке.
