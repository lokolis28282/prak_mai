# Agent Handoff

Перед любым изменением:

1. Прочитать repository `AGENTS.md`.
2. Прочитать `docs/project/CURRENT_STATE.md` и relevant roadmap lane.
3. Через `codebase-memory-mcp` найти symbols/call paths и проверить свежесть
   индекса.
4. Подтвердить критические связи через `rg` и чтение файлов.
5. Проверить `git status`; не трогать неизвестный dirty scope.
6. Для DB-related задачи записать path/SHA/sidecars и использовать temp copy.
7. Прочитать relevant Warehouse contract либо target ADR/DDL — не оба трека
   как будто это один runtime.
8. Сформулировать scope, invariants и tests до edit.

Текущий продуктовый приоритет: Warehouse stabilization. Monitoring/Reports не
расширять. Target Platform Stage 0.13.2 не начинать без post-fix Stage 0.13.1
review и отдельного approval.

Нельзя commit/push, reset/clean, production DB mutation или перенос из второй
копии без явного разрешения и соответствующего gate.
