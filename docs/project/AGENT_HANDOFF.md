# Agent Handoff — ODE 0.21.1

Минимальный безопасный вход в задачу:

1. Прочитать root `AGENTS.md`, `CURRENT_STATE.md` и
   `SYSTEM_FUNCTION_MATRIX.md`.
2. Проверить `git status`, branch/upstream и не смешивать неизвестный dirty
   scope со своей задачей.
3. Найти реальный call path через `rg` и исходники. Важные связи из внешнего
   индекса всегда перепроверять локально.
4. Определить владельца данных и идти `UI/API → ApplicationContext → facade`;
   не создавать прямой SQL из route/template.
5. Перед DB-related проверкой записать пути, SHA-256, sidecars,
   integrity/FK. Mutation/smoke — только на временной byte-copy.
6. Для frontend помнить: итоговый inline `<style>/<script>` удаляется;
   runtime-код живёт в `static/`, итог проверяется через `webapp.HTML`.
7. До edit сформулировать scope, invariants, permissions и executable tests.
8. Для HTTP/auth/config задач прочитать `AUTHENTICATION_AND_API_ACCESS.md` и
   `RUNTIME_CONFIGURATION.md`; не придумывать API keys или `.env` autoload,
   которых нет в runtime.

Текущий приоритет — эксплуатационная устойчивость ODE 0.21.1: Windows
double-click acceptance, поиск по
целевой железке, Equipment Composition как evidence issue-history,
Multi-Warehouse, Vacations, multi-database backup и согласованность living-
документации. Monitoring/Reports/Knowledge развиваются только внутри своих
facade/storage boundaries.

Restore остаётся fail-closed до ADR-013; складские correction/reversal — до
ADR-014. Нельзя угадывать слоты компонентов, подменять runtime-БД candidate/
test файлом или включать данные в code release.

Базовый gate: compile, JS syntax, module/frontend/documentation/repository
audits, code graph, full warning-clean unittest, clean DB dry-run, Chrome E2E,
`git diff --check` и повторная SHA/integrity/FK проверка трёх рабочих БД.

Commit/push, production mutation, release artifact и перенос из другой копии
требуют явного scope/разрешения владельца и соответствующего gate.
