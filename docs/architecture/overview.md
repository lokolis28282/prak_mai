# ODE 0.13 — архитектурный обзор

Статус: **APPROVED — ODE 0.13 architecture baseline**
Решение: модульный монолит на SQLite для локальной складской эксплуатации.

## Назначение

ODE ведет актуальный складской учет оборудования и материалов ЦОД после
утвержденной физической инвентаризации, предоставляет доказуемую историю по
идентификатору и сохраняет происхождение каждого импортированного факта.

ODE не является устройством первичного сканирования. Инженеры выполняют полную
физическую инвентаризацию во внешнем утвержденном XLSX. Оператор ODE загружает
файл, проверяет Preview и утверждает baseline.

## Пользователи и внешние системы

| Участник | Взаимодействие |
|---|---|
| Operator | Preview, разрешение findings, approval, штатные движения |
| Admin | Учетные записи, справочники, корректировки, reversal, backup/restore |
| Auditor | Read-only balance, history и audit |
| Инженер ЦОД | Физически сканирует склад в Excel; не получает общий write-login |
| Approved inventory XLSX | Внешний источник нового физического snapshot |
| Legacy Excel | Неизменяемый источник архивных событий |
| Filesystem storage | Source files, Preview workspace, candidate, backups |
| SQLite | Локальная operational database ODE 0.13 |
| Future DCIM | Потенциальный versioned API consumer/source, вне scope 0.13 |

См. [system context](diagrams/system-context.md).

## Границы доверия

- Browser и загружаемый файл недоверенные.
- API проверяет session, CSRF, Origin/Host, permission и DTO.
- Парсер XLSX работает с лимитами размера, строк, XML и decompression.
- Preview workspace недоверен до повторной проверки hash/digest.
- Operational DB доступна только процессу ODE и operations tooling.
- Source vault и backups доступны только уполномоченному администратору.
- Future DCIM не получает прямого доступа к SQLite.

## Входит в ODE 0.13

- персональные accounts и role-based permissions;
- полный XLSX Preview → Review → Approve;
- immutable snapshots и warehouse ledger;
- синхронная balance projection;
- exact identity search и legacy timeline;
- справочники и catalog;
- resource API v1 и feature-oriented UI;
- audit, backup, restore, candidate publish и rollback;
- migration 0.12 → 0.13 без dual-write.

## Не входит

- Kafka и внешний event broker;
- микросервисы;
- server deployment;
- DCIM synchronization;
- mobile scanner;
- автоматический semantic merge;
- partial snapshot как источник баланса;
- переписывание posted history;
- использование legacy receipts/issues как opening balance.

Kafka локальной ODE 0.13 не нужна: write-процесс один, projection обновляется
синхронно в той же Unit of Work, интеграционных consumers нет. Возможная
будущая интеграция получает outbox/API adapter, не меняя snapshot, ledger и
identity model.

## Источники истины

| Область | Источник истины |
|---|---|
| Физическое состояние на baseline | Active APPROVED InventorySnapshot |
| Изменения после cutoff | Posted immutable WarehouseTransaction ledger |
| Текущий баланс | Snapshot + ledger; projection только производная |
| Текущая идентичность | Equipment и active EquipmentIdentity |
| Старые события | LegacyHistoryEvent и immutable source |
| Справочники | Approved ReferenceValue/CatalogItem |
| Предварительный импорт | Внешний Preview workspace до publish |
| Security actions | Append-only AuditEvent |

До первого APPROVED snapshot состояние баланса — NOT_INITIALIZED, а posting
запрещен.

## Уточнения исходного review

1. S/N не объявляется глобально уникальным: его namespace задается vendor
   scope; raw значение никогда не теряется.
2. Полный пересчет требует posting-freeze. Cutoff фиксируется до физического
   подсчета, а approve проверяет неизменность ledger head.
3. Pre-approval InventorySession хранится во внешнем workspace. Рабочая БД до
   publish не меняется.
4. Partial inventory не может стать baseline в ODE 0.13.
5. Штатный projection имеет lag=0. Shadow rebuild не становится видимым, пока
   не догнан ledger head и не проверен checksum.
6. Legacy source фактически не всегда содержит ФИО. ODE сохраняет raw значение
   и actor quality, но не выдумывает имя.
7. Candidate publish требует одного filesystem volume, закрытых SQLite handles
   и platform-specific atomic replace.
8. Новый snapshot не создает adjustment из reconciliation: он становится новой
   точкой истины, а объяснение расхождений сохраняется отдельно.

## Архитектурные запреты

- универсальный WarehouseCore;
- string-based dispatch и service: Any;
- SQL в UI, API или reports;
- commit внутри repository;
- repository одного bounded context из другого;
- infrastructure imports в domain models;
- startup schema/data migration;
- posted UPDATE/DELETE;
- live DB в Git или release ZIP;
- пустые facade/models-модули.

## Комплект

Границы модулей описаны в [module-boundaries.md](module-boundaries.md),
сущности — в [domain-model.md](domain-model.md), данные — в
[data-model.md](data-model.md), транзакции — в
[transaction-model.md](transaction-model.md).
