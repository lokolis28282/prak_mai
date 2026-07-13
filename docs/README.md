# Техническая документация ODE

Этот каталог содержит актуальные архитектурные контракты и карты миграции ODE
0.12.17.1 RC2. Пользовательский запуск и рабочие сценарии описаны в корневом
`README.md`, запуск на Windows - в `README_WINDOWS.md`.

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
- [Codebase memory MCP (developer tooling)](CODEBASE_MEMORY_MCP.md)

## Предметные модули

- [Складской API](WAREHOUSE_API_MIGRATION.md)
- [Складские события](WAREHOUSE_EVENTS.md)
- [Приход](WAREHOUSE_RECEIPT_ARCHITECTURE.md)
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

## Правила актуализации

- изменение пользовательского поведения отражается в `README.md` и
  `CHANGELOG.md`;
- изменение публичного API или границы модуля отражается в соответствующем
  архитектурном документе;
- локальные backup, release-каталоги, экспорты, скриншоты и QA-архивы не
  коммитятся;
- перед публикацией запускаются `python3 -m unittest discover -s tests` и
  `python3 scripts/audit_module_boundaries.py`.
