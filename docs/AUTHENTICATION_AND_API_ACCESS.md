# ODE 0.21.0 — аутентификация и доступ к HTTP API

Статус: **CURRENT RUNTIME CONTRACT**. Проверено по
`inventory/webapp.py` и auth/security-тестам 2026-08-11.

ODE 0.21.0 — локальное браузерное приложение. Его HTTP API обслуживает
собственный frontend и по умолчанию доступен только на
`http://127.0.0.1:8765`. Это не опубликованный интеграционный API.

## Короткий ответ про API-ключи

В текущей версии **нет входа по API-ключу**. ODE не принимает
`Authorization: Bearer …`, `X-API-Key`, JWT, OAuth/OIDC token или service
account credential. Переменной `ODE_API_KEY` также не существует.

Все защищённые `/api/*` используют только cookie `ode_session`, которую
сервер выдаёт после `POST /api/login`. Нельзя подставлять произвольный token
в cookie: сессия должна существовать в памяти текущего процесса ODE.

## Два режима входа

`mode` — режим создания HTTP-сессии, а не самостоятельная роль. Фактические
permissions проверяются backend по session context и роли пользователя.

| Режим | Payload `POST /api/login` | Текущий смысл |
|---|---|---|
| Инженер | `{"mode":"engineer","full_name":"Иванов Иван Иванович"}` | Локальный сменный вход без пароля. ФИО сохраняется как автор операций, а backend принудительно ограничивает сессию ролью `engineer`. Технической учётной записью остаётся локальный `lokolis`. |
| Credentialed/admin | `{"mode":"admin","email":"…","password":"…"}` | Проверка локальной записи `users` и PBKDF2-SHA256 hash. Роль берётся из БД; административные endpoints дополнительно требуют credentialed/admin session. |

Отдельного `mode:"viewer"` и отдельной кнопки входа viewer нет. Роль
`viewer` существует в permission model и тестах; она остаётся read-only.

Инженерный вход по произвольному ФИО рассчитан только на доверенный локальный
ноутбук смены. Это не строгая персональная аутентификация и не основание для
сетевого/server deployment.

На новой пустой БД создаётся локальный bootstrap-администратор
`lokolis`/`lokolis`. До немедленной смены начального пароля backend разрешает
ему только смену пароля. Обновление кода не пересоздаёт пользователя и не
сбрасывает существующий пароль.

## Жизненный цикл сессии

- token создаётся через `secrets.token_urlsafe(32)`;
- сервер хранит сессии только в памяти процесса, максимум 500;
- cookie: `ode_session`, `Path=/`, `HttpOnly`, `SameSite=Strict`;
- после 12 часов бездействия сессия удаляется;
- logout и перезапуск процесса инвалидируют её сразу;
- пять неудачных credentialed-входов за пять минут блокируют пару
  `client address + normalized email` на 15 минут;
- cookie не имеет `Secure`, потому что штатный профиль использует loopback
  HTTP. Это ещё одна причина не публиковать текущий runtime в сеть.

POST с браузерным `Origin` принимается только при совпадении `Origin` и
`Host`; hostname должен быть localhost, loopback/private IP либо явно входить
в `ODE_ALLOWED_HOSTS`. Это защита локального профиля, а не замена HTTPS,
полноценного CSRF-token, reverse proxy и централизованных sessions.

## Пример обращения к API

Примеры предназначены для локальной диагностики разработчиком. Cookie jar
содержит действующий session token: не коммитьте, не отправляйте и удаляйте
его после проверки.

```bash
# Инженерная сессия без пароля
curl --fail-with-body --silent --show-error \
  --cookie-jar .ode-session.cookies \
  --header 'Content-Type: application/json' \
  --data '{"mode":"engineer","full_name":"Инженер Локальной Проверки"}' \
  http://127.0.0.1:8765/api/login

# Чтение под выданной сессией
curl --fail-with-body --silent --show-error \
  --cookie .ode-session.cookies \
  'http://127.0.0.1:8765/api/data?include_balance=0'

# Выбор Solar только в этой сессии
curl --fail-with-body --silent --show-error \
  --cookie .ode-session.cookies \
  --header 'Content-Type: application/json' \
  --data '{"warehouse":"solar"}' \
  http://127.0.0.1:8765/api/warehouse/select

# Завершение сессии
curl --fail-with-body --silent --show-error \
  --cookie .ode-session.cookies \
  --header 'Content-Type: application/json' \
  --data '{}' \
  http://127.0.0.1:8765/api/logout
```

Для credentialed-входа используйте `mode:"admin"`, `email` и `password`, но
не вставляйте реальный пароль в сохраняемую shell history, скрипт или Git.
Ответ `/api/login` ставит cookie заголовком `Set-Cookie`; body не возвращает
session token.

`X-Correlation-ID` можно передать для трассировки операции. Сервер принимает
16–200 символов `[A-Za-z0-9._:-]`; иначе генерирует безопасный `corr_*` сам.
Этот ID не является credential.

## Что защищать как секрет

- пароль и его ввод;
- cookie `ode_session` и cookie jar;
- локальные `data/monitoring/*.json` с hostname/адресатами;
- Edge profile/cookies корпоративного DCIM;
- рабочие БД, backup и выгрузки.

Password hash, cookie, raw auth header и credentials не должны попадать в
логи, audit details, отчёты, тестовые fixtures, Git или release ZIP.

## Monitoring и внешние учётные данные

Optional DCIM collector не принимает API-ключ через ODE. Он использует
локальный Microsoft Edge/WebDriver и существующую разрешённую браузерную
сессию. `ODE_MONITORING_DCIM_BASE_URL` — URL, а не secret. Edge profile и
corporate cookies хранятся вне Git.

ODE формирует текст Rooms/email, но не отправляет его и не хранит transport
credentials. Zabbix, Kaiten, ITSM, email и Rooms API-auth не реализованы.

## Требования к будущему API-key профилю

Нельзя «добавить ключ» одной env-переменной и считать внешний API готовым.
До реализации нужны отдельный ADR и executable security tests как минимум для:

1. отдельного machine principal и scopes, без engineer/admin browser mode;
2. генерации не менее 256 бит entropy и показа plaintext только один раз;
3. хранения только hash + безопасного публичного prefix;
4. expiry, rotation, revoke и немедленной инвалидизации;
5. allowlist endpoints, write-idempotency и rate limit;
6. audit actor/key ID без записи plaintext token;
7. HTTPS, trusted reverse proxy, Host/Origin policy и secret manager;
8. отрицательных тестов на scope bypass, replay, утечку и disabled key.

Пока этот профиль не реализован, автоматизации должны запускаться внутри
доверенного процесса через публичные фасады либо оставаться offline scripts,
а не имитировать API-key с помощью session cookie.

Список маршрутов находится в [API_REFERENCE.md](API_REFERENCE.md), параметры
процесса — в [RUNTIME_CONFIGURATION.md](RUNTIME_CONFIGURATION.md), общие
security-границы — в [SECURITY_BOUNDARIES.md](SECURITY_BOUNDARIES.md).
