from __future__ import annotations

import hashlib
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock

# Initialize the existing package graph before importing Warehouse submodules directly.
from inventory.core.application import create_application_context  # noqa: F401
from inventory.db import initialize
from scripts import create_clean_test_db

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "create_clean_test_db.py"


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_script(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def build_source(path: Path) -> None:
    """Create a small but realistic working database with operational rows."""
    initialize(path)
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(
            """INSERT INTO stock_receipts(
                   receipt_date, responsible, item_name, serial_number, inventory_number,
                   supplier, vendor, model, object_name, datacenter, equipment_type, unit, quantity
               ) VALUES ('2026-01-01','Инженер','Сервер','SRC-SN-0001','SRC-INV-0001',
                         'Supplier','Dell','R650','Склад','Ixcellerate','Сервер','шт',1)"""
        )
        connection.execute(
            """INSERT INTO work_logs(work_date, task_source, task_type, task_number, description, status)
               VALUES ('2026-01-01','Rooms','ПНР','1','Работа','Выполнено')"""
        )
        connection.commit()


def preserved_rows(path: Path) -> dict[str, list[tuple[object, ...]]]:
    with closing(sqlite3.connect(path)) as connection:
        return {
            table: [tuple(row) for row in connection.execute(f"SELECT * FROM {table} ORDER BY rowid")]
            for table in create_clean_test_db.PRESERVED_TABLES
        }


class CreateCleanTestDbTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp_path = Path(self._tmp.name)
        self.source = self.tmp_path / "warehouse.db"
        build_source(self.source)
        self.source_sha_initial = file_sha256(self.source)

    def assertSourceUnchanged(self) -> None:
        self.assertEqual(file_sha256(self.source), self.source_sha_initial)

    def test_dry_run_creates_no_files_and_reports_counts(self) -> None:
        output = self.tmp_path / "clean.db"
        result = run_script("--source", str(self.source), "--output", str(output), "--dry-run")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(output.exists())
        self.assertIn("stock_receipts", result.stdout)
        self.assertSourceUnchanged()

    def test_source_equal_to_output_is_rejected(self) -> None:
        result = run_script("--source", str(self.source), "--output", str(self.source), "--overwrite")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("не могут указывать на один и тот же файл", result.stdout + result.stderr)
        self.assertSourceUnchanged()

    def test_source_hardlink_as_output_is_rejected(self) -> None:
        output = self.tmp_path / "source_hardlink.db"
        os.link(self.source, output)
        result = run_script("--source", str(self.source), "--output", str(output), "--overwrite")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("не могут указывать на один и тот же файл", result.stdout + result.stderr)
        self.assertSourceUnchanged()

    def test_missing_source_is_rejected(self) -> None:
        missing = self.tmp_path / "does_not_exist.db"
        output = self.tmp_path / "clean.db"
        result = run_script("--source", str(missing), "--output", str(output))
        self.assertNotEqual(result.returncode, 0)

    def test_empty_profile_clears_operational_data_and_keeps_references(self) -> None:
        output = self.tmp_path / "clean_empty.db"
        expected_preserved_rows = preserved_rows(self.source)
        result = run_script("--source", str(self.source), "--output", str(output), "--profile", "empty")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(output.exists())
        with closing(sqlite3.connect(output)) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM stock_receipts").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM work_logs").fetchone()[0], 0)
            self.assertGreater(connection.execute("SELECT COUNT(*) FROM users").fetchone()[0], 0)
            self.assertGreater(connection.execute("SELECT COUNT(*) FROM reference_values").fetchone()[0], 0)
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
        self.assertEqual(preserved_rows(output), expected_preserved_rows)
        self.assertSourceUnchanged()

    def test_existing_output_requires_overwrite(self) -> None:
        output = self.tmp_path / "clean_twice.db"
        first = run_script("--source", str(self.source), "--output", str(output), "--profile", "empty")
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        second = run_script("--source", str(self.source), "--output", str(output), "--profile", "empty")
        self.assertNotEqual(second.returncode, 0)
        self.assertIn("--overwrite", second.stdout + second.stderr)
        third = run_script(
            "--source", str(self.source), "--output", str(output), "--profile", "empty", "--overwrite",
        )
        self.assertEqual(third.returncode, 0, third.stdout + third.stderr)
        self.assertSourceUnchanged()

    def test_demo_profile_seeds_operational_data_and_passes_integrity(self) -> None:
        output = self.tmp_path / "clean_demo.db"
        result = run_script(
            "--source", str(self.source), "--output", str(output), "--profile", "demo", "--overwrite",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        with closing(sqlite3.connect(output)) as connection:
            self.assertGreater(connection.execute("SELECT COUNT(*) FROM stock_receipts").fetchone()[0], 0)
            self.assertGreater(connection.execute("SELECT COUNT(*) FROM stock_issues").fetchone()[0], 0)
            # The demo receipt seeded by the source-building helper above must
            # not leak into the demo dataset produced by the script.
            leftover = connection.execute(
                "SELECT COUNT(*) FROM stock_receipts WHERE serial_number = 'SRC-SN-0001'"
            ).fetchone()[0]
            self.assertEqual(leftover, 0)
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
        self.assertSourceUnchanged()

    def test_source_connection_is_sqlite_enforced_read_only(self) -> None:
        with closing(create_clean_test_db.connect_source_readonly(self.source)) as connection:
            self.assertEqual(connection.execute("PRAGMA query_only").fetchone()[0], 1)
            with self.assertRaises(sqlite3.OperationalError):
                connection.execute(
                    "INSERT INTO reference_values(kind, name) VALUES ('supplier', 'forbidden')"
                )
        self.assertSourceUnchanged()

    def test_wal_snapshot_includes_committed_rows_without_changing_source_files(self) -> None:
        output = self.tmp_path / "clean_wal.db"
        writer = sqlite3.connect(self.source)
        self.addCleanup(writer.close)
        self.assertEqual(writer.execute("PRAGMA journal_mode = WAL").fetchone()[0], "wal")
        writer.execute("PRAGMA wal_autocheckpoint = 0")
        writer.execute(
            "INSERT INTO reference_values(kind, name) VALUES ('supplier', 'WAL Snapshot Supplier')"
        )
        writer.commit()

        wal_path = Path(str(self.source) + "-wal")
        self.assertTrue(wal_path.exists())
        source_before = create_clean_test_db.source_content_state(self.source)

        result = run_script(
            "--source", str(self.source), "--output", str(output), "--profile", "empty"
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(create_clean_test_db.source_content_state(self.source), source_before)
        with closing(sqlite3.connect(output)) as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM reference_values WHERE name='WAL Snapshot Supplier'"
            ).fetchone()[0]
            self.assertEqual(count, 1)
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_demo_seed_runs_with_foreign_keys_enabled(self) -> None:
        output = self.tmp_path / "clean_fk.db"
        observed: list[int] = []
        original_seed = create_clean_test_db.seed_demo_data

        def observing_seed(connection: sqlite3.Connection) -> None:
            observed.append(int(connection.execute("PRAGMA foreign_keys").fetchone()[0]))
            original_seed(connection)

        with mock.patch.object(create_clean_test_db, "seed_demo_data", observing_seed):
            result = create_clean_test_db.main([
                "--source", str(self.source), "--output", str(output), "--profile", "demo"
            ])
        self.assertEqual(result, 0)
        self.assertEqual(observed, [1])
        self.assertSourceUnchanged()

    def test_foreign_key_failure_does_not_publish_output(self) -> None:
        output = self.tmp_path / "existing_fk.db"
        sentinel = b"existing output must survive"
        output.write_bytes(sentinel)

        def invalid_seed(connection: sqlite3.Connection) -> None:
            self.assertEqual(connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)
            connection.execute(
                "INSERT INTO stock_issue_allocations(issue_id, receipt_id, quantity) "
                "VALUES (999999, 999999, 1)"
            )

        with mock.patch.object(create_clean_test_db, "seed_demo_data", invalid_seed):
            result = create_clean_test_db.main([
                "--source", str(self.source), "--output", str(output),
                "--profile", "demo", "--overwrite",
            ])
        self.assertEqual(result, 1)
        self.assertEqual(output.read_bytes(), sentinel)
        self.assertSourceUnchanged()

    def test_atomic_replace_failure_preserves_existing_output_and_cleans_staging(self) -> None:
        output = self.tmp_path / "existing_atomic.db"
        sentinel = b"old verified database"
        output.write_bytes(sentinel)

        with mock.patch.object(
            create_clean_test_db.os, "replace", side_effect=OSError("simulated replace failure")
        ):
            result = create_clean_test_db.main([
                "--source", str(self.source), "--output", str(output),
                "--profile", "empty", "--overwrite",
            ])
        self.assertEqual(result, 1)
        self.assertEqual(output.read_bytes(), sentinel)
        self.assertEqual(list(self.tmp_path.glob(f".{output.name}.*.tmp")), [])
        self.assertSourceUnchanged()

    def test_output_sidecar_blocks_overwrite(self) -> None:
        output = self.tmp_path / "existing_with_sidecar.db"
        output.write_bytes(b"old database")
        sidecar = Path(str(output) + "-journal")
        sidecar.write_bytes(b"possible active journal")

        result = run_script(
            "--source", str(self.source), "--output", str(output),
            "--profile", "empty", "--overwrite",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("sidecar", result.stdout + result.stderr)
        self.assertEqual(output.read_bytes(), b"old database")
        self.assertEqual(sidecar.read_bytes(), b"possible active journal")
        self.assertSourceUnchanged()

    def test_test_launchers_isolate_environment_and_select_disposable_database(self) -> None:
        macos = (ROOT / "start_test_macos.command").read_text(encoding="utf-8")
        windows = (ROOT / "start_test_windows.bat").read_text(encoding="utf-8")
        self.assertIn(
            "ODE_TEST_MODE=1 python3 app.py web --db data/warehouse_test_clean.db",
            macos,
        )
        self.assertNotIn("export ODE_TEST_MODE", macos)
        self.assertIn("setlocal", windows.casefold())
        self.assertIn("set ODE_TEST_MODE=1", windows)
        self.assertIn("--db data\\warehouse_test_clean.db", windows)
        self.assertIn("endlocal", windows.casefold())

    def test_test_mode_rejects_the_working_database(self) -> None:
        from inventory import webapp

        with mock.patch.object(webapp, "ODE_TEST_MODE", True):
            with self.assertRaisesRegex(RuntimeError, "нельзя использовать с рабочей"):
                webapp._validate_test_mode_database(webapp.DEFAULT_DB_PATH)
            webapp._validate_test_mode_database(self.tmp_path / "separate_test.db")
        environment = {**os.environ, "ODE_TEST_MODE": "1"}
        banner_probe = subprocess.run(
            [
                sys.executable,
                "-c",
                "from inventory import webapp; "
                "assert 'ТЕСТОВЫЙ КОНТУР' in webapp.HTML; "
                "assert 'ТЕСТОВЫЙ КОНТУР' in webapp.LOGIN_HTML",
            ],
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(
            banner_probe.returncode,
            0,
            banner_probe.stdout + banner_probe.stderr,
        )


if __name__ == "__main__":
    unittest.main()
