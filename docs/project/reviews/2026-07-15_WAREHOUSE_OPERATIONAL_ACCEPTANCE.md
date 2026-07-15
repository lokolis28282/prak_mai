# Warehouse Operational Acceptance — Stabilization Gate

Статус: **PASS — LOCAL STABILIZATION GATE COMPLETE**

Дата: 2026-07-15. Scope: активный Warehouse runtime на временной byte-copy
`data/warehouse.db`. Monitoring и Reports не принимались и остаются
placeholder-направлениями.

## Data safety

- Рабочая `data/warehouse.db` не использовалась для mutation-тестов.
- Все receipt/issue/inventory-number операции выполнялись на disposable DB в
  `/private/tmp` либо внутри `scripts/smoke_ui.py`.
- Контрольный SHA рабочей БД:
  `73568a1c3eecbd4476473f064620d7f0a196b336ce8ea6d834c5b99359d4b010`.
- Финальный read-only/immutable check: `PRAGMA integrity_check` — `ok`,
  `foreign_key_check` — пусто; `warehouse.db-wal`/`-journal` отсутствуют.
- SHA после всех проверок совпадает с контрольным значением выше.

## Найденные и закрытые defects

### 1. Hidden elements оставались видимыми

Компонентные правила `.button`, `.form` и `.ux-form` с собственным `display`
перекрывали browser user-agent rule для HTML `hidden`. В результате инженер
видел вход в Administration, а сценарий прихода показывал несколько форм
одновременно, хотя JS корректно устанавливал `.hidden=true`.

Исправление: runtime CSS получил глобальный контракт
`[hidden]{display:none!important}`. Backend role checks не менялись и остаются
обязательным вторым слоем защиты.

### 2. Placeholder справочника дублировался

`Не указан` одновременно добавлялся как placeholder и canonical supplier
value. Общий `setOptions` и receipt wizard теперь удаляют пустые значения,
дубликаты и значение, равное placeholder label.

### 3. Нулевой остаток можно было выбрать для списания

Legacy balance renderer отключал кнопку «Списать» при `balance <= 0`, а новый
component renderer потерял этот guard. Guard восстановлен. Backend по-прежнему
проверяет остаток внутри транзакции.

## Operator scenarios

На disposable DB подтверждены:

- engineer login и отсутствие видимого Administration;
- Warehouse overview и reference-driven controls;
- ручной сценарий показывает только одну выбранную форму;
- scanner receipt, удаление/повторное добавление строк, draft restore и confirm;
- scanner issue, unknown S/N handling, draft restore и confirm;
- balance, exact S/N search, Equipment Card и Timeline;
- single и CSV Inventory Number assignment через Preview/Confirm;
- disabled issue action при нулевом остатке и enabled action при положительном;
- admin login, users, backups, audit, reference editor и profile;
- Monitoring/Reports placeholder boundaries;
- console error, `window.onerror`, unhandled rejection, resource error,
  HTTP error и API 500 — по нулям.

## Automated gate

- `python3 -W error::ResourceWarning -m unittest discover -s tests -v` —
  **394 tests, OK, skipped=8**, без ResourceWarning. Skip относятся к удалённым
  ignored full/pilot candidate DB и не к runtime Warehouse.
- `python3 scripts/smoke_ui.py` — **PASS** со всеми visited flags `true`,
  `issueBalances=[0,1,0]`, без console/window/resource/HTTP/API500 errors.
- Python compilation — PASS.
- JavaScript syntax — PASS.
- module-boundary audit — PASS.
- frontend-contract audit — PASS.
- clean-test-DB dry-run — PASS.
- `git diff --check` — PASS.

## Verdict and next gate

Warehouse признан готовым к финальному owner walkthrough как локальная
однопользовательская складская система. Это не разрешение на server deployment
и не release verdict. До серверного контура остаются correction/reversal
business contract, backup/restore drill, single-writer/process ownership,
secrets/bootstrap policy и отдельный deployment runbook.
