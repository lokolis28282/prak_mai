from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock

from inventory.vacations.schema import DEFAULT_VACATIONS_DB_PATH, VACATION_TABLES
from inventory.shared.runtime_paths import (
    install_test_contour_marker,
    test_contour_database_has_sidecars,
    test_contour_database_role,
)
from scripts import create_clean_vacations_test_db


class CreateCleanVacationsTestDbTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.output = Path(self.tmp.name) / "vacations_test.db"

    def test_build_creates_empty_verified_schema(self) -> None:
        result = create_clean_vacations_test_db.build(self.output)
        self.assertEqual(result, self.output.resolve())
        with closing(sqlite3.connect(result)) as connection:
            tables = {
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            self.assertTrue(VACATION_TABLES.issubset(tables))
            for table in VACATION_TABLES:
                self.assertEqual(
                    connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0],
                    0,
                )
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_existing_output_requires_overwrite_and_is_rebuilt(self) -> None:
        create_clean_vacations_test_db.build(self.output)
        with closing(sqlite3.connect(self.output)) as connection, connection:
            connection.execute(
                """INSERT INTO vacation_employees(
                       first_name, last_name, full_name
                   ) VALUES ('Test', 'User', 'Test User')"""
            )
        with self.assertRaisesRegex(RuntimeError, "--overwrite"):
            create_clean_vacations_test_db.build(self.output)
        create_clean_vacations_test_db.build(self.output, overwrite=True)
        with closing(sqlite3.connect(self.output)) as connection:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM vacation_employees").fetchone()[0],
                0,
            )

    def test_overwrite_rejects_unmarked_custom_existing_database(self) -> None:
        output = Path(self.tmp.name) / "custom-production.db"
        with closing(sqlite3.connect(output)) as connection, connection:
            connection.execute("CREATE TABLE production_marker(id INTEGER PRIMARY KEY)")
        before = output.read_bytes()
        with self.assertRaisesRegex(RuntimeError, "marker"):
            create_clean_vacations_test_db.build(output, overwrite=True)
        self.assertEqual(output.read_bytes(), before)

    def test_sidecar_and_working_database_targets_fail_closed(self) -> None:
        sidecar = Path(str(self.output) + "-journal")
        sidecar.write_bytes(b"active")
        with self.assertRaisesRegex(RuntimeError, "sidecar"):
            create_clean_vacations_test_db.build(self.output, overwrite=True)
        with self.assertRaisesRegex(RuntimeError, "runtime-БД"):
            create_clean_vacations_test_db.build(
                DEFAULT_VACATIONS_DB_PATH, overwrite=True
            )

    def test_builder_cannot_replace_any_runtime_database(self) -> None:
        from inventory.shared import runtime_paths

        for label in runtime_paths.RUNTIME_DATABASE_PATHS:
            protected = Path(self.tmp.name) / f"protected-{label}.db"
            protected.write_bytes(b"protected runtime sentinel")
            with self.subTest(runtime=label), mock.patch.dict(
                runtime_paths.RUNTIME_DATABASE_PATHS, {label: protected}, clear=True
            ):
                with self.assertRaisesRegex(RuntimeError, "рабочую"):
                    create_clean_vacations_test_db.build(
                        protected, overwrite=True
                    )
                self.assertEqual(protected.read_bytes(), b"protected runtime sentinel")

            future_protected = Path(self.tmp.name) / f"Future-Protected-{label}.db"
            casefold_alias = Path(self.tmp.name) / f"future-protected-{label}.DB"
            with self.subTest(runtime=f"{label}-future-casefold"), mock.patch.dict(
                runtime_paths.RUNTIME_DATABASE_PATHS,
                {label: future_protected},
                clear=True,
            ):
                with self.assertRaisesRegex(RuntimeError, "рабочую"):
                    create_clean_vacations_test_db.build(casefold_alias)
                self.assertFalse(future_protected.exists())
                self.assertFalse(casefold_alias.exists())

    def test_marker_probe_is_immutable_and_sidecars_fail_closed(self) -> None:
        marked = Path(self.tmp.name) / "marked-wal.db"
        with closing(sqlite3.connect(marked)) as connection:
            self.assertEqual(connection.execute("PRAGMA journal_mode = WAL").fetchone()[0], "wal")
            with connection:
                install_test_contour_marker(connection, "vacations")
        for suffix in ("-wal", "-shm", "-journal"):
            Path(str(marked) + suffix).unlink(missing_ok=True)
        before_bytes = marked.read_bytes()
        before_files = {path.name for path in Path(self.tmp.name).iterdir()}

        self.assertFalse(test_contour_database_has_sidecars(marked))
        self.assertEqual(test_contour_database_role(marked), "vacations")
        self.assertEqual(marked.read_bytes(), before_bytes)
        self.assertEqual(
            {path.name for path in Path(self.tmp.name).iterdir()}, before_files
        )

        for suffix in ("-wal", "-shm", "-journal"):
            sidecar = Path(str(marked) + suffix)
            sentinel = f"pre-existing {suffix} sentinel".encode()
            sidecar.write_bytes(sentinel)
            with self.subTest(sidecar=suffix):
                self.assertTrue(test_contour_database_has_sidecars(marked))
                self.assertEqual(test_contour_database_role(marked), "")
                self.assertEqual(sidecar.read_bytes(), sentinel)
            sidecar.unlink()

    def test_pre_publish_sidecar_race_preserves_existing_output(self) -> None:
        create_clean_vacations_test_db.build(self.output)
        sentinel = self.output.read_bytes()
        inode = self.output.stat().st_ino
        sidecar = Path(str(self.output) + "-wal")
        real_chmod = create_clean_vacations_test_db.os.chmod

        def racing_chmod(path: Path, mode: int) -> None:
            real_chmod(path, mode)
            sidecar.write_bytes(b"active vacations writer")

        with mock.patch.object(
            create_clean_vacations_test_db.os,
            "chmod",
            side_effect=racing_chmod,
        ), self.assertRaisesRegex(RuntimeError, "sidecar"):
            create_clean_vacations_test_db.build(self.output, overwrite=True)

        self.assertEqual(self.output.stat().st_ino, inode)
        self.assertEqual(self.output.read_bytes(), sentinel)
        self.assertEqual(sidecar.read_bytes(), b"active vacations writer")
        self.assertEqual(list(Path(self.tmp.name).glob(f".{self.output.name}.*.tmp")), [])

    def test_pre_publish_target_replacement_is_not_overwritten(self) -> None:
        create_clean_vacations_test_db.build(self.output)
        sentinel = self.output.read_bytes()
        replacement = Path(self.tmp.name) / "replacement.db"
        raced_inode: list[int] = []
        real_chmod = create_clean_vacations_test_db.os.chmod

        def racing_chmod(path: Path, mode: int) -> None:
            real_chmod(path, mode)
            replacement.write_bytes(sentinel)
            os.replace(replacement, self.output)
            raced_inode.append(self.output.stat().st_ino)

        with mock.patch.object(
            create_clean_vacations_test_db.os,
            "chmod",
            side_effect=racing_chmod,
        ), self.assertRaisesRegex(RuntimeError, "identity"):
            create_clean_vacations_test_db.build(self.output, overwrite=True)

        self.assertEqual(self.output.stat().st_ino, raced_inode[0])
        self.assertEqual(self.output.read_bytes(), sentinel)
        self.assertEqual(list(Path(self.tmp.name).glob(f".{self.output.name}.*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
