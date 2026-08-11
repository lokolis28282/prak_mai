# Матрица функций ODE 0.21.0

Актуализировано: 2026-08-11. Это living-карта текущего runtime: где находится
функция, через какую границу она работает, чем хранится и как проверяется.

Обозначения: **write** — меняет только принадлежащую модулю БД; **read** — не
меняет business data; **fail-closed** — действие намеренно недоступно.

## Запуск, сессия и навигация

| Функция | Runtime-граница | Данные/эффект | Проверка |
|---|---|---|---|
| `python app.py` | `app.py → inventory.webapp` | Подключает IXcellerate, Solar и Vacations | startup/unit/headless smoke |
| Вход инженера и администратора | session + backend permission | Session; audit в primary DB | auth/security tests |
| Главная и карточки модулей | внешний HTML + `static/js` | Только навигация | frontend audit + Chrome |
| Выбор IXcellerate/Solar | `ApplicationContext → WarehouseFacade` | Site хранится в session, DB физически раздельны | multi-warehouse tests + Chrome |
| Глобальный поиск | `/api/search` | read по оборудованию, поставкам и инженерам | API/unit/headless |

## Warehouse

| Экран/функция | API/фасад | Владелец данных | Статус и доказательство |
|---|---|---|---|
| Приход: ручной, scanner, CSV | Warehouse routes/facade | выбранная Warehouse DB, `stock_receipts` | write; Preview/Confirm, transaction tests, Chrome |
| Расход: scanner, balance, CSV | Warehouse routes/facade | `stock_issues`, `stock_issue_allocations` | write; S/N-state и rollback tests, Chrome |
| Кабель FIFO | WarehouseFacade | receipts/issues/allocations | write; FIFO/unit tests |
| Баланс и ленивое дерево | `/api/warehouse-stock-tree` | read projection Warehouse | read; tree/API/headless |
| Поставки | delivery routes/facade | `deliveries`, `delivery_lines`, receipts | write; Preview/Confirm tests |
| Инвентаризация по S/N | WarehouseFacade | read projection | read; reconciliation tests |
| Inventory Number import | preview token + confirm | карточка по S/N | write одной транзакцией; contract/headless |
| Reference Data | WarehouseFacade → ReferenceDataService | `reference_*_v2` | admin write; alias/rename tests |
| Equipment Card/Timeline | WarehouseFacade | read по receipts/issues/audit | read; card/timeline tests |
| Состав целевой железки | `/api/position-card` → WarehouseFacade | подтверждённые issue/allocations | read; API/service/UI/headless |

Состав оборудования не заявляет точный физический слот, заводскую
комплектацию или текущее присутствие компонента без обратной операции. Схемы
«перед/зад» — обзорная группировка, а доказательство — строка расхода, дата,
задача/ИЗМ, инженер и S/N компонента.

## Отдельные модули

| Модуль | Рабочие функции | Storage boundary | Проверка |
|---|---|---|---|
| Reports | work logs, PNR checklist, shift KPI/CRUD, передача backlog, server filters/page 25, XLSX + legacy CSV read aliases | reporting tables primary DB; Warehouse events только через reader | reports/API/XLSX/unit/headless |
| Monitoring | ручной hostname/DCIM поиск, очистка вставленного hostname, routing по hostname/project/ИС, ITSM/criticality и шаблон Rooms/письма, optional collector | local ignored JSON config; без Warehouse/Reports storage и imports | boundary/routing/parser/API/frontend/headless без live DCIM |
| Knowledge | статьи, теги, private attachments | `knowledge_*` и private attachment root | permissions/upload/headless |
| Vacations | roster, requests, календарь, конфликты, history/audit | только `data/vacations.db` | facade/API/rules/headless |
| Administration | users, roles, audit, diagnostics, topology, backup | primary admin tables + внешний backup root | permission/backup/headless |

## Administration backup/restore

| Действие | Состояние |
|---|---|
| Показать health трёх runtime-БД | read, реализовано |
| Создать snapshot выбранной allowlisted DB | write во внешний каталог через SQLite Backup API, реализовано |
| Проверить size/SHA/integrity/FK и manifest | реализовано |
| Restore из UI/API | **fail-closed**, до ADR-013 не реализовано |
| Автоматическое расписание/ротация/шифрование | не реализовано |

## Кнопочный контракт

Статические элементы проверяются `scripts/audit_frontend_contracts.py`,
серверные действия — API/permission tests, пользовательские цепочки —
`scripts/smoke_ui.py` в headless Chrome. Smoke обязан открыть и использовать:

- вход, выход, профиль и возврат на главную;
- обе площадки Warehouse и семь складских разделов;
- поиск, баланс, карточку и состав оборудования;
- Preview/Confirm сценарии прихода, расхода, поставки и Inventory Number только
  на disposable DB;
- Reports, Monitoring, Knowledge, Vacations и Administration;
- Reports create/edit/delete/viewer, PNR checklist, handover, filters,
  pagination, bulk section и корректные XLSX downloads;
- диагностику и создание backup только во временный внешний каталог.

Деструктивные/подтверждающие кнопки нельзя «тыкать» на рабочих БД. Реальный
контур проверяется read-only: запуск, вход, навигация, поиск, карточки, отчёты и
состояние модулей; после smoke SHA-256 всех трёх DB обязан совпасть.

## Не являются текущей функцией

- restore из браузера;
- корректировка/сторно проведённой складской операции;
- точная slot/rack topology установленного компонента;
- серверный многопользовательский deployment;
- физически подтверждённый Windows rollout 0.21.0;
- transport-интеграции email/Rooms/Kaiten.
