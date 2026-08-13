from __future__ import annotations

import hashlib
import json
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
from inventory.core.web_runtime import validate_runtime_database_contours
from inventory.db import initialize
from inventory.shared.runtime_paths import install_test_contour_marker
from inventory.vacations.schema import DEFAULT_VACATIONS_DB_PATH
from inventory.warehouse.sites import SOLAR_DB_PATH
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


def add_promoted_migration_provenance(path: Path) -> None:
    """Model the FK chain present in the promoted historical working DB."""
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("PRAGMA foreign_keys = ON")
        receipt_id = int(
            connection.execute(
                "SELECT id FROM stock_receipts WHERE serial_number='SRC-SN-0001'"
            ).fetchone()[0]
        )
        connection.executescript(
            """
            CREATE TABLE migration_batches(id INTEGER PRIMARY KEY);
            CREATE TABLE migration_source_files(
                id INTEGER PRIMARY KEY,
                batch_id INTEGER REFERENCES migration_batches(id)
            );
            CREATE TABLE migration_staging_rows(
                id INTEGER PRIMARY KEY,
                source_file_id INTEGER REFERENCES migration_source_files(id)
            );
            CREATE TABLE migration_full_identities(
                id INTEGER PRIMARY KEY,
                primary_staging_row_id INTEGER REFERENCES migration_staging_rows(id),
                target_receipt_id INTEGER REFERENCES stock_receipts(id)
            );
            CREATE TABLE migration_full_reconciliation(
                id INTEGER PRIMARY KEY,
                staging_row_id INTEGER REFERENCES migration_staging_rows(id),
                target_identity_id INTEGER REFERENCES migration_full_identities(id),
                target_receipt_id INTEGER REFERENCES stock_receipts(id),
                target_issue_id INTEGER REFERENCES stock_issues(id)
            );
            CREATE TABLE migration_full_warnings(
                id INTEGER PRIMARY KEY,
                reconciliation_id INTEGER REFERENCES migration_full_reconciliation(id),
                identity_id INTEGER REFERENCES migration_full_identities(id)
            );
            INSERT INTO migration_batches VALUES (1);
            INSERT INTO migration_source_files VALUES (1, 1);
            INSERT INTO migration_staging_rows VALUES (1, 1);
            """
        )
        connection.execute(
            "INSERT INTO migration_full_identities VALUES (1, 1, ?)", (receipt_id,)
        )
        connection.execute(
            "INSERT INTO migration_full_reconciliation VALUES (1, 1, 1, ?, NULL)",
            (receipt_id,),
        )
        connection.execute("INSERT INTO migration_full_warnings VALUES (1, 1, 1)")


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

    def test_output_cannot_alias_any_runtime_database(self) -> None:
        from inventory.shared import runtime_paths

        for label in runtime_paths.RUNTIME_DATABASE_PATHS:
            protected = self.tmp_path / f"protected-{label}.db"
            protected.write_bytes(b"protected runtime sentinel")
            with self.subTest(runtime=label), mock.patch.dict(
                runtime_paths.RUNTIME_DATABASE_PATHS, {label: protected}, clear=True
            ):
                result = create_clean_test_db.main(
                    [
                        "--source", str(self.source),
                        "--output", str(protected),
                        "--overwrite",
                    ]
                )
                self.assertEqual(result, 1)
                self.assertEqual(protected.read_bytes(), b"protected runtime sentinel")

            future_protected = self.tmp_path / f"Future-Protected-{label}.db"
            casefold_alias = self.tmp_path / f"future-protected-{label}.DB"
            with self.subTest(runtime=f"{label}-future-casefold"), mock.patch.dict(
                runtime_paths.RUNTIME_DATABASE_PATHS,
                {label: future_protected},
                clear=True,
            ):
                result = create_clean_test_db.main(
                    [
                        "--source", str(self.source),
                        "--output", str(casefold_alias),
                    ]
                )
                self.assertEqual(result, 1)
                self.assertFalse(future_protected.exists())
                self.assertFalse(casefold_alias.exists())
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
            self.assertIsNone(
                connection.execute(
                    """SELECT 1 FROM sqlite_master
                       WHERE type='table' AND name='vacation_employees'"""
                ).fetchone()
            )
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

    def test_overwrite_rejects_unmarked_custom_existing_database(self) -> None:
        output = self.tmp_path / "custom-production.db"
        with closing(sqlite3.connect(output)) as connection, connection:
            connection.execute("CREATE TABLE production_marker(id INTEGER PRIMARY KEY)")
        before = output.read_bytes()
        result = create_clean_test_db.main(
            [
                "--source", str(self.source),
                "--output", str(output),
                "--profile", "empty",
                "--overwrite",
            ]
        )
        self.assertEqual(result, 1)
        self.assertEqual(output.read_bytes(), before)
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

    def test_promoted_migration_provenance_is_cleared_before_receipts(self) -> None:
        add_promoted_migration_provenance(self.source)
        self.source_sha_initial = file_sha256(self.source)
        output = self.tmp_path / "clean_promoted.db"

        result = run_script(
            "--source", str(self.source), "--output", str(output), "--profile", "demo"
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        with closing(sqlite3.connect(output)) as connection:
            for table in create_clean_test_db.MIGRATION_TABLES_IN_DROP_ORDER:
                self.assertIsNone(
                    connection.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
                    ).fetchone(),
                    table,
                )
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

    def test_idle_persistent_wal_source_does_not_gain_reader_sidecars(self) -> None:
        output = self.tmp_path / "clean_idle_wal.db"
        with closing(sqlite3.connect(self.source)) as connection:
            self.assertEqual(connection.execute("PRAGMA journal_mode = WAL").fetchone()[0], "wal")
        for suffix in ("-wal", "-shm", "-journal"):
            Path(str(self.source) + suffix).unlink(missing_ok=True)
        self.source_sha_initial = file_sha256(self.source)
        source_state_before = create_clean_test_db.source_content_state(self.source)

        result = run_script(
            "--source", str(self.source), "--output", str(output), "--profile", "empty"
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(output.is_file())
        self.assertEqual(
            create_clean_test_db.source_content_state(self.source), source_state_before
        )
        for suffix in ("-wal", "-shm", "-journal"):
            self.assertFalse(Path(str(self.source) + suffix).exists(), suffix)
        self.assertSourceUnchanged()

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
        self.assertEqual(
            create_clean_test_db.main(
                ["--source", str(self.source), "--output", str(output)]
            ),
            0,
        )
        sentinel = output.read_bytes()

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
        self.assertEqual(
            create_clean_test_db.main(
                ["--source", str(self.source), "--output", str(output)]
            ),
            0,
        )
        sentinel = output.read_bytes()

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

    def test_pre_publish_sidecar_race_preserves_existing_output(self) -> None:
        output = self.tmp_path / "sidecar_race.db"
        self.assertEqual(
            create_clean_test_db.main(
                ["--source", str(self.source), "--output", str(output)]
            ),
            0,
        )
        sentinel = output.read_bytes()
        inode = output.stat().st_ino
        sidecar = Path(str(output) + "-wal")
        real_copyfile = create_clean_test_db.shutil.copyfile

        def racing_copyfile(source: Path, destination: Path) -> str:
            copied = real_copyfile(source, destination)
            sidecar.write_bytes(b"active writer appeared during build")
            return copied

        with mock.patch.object(
            create_clean_test_db.shutil,
            "copyfile",
            side_effect=racing_copyfile,
        ):
            result = create_clean_test_db.main([
                "--source", str(self.source), "--output", str(output), "--overwrite",
            ])

        self.assertEqual(result, 1)
        self.assertEqual(output.stat().st_ino, inode)
        self.assertEqual(output.read_bytes(), sentinel)
        self.assertEqual(sidecar.read_bytes(), b"active writer appeared during build")
        self.assertEqual(list(self.tmp_path.glob(f".{output.name}.*.tmp")), [])

    def test_pre_publish_target_replacement_is_not_overwritten(self) -> None:
        output = self.tmp_path / "identity_race.db"
        self.assertEqual(
            create_clean_test_db.main(
                ["--source", str(self.source), "--output", str(output)]
            ),
            0,
        )
        sentinel = output.read_bytes()
        replacement = self.tmp_path / "replacement.db"
        raced_inode: list[int] = []
        real_copyfile = create_clean_test_db.shutil.copyfile

        def racing_copyfile(source: Path, destination: Path) -> str:
            copied = real_copyfile(source, destination)
            replacement.write_bytes(sentinel)
            os.replace(replacement, output)
            raced_inode.append(output.stat().st_ino)
            return copied

        with mock.patch.object(
            create_clean_test_db.shutil,
            "copyfile",
            side_effect=racing_copyfile,
        ):
            result = create_clean_test_db.main([
                "--source", str(self.source), "--output", str(output), "--overwrite",
            ])

        self.assertEqual(result, 1)
        self.assertEqual(output.stat().st_ino, raced_inode[0])
        self.assertEqual(output.read_bytes(), sentinel)
        self.assertEqual(list(self.tmp_path.glob(f".{output.name}.*.tmp")), [])

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
            "python3 scripts/create_clean_test_db.py --source data/warehouse_solar.db --output data/warehouse_solar_test_disposable_v1.db --profile empty --overwrite",
            macos,
        )
        self.assertIn("python3 scripts/create_clean_vacations_test_db.py --overwrite", macos)
        self.assertIn("--db data/warehouse_test_disposable_v1.db", macos)
        self.assertIn("--solar-db data/warehouse_solar_test_disposable_v1.db", macos)
        self.assertIn("--vacations-db data/vacations_test_disposable_v1.db", macos)
        self.assertNotIn("export ODE_TEST_MODE", macos)
        self.assertIn("setlocal", windows.casefold())
        self.assertIn("set ODE_TEST_MODE=1", windows)
        self.assertIn("--db data\\warehouse_test_disposable_v1.db", windows)
        self.assertIn("--solar-db data\\warehouse_solar_test_disposable_v1.db", windows)
        self.assertIn("--vacations-db data\\vacations_test_disposable_v1.db", windows)
        self.assertIn("create_clean_vacations_test_db.py --overwrite", windows)
        self.assertIn("endlocal", windows.casefold())

    def test_test_mode_rejects_the_working_database(self) -> None:
        safe_paths = {
            "primary": self.tmp_path / "primary.db",
            "solar": self.tmp_path / "solar.db",
            "vacations": self.tmp_path / "vacations.db",
        }
        for name, path in safe_paths.items():
            with closing(sqlite3.connect(path)) as connection, connection:
                install_test_contour_marker(
                    connection, "vacations" if name == "vacations" else "warehouse"
                )
        with self.assertRaisesRegex(RuntimeError, "требует явные"):
            validate_runtime_database_contours(
                test_mode=True, db_path=safe_paths["primary"]
            )
        with self.assertRaisesRegex(RuntimeError, "нельзя использовать с рабочей"):
            validate_runtime_database_contours(
                test_mode=True,
                db_path=create_clean_test_db.DEFAULT_DB_PATH,
                solar_db_path=safe_paths["solar"],
                vacations_db_path=safe_paths["vacations"],
            )
        with self.assertRaisesRegex(RuntimeError, "Solar"):
            validate_runtime_database_contours(
                test_mode=True,
                db_path=safe_paths["primary"],
                solar_db_path=SOLAR_DB_PATH,
                vacations_db_path=safe_paths["vacations"],
            )
        with self.assertRaisesRegex(RuntimeError, "Vacations"):
            validate_runtime_database_contours(
                test_mode=True,
                db_path=safe_paths["primary"],
                solar_db_path=safe_paths["solar"],
                vacations_db_path=DEFAULT_VACATIONS_DB_PATH,
            )
        validate_runtime_database_contours(
            test_mode=True,
            db_path=safe_paths["primary"],
            solar_db_path=safe_paths["solar"],
            vacations_db_path=safe_paths["vacations"],
        )

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

    def test_normal_mode_rejects_every_marked_test_database(self) -> None:
        ordinary = self.tmp_path / "ordinary.db"
        with closing(sqlite3.connect(ordinary)) as connection, connection:
            connection.execute("CREATE TABLE ordinary(id INTEGER PRIMARY KEY)")
        marked = {
            "IXcellerate": (self.tmp_path / "marked-ix.db", "warehouse"),
            "Solar": (self.tmp_path / "marked-solar.db", "warehouse"),
            "Vacations": (self.tmp_path / "marked-vacations.db", "vacations"),
        }
        for path, role in marked.values():
            with closing(sqlite3.connect(path)) as connection, connection:
                install_test_contour_marker(connection, role)

        selections = {
            "IXcellerate": (marked["IXcellerate"][0], None, None),
            "Solar": (ordinary, marked["Solar"][0], None),
            "Vacations": (ordinary, None, marked["Vacations"][0]),
        }
        for label, (primary, solar, vacations) in selections.items():
            before = {path.name: path.read_bytes() for path in self.tmp_path.iterdir()}
            with self.subTest(database=label), self.assertRaisesRegex(
                RuntimeError, "test contour marker/state"
            ):
                validate_runtime_database_contours(
                    test_mode=False,
                    db_path=primary,
                    solar_db_path=solar,
                    vacations_db_path=vacations,
                )
            after = {path.name: path.read_bytes() for path in self.tmp_path.iterdir()}
            self.assertEqual(after, before)

    def test_normal_web_start_rejects_marked_primary_before_any_write(self) -> None:
        from inventory import webapp

        marked = self.tmp_path / "marked-primary.db"
        with closing(sqlite3.connect(marked)) as connection, connection:
            install_test_contour_marker(connection, "warehouse")
        before = {path.name: path.read_bytes() for path in self.tmp_path.iterdir()}

        with mock.patch.object(webapp, "ODE_TEST_MODE", False), self.assertRaises(
            SystemExit
        ) as stopped:
            webapp.main(["--db", str(marked), "--no-browser", "--port", "0"])

        self.assertEqual(stopped.exception.code, 2)
        self.assertEqual(
            {path.name: path.read_bytes() for path in self.tmp_path.iterdir()},
            before,
        )
        self.assertFalse((self.tmp_path / "vacations.db").exists())

    def test_demo_mode_rejects_any_installation_runtime_database(self) -> None:
        safe_primary = self.tmp_path / "safe-demo.db"
        with closing(sqlite3.connect(safe_primary)) as connection, connection:
            connection.execute("CREATE TABLE ordinary(id INTEGER PRIMARY KEY)")
        with self.assertRaisesRegex(RuntimeError, "Demo contour.*Solar"):
            validate_runtime_database_contours(
                test_mode=False,
                db_path=safe_primary,
                solar_db_path=SOLAR_DB_PATH,
                vacations_db_path=self.tmp_path / "safe-vacations.db",
                warehouse_contour="demo",
            )

    def test_runtime_validation_rejects_selected_sidecar_before_writes(self) -> None:
        selected = self.tmp_path / "selected.db"
        with closing(sqlite3.connect(selected)) as connection, connection:
            install_test_contour_marker(connection, "warehouse")
        sidecar = Path(str(selected) + "-wal")
        sidecar.write_bytes(b"possible active writer")
        before = {path.name: path.read_bytes() for path in self.tmp_path.iterdir()}

        with self.assertRaisesRegex(RuntimeError, "SQLite sidecar"):
            validate_runtime_database_contours(
                test_mode=False,
                db_path=selected,
            )

        self.assertEqual(
            {path.name: path.read_bytes() for path in self.tmp_path.iterdir()},
            before,
        )

    def test_selected_runtime_aliases_fail_before_any_startup_write(self) -> None:
        from inventory.core.web_runtime import prepare_web_runtime

        primary = self.tmp_path / "selected-primary.db"
        build_source(primary)
        alias = self.tmp_path / "selected-solar-hardlink.db"
        os.link(primary, alias)
        before = {path.name: path.read_bytes() for path in self.tmp_path.iterdir()}

        with self.assertRaisesRegex(RuntimeError, "один файл"):
            prepare_web_runtime(
                db_path=primary,
                solar_db_path=alias,
                vacations_db_path=self.tmp_path / "would-have-been-created.db",
                warehouse_contour="production",
                inventory_state_root=None,
                test_mode=False,
            )

        self.assertEqual(
            {path.name: path.read_bytes() for path in self.tmp_path.iterdir()},
            before,
        )
        self.assertFalse((self.tmp_path / "would-have-been-created.db").exists())

    def test_runtime_symlink_and_malformed_test_marker_fail_closed(self) -> None:
        real = self.tmp_path / "real.db"
        with closing(sqlite3.connect(real)) as connection, connection:
            connection.execute("CREATE TABLE ordinary(id INTEGER PRIMARY KEY)")
        alias = self.tmp_path / "alias.db"
        alias.symlink_to(real)
        Path(str(real) + "-wal").write_bytes(b"target-sidecar")
        with self.assertRaisesRegex(RuntimeError, "symbolic link"):
            validate_runtime_database_contours(
                test_mode=False,
                db_path=alias,
            )

        malformed = self.tmp_path / "malformed-marker.db"
        with closing(sqlite3.connect(malformed)) as connection, connection:
            connection.execute(
                "CREATE TABLE ode_test_contour_marker("
                "id INTEGER PRIMARY KEY, marker TEXT, database_role TEXT)"
            )
            connection.execute(
                "INSERT INTO ode_test_contour_marker VALUES (1, 'WRONG', 'warehouse')"
            )
        before = malformed.read_bytes()
        with self.assertRaisesRegex(RuntimeError, "повреждённый marker"):
            validate_runtime_database_contours(
                test_mode=False,
                db_path=malformed,
            )
        self.assertEqual(malformed.read_bytes(), before)

    def test_existing_non_regular_runtime_path_fails_before_sibling_write(self) -> None:
        from inventory.core.web_runtime import prepare_web_runtime

        selected = self.tmp_path / "directory-instead-of-db"
        selected.mkdir()
        vacations = self.tmp_path / "must-not-be-created.db"

        with self.assertRaisesRegex(RuntimeError, "marker/state invalid"):
            prepare_web_runtime(
                db_path=selected,
                solar_db_path=None,
                vacations_db_path=vacations,
                warehouse_contour="production",
                inventory_state_root=None,
                test_mode=False,
            )

        self.assertFalse(vacations.exists())

    def test_future_database_names_cannot_collide_by_case(self) -> None:
        upper = self.tmp_path / "Future-Warehouse.db"
        lower = self.tmp_path / "future-warehouse.DB"

        with self.assertRaisesRegex(RuntimeError, "один файл"):
            validate_runtime_database_contours(
                test_mode=False,
                db_path=upper,
                solar_db_path=lower,
                vacations_db_path=self.tmp_path / "vacations-future.db",
            )

        self.assertFalse(upper.exists())
        self.assertFalse(lower.exists())

    def test_test_runtime_isolates_all_auxiliary_state_and_external_monitoring(self) -> None:
        from inventory.core.web_runtime import prepare_web_runtime
        from inventory.vacations.schema import install_vacations_schema

        primary = self.tmp_path / "isolated-primary.db"
        solar = self.tmp_path / "isolated-solar.db"
        vacations = self.tmp_path / "isolated-vacations.db"
        build_source(primary)
        build_source(solar)
        install_vacations_schema(vacations)
        for path, role in (
            (primary, "warehouse"),
            (solar, "warehouse"),
            (vacations, "vacations"),
        ):
            with closing(sqlite3.connect(path)) as connection, connection:
                install_test_contour_marker(connection, role)
        forbidden_aux_root = self.tmp_path / "production-aux-must-stay-absent"
        production_legacy_backups = self.tmp_path / "backups"
        production_runtime_backups = self.tmp_path / "ode-runtime-backups"
        for backup_root in (production_legacy_backups, production_runtime_backups):
            backup_root.mkdir()
            (backup_root / "production-sentinel.db").write_bytes(b"do not read or write")
        production_backup_state = {
            path: {item.name: item.read_bytes() for item in path.iterdir()}
            for path in (production_legacy_backups, production_runtime_backups)
        }
        production_rules = self.tmp_path / "production-monitoring-rules"
        production_rules.mkdir()
        (production_rules / "Hostname Tech.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "cc_exclusions": [],
                    "global_cc": [],
                    "rules": [
                        {
                            "hostname_pattern": "prod-only-host",
                            "match_type": "exact",
                            "project": "X5Tech",
                            "is_salt": False,
                            "to": ["Prod.Owner"],
                            "cc": [],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        (production_rules / "Hostname Digital.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "default_to": [],
                    "default_cc": [],
                    "hostnames": [],
                }
            ),
            encoding="utf-8",
        )

        with mock.patch.dict(
            os.environ,
            {"ODE_MONITORING_RULES_DIR": str(production_rules)},
            clear=False,
        ):
            runtime = prepare_web_runtime(
                db_path=primary,
                solar_db_path=solar,
                vacations_db_path=vacations,
                warehouse_contour="demo",
                inventory_state_root=forbidden_aux_root,
                test_mode=True,
            )
        try:
            inventory_root = runtime.app_context.full_inventory.paths.root
            knowledge_root = runtime.app_context.knowledge.upload_root
            owned_root = inventory_root.parent
            self.assertEqual(knowledge_root.parent, owned_root)
            legacy_backup_root = runtime.app_context.administration.backup_dir
            runtime_backup_root = (
                runtime.app_context.administration.service
                .multi_database_backup_service.backup_root
            )
            self.assertEqual(legacy_backup_root, owned_root / "backups")
            self.assertEqual(runtime_backup_root, owned_root / "backups")
            self.assertEqual(inventory_root.name, "full_inventory")
            self.assertEqual(knowledge_root.name, "knowledge_uploads")
            self.assertNotEqual(inventory_root, forbidden_aux_root.resolve())
            capabilities = runtime.app_context.monitoring.module_status()["capabilities"]
            monitoring_configuration = runtime.app_context.monitoring.module_status()[
                "configuration"
            ]
            monitoring_rules = runtime.app_context.monitoring._rules_dir
            self.assertEqual(monitoring_rules, owned_root / "monitoring_rules")
            self.assertTrue(monitoring_rules.is_dir())
            self.assertTrue(monitoring_configuration["rules_configured"])
            self.assertFalse(capabilities["external_collection"])
            self.assertTrue(capabilities["development_mock"])
            decision = runtime.app_context.monitoring.resolve_hostname("prod-only-host")
            self.assertEqual(decision.project, "")
            self.assertNotIn("Prod.Owner", decision.to)
            overview = runtime.app_context.administration.get_administration_overview()
            self.assertEqual(overview["backups"], [])
            self.assertEqual(
                {
                    path: {item.name: item.read_bytes() for item in path.iterdir()}
                    for path in (production_legacy_backups, production_runtime_backups)
                },
                production_backup_state,
            )
            self.assertTrue(owned_root.is_dir())
            self.assertFalse(forbidden_aux_root.exists())
        finally:
            runtime.close()
        self.assertFalse(owned_root.exists())
        self.assertFalse(forbidden_aux_root.exists())
        self.assertEqual(
            {
                path: {item.name: item.read_bytes() for item in path.iterdir()}
                for path in (production_legacy_backups, production_runtime_backups)
            },
            production_backup_state,
        )

    def test_production_runtime_roles_cannot_be_swapped(self) -> None:
        from inventory.shared import runtime_paths

        protected = {
            "IXcellerate": self.tmp_path / "installation-ix.db",
            "Solar": self.tmp_path / "installation-solar.db",
            "Vacations": self.tmp_path / "installation-vacations.db",
        }
        for path in protected.values():
            with closing(sqlite3.connect(path)) as connection, connection:
                connection.execute("CREATE TABLE ordinary(id INTEGER PRIMARY KEY)")

        with mock.patch.dict(runtime_paths.RUNTIME_DATABASE_PATHS, protected, clear=True):
            swaps = {
                "IX-as-Solar": (
                    protected["Solar"], protected["IXcellerate"], protected["Vacations"]
                ),
                "Warehouse-as-Vacations": (
                    protected["IXcellerate"], protected["Solar"], protected["Solar"]
                ),
            }
            for label, (primary, solar, vacations) in swaps.items():
                with self.subTest(case=label), self.assertRaisesRegex(
                    RuntimeError, "роли runtime-БД перепутаны|один файл"
                ):
                    validate_runtime_database_contours(
                        test_mode=False,
                        db_path=primary,
                        solar_db_path=solar,
                        vacations_db_path=vacations,
                        warehouse_contour="production",
                    )


if __name__ == "__main__":
    unittest.main()
