from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from inventory.vacations.schema import DEFAULT_VACATIONS_DB_PATH, VACATION_TABLES
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

    def test_sidecar_and_working_database_targets_fail_closed(self) -> None:
        sidecar = Path(str(self.output) + "-journal")
        sidecar.write_bytes(b"active")
        with self.assertRaisesRegex(RuntimeError, "sidecar"):
            create_clean_vacations_test_db.build(self.output, overwrite=True)
        with self.assertRaisesRegex(RuntimeError, "рабочей"):
            create_clean_vacations_test_db.build(
                DEFAULT_VACATIONS_DB_PATH, overwrite=True
            )


if __name__ == "__main__":
    unittest.main()
