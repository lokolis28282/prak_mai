from __future__ import annotations

import hashlib
import os
import sqlite3
import subprocess
import sys
import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from ode.application.context import build_application_context
from ode.application.errors import DatabaseError, MigrationError
from ode.infrastructure.migrations import MigrationRunner
from ode.system.models import (
    BaselineState,
    DatabaseDiagnostics,
    HealthStatus,
    LegacyHistoryState,
    MigrationStatus,
    ProjectionState,
)
from ode.system.service import SystemService
from tests.ode013.support import config


def _database_file_state(path: Path) -> tuple[object, ...]:
    files: list[tuple[object, ...]] = []
    for candidate in (path, Path(f"{path}-wal"), Path(f"{path}-shm"), Path(f"{path}-journal")):
        if candidate.exists():
            files.append(
                (
                    candidate.name,
                    hashlib.sha256(candidate.read_bytes()).hexdigest(),
                    candidate.stat().st_size,
                    candidate.stat().st_mtime_ns,
                )
            )
        else:
            files.append((candidate.name, None, None, None))
    return tuple(files)


class DiagnosticsHealthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.path = Path(self.temporary.name) / "diagnostics.db"
        self.config = config(self.path)
        MigrationRunner(self.config).create()
        self.context = build_application_context(self.config)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_clean_database_is_not_initialized_with_exact_empty_state(self) -> None:
        diagnostics = self.context.diagnostics.diagnostics()
        health = self.context.system.health()
        self.assertEqual(health.status, HealthStatus.NOT_INITIALIZED)
        self.assertTrue(health.schema_ready)
        self.assertEqual(health.baseline_state, BaselineState.NOT_INITIALIZED)
        self.assertFalse(health.warehouse_posting_enabled)
        self.assertIsNone(health.active_snapshot_id)
        self.assertEqual(health.ledger_head, 0)
        self.assertEqual(health.projection_state, ProjectionState.UNAVAILABLE)
        self.assertEqual(
            health.legacy_history_state, LegacyHistoryState.NOT_IMPORTED
        )
        self.assertEqual(diagnostics.objects.to_dict(), {
            "tables": 41, "indexes": 73, "triggers": 73, "views": 3
        })
        self.assertEqual(
            (
                diagnostics.users_count,
                diagnostics.equipment_count,
                diagnostics.legacy_events_count,
                diagnostics.snapshots_count,
                diagnostics.ledger_count,
                diagnostics.projections_count,
            ),
            (0, 0, 0, 0, 0, 0),
        )

    def test_diagnostics_do_not_change_sha_mtime_or_create_sidecars(self) -> None:
        before = (
            hashlib.sha256(self.path.read_bytes()).hexdigest(),
            self.path.stat().st_mtime_ns,
        )
        self.context.diagnostics.diagnostics()
        after = (
            hashlib.sha256(self.path.read_bytes()).hexdigest(),
            self.path.stat().st_mtime_ns,
        )
        self.assertEqual(before, after)
        self.assertFalse(Path(f"{self.path}-wal").exists())
        self.assertFalse(Path(f"{self.path}-shm").exists())
        self.assertFalse(Path(f"{self.path}-journal").exists())

    @unittest.skipIf(os.name == "nt", "requires unlinking an open SQLite SHM file")
    def test_active_wal_is_rejected_without_checkpoint_or_file_mutation(self) -> None:
        writer = sqlite3.connect(self.path, isolation_level=None)
        try:
            writer.execute("PRAGMA foreign_keys = ON")
            writer.execute("PRAGMA journal_mode = WAL")
            writer.execute("PRAGMA wal_autocheckpoint = 0")
            writer.execute("BEGIN IMMEDIATE")
            writer.execute(
                "INSERT INTO users "
                "(user_id, public_id, login_key, display_name, password_hash, status, "
                "created_at_us, updated_at_us) VALUES "
                "(1, ?, 'wal-user', 'WAL User', ?, 'ACTIVE', 1, 1)",
                ("w" * 32, "$argon2id$" + "x" * 30),
            )
            writer.commit()
            self.assertTrue(Path(f"{self.path}-wal").exists())
            self.assertTrue(Path(f"{self.path}-shm").exists())
            ordinary = sqlite3.connect(f"{self.path.as_uri()}?mode=ro", uri=True)
            immutable = sqlite3.connect(
                f"{self.path.as_uri()}?mode=ro&immutable=1", uri=True
            )
            try:
                self.assertEqual(ordinary.execute("SELECT count(*) FROM users").fetchone()[0], 1)
                self.assertEqual(immutable.execute("SELECT count(*) FROM users").fetchone()[0], 0)
            finally:
                ordinary.close()
                immutable.close()

            before = _database_file_state(self.path)
            operations = (
                self.context.diagnostics.diagnostics,
                self.context.diagnostics.diagnostics,
                self.context.diagnostics.migration_status,
                self.context.system.health,
                MigrationRunner(config(self.path, read_only=True)).verify,
            )
            for operation in operations:
                with self.subTest(operation=operation):
                    with self.assertRaises(DatabaseError) as caught:
                        operation()
                    self.assertEqual(caught.exception.code, "IMMUTABLE_SNAPSHOT_UNSAFE")
                    self.assertTrue(caught.exception.body.details["wal"])
                    self.assertTrue(caught.exception.body.details["shm"])
            self.assertEqual(before, _database_file_state(self.path))
            self.assertEqual(writer.execute("SELECT count(*) FROM users").fetchone()[0], 1)

            Path(f"{self.path}-shm").unlink()
            wal_only_before = _database_file_state(self.path)
            with self.assertRaises(DatabaseError) as wal_only:
                self.context.diagnostics.diagnostics()
            self.assertEqual(wal_only.exception.code, "IMMUTABLE_SNAPSHOT_UNSAFE")
            self.assertTrue(wal_only.exception.body.details["wal"])
            self.assertFalse(wal_only.exception.body.details["shm"])
            self.assertEqual(wal_only_before, _database_file_state(self.path))
        finally:
            writer.close()

    def test_crash_stale_wal_is_rejected_without_mutation(self) -> None:
        script = (
            "import os, sqlite3, sys; "
            "c=sqlite3.connect(sys.argv[1], isolation_level=None); "
            "c.execute('PRAGMA journal_mode=WAL'); "
            "c.execute('PRAGMA wal_autocheckpoint=0'); "
            "c.execute('BEGIN IMMEDIATE'); "
            "c.execute(\"INSERT INTO users "
            "(user_id,public_id,login_key,display_name,password_hash,status,"
            "created_at_us,updated_at_us) VALUES "
            "(1,?,'crash','Crash',?,'ACTIVE',1,1)\","
            "('c'*32,'$argon2id$'+'x'*30)); "
            "c.commit(); os._exit(0)"
        )
        subprocess.run([sys.executable, "-c", script, str(self.path)], check=True)
        self.assertTrue(Path(f"{self.path}-wal").exists())
        before = _database_file_state(self.path)
        with self.assertRaises(DatabaseError) as caught:
            self.context.diagnostics.diagnostics()
        self.assertEqual(caught.exception.code, "IMMUTABLE_SNAPSHOT_UNSAFE")
        self.assertEqual(before, _database_file_state(self.path))

    def test_zero_byte_sidecars_fail_closed_and_unrelated_names_are_ignored(self) -> None:
        for suffix in ("-wal", "-shm", "-journal"):
            with self.subTest(suffix=suffix):
                sidecar = Path(f"{self.path}{suffix}")
                sidecar.touch()
                before = _database_file_state(self.path)
                with self.assertRaises(DatabaseError) as caught:
                    self.context.diagnostics.diagnostics()
                self.assertEqual(caught.exception.code, "IMMUTABLE_SNAPSHOT_UNSAFE")
                self.assertEqual(before, _database_file_state(self.path))
                sidecar.unlink()
        Path(f"{self.path}-wal-backup").write_text("unrelated", encoding="utf-8")
        Path(f"{self.path}-shm.old").write_text("unrelated", encoding="utf-8")
        diagnostics = self.context.diagnostics.diagnostics()
        self.assertFalse(diagnostics.wal_present)
        self.assertFalse(diagnostics.shm_present)

    def test_missing_database_is_typed_and_not_created(self) -> None:
        missing = Path(self.temporary.name) / "missing.db"
        context = build_application_context(config(missing, read_only=True))
        with self.assertRaises((DatabaseError, MigrationError)) as caught:
            context.diagnostics.diagnostics()
        self.assertEqual(caught.exception.code, "DATABASE_NOT_FOUND")
        self.assertFalse(missing.exists())

    def test_wrong_application_id_and_user_version_are_non_mutating_failures(self) -> None:
        for pragma, value, expected in (
            ("application_id", 1, "INVALID_APPLICATION_ID"),
            ("user_version", 7, "SCHEMA_VERSION_MISMATCH"),
        ):
            with self.subTest(pragma=pragma):
                copy = Path(self.temporary.name) / f"wrong-{pragma}.db"
                copy.write_bytes(self.path.read_bytes())
                connection = sqlite3.connect(copy)
                connection.execute(f"PRAGMA {pragma} = {value}")
                connection.close()
                before = hashlib.sha256(copy.read_bytes()).hexdigest()
                runner = MigrationRunner(config(copy, read_only=True))
                with self.assertRaises(MigrationError) as caught:
                    runner.verify()
                self.assertEqual(caught.exception.code, expected)
                self.assertEqual(before, hashlib.sha256(copy.read_bytes()).hexdigest())

    def test_old_database_application_id_is_rejected_by_health(self) -> None:
        old = Path(self.temporary.name) / "old.db"
        connection = sqlite3.connect(old)
        connection.execute("CREATE TABLE legacy_example(id INTEGER PRIMARY KEY)")
        connection.close()
        before = (hashlib.sha256(old.read_bytes()).hexdigest(), old.stat().st_mtime_ns)
        context = build_application_context(config(old, read_only=True))
        with self.assertRaises(DatabaseError) as caught:
            context.system.health()
        self.assertEqual(caught.exception.code, "INVALID_APPLICATION_ID")
        self.assertEqual(
            before, (hashlib.sha256(old.read_bytes()).hexdigest(), old.stat().st_mtime_ns)
        )

    def test_foreign_key_violation_is_reported_by_health(self) -> None:
        connection = sqlite3.connect(self.path)
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute(
            "INSERT INTO role_permissions "
            "(role_id, permission_code, granted_at_us) VALUES (900, 'missing', 1)"
        )
        connection.commit()
        connection.close()
        diagnostics = self.context.diagnostics.diagnostics()
        health = self.context.system.health()
        self.assertGreater(diagnostics.foreign_key_violations, 0)
        self.assertEqual(health.status, HealthStatus.FOREIGN_KEY_FAILED)

    def test_truncated_disposable_database_fails_without_mutation(self) -> None:
        corrupt = Path(self.temporary.name) / "corrupt.db"
        corrupt.write_bytes(self.path.read_bytes())
        with corrupt.open("r+b") as stream:
            stream.truncate(4096)
        before = (hashlib.sha256(corrupt.read_bytes()).hexdigest(), os.stat(corrupt).st_mtime_ns)
        context = build_application_context(config(corrupt, read_only=True))
        with self.assertRaises((DatabaseError, MigrationError)):
            context.system.health()
        after = (hashlib.sha256(corrupt.read_bytes()).hexdigest(), os.stat(corrupt).st_mtime_ns)
        self.assertEqual(before, after)

    def test_health_policy_maps_all_critical_diagnostic_states(self) -> None:
        clean = self.context.diagnostics.diagnostics()

        class StaticDiagnostics:
            def __init__(self, diagnostics: DatabaseDiagnostics) -> None:
                self._diagnostics = diagnostics

            def diagnostics(self) -> DatabaseDiagnostics:
                return self._diagnostics

            def migration_status(self) -> MigrationStatus:
                return self._diagnostics.migrations

        cases = (
            (replace(clean, integrity_result="corrupt"), HealthStatus.INTEGRITY_FAILED),
            (replace(clean, foreign_key_violations=1), HealthStatus.FOREIGN_KEY_FAILED),
            (replace(clean, user_version=7), HealthStatus.UNSUPPORTED_VERSION),
            (replace(clean, schema_ready=False), HealthStatus.INVALID_SCHEMA),
            (
                replace(clean, baseline_state=BaselineState.INCONSISTENT),
                HealthStatus.DEGRADED,
            ),
        )
        for diagnostics, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(
                    SystemService(StaticDiagnostics(diagnostics)).health().status,
                    expected,
                )


if __name__ == "__main__":
    unittest.main()
