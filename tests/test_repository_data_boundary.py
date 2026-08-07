from __future__ import annotations

import ast
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from inventory.db import initialize
from scripts.audit_repository_data import (
    SQLITE_HEADER,
    audit_tracked_files,
    forbidden_path,
)


ROOT = Path(__file__).resolve().parents[1]


class RepositoryDataBoundaryTest(unittest.TestCase):
    def test_current_git_index_contains_no_runtime_data(self) -> None:
        self.assertEqual(audit_tracked_files(ROOT), [])

    def test_sensitive_artifact_paths_and_disguised_sqlite_are_rejected(self) -> None:
        for path in (
            "data/warehouse.db",
            "data/monitoring/Hostname Internal.json",
            "migration_inputs/raw/source.xlsx",
            "backups/QWERTY/warehouse.db",
            "release/ODE.zip",
            "exports/issues.csv",
        ):
            with self.subTest(path=path):
                self.assertTrue(forbidden_path(path))
        self.assertFalse(forbidden_path("data/README.md"))
        self.assertFalse(forbidden_path("ode/schema_manifest.json"))

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            disguised = root / "apparently-safe.bin"
            disguised.write_bytes(SQLITE_HEADER + b"private rows")
            with patch(
                "scripts.audit_repository_data.tracked_paths",
                return_value=[disguised.name],
            ):
                self.assertEqual(
                    audit_tracked_files(root),
                    ["SQLite content in tracked file: apparently-safe.bin"],
                )

    def test_absent_runtime_database_bootstraps_without_warehouse_rows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "data" / "warehouse.db"
            self.assertFalse(database.exists())
            initialize(database)
            self.assertTrue(database.exists())
            with closing(sqlite3.connect(database)) as connection:
                for table in (
                    "stock_receipts",
                    "stock_issues",
                    "stock_issue_allocations",
                    "deliveries",
                    "delivery_lines",
                ):
                    with self.subTest(table=table):
                        count = connection.execute(
                            f"SELECT COUNT(*) FROM {table}"
                        ).fetchone()[0]
                        self.assertEqual(count, 0)

    def test_raw_sqlite_context_managers_cannot_leak_connections(self) -> None:
        violations: list[str] = []
        for source_root in ("inventory", "scripts", "tests"):
            for path in (ROOT / source_root).rglob("*.py"):
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
                for node in ast.walk(tree):
                    if not isinstance(node, (ast.With, ast.AsyncWith)):
                        continue
                    for item in node.items:
                        expression = item.context_expr
                        if not isinstance(expression, ast.Call):
                            continue
                        function = expression.func
                        if (
                            isinstance(function, ast.Attribute)
                            and function.attr == "connect"
                            and isinstance(function.value, ast.Name)
                            and function.value.id == "sqlite3"
                        ):
                            violations.append(
                                f"{path.relative_to(ROOT)}:{node.lineno}"
                            )

        self.assertEqual(
            violations,
            [],
            "sqlite3.Connection.__enter__ does not close the connection; "
            "wrap sqlite3.connect(...) in contextlib.closing",
        )


if __name__ == "__main__":
    unittest.main()
