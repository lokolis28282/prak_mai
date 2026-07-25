# QA Stage 0.12.17

Дата прогона: 2026-07-11
Версия: ODE 0.12.17 RC1
Решение: `PASS` для Release Candidate и контролируемого single-node пилота;
`HOLD` для production 1.0 до целевой Windows/load/restore acceptance.

## 1. Контур проверки

- macOS arm64, Python 3.14, SQLite, Node.js, headless Google Chrome;
- unit, contract, API, architecture, frontend contract и UI smoke tests;
- временные SQLite-БД для всех изменяющих и нагрузочных сценариев;
- рабочая `data/warehouse.db` не использовалась для генерации нагрузки и не
  сбрасывалась;
- текущая рабочая БД отдельно проверена через `integrity_check` и
  `foreign_key_check`.

## 2. Итог автоматизации

| Gate | Результат |
|---|---|
| `python3 -W error::ResourceWarning -m unittest discover -s tests -v` | 185 tests, OK |
| `python3 scripts/audit_module_boundaries.py` | OK |
| `python3 scripts/audit_frontend_contracts.py` | OK, отсутствующих DOM id нет |
| `node --check static/js/product.js tests/headless_smoke.js` | OK |
| `python3 scripts/smoke_ui.py` | OK |
| `git diff --check` | OK |
| SQLite `PRAGMA integrity_check` | `ok` |
| SQLite `PRAGMA foreign_key_check` | строк ошибок нет |

## 3. Экраны и навигация

| Область | Проверено | Результат |
|---|---|---|
| Главная | Dashboard, 6 KPI, быстрые действия, последние события | PASS |
| ODE | возврат на Главную из рабочих и admin-разделов | PASS |
| Верхняя навигация | Главная, Склад, Отчеты, Monitoring, admin visibility | PASS |
| Глобальный поиск | exact S/N, hostname mapping, карточка, keyboard panel | PASS |
| Склад | обзор, приход, расход, баланс, поставки, inventory | PASS |
| Проблемы/События | находятся в Склад, фильтр/reset истории | PASS |
| Monitoring | только placeholder, складских действий нет | PASS |
| Карточка | обязательные поля, история, проблемы, export path | PASS |
| Профиль | открытие, обновление данных, смена инженера | PASS |
| Администрирование | отдельный login, реальный `/api/admin`, users/backup/audit | PASS |
| Back/reload | Back закрывает карточку, reload восстанавливает раздел | PASS |
| Mobile 390 px | ODE, профиль и global search видимы, page overflow отсутствует | PASS |

UI smoke завершился со значениями:

```text
noConsoleErrors=true
noWindowErrors=true
noUnhandledRejections=true
noResourceErrors=true
noHttpErrors=true
noApi500=true
```

## 4. Приход, расход и сканер

- ручной и сканерный приход сохраняют складскую позицию;
- повторный S/N блокируется до записи;
- список сканирования сохраняется как browser draft;
- повторный submit подавляется на клиенте, уникальность повторно проверяется БД;
- расход известного оборудования создает allocation;
- неизвестный S/N в разрешенном массовом сценарии попадает в проблемы;
- недостаточный остаток оборудования и кабеля возвращает пользовательскую
  ошибку и не создает отрицательный баланс;
- оборудование нельзя списать само на себя;
- компонент требует целевое оборудование;
- batch validation выполняется до commit, ошибка строки откатывает весь batch.

Результат: PASS.

## 5. Поставки

- UTF-8 BOM, cp1251, `;` и `,`;
- дубли в файле, существующий S/N, пустой S/N и неверное количество;
- preview не создает приход;
- confirm создает документ и строки атомарно;
- повторный confirm token отклоняется;
- preview изолирован по session token;
- один receipt нельзя связать с двумя поставками;
- planned, existing fill-empty, unplanned и batch acceptance;
- accepted line read-only;
- закрытая поставка не принимает новые строки;
- карточка поставки получает summary и страницы по 500 строк.

Результат: PASS.

## 6. CSV, import и export

| Сценарий | Ожидаемое поведение | Результат |
|---|---|---|
| Пустой CSV | 400 с понятной ошибкой | PASS |
| Неверные/неизвестные заголовки | 400, имя обязательного столбца | PASS |
| Поврежденный JSON/CSV request | 400, без traceback | PASS |
| 40 000 строк | preview/confirm в поддерживаемых сценариях | PASS |
| 100 000 строк | контролируемый отказ: лимит 40 000 | PASS |
| Файл больше 50 МБ | отказ до парсинга | PASS |
| UTF-8 BOM / cp1251 | корректный импорт | PASS |
| CSV formula payload | апостроф + корректное quoting | PASS |
| Inventory duplicate S/N | отдельная статистика дублей | PASS |
| Повтор preview confirm | отказ без второй записи | PASS |

Ограничение: 100 000 строк не импортируются одной операцией. Это проверенный
безопасный отказ, а не поддержка такого размера.

## 7. API и ошибочные параметры

- JSON root `null/list/string/number` отклоняется;
- scalar `dict/list/null/bool` и неверная форма nested collection дают 400;
- boolean strings `true/false/on/off/1/0` трактуются однозначно;
- `id=abc`, отрицательные и превышающие limit query parameters дают 400;
- unknown endpoint/action/import kind дают 4xx;
- внутренний exception text не раскрывается;
- штатный E2E-маршрут не получил ни одного 4xx/5xx;
- contract tests не обнаружили HTTP 500 на negative matrices.

Результат: PASS.

## 8. SQLite и атомарность

- `foreign_keys=ON` устанавливается на каждом app connection;
- успешный context commit, исключение rollback, connection закрывается;
- receipt, issue, delivery acceptance, work logs и report imports имеют
  атомарные batch tests;
- foreign key corruption обнаруживается `_database_check`;
- backup проверяется до использования;
- restore и production DB upload создают safety backup и откатываются при
  ошибке;
- существующая схема таблиц не изменена Stage 0.12.17.

Результат: PASS.

## 9. Безопасность

- admin upload/audit недоступны engineer-session;
- engineer service context принудительно ограничен ролью `engineer`;
- начальный admin password допускает только `CHANGE_PASSWORD`;
- login rate limit: 5 ошибок / 5 минут, block 15 минут;
- session inactivity TTL 12 часов, максимум 500 sessions;
- preview owner/session isolation и TTL;
- Host/Origin allowlist для browser POST;
- anti-sniff, frame deny, referrer и permissions headers;
- SQL values параметризованы, подтвержденного SQL injection нет;
- найденный wizard XSS sink исправлен и имеет negative browser assertion.

Остаточные риски перечислены в [SECURITY_REVIEW.md](SECURITY_REVIEW.md).

## 10. Производительность

- измерены 100, 1 000, 10 000, 100 000 и 1 000 000 записей;
- ответ `/api/data` ограничен примерно 2,3 МиБ на 100k и 1M;
- exact S/N: около 8 мс на 100k и 81 мс на 1M в исходном post-limit замере;
- batch 1 000 приходов: около 47 мс;
- batch acceptance 1 000 строк: около 0,85 с;
- категории агрегируются шестью SQLite-группами без Python materialization;
- примеры и counts проблем строятся в общих SQL-проходах.

Миллионный bootstrap ускорен с исходных `9,742 с` до актуальных `7,482 с`, но
по-прежнему не проходит production SLO; ограничения находятся в
[PERFORMANCE_REVIEW.md](PERFORMANCE_REVIEW.md).

## 11. Что не подтверждено этим Stage

- физический запуск релизного ZIP на целевом Windows-ноутбуке;
- работа конкретной модели USB/Bluetooth-сканера;
- Excel-проверка на рабочей корпоративной версии Office;
- 50 одновременных реальных браузеров в целевой сети;
- p95/p99 под смешанной read/write нагрузкой;
- аварийное отключение питания во время commit/restore;
- восстановление внешнего backup на отдельном физическом компьютере;
- TLS/reverse proxy/SSO/MFA и внешний penetration test;
- миллионный production SLO.

## 12. Release decision

`0.12.17 RC1` можно передавать на целевой Windows-компьютер для контролируемой
приемки и ежедневного пилота на одном узле. Метку production 1.0 следует ставить
только после закрытия эксплуатационных пунктов из
[PRODUCT_REVIEW.md](PRODUCT_REVIEW.md).
