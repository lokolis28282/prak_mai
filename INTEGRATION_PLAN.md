# План интеграции Monitoring и Knowledge Base

Дата: 2026-07-17  
Рабочая ветка: `feature/integrate-monitoring-knowledge-base`  
Целевой проект: `E:\prak_mai_integrated`  
Источник функциональности: `E:\ODE v0.2\prak_mai-main` (только чтение)

## 1. Архитектура проектов

### prak_mai

- Python 3.11, стандартная библиотека, `ThreadingHTTPServer`, SQLite.
- Точка входа: `app.py`, HTTP/API: `inventory/webapp.py`.
- Контексты приложения соединяются через `ApplicationContext` и фасады
  `WarehouseFacade`, `ReportsFacade`, `MonitoringFacade`,
  `AdministrationFacade`.
- Основной runtime пока использует `inventory/db.py` и идемпотентную
  инициализацию схемы. Параллельный пакет `ode/db` относится к следующему
  архитектурному контуру и не должен смешиваться с текущей рабочей БД.
- Frontend: внешние vanilla-JS модули в `static/js`, единый API-клиент,
  навигация через History API/hash, общие компоненты и уведомления.
- Авторизация: серверные сессии; роли `admin`, `engineer`, `viewer`.

### ODE v0.2

- Основан на более раннем коммите того же продукта и использует тот же стек.
- Monitoring добавляет ручной pipeline: hostname и Zabbix problem -> DCIM
  через Selenium/Microsoft Edge -> management IP -> ping -> классификация ->
  Rooms message -> маршрутизация адресатов -> подготовленный текст письма.
- Knowledge Base реализован отдельными facade/repository/models/Markdown
  модулями, двумя SQLite-таблицами, API и SPA-интерфейсом.
- Вложения хранятся вне public/static, в БД остаются безопасные метаданные и
  относительный путь.

## 2. Технологические различия

- Целевой `main` новее источника: навигация, Warehouse и архитектурные gates
  нельзя заменять файлами ODE v0.2 целиком.
- В целевом проекте Monitoring уже имеет безопасное hostname-routing ядро,
  которого нет в старом `MonitoringFacade` источника. Ручной сбор должен быть
  добавлен поверх текущего ядра.
- Selenium отсутствует в базовых зависимостях. Он останется опциональной
  зависимостью Monitoring, загружаемой только при живом DCIM-сборе.
- Knowledge source не имеет поиска, тегов, пагинации, редактирования и
  удаления. Эти функции будут добавлены в рамках существующего фасада и API,
  без отдельного frontend/backend стека.
- Целевой репозиторий содержит строгий будущий migration contour `ode/db`.
  Knowledge относится к текущему `inventory` runtime и получает отдельную
  идемпотентную runtime-миграцию, не меняя offline manifests ODE 0.13.

## 3. Переносимые компоненты

### Monitoring

- parser и классификаторы из `inventory/monitoring/manual_search.py`;
- Selenium/Edge DCIM collector как изолированный adapter;
- ping и формирование результата;
- текущее безопасное `hostname_routing.py` целевого проекта;
- authenticated API `/api/monitoring/status` и
  `/api/monitoring/manual-search`;
- ручная форма, результат, копирование Rooms/email и локальная история;
- адаптивные карточки и состояния загрузки/ошибки.

### Knowledge Base

- `inventory/knowledge/{models,markdown,repository,facade}.py`;
- статьи, категории, теги, поиск, пагинация;
- создание, редактирование и мягкое удаление;
- безопасные вложения и authenticated download;
- SPA hub, списки, фильтры, карточка, create/edit forms;
- таблицы `knowledge_articles`, `knowledge_attachments`,
  `knowledge_article_tags` и индексы;
- аудит create/update/delete/attachment.

## 4. Изменения frontend

- Добавить `knowledge` в общую навигацию и на главную страницу.
- Заменить placeholder Monitoring на компактный operational launcher.
- Подключить `static/js/knowledge/index.js` через фактический список внешних
  скриптов `webapp._externalized_html()`.
- Сохранить единый `request`, `notify`, `renderElement`, button/form/table
  helpers, без второго API-клиента и второй системы ошибок.
- Добавить History API/hash routes для прямого открытия и reload.
- Добавить responsive CSS без копирования старой глобальной темы.

## 5. Изменения backend

- Расширить текущий `MonitoringFacade`, не возвращаться к legacy
  `WarehouseService.manual_problem_search`.
- Ввести конфигурацию Monitoring через `os.environ` и передавать её в facade.
- Добавить KnowledgeFacade в `ApplicationContext`.
- Добавить authenticated GET/POST/PUT/DELETE endpoints Knowledge.
- Ограничить размеры JSON и файлов, возвращать типизированные русские ошибки.
- Не использовать прямой SQL из web handler.

## 6. Изменения базы данных

- `knowledge_articles`: content, category, автор, timestamps, active flag.
- `knowledge_attachments`: UUID stored name, MIME, size, relative path.
- `knowledge_article_tags`: нормализованные теги с уникальностью на статью.
- Индексы для category/updated/title, tags и attachment lookup.
- Идемпотентный скрипт `scripts/migrate_knowledge_base.py`.
- Monitoring не получает таблиц: история исходного раздела хранится локально
  в браузере и не является общей операционной истиной.

## 7. Новые зависимости

- Обязательных Python-зависимостей нет.
- Для живого DCIM-сбора опционально: `selenium>=4.18,<5` и установленный
  Microsoft Edge. Это будет вынесено в `requirements-monitoring.txt`.
- Development/mock не включается автоматически и не выдаётся за реальные
  данные.

## 8. Конфигурация

- `ODE_MONITORING_DCIM_BASE_URL`;
- `ODE_MONITORING_RULES_DIR`;
- `ODE_MONITORING_EDGE_PROFILE_DIR`;
- `ODE_MONITORING_HEADLESS`;
- `ODE_MONITORING_COLLECT_DCIM`;
- `ODE_MONITORING_DEV_MOCK` (только явный development mode);
- `ODE_KNOWLEDGE_UPLOAD_DIR`;
- `ODE_KNOWLEDGE_MAX_ATTACHMENT_MB`.

Значения документируются в `.env.example`; приложение читает переменные ОС и
не загружает реальный `.env` автоматически.

## 9. Авторизация и права

- Все Monitoring и Knowledge endpoints требуют действующей сессии.
- Monitoring manual search доступен `admin`, `engineer`, `viewer` как
  read/diagnostic operation; отправки письма не происходит.
- Knowledge read доступен всем авторизованным ролям.
- Knowledge create/update/delete/attachment доступны только `admin` и
  `engineer`; серверная проверка обязательна и не зависит от UI.

## 10. Возможные конфликты

- Старый `static/js/product.js` нельзя копировать целиком: он откатит новый
  portal/navigation target.
- Старый `MonitoringFacade` нельзя копировать: он удалит hostname routing.
- Нельзя копировать `data/monitoring/*.json`: они содержат внутренние hostname
  и адресатов и уже исключены из Git.
- Нельзя копировать Edge profile, cookies, `.env`, рабочую БД или вложения.
- В Windows checkout baseline выявлены line-ending checksum и POSIX-mode test
  failures; они учитываются отдельно от integration gates.

## 11. Риски

- DCIM markup может измениться; collector обязан выдавать понятную ошибку и
  закрывать WebDriver в `finally`.
- Долгий Selenium request выполняется в отдельном HTTP worker thread, но пока
  не является фоновой задачей. Для серверного deployment понадобится очередь.
- Внутренние routing JSON отсутствуют в публичном клоне; без настроенного
  каталога письмо остаётся неготовым с явным предупреждением.
- SQLite full-text search не вводится; для текущих объёмов используется
  параметризованный `LIKE`. При росте потребуется FTS5 и cursor pagination.
- Soft delete статьи сохраняет attachment bytes для аудита; отдельная политика
  retention остаётся будущей задачей.

## 12. Порядок выполнения

1. Зафиксировать baseline и создать этот план.
2. Добавить Monitoring adapter, facade API и unit tests.
3. Адаптировать Monitoring UI и navigation.
4. Добавить Knowledge schema, repository, facade и migration.
5. Добавить Knowledge API и security tests.
6. Добавить Knowledge SPA, routes, responsive styles и frontend contracts.
7. Добавить `.env.example`, optional requirements и документацию.
8. Применить миграцию только к disposable test DB, не к production DB.
9. Выполнить focused tests, module-boundary audit, syntax checks и smoke UI.
10. Проверить секреты, source immutability и Git status.
11. Создать audit/integration reports и локальные тематические коммиты.

## 13. Критерии готовности

- Существующая главная и Warehouse не регрессировали.
- Monitoring открывается, валидирует ввод, даёт controlled state без внешней
  конфигурации и выполняет живой сбор при наличии Selenium/Edge/DCIM session.
- Knowledge list/search/filter/pagination/article/create/edit/delete работают.
- Вложения проходят server-side type/size/path/signature validation.
- Viewer не может менять Knowledge через прямой API.
- Прямые URL и reload не возвращают 404.
- Миграция идемпотентна, SQLite integrity/FK checks проходят.
- Новые focused tests и architecture audit проходят.
- В Git нет секретов, routing data, профиля Edge, БД и пользовательских файлов.
- Исходный `E:\ODE v0.2` не изменён этой работой.
