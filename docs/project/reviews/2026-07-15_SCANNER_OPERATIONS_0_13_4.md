# Scanner Operations 0.13.4 — Component to Server

Статус: **IMPLEMENTED AND TESTED ON DISPOSABLE DATABASES**

Дата: 2026-07-15. Scope: быстрый интерактивный расход serialized equipment и
компонентов. Рабочая `data/warehouse.db` не использовалась для mutation-тестов.

## Operator workflow

Доступны два режима:

- `Один сервер`: целевой S/N задаётся один раз, после чего оператор сканирует
  список выдаваемых позиций;
- `Пары: компонент → сервер`: скан компонента переводит UI в ожидание сервера,
  скан сервера создаёт готовую пару и возвращает фокус к следующему компоненту.

Задача, дата, инженер и комментарий задаются один раз на пачку. Между сканами
кнопки не требуются. Prompt даёт цветовую обратную связь; звук включается
только при разрешённой browser user activation и не создаёт console warnings.

## Safety contract

- unknown source S/N — blocking error, unmatched operational issue не создаётся;
- source обязан иметь положительный остаток;
- component требует target S/N;
- target обязан существовать как equipment;
- source и target не могут совпадать;
- source S/N не может повторяться в одной пачке;
- максимум 1000 пар;
- все пары проводятся одной SQLite transaction;
- ошибка любой строки откатывает всю пачку;
- каждая issue и batch получают audit events.

Historical CSV/migration import сохраняет собственные soft/problem contracts;
ужесточение относится к interactive scanner confirmation.

## Verification

- focused API contract: valid pair PASS, mixed valid/unknown rollback PASS;
- load test: 100 components → 10 servers, 100/100 posted, sampled balances zero;
- frontend contract and frontend audit PASS;
- headless Chrome: pair mode, prompt transitions, pair confirmation, switch to
  fixed-target mode, unknown blocking, drafts and prior Warehouse scenarios PASS;
- console/window/unhandled/resource/HTTP/API500 errors — zero.
- full discovery: **397 tests, OK (skipped=8)**, без ResourceWarning;
- рабочая БД SHA после gate:
  `73568a1c3eecbd4476473f064620d7f0a196b336ce8ea6d834c5b99359d4b010`;
  `integrity_check=ok`, FK errors/sidecars отсутствуют.

## Boundary

Этот slice доказывает operator UX и strict transaction semantics на текущем
compatibility Warehouse. Он не превращает legacy balance в operational truth.
До FULL inventory рабочее состояние продукта должно получить явный
`NOT_INITIALIZED` gate; фактический balance начнётся от approved snapshot и
последующего immutable ledger.
