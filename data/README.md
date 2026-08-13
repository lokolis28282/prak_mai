# Runtime data — ODE 0.21.1

ODE uses three installation-owned local runtime databases:

- `data/warehouse.db` — IXcellerate plus primary Administration, Reports and
  Knowledge tables;
- `data/warehouse_solar.db` — physically separate Solar Warehouse;
- `data/vacations.db` — standalone common Vacations plan.

Monitoring owns no database tables; its approved local routing JSON and browser
history are separate runtime state. None of the three databases or Monitoring
rules belongs to Git, a public source archive or a code release. A repository
clone intentionally contains no production or operator data.

For a new local installation, use ordinary `python3 app.py`: it composes all
three installation-owned paths and can initialize missing local schemas. This
is a local bootstrap, not authority to import production data or apply an
unreviewed server migration. Do not use a single arbitrary `--db` as a test or
restore workflow; the safe test contour requires all three marker-validated
paths and the documented launcher. Production schema/data migration requires
its own approved backup, migration and rollback procedure.

Before first use:

1. create `data/` with access limited to the service/operator account;
2. ensure each database file is writable only by that account (`0600` on POSIX);
3. keep backups outside the repository and verify them with SQLite
   `integrity_check` and `foreign_key_check`;
4. never copy a test, candidate or historical source DB over any runtime DB.

The ordinary IXcellerate path remains `data/warehouse.db`. On normal startup,
ODE creates `data/warehouse_solar.db` only if it is absent: the Solar database
starts with zero operational rows and receives a one-time snapshot of
IXcellerate reference tables. Existing Solar data is never resynchronized or
overwritten by startup. Test and migration review databases must use distinct
filenames and the documented guarded launchers.

The ordinary Vacations path is `data/vacations.db`. It is initialized with an
empty roster and its own `vacation_*`/`vacation_audit_log` schema; it never
installs those tables into either Warehouse DB. Back up and verify all three
targets independently.

`data/monitoring/*.json` contains generated, environment-specific hostname
routing and recipient data. These files are local runtime configuration and
must not be committed to the public repository. Regenerate them from approved
local XLSX sources using the command documented in
`docs/MONITORING_HOSTNAME_ROUTING.md`.
