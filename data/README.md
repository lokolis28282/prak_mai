# Runtime Warehouse data

`data/warehouse.db` is a local runtime database. It never belongs to Git, a
source archive or a code release. A repository clone intentionally contains no
production or operator data.

For a new local installation, select an installation-owned database path
explicitly, for example `python3 app.py web --db data/warehouse.db`. The current
compatibility runtime can initialize an absent local database when it is
explicitly launched against that path; this is a local bootstrap, not authority
to import production data or apply an unreviewed server migration. Production
schema/data migration requires its own approved backup, migration and rollback
procedure.

Before first use:

1. create `data/` with access limited to the service/operator account;
2. ensure the database file is writable only by that account (`0600` on POSIX);
3. keep backups outside the repository and verify them with SQLite
   `integrity_check` and `foreign_key_check`;
4. never copy a test, candidate or historical source DB over the runtime DB.

The ordinary local Warehouse path remains `data/warehouse.db`. Test and
migration review databases must use distinct filenames and the documented
guarded launchers.

`data/monitoring/*.json` contains generated, environment-specific hostname
routing and recipient data. These files are local runtime configuration and
must not be committed to the public repository. Regenerate them from approved
local XLSX sources using the command documented in
`docs/MONITORING_HOSTNAME_ROUTING.md`.
