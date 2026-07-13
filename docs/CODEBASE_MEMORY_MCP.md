# CODEBASE_MEMORY_MCP

Локальный developer-инструмент для структурного поиска по ODE. Он не является
runtime-зависимостью приложения, не нужен инженерам для обычной работы и не
должен попадать в release ZIP.

## Проверенная установка

- upstream: <https://github.com/DeusData/codebase-memory-mcp>;
- stable release: `v0.9.0` (2026-07-08);
- asset: `codebase-memory-mcp-darwin-arm64.tar.gz` (standard/headless);
- SHA-256 asset: `faa02f0404230c451a9812230394481948f80183801fa5bf67044b41c2f25ed4`;
- SHA-256 `checksums.txt`:
  `b7294616f22050124c8f2cf029cc9943e0b7d6e426fb9a0b95b1de9815c76e57`;
- SHA-256 распакованного бинарника:
  `d9fbdd7d8570a77b2fb32453e00bd52a02627281309cd56003a4eccfcfe878d6`;
- установленный бинарник: `/Users/lokolis/.local/bin/codebase-memory-mcp`;
- cache/index: `/Users/lokolis/Library/Caches/codebase-memory-mcp/ode`.

Архив и checksum были скачаны только с GitHub release, сверены с GitHub API и
`checksums.txt` до первого запуска. `curl | bash`, UI-вариант и автоматический
installer не использовались.

## Почему конфигурация ручная

`install --dry-run` версии 0.9.0 обнаружил Claude Code, Codex, VS Code и
OpenClaw и собирался изменить их все, добавить shell PATH, Claude skill и
hooks, а также Codex instructions. У CLI нет селектора «только Claude+Codex» и
нет флагов отключения hooks/skills. Поэтому установлен только проверенный
бинарник и две MCP-записи.

Не использовать `install --help`/`uninstall --help`: в 0.9.0 они могут
запустить саму операцию. Справка верхнего уровня доступна через `--help`, а
безопасный план установки — через `install --dry-run` или `install --plan`.

## Codex CLI

Файл: `~/.codex/config.toml`. Существующее содержимое сохранено; добавлен один
блок:

```toml
[mcp_servers.codebase-memory-mcp]
command = "/Users/lokolis/.local/bin/codebase-memory-mcp"

[mcp_servers.codebase-memory-mcp.env]
CBM_ALLOWED_ROOT = "/Users/lokolis/Documents/prak_mai"
CBM_CACHE_DIR = "/Users/lokolis/Library/Caches/codebase-memory-mcp/ode"
CBM_LOG_LEVEL = "warn"
```

Project `.codex/config.toml` и `AGENTS.md` не создавались. После изменения
config нужен новый процесс/перезапуск Codex. Проверка: `codex mcp list`, затем
`/mcp` в TUI.

## Claude Code

User-scope запись находится в `~/.claude.json`:

```json
{
  "mcpServers": {
    "codebase-memory-mcp": {
      "type": "stdio",
      "command": "/Users/lokolis/.local/bin/codebase-memory-mcp",
      "args": [],
      "env": {
        "CBM_ALLOWED_ROOT": "/Users/lokolis/Documents/prak_mai",
        "CBM_CACHE_DIR": "/Users/lokolis/Library/Caches/codebase-memory-mcp/ode",
        "CBM_LOG_LEVEL": "warn"
      }
    }
  }
}
```

Остальные ключи JSON сохранены. Project `.mcp.json`, `.claude/.mcp.json`,
skills и hooks не создавались. Проверка после перезапуска: `claude mcp list`.

## Hooks и skills

На первом этапе не установлены. Аудит официального исходника 0.9.0 показал,
что автоматический Claude `PreToolUse` hook перехватывает только `Grep|Glob`,
добавляет контекст и всегда завершается кодом 0; `Read`, `Edit` и `Bash` не
перехватываются. Однако installer владеет hook-записями по matcher и может
заменить чужой hook с тем же matcher. Поэтому доказанная non-blocking реализация
всё равно не установлена.

Codex `AGENTS.md`/SessionStart reminder также не устанавливались. Короткое
правило проекта находится в существующем `CLAUDE.md`.

## Индексация и ограничения

Config в `_config.db`:

```text
auto_index=false
auto_watch=false
auto_index_limit=50000
```

Индексировать только явно:

```bash
CBM_ALLOWED_ROOT=/Users/lokolis/Documents/prak_mai \
CBM_CACHE_DIR=/Users/lokolis/Library/Caches/codebase-memory-mcp/ode \
/Users/lokolis/.local/bin/codebase-memory-mcp cli index_repository \
  --repo-path /Users/lokolis/Documents/prak_mai \
  --mode full --persistence false
```

`persistence=false` обязателен. При `true` upstream пишет
`.codebase-memory/graph.db.zst`, metadata/`.gitattributes` и локальный Git
merge driver. Глобального kill-switch нет; если совместимый artifact уже
существует, incremental reindex может обновить его даже при последующем
`false`. Поэтому перед и после индексации проверять отсутствие
`.codebase-memory/` и `artifact_present:false`.

Локальные исключения находятся только в `.git/info/exclude`; project
`.gitignore` не менялся. Исключены `.git`, SQLite DB/sidecars, release и
backup, ZIP, caches/pyc, screenshots/exports/logs, node_modules/venv,
secrets/credentials и session-data. SQLite-файлы дополнительно hard-skipped
самим indexer. `.cbmignore` сейчас не используется.

Текущий проект в cache называется `Users-lokolis-Documents-prak_mai`.
Первичная full-индексация: 2 478 узлов, 11 168 рёбер, 221 файл, около 10 MiB;
`artifact_present=false`, DB-файлов в `File` nodes нет.

## Диагностика и stale index

```bash
CBM_CACHE_DIR=/Users/lokolis/Library/Caches/codebase-memory-mcp/ode \
  /Users/lokolis/.local/bin/codebase-memory-mcp config list

CBM_CACHE_DIR=/Users/lokolis/Library/Caches/codebase-memory-mcp/ode \
  /Users/lokolis/.local/bin/codebase-memory-mcp cli index_status \
  --project Users-lokolis-Documents-prak_mai

CBM_CACHE_DIR=/Users/lokolis/Library/Caches/codebase-memory-mcp/ode \
  /Users/lokolis/.local/bin/codebase-memory-mcp cli list_projects
```

`index_status=ready` означает читаемый index, но не доказывает свежесть при
`auto_watch=false`. После существенного `git diff` выполнить явный reindex и
сверить структурные ответы с `rg`/чтением исходника. Наличие cache
`.db-wal/.db-shm` нормально, пока MCP-процесс работает; не копировать и не
удалять cache до остановки Codex/Claude. Ненулевой WAL после остановки — повод
сначала открыть DB SQLite и выполнить `PRAGMA integrity_check`, а не удалять
sidecar вслепую.

Для диагностики утечек можно временно добавить `CBM_DIAGNOSTICS=1`; отчёты
пишутся в системный temp и не содержат исходный код/тексты запросов. Standard
binary не содержит graph UI. На старте есть upstream GitHub update check; в
0.9.0 документированного off-switch нет.

## Обновление

Не использовать слепой `update`. Для новой версии повторить процедуру:

1. проверить `/releases/latest`, что release stable, не draft/prerelease;
2. скачать standard arm64 archive и `checksums.txt` с официального GitHub;
3. сверить checksum list с GitHub API, затем архив с checksum list;
4. распаковать вне Git, проверить `--version`/верхнеуровневый `--help`;
5. сохранить backup конфигов и вручную заменить бинарник;
6. проверить configs, reindex с `persistence=false`, `/mcp` и `claude mcp list`.

## Безопасное удаление

Для этой ручной установки не использовать upstream `uninstall`: в 0.9.0 его
`--dry-run -y` имеет известный путь, способный удалить cache DB, а обычный
uninstall может затронуть matcher-совпадающие чужие hooks и оставляет часть
своих файлов.

После backup и остановки Codex/Claude удалять точечно:

```bash
codex mcp remove codebase-memory-mcp
claude mcp remove --scope user codebase-memory-mcp
```

Затем отдельно, только с явным подтверждением, удалить бинарник
`~/.local/bin/codebase-memory-mcp` и dedicated cache
`~/Library/Caches/codebase-memory-mcp/ode`. Hook/skill/AGENTS cleanup для этой
установки не нужен, потому что они не создавались.

## Известные ограничения

- Структурный граф дополняет, но не заменяет актуальный `rg`/read и тесты.
- JavaScript callback/динамический DOM и Python runtime routing могут быть
  представлены неполно; неподтверждённые связи нельзя считать фактом.
- В текущем Codex 0.144.1 `/mcp` показывает восемь core tools, хотя бинарный
  CLI 0.9.0 содержит 14; дополнительные `detect_changes`, `index_status` и
  lifecycle tools доступны прямым `cli`-режимом.
- Cache/graph никогда не коммитить и не включать в release/backup ODE.
