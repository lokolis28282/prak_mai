# Repository Data Separation and Safe Git Baseline

Статус: **IMMEDIATE PROTECTION PASS — COMMIT READY, RELEASE BLOCKED**

Дата: 2026-07-16. Scope ограничен Git/data policy. Product code, tests,
approved DDL и migration sources не изменялись.

## Initial state

- repository: `~/Documents/prak_mai`;
- branch: `main`;
- HEAD и `origin/main`:
  `76afadd5355f4d379b19dcabf1f28850986d5300`;
- исходный worktree: 57 modified tracked entries, 1 deleted tracked entry и
  61 untracked status entries; ничего не было staged;
- `data/warehouse.db` была tracked и modified относительно HEAD;
- рабочая DB: 579461120 bytes, mode `0600`, SHA-256
  `73568a1c3eecbd4476473f064620d7f0a196b336ce8ea6d834c5b99359d4b010`;
- HEAD DB: 245760 bytes, SHA-256
  `d9299f6b16ee60e42aab05dd73f41aaf6c73e3e82a80184d2fc8fd6ee44cc0b7`;
- SQLite source check: `integrity_check=ok`, foreign-key violations `0`;
- `warehouse.db-wal`, `warehouse.db-shm` и `warehouse.db-journal` отсутствовали;
- `lsof` не показал открытых handles рабочей DB.

Полный исходный porcelain status сохранён вместе с внешним backup. Не
выполнялись `clean`, reset, restore, stash, merge, rebase или broad staging.

## External backup

До изменения index создан внешний byte-copy:

`~/Documents/ODE_BACKUPS/repository-data-separation-20260715T211706Z/`

Каталог содержит DB, SHA-256, metadata, HEAD и исходный Git status. Source и
backup имеют одинаковые size, SHA, mode и mtime; `cmp` подтвердил byte identity.
Backup открыт через SQLite `mode=ro&immutable=1`: integrity `ok`, FK violations
`0`. Backup находится вне repository.

## Canonical ignore policy

`.gitignore` теперь покрывает:

- scoped runtime DB и SQLite sidecars в `data/`;
- DB backups/candidates;
- `.stabilization/`;
- generated migration normalized/reports/workspace;
- generated release ZIP и runtime exports;
- Python/tool caches.

Глобальное `*.db` намеренно не добавлено: inventory подтвердил, что сейчас в
worktree есть только runtime `data/warehouse.db`, но policy не должна случайно
запретить будущий явно versioned fixture вне `data/`. `.git/info/exclude`
остаётся локальной дополнительной защитой и не является canonical policy.

## Index separation

Выполнено только:

```text
git rm --cached -- data/warehouse.db
git add -u -- release/ODE_windows_test.zip
```

Локальная DB осталась по прежнему пути; size, SHA, mode и mtime не изменились.
`git ls-files data/warehouse.db` пуст, а `git check-ignore` указывает на
repository `.gitignore`. Старый generated `release/ODE_windows_test.zip` уже
отсутствовал в worktree; его tracked deletion подготовлен отдельно. Canonical
local `release/ODE_0.12.17_RC1.zip` не изменялся и остаётся ignored artifact.

## Sensitive and generated inventory

| Path/category | Git state | Recommendation |
|---|---|---|
| `data/warehouse.db` | removed from index; local ignored | KEEP local + external backups; never commit/release |
| old DB blobs on `origin/main` | tracked history | coordinated future remediation only |
| local `refs/codex/turn-diffs/*` DB blob | local Git refs | treat `.git` as sensitive; coordinate safe ref/prune maintenance |
| `release/ODE_windows_test.zip` | staged deletion | commit deletion in this changeset |
| `release/ODE_0.12.17_RC1.zip` | untracked/ignored | local artifact; archive/delete independently |
| `migration_inputs/raw/` | untracked/ignored source | preserve externally; never commit |
| `migration_inputs/normalized/`, `reports/` | untracked/ignored generated evidence | regenerate/archive; never commit |
| `.stabilization/` | untracked/ignored local evidence | archive/delete independently |
| credential/key/token filenames | none found | no action |

Pattern review found no private key, API token or committed credential file.
The old HEAD DB contains one user row with a non-empty password hash. The value
was not displayed. **SECURITY FOLLOW-UP BLOCKER:** because a password verifier
is sensitive material, credential rotation/recovery review is required
separately; deleting the current index entry does not remove historical blobs.

## History assessment

`origin/main` contains five unique historical DB blobs of 229376–245760 bytes,
approximately 1179648 bytes uncompressed in total. The current 579461120-byte
runtime DB is not on `main`/`origin/main`, but one identical Git blob is retained
by four local Codex capture/checkpoint refs. Those refs were not modified.

Immediate protection is index removal plus repository ignore policy. Optional
future cleanup is a coordinated maintenance procedure: credential rotation,
collaborator notification, remote backup, history/ref decision and fresh-clone
validation. No `filter-repo`, BFG, GC, ref deletion or history rewrite was run.

## Release blocker

The current `build_windows_package.py` still adds `data/warehouse.db`, and the
current regression test expects that filename in the ZIP. This contradicts the
new data-separation policy. The builder/tests are outside this changeset and
were not modified, so **creating a new release remains blocked** until a separate
release-packaging changeset implements explicit empty-install bootstrap without
shipping the local runtime DB.

## Clone and installation contract

- a clone contains no production/runtime DB;
- `data/README.md` keeps the directory and documents the local path contract;
- a new installation explicitly selects and bootstraps its own DB;
- compatibility initialization is not authority for automatic production
  migration;
- production migration requires backup, validation and rollback;
- local runtime DB never enters a code release.

The old small DB remains in old history until a separately coordinated decision.

## Validation gate

- local DB exists; size `579461120`, mode `0600`, mtime and SHA unchanged;
- source and external backup remain byte-identical, integrity `ok`, FK `0`;
- no source or backup SQLite sidecars exist;
- `git ls-files data/warehouse.db` is empty;
- local DB is ignored by `.gitignore`, not only `.git/info/exclude`;
- no DB/SQLite/release ZIP remains tracked in the prepared index;
- staged scope is exactly the eight allowlisted paths below;
- `git add -n -A` completed as dry-run and proposed 240 unrelated dirty paths,
  but zero DB/SQLite/release-ZIP paths; this confirms that broad add must not be
  used and that runtime data is protected by repository policy;
- `git diff --check` and `git diff --cached --check` pass;
- `PYTHONDONTWRITEBYTECODE=1 python3 -c 'import app'` passes;
- `PYTHONDONTWRITEBYTECODE=1 python3 app.py --help` passes without DB write;
- no Markdown links were added, so there are no new link targets to resolve;
- product code, tests, approved DDL and migration sources are absent from the
  staged changeset;
- all pre-existing work remains unstaged: 55 modified tracked files and 185
  untracked non-ignored files. The tracked groups are docs (17), inventory (16),
  tests (7), static (6), scripts (3) and six root documents; untracked groups
  are docs (109), tests (21), inventory (21), ode (17), scripts (8), static (2)
  and seven root/launcher/migration entries;
- full 397-test suite was not rerun because source code was not changed by this
  task and the requested validation was intentionally read-only/minimal.

## Prepared changeset

Allowed staged scope:

```text
.gitignore
data/README.md
data/warehouse.db                         (deletion from index only)
docs/project/CURRENT_STATE.md
docs/project/REPOSITORY_MAP.md
docs/project/RISKS_AND_BACKLOG.md
docs/project/reviews/2026-07-16_REPOSITORY_DATA_SEPARATION.md
release/ODE_windows_test.zip              (generated artifact deletion)
```

Commit and push were not performed. The next recommended changeset is release
package data separation (builder + tests + release documentation), followed by
FULL inventory `NOT_INITIALIZED`/Preview/approved-baseline work.
