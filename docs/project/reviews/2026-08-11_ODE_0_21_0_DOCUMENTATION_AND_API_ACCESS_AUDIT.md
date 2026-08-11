# ODE 0.21.0 — documentation and API access audit

Дата: 2026-08-11
Scope: весь tracked/current Markdown, user/developer/API/security/configuration
Вердикт: **PASS после синхронизации; внешний API и API-key auth не заявлены**

## Цель

После Monitoring integration выполнен отдельный семантический проход по
общей документации. Проверялись не только версия и ссылки, но и соответствие
описаний исполняемому runtime: вход, roles, cookie lifecycle, endpoints,
Monitoring/DCIM, env/CLI, topology БД, release ZIP, тестовые counts и code
graph.

Исторические release reports и датированные reviews не переписывались задним
числом. Version-specific counts внутри `CURRENT_STATE.md` сохранены как
provenance и явно отделены от текущего общего gate.

## Подтверждённый auth/API runtime

- `/api/login` имеет два payload: engineer `full_name` без пароля и
  credentialed/admin `email/password`;
- engineer session получает server-side role override `engineer`; ФИО —
  attribution, не admin grant;
- защищённые endpoints используют только in-memory HttpOnly/SameSite cookie
  `ode_session`;
- idle TTL — 12 часов, store — максимум 500 sessions, restart/logout
  инвалидируют token;
- пять credentialed failures за пять минут блокируют client+email на 15 минут;
- POST проверяет совпадение Origin/Host при присутствующем Origin и допустимый
  local/private/allowlisted host;
- API-key, `Authorization: Bearer`, `X-API-Key`, JWT/OAuth/OIDC, service account
  и `ODE_API_KEY` в ODE 0.21.0 отсутствуют;
- `X-Correlation-ID` является диагностическим ID, а не credential.

Центральный current contract:
`docs/AUTHENTICATION_AND_API_ACCESS.md`. Future API-key profile оставлен
fail-closed до отдельного ADR для principals/scopes/hash/expiry/revoke/audit/
rate-limit/TLS.

## Исправленные расхождения

- README больше не называет optional DCIM-enabled продукт полностью offline;
- user guide различает engineer и credentialed/admin вход и объясняет
  `401/403/429`;
- API reference содержит оба точных login payload и session lifecycle;
- developer/security docs явно запрещают использовать cookie как machine key;
- добавлен единый `RUNTIME_CONFIGURATION.md`; `.env.example` помечен как
  не загружаемый автоматически;
- Monitoring architecture отражает реализованные UI/manual DCIM/routing и
  отсутствие automatic transports;
- function matrix использует `/api/global-search`, а не удалённый
  `/api/search`;
- ITOG синхронизирован с 703 tests, code graph 252/512 и release 0.21.0;
- исторический Stage 0.13.2 inventory-number документ больше не выдаёт ZIP
  0.12.17 за текущий artifact;
- Windows docs явно отделяют legacy LAN launcher от утверждённого local
  source package.

## Проверки

- `python3 scripts/audit_documentation.py` — PASS, 212 Markdown files, links и
  current-version/auth markers;
- `python3 scripts/audit_repository_data.py` — PASS;
- `python3 scripts/audit_module_boundaries.py` — PASS;
- `python3 scripts/audit_frontend_contracts.py` — PASS;
- `python3 scripts/generate_code_graph.py --check` — PASS, 252/512;
- `python3 scripts/refresh_project_knowledge.py` — PASS, external index
  7 758/33 357, `skipped_count=0`, `persistence=false`;
- Python compile и JavaScript syntax — PASS;
- warning-clean unittest discover — 703 tests, `OK (skipped=8)`;
- `git diff --check` — PASS;
- три runtime-БД сохранили исходные SHA-256, integrity/FK PASS, sidecars
  отсутствуют.

Это documentation-only изменение: auth/API/runtime code и рабочие БД не
менялись. Physical Windows sign-off и разрешённый live DCIM acceptance остаются
отдельными следующими действиями.
