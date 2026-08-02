# ODE 0.20.0 — исправление текущих визуальных артефактов

Дата: 2026-08-02.

## Причина

После публикации полного system audit главная страница GitHub текстом
описывала ODE 0.20.0, но показывала крупный historical PNG графа 0.18.1.
Дополнительная проверка выявила тот же version drift внутри архитектурного SVG
и устаревшие числа в `docs/CODEBASE_GRAPH.md`.

## Исправление

- из текущего `docs/assets/code_graph.html` создан и визуально проверен
  `ode-code-graph-0.20.0.png` размером 2048×1152;
- README и CODEBASE_GRAPH показывают только current PNG 0.20.0;
- SVG обновлён до ODE 0.20.0, 248 модулей и 506 связей;
- внешний non-persistent Codebase Memory refresh: 7 416 узлов / 31 569 рёбер;
- `generate_code_graph.py --check` требует валидный current-version PNG;
- documentation audit запрещает старый versioned PNG в current README/docs;
- regression test проверяет ссылки, PNG signature/IHDR/dimensions и версию SVG.

Historical PNG-файлы остаются repository evidence прошлых этапов, но ни один
living/current документ больше не выводит их как актуальную карту.

## Gate

- code graph: 248 nodes / 506 edges — current;
- documentation audit: 202 Markdown-файла — PASS;
- full warning-clean unittest: 642 теста, `skipped=8` — PASS;
- module/frontend/repository-data audits — PASS;
- Python/JavaScript syntax — PASS;
- `git diff --check` — PASS;
- runtime-БД не открывались и не изменялись этим documentation/assets fix.

## Verdict

**PASS:** GitHub-visible README, static PNG, interactive HTML, architecture SVG
и living code-graph document относятся к одной текущей версии ODE 0.20.0.
