# ADR-014 — Warehouse correction and reversal contract

Статус: **PROPOSED**
Дата: 2026-07-27

## Context

Ошибочно проведённый приход/расход нельзя исправлять удалением исходной записи:
это разрушает audit/history, баланс и FIFO allocations. Correction/reversal не
входит в ODE 0.18.1 multi-DB backup change.

## Decision

Будущий Warehouse workflow обязан:

1. сохранять исходный приход/расход неизменным;
2. создавать отдельное компенсирующее событие со ссылкой на original event;
3. иметь read-only Preview до любой записи;
4. требовать явный Confirm, authenticated actor и непустой reason;
5. пересчитывать balance только проведёнными ledger events;
6. для расхода строить детерминированный reverse-allocation plan, не изменяя
   исторические FIFO allocations in place;
7. блокировать reversal, если более поздние события делают компенсацию
   неоднозначной или дают отрицательный/несогласованный остаток;
8. писать audit с ids/quantity/reason, но не дублировать S/N/ФИО в технические
   логи;
9. поддерживать повторный reversal только как новую компенсирующую операцию,
   никогда как delete/update предыдущей;
10. иметь отдельный whole-DB rollback contract и проверенный backup до
    migration/cutover, но не создавать backup на каждую обычную correction.

## Required tests

- Preview не меняет БД;
- Confirm одной транзакцией;
- insufficient/later-consumed balance blocked;
- FIFO allocation graph preserved;
- double submit idempotent или явно blocked;
- viewer denied, actor/reason/audit обязательны;
- failure rolls back all rows;
- reports, position Timeline and exports show original plus compensation;
- working production DB никогда не используется в mutation tests.

## Consequences

До отдельной реализации UI не должен обещать сторно. Текущие fill-empty и
duplicate-data-quality операции не считаются ledger correction/reversal.
