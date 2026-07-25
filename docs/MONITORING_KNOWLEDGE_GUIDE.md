# Monitoring and Knowledge Base

Status: implemented on integration branch, 2026-07-17.

## Architecture

Both modules are connected through `ApplicationContext` and expose only their
facades to `inventory/webapp.py`:

- `inventory/monitoring`: hostname routing and an optional external DCIM
  collector. It imports neither Warehouse nor Reports and owns no tables.
- `inventory/knowledge`: articles, tags, attachments and safe Markdown. It
  owns only `knowledge_*` tables and may append events to shared `audit_log`.

The browser uses the existing `request`, notification, component and History
API infrastructure. Monitoring history is per-browser `localStorage`; it is
not a shared operational log. Knowledge content is shared through SQLite.

## Monitoring setup

Base ODE has no new mandatory dependency. For live DCIM collection install:

```powershell
python -m pip install -r requirements-monitoring.txt
```

Configure values in the process environment; `.env.example` contains safe
placeholders:

```text
ODE_MONITORING_DCIM_BASE_URL=https://dcim.example.invalid
ODE_MONITORING_RULES_DIR=C:\private\monitoring-rules
ODE_MONITORING_EDGE_PROFILE_DIR=C:\private\ode-edge-profile
ODE_MONITORING_HEADLESS=false
ODE_MONITORING_COLLECT_DCIM=true
ODE_MONITORING_DEV_MOCK=false
```

`ODE_MONITORING_RULES_DIR` must contain local Tech/Digital JSON rules described
in [MONITORING_HOSTNAME_ROUTING.md](MONITORING_HOSTNAME_ROUTING.md). Those files
contain internal hostnames and recipients and are ignored by Git. Do not put
them, an Edge profile, cookies or credentials into the repository.

Use a dedicated Edge profile, sign in to DCIM once, close the interactive Edge
window, then start ODE. The collector reuses that profile. `HEADLESS=false` is
the safest first-run setting because SSO prompts remain visible. ODE validates
hostname/problem input, always closes WebDriver and returns controlled errors.

`ODE_MONITORING_DEV_MOCK=true` is allowed only for explicit local development
with `ODE_MONITORING_COLLECT_DCIM=false`. Mock results are visibly marked and
must never be presented as real DCIM data. ODE prepares message text and
recipients but does not send email or Rooms messages.

## Runtime module setup

An existing promoted database does not migrate itself during ordinary startup.
Check readiness first, then run the combined backup-guarded additive migration
with all ODE writers stopped:

```powershell
python scripts\migrate_runtime_modules.py --db data\warehouse.db
python scripts\migrate_runtime_modules.py --db data\warehouse.db --backup-dir C:\ODE_BACKUPS\runtime-modules-20260718 --apply
```

The backup directory must be new and outside the repository. The command creates
a byte-copy, a SQLite backup and a JSON manifest, verifies SHA-256, integrity,
foreign keys and sidecars, then installs Reports UVR references/columns and
Knowledge tables. Fresh databases already receive the complete current schema.

The Knowledge-only additive installer remains available for controlled legacy
setups:

```powershell
python scripts\migrate_knowledge_base.py --db data\warehouse.db
```

Before production use, back up the SQLite database and attachment directory
together.

```text
ODE_KNOWLEDGE_UPLOAD_DIR=C:\private\ode-knowledge-uploads
ODE_KNOWLEDGE_MAX_ATTACHMENT_MB=15
```

When the upload directory is omitted, ODE uses `data/uploads`; it is ignored by
Git. Allowed files are PDF, DOCX, XLSX, TXT, PNG and JPEG. Server validation
checks size, extension, MIME, signatures, safe names, path containment and
Office Open XML structure. Stored names are random UUIDs; downloads require an
authenticated session and include `nosniff`/`no-store` headers.

## Roles and API

All endpoints require an ODE session.

| Operation | viewer | engineer | admin |
|---|---:|---:|---:|
| Monitoring status/manual search | yes | yes | yes |
| Knowledge list/read/download | yes | yes | yes |
| Knowledge create/update/delete/attachment | no | yes | yes |

Knowledge endpoints:

- `GET /api/knowledge/articles?category=...&query=...&tag=...&page=...`
- `GET`, `PUT`, `DELETE /api/knowledge/articles/{id}`
- `POST /api/knowledge/articles`
- `POST /api/knowledge/articles/{id}/attachments`
- `GET /api/knowledge/attachments/{id}`

Monitoring endpoints:

- `GET /api/monitoring/status`
- `POST /api/monitoring/manual-search`

## Backup, rollback and limits

- Database backup alone does not contain attachment bytes. Back up both paths.
- Article deletion is soft; attachment bytes remain for audit/retention.
- Restore code and SQLite from the pre-integration backup to roll back schema
  usage; additive `knowledge_*` tables can remain without affecting Warehouse.
- Search uses parameterized `LIKE` and offset pagination. Move to FTS5/cursor
  pagination if the article corpus becomes large.
- Selenium work occupies one HTTP worker until the external collection ends.
  A shared server deployment should move it to a bounded background queue.
