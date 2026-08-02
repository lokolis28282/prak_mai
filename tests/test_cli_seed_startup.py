from __future__ import annotations

import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CliSeedStartupTest(unittest.TestCase):
    def test_seed_reset_starts_in_a_fresh_process(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "seed.db"
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "app.py"),
                    "--db",
                    str(database),
                    "--warehouse-contour",
                    "demo",
                    "seed",
                    "--reset",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            with closing(sqlite3.connect(database)) as connection:
                self.assertEqual(
                    connection.execute("PRAGMA integrity_check").fetchone()[0],
                    "ok",
                )
                self.assertEqual(
                    connection.execute("PRAGMA foreign_key_check").fetchall(),
                    [],
                )
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM equipment").fetchone()[0],
                    8,
                )


if __name__ == "__main__":
    unittest.main()
