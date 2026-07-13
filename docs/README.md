# Техническая документация ODE

Этот каталог содержит актуальные архитектурные контракты текущего исходного
кода ODE Stage 0.13.2 и исторические карты миграции. Runtime-метаданные и
target package builder остаются `0.12.17.1 RC2`, но последний фактически
собранный Windows ZIP содержит `ODE 0.12.17 RC1`; ZIP RC2/Stage 0.13.2 не
создавался. Пользовательские сценарии описаны в корневом `README.md`, запуск
на Windows — в `README_WINDOWS.md`.

## Основные документы

- [Контекст приложения](APPLICATION_CONTEXT.md)
- [Архитектура backend](BACKEND_ARCHITECTURE.md)
- [Модульная архитектура](MODULE_ARCHITECTURE.md)
- [Владение таблицами БД](DATABASE_OWNERSHIP.md)
- [Границы безопасности](SECURITY_BOUNDARIES.md)
- [Контракты frontend](FRONTEND_CONTRACTS.md)
- [Компоненты интерфейса](UI_COMPONENTS.md)
- [Тестовая база и тестовый контур](TEST_DATABASE_GUIDE.md)
- [Ручная проверка 0.12.17.1 RC2](MANUAL_TESTING_0_12_17_1.md)
- [Ручная проверка массового Inventory Number, Stage 0.13.2](MANUAL_TESTING_0_13_2.md)
- [Codebase memory MCP (developer tooling)](CODEBASE_MEMORY_MCP.md)
- [Release Review Stage 0.13.2](../RELEASE_REPORT_ODE_0_13_2.md)

## Предметные модули

- [Складской API](WAREHOUSE_API_MIGRATION.md)
- [Складские события](WAREHOUSE_EVENTS.md)
- [Приход](WAREHOUSE_RECEIPT_ARCHITECTURE.md)
- [Массовое назначение Inventory Number](INVENTORY_NUMBER_IMPORT_ARCHITECTURE.md)
- [Расход](WAREHOUSE_ISSUE_ARCHITECTURE.md)
- [Кабели](WAREHOUSE_CABLE_ARCHITECTURE.md)
- [Импорт поставок](DELIVERY_IMPORT_ARCHITECTURE.md)
- [Приемка поставок](DELIVERY_ACCEPTANCE_ARCHITECTURE.md)
- [Отчеты](REPORTS_ARCHITECTURE.md)
- [Администрирование](ADMINISTRATION_ARCHITECTURE.md)
- [Мониторинг](MONITORING_MODULE_BOUNDARIES.md)

## Карты миграции

Файлы `*_MIGRATION.md` и `*_MIGRATION_PLAN.md` фиксируют переход от legacy-слоя
к модульным фасадам. Они являются технической историей и контрольными списками,
а не пользовательскими инструкциями. План целевой модели данных ODE 0.13
находится в [DATA_MODEL_ODE_013.md](DATA_MODEL_ODE_013.md).

В репозитории нет отдельной OpenAPI/Swagger schema: ODE использует локальный
session-based HTTP API. Для Stage 0.13.2 нормативным описанием endpoints,
request/response и ошибок является
[INVENTORY_NUMBER_IMPORT_ARCHITECTURE.md](INVENTORY_NUMBER_IMPORT_ARCHITECTURE.md),
а исполняемый contract фиксируют API tests.

## Правила актуализации

- изменение пользовательского поведения отражается в `README.md` и
  `CHANGELOG.md`;
- изменение публичного API или границы модуля отражается в соответствующем
  архитектурном документе;
- локальные backup, release-каталоги, экспорты, скриншоты и QA-архивы не
  коммитятся;
- перед публикацией запускаются syntax checks, module/frontend audits, полный
  unittest suite, clean-test-DB dry-run, headless smoke, SQLite checks и
  `git diff --check`;
- commit запрещён, пока code/tests/README/CHANGELOG/API/security/data/event/
  diagram documentation не синхронизированы и не прошли self-review.
