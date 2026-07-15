# ADR-001: Модульный монолит

Статус: **APPROVED**

## Context

ODE использует один локальный writer, SQLite и общие атомарные инварианты
snapshot/ledger/projection. Текущий string-dispatch WarehouseCore не создает
реальных границ.

## Decision

ODE 0.13 — modular monolith с typed ports, bounded contexts и общей Unit of
Work для cross-context command. Infrastructure реализует ports; domain ее не
импортирует. Внутренние события синхронны.

## Alternatives

- микросервисы с отдельными DB;
- service-oriented monolith без enforced boundaries;
- оставить WarehouseCore.

## Consequences

Простая атомарность и deployment; CI обязан запрещать cycles, SQL вне adapters,
string dispatch и service locator.

## Rejected options

Микросервисы/Kafka отклонены: нет независимого deployment/scale и потребуется
distributed consistency. WarehouseCore отклонен как неконтролируемая связь.

## Migration impact

Новая реализация строится side-by-side; compatibility layer не становится
частью target schema.

## Security impact

Одна authorization boundary и одна audit transaction; module ports не обходят
permission checks.

## Performance impact

Нет network hops; один writer соответствует SQLite profile.

## Rollback impact

Rollback переключает целый old/new application+DB set.

## Approval status

Утверждено как часть ODE 0.13 architecture baseline. DDL blocker: нет.
