"""Side-effect-free database diagnostics over the approved ODE schema."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from ode.application.config import DatabaseConfig
from ode.application.errors import DatabaseError, MigrationError
from ode.infrastructure.database import (
    ConnectionMode,
    SQLiteConnectionFactory,
    compute_schema_hash,
    require_immutable_snapshot_safe,
    sqlite_sidecar_state,
)
from ode.infrastructure.migrations import MigrationRunner
from ode.system.models import (
    BaselineState,
    DatabaseDiagnostics,
    DatabaseObjectCounts,
    LegacyHistoryState,
    MigrationStatus,
    ProjectionState,
)


class DiagnosticsService:
    """Reads database state without creating, migrating, repairing, or checkpointing."""

    def __init__(
        self,
        config: DatabaseConfig,
        factory: SQLiteConnectionFactory,
        migration_runner: MigrationRunner,
    ) -> None:
        self._config = config
        self._factory = factory
        self._migration_runner = migration_runner

    def migration_status(self) -> MigrationStatus:
        return self._migration_runner.migration_status()

    def diagnostics(self) -> DatabaseDiagnostics:
        path = self._config.db_path
        if not path.exists():
            raise DatabaseError("DATABASE_NOT_FOUND", "Database file does not exist")
        require_immutable_snapshot_safe(path)
        stat = path.stat()
        migrations = self._migration_runner.migration_status()
        if migrations.application_id != migrations.expected_application_id:
            raise DatabaseError(
                "INVALID_APPLICATION_ID", "Database is not an ODE 0.13 database"
            )
        warnings = ["NETWORK_FILESYSTEM_NOT_VERIFIED"]
        if self._config.external_path_override:
            warnings.append("EXTERNAL_DEV_PATH_OVERRIDE")
        try:
            with self._factory.connect(ConnectionMode.IMMUTABLE_READ_ONLY) as connection:
                integrity_rows = connection.execute("PRAGMA integrity_check").fetchall()
                integrity = (
                    "ok"
                    if len(integrity_rows) == 1 and str(integrity_rows[0][0]) == "ok"
                    else "; ".join(str(row[0]) for row in integrity_rows)
                )
                foreign_key_violations = len(
                    connection.execute("PRAGMA foreign_key_check").fetchall()
                )
                objects = self._object_counts(connection)
                schema_hash = compute_schema_hash(connection)
                tables = {
                    str(row[0])
                    for row in connection.execute(
                        "SELECT name FROM sqlite_schema WHERE type='table'"
                    )
                }

                users_count = self._count(connection, tables, "users")
                equipment_count = self._count(connection, tables, "equipment")
                legacy_events_count = self._count(
                    connection, tables, "legacy_history_events"
                )
                snapshots_count = self._count(
                    connection, tables, "inventory_snapshots"
                )
                ledger_count = self._count(
                    connection, tables, "warehouse_transactions"
                )
                projections_count = self._count(
                    connection, tables, "balance_projection_versions"
                )
                ledger_head = 0
                if "warehouse_transactions" in tables:
                    ledger_head = int(
                        connection.execute(
                            "SELECT ifnull(max(ledger_sequence), 0) "
                            "FROM warehouse_transactions"
                        ).fetchone()[0]
                    )
                active_snapshot_id: int | None = None
                active_projection_id: int | None = None
                stored_ledger_head: int | None = None
                baseline = BaselineState.UNKNOWN
                if "app_state" in tables:
                    state = connection.execute(
                        "SELECT balance_state, active_snapshot_id, "
                        "active_projection_version_id, last_ledger_sequence "
                        "FROM app_state WHERE singleton_id = 1"
                    ).fetchone()
                    if state is not None:
                        raw_baseline = str(state[0])
                        baseline = (
                            BaselineState(raw_baseline)
                            if raw_baseline in {item.value for item in BaselineState}
                            else BaselineState.UNKNOWN
                        )
                        active_snapshot_id = (
                            int(state[1]) if state[1] is not None else None
                        )
                        active_projection_id = (
                            int(state[2]) if state[2] is not None else None
                        )
                        stored_ledger_head = int(state[3])
                if stored_ledger_head is not None and stored_ledger_head != ledger_head:
                    warnings.append("APP_STATE_LEDGER_HEAD_MISMATCH")

                projection_state = ProjectionState.UNAVAILABLE
                if active_projection_id is not None:
                    projection_state = ProjectionState.INCONSISTENT
                    if "balance_projection_versions" in tables:
                        projection = connection.execute(
                            "SELECT build_status FROM balance_projection_versions "
                            "WHERE projection_version_id = ?",
                            (active_projection_id,),
                        ).fetchone()
                        if projection is not None and str(projection[0]) == "ACTIVE":
                            projection_state = ProjectionState.ACTIVE
                legacy_state = (
                    LegacyHistoryState.IMPORTED
                    if legacy_events_count > 0
                    else LegacyHistoryState.NOT_IMPORTED
                )
                schema_ready = (
                    migrations.ready
                    and schema_hash
                    == self._migration_runner.manifest.approved_schema_hash
                    and objects == DatabaseObjectCounts(41, 73, 73, 3)
                    and "app_state" in tables
                )
                posting_enabled = (
                    schema_ready
                    and baseline is BaselineState.ACTIVE
                    and active_snapshot_id is not None
                    and projection_state is ProjectionState.ACTIVE
                    and stored_ledger_head == ledger_head
                )
        except (DatabaseError, MigrationError):
            raise
        except Exception as exc:
            raise DatabaseError(
                "DIAGNOSTICS_FAILED",
                "Read-only database diagnostics could not complete",
                details={"failure_type": type(exc).__name__},
            ) from exc

        require_immutable_snapshot_safe(path)
        sidecars = sqlite_sidecar_state(path)

        return DatabaseDiagnostics(
            database_path=str(path),
            file_size_bytes=stat.st_size,
            user_version=migrations.user_version,
            application_id=migrations.application_id,
            migrations=migrations,
            integrity_result=integrity,
            foreign_key_violations=foreign_key_violations,
            wal_present=sidecars["wal"],
            shm_present=sidecars["shm"],
            journal_present=sidecars["journal"],
            objects=objects,
            active_snapshot_id=active_snapshot_id,
            ledger_head=ledger_head,
            baseline_state=baseline,
            projection_state=projection_state,
            legacy_history_state=legacy_state,
            schema_hash=schema_hash,
            schema_ready=schema_ready,
            warehouse_posting_enabled=posting_enabled,
            users_count=users_count,
            equipment_count=equipment_count,
            legacy_events_count=legacy_events_count,
            snapshots_count=snapshots_count,
            ledger_count=ledger_count,
            projections_count=projections_count,
            external_path_override=self._config.external_path_override,
            warnings=tuple(warnings),
        )

    @staticmethod
    def _object_counts(connection: sqlite3.Connection) -> DatabaseObjectCounts:
        rows = connection.execute(
            "SELECT type, count(*) FROM sqlite_schema "
            "WHERE (type <> 'table' OR name NOT LIKE 'sqlite_%') "
            "AND (type <> 'index' OR sql IS NOT NULL) GROUP BY type"
        ).fetchall()
        counts = {str(row[0]): int(row[1]) for row in rows}
        return DatabaseObjectCounts(
            tables=counts.get("table", 0),
            indexes=counts.get("index", 0),
            triggers=counts.get("trigger", 0),
            views=counts.get("view", 0),
        )

    @staticmethod
    def _count(connection: sqlite3.Connection, tables: set[str], table: str) -> int:
        if table not in tables:
            return 0
        return int(connection.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0])
