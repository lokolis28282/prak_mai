# Target ODE 0.13 Architecture Documentation

Статус комплекта ODE 0.13: **APPROVED architecture; Stage 0.13.1 REVIEW_READY**.
Нормативная дата комплекта: 2026-07-15.

Этот файл — индекс target ODE 0.13 architecture track. Текущее состояние всего
repository, включая рабочий Warehouse source/runtime track, находится в
[`project/README.md`](project/README.md). Архитектурный baseline утверждён;
реализация Platform Stage 0.13.1 ожидает финальный post-fix independent review.
Остальные Platform Stage не считаются реализованными или разрешёнными
автоматически.

## Порядок чтения ODE 0.13

1. [Архитектурный обзор](architecture/overview.md)
2. [Границы модулей](architecture/module-boundaries.md)
3. [Доменная модель](architecture/domain-model.md)
4. [Логическая модель данных](architecture/data-model.md)
5. [Жизненный цикл инвентаризации](architecture/inventory-lifecycle.md)
6. [Импорт, Preview и Publish](architecture/import-preview-publish.md)
7. [Складской ledger](architecture/warehouse-ledger.md)
8. [Проекция баланса](architecture/balance-projection.md)
9. [Транзакционная модель](architecture/transaction-model.md)
10. [Справочники и catalog](architecture/references-catalog.md)
11. [API](architecture/api-contract.md), [UI](architecture/ui-contract.md),
    [безопасность](architecture/security.md) и
    [производительность](architecture/performance.md)
12. [Стратегия миграции](migration/0.12-to-0.13-strategy.md)
13. [Открытые решения](architecture/OPEN_DECISIONS.md)
14. [Versioned DDL review artifacts](architecture/ddl/README.md) и
    [field-level migration mapping](migration/source-to-target-field-mapping.md)

Результат независимой внутренней проверки:
[SELF_REVIEW.md](architecture/SELF_REVIEW.md).

Диаграммы находятся в [architecture/diagrams](architecture/diagrams/).
Утверждённые архитектурные решения находятся в [decisions](decisions/),
включая cutoff, FULL/PARTIAL и projection ADR-010..012.

## Нормативность

При конфликте документов применяется следующий приоритет:

1. утвержденные бизнес-инварианты в [overview.md](architecture/overview.md);
2. ADR в [decisions](decisions/);
3. профильный архитектурный контракт;
4. migration и operations runbooks;
5. исходный review;
6. документы ODE 0.12 и stage-specific документы.

Термины MUST, MUST NOT, SHOULD и MAY означают обязательное требование,
запрет, рекомендуемое решение и допустимую опцию.

## Исходная ревизия

[ODE 0.13 Architecture Review](architecture/ODE_0_13_ARCHITECTURE_REVIEW.md)
сохранена как доказательная ревизия текущего состояния. Она не является
самостоятельной спецификацией реализации. Уникальные факты из нее разнесены по
профильным документам; найденные уточнения перечислены в
[overview.md](architecture/overview.md#уточнения-исходного-review).

## Migration и разработка

- [Стратегия 0.12 → 0.13](migration/0.12-to-0.13-strategy.md)
- [Source-to-target mapping](migration/source-to-target-mapping.md)
- [Legacy mapping](migration/legacy-history-mapping.md)
- [Verification gates](migration/verification-gates.md)
- [Rollback](migration/rollback-plan.md)
- [Порядок реализации](development/implementation-order.md)
- [Stage 0.13.1 foundation evidence](development/STAGE_0_13_1.md)
- [Cleanup plan](development/cleanup-plan.md)
- [Стандарты кода](development/coding-standards.md)
- [Стратегия тестирования](development/testing-strategy.md)
- [Documentation gate](development/documentation-gate.md)

## Operations

- [Жизненный цикл БД](operations/database-lifecycle.md)
- [Backup и restore](operations/backup-restore.md)
- [Разделение релиза и данных](operations/release-data-separation.md)

## Существующие документы ODE 0.12

Все остальные Markdown-файлы в корне и docs/ описывают текущий код, отдельные
stage, review или миграционные эксперименты. До cutover они сохранены на месте,
но **не являются целевой спецификацией ODE 0.13**. Их точная дальнейшая судьба
описана в [cleanup-plan.md](development/cleanup-plan.md). Документ нельзя
архивировать или удалить, пока его уникальная информация не перенесена и не
проверена.

## Статусы документов

- **PROPOSED** — спроектировано, но не разрешено к реализации;
- **APPROVED** — архитектурно утверждено;
- **IMPLEMENTED** — подтверждено кодом и тестами;
- **OPERATING** — подтверждено production/runbook-процедурой;
- **ARCHIVED** — исторический материал, не нормативный;
- **OPEN** — требуется решение из OPEN_DECISIONS.

Фактический статус указан в каждом документе; Stage implementation status не
изменяет утверждённый ADR/DDL contract и не разрешает следующий Stage.
