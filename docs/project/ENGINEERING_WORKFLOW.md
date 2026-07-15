# Engineering Workflow

## Поиск и анализ

1. Для структурного поиска сначала использовать `codebase-memory-mcp`:
   architecture, graph search, callers/callees и impact path.
2. Проверить свежесть индекса; после существенного diff выполнить explicit
   index только для authoritative repository, без persistence.
3. Важные связи обязательно подтвердить `rg` и чтением актуального кода.
4. Не индексировать `data/*.db*`, secrets, raw/workspace/release/backups/cache.

Граф помогает экономить контекст, но не является source of truth для dirty
worktree, динамических Python calls или runtime-generated frontend.

## Цикл изменения

1. Зафиксировать scope, source of truth, transaction boundary и invariants.
2. Проверить `git status` и пересекающийся dirty diff.
3. Для DB-related задачи зафиксировать path/SHA/sidecars; mutation только на
   временной копии или после отдельной production procedure.
4. Найти существующий facade/service/repository; не создавать параллельный
   runtime.
5. Исправить первопричину минимальным cohesive change.
6. Добавить regression test.
7. Выполнить targeted tests, затем полный gate в объёме риска.
8. Проверить рабочую DB SHA/integrity/FK и отсутствие sidecars.
9. Обновить living docs и `CURRENT_STATE.md`, если изменился статус.
10. Передать Claude только focused review scope и evidence.

## Blocking findings

Потеря данных, balance/identity violation, authorization bypass, schema
corruption, production DB mutation или critical migration failure блокируют
следующий Stage. Platform/deployment ограничения фиксируются в backlog, если
не влияют на текущий локальный Warehouse gate.

## Git

Не выполнять clean/reset/force operations. Не коммитить DB, raw, candidate,
test, backup, release ZIP или secrets. Commit/push — только по явному approval.
