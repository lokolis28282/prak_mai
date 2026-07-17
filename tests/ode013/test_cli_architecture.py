from __future__ import annotations

import ast
import json
import os
import sqlite3
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from ode.infrastructure.paths import PROJECT_ROOT


class CliTests(unittest.TestCase):
    def run_cli(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        environment = dict(os.environ)
        environment["PYTHONWARNINGS"] = "error::ResourceWarning"
        return subprocess.run(
            [sys.executable, "-m", "ode", *arguments],
            cwd=PROJECT_ROOT,
            text=True,
            capture_output=True,
            env=environment,
            check=False,
        )

    def test_all_human_commands_succeed(self) -> None:
        with TemporaryDirectory() as directory:
            path = str(Path(directory) / "human.db")
            commands = (
                ("db", "create", "--path", path),
                ("db", "status", "--path", path),
                ("db", "verify", "--path", path),
                ("db", "migrations", "--path", path),
                ("system", "health", "--path", path),
            )
            for command in commands:
                with self.subTest(command=command):
                    result = self.run_cli(*command)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn("OK:", result.stdout)
                    self.assertNotIn("Traceback", result.stdout + result.stderr)

    def test_all_json_commands_have_valid_contract_and_exit_codes(self) -> None:
        with TemporaryDirectory() as directory:
            path = str(Path(directory) / "json.db")
            commands = (
                ("db", "create", "--path", path, "--json"),
                ("db", "status", "--path", path, "--json"),
                ("db", "verify", "--path", path, "--json"),
                ("db", "migrations", "--path", path, "--json"),
                ("system", "health", "--path", path, "--json"),
            )
            payloads: list[dict[str, object]] = []
            for command in commands:
                result = self.run_cli(*command)
                self.assertEqual(result.returncode, 0, result.stderr)
                payload = json.loads(result.stdout)
                self.assertTrue(payload["ok"])
                payloads.append(payload)
            health = payloads[-1]["health"]
            self.assertIsInstance(health, dict)
            self.assertEqual(health["status"], "NOT_INITIALIZED")

    def test_existing_target_and_missing_database_use_stable_error_envelopes(self) -> None:
        with TemporaryDirectory() as directory:
            path = str(Path(directory) / "errors.db")
            self.assertEqual(
                self.run_cli("db", "create", "--path", path).returncode, 0
            )
            existing = self.run_cli("db", "create", "--path", path, "--json")
            self.assertNotEqual(existing.returncode, 0)
            payload = json.loads(existing.stdout)
            self.assertEqual(payload["error"]["code"], "DATABASE_ALREADY_EXISTS")
            missing = self.run_cli(
                "system", "health", "--path", str(Path(directory) / "missing.db"), "--json"
            )
            self.assertNotEqual(missing.returncode, 0)
            payload = json.loads(missing.stdout)
            self.assertEqual(payload["error"]["code"], "DATABASE_NOT_FOUND")
            self.assertNotIn("Traceback", existing.stdout + existing.stderr + missing.stdout + missing.stderr)

    def test_write_commands_have_no_implicit_default_path(self) -> None:
        result = self.run_cli("db", "create", "--json")
        self.assertNotEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["error"]["code"], "INVALID_CLI_ARGUMENTS")
        self.assertIn("--path", payload["error"]["message"])

    @unittest.skipIf(os.name == "nt", "Windows forbids control characters in filenames")
    def test_human_output_sanitizes_terminal_controls_and_preserves_unicode(self) -> None:
        cases = (
            ("escape-\x1b[31m", "\\x1b[31m"),
            ("newline-\nvalue", "newline-\\x0avalue"),
            ("return-\rvalue", "return-\\x0dvalue"),
            ("bell-\x07value", "bell-\\x07value"),
            ("c1-\x85value", "c1-\\x85value"),
            ("bidi-\u202evalue", "bidi-\\u202evalue"),
        )
        with TemporaryDirectory() as directory:
            for fragment, representation in cases:
                with self.subTest(fragment=repr(fragment)):
                    path = str(Path(directory) / f"{fragment}.db")
                    result = self.run_cli("db", "create", "--path", path)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn(representation, result.stdout)
                    self.assertNotIn(fragment, result.stdout + result.stderr)
                    self.assertNotIn("\x1b", result.stdout + result.stderr)
                    self.assertNotIn("\x07", result.stdout + result.stderr)
                    self.assertNotIn("\r", result.stdout + result.stderr)
                    self.assertNotIn("\u202e", result.stdout + result.stderr)

            unicode_path = str(Path(directory) / "кириллица-設備.db")
            unicode_result = self.run_cli("db", "create", "--path", unicode_path)
            self.assertEqual(unicode_result.returncode, 0, unicode_result.stderr)
            self.assertIn("кириллица-設備.db", unicode_result.stdout)

    @unittest.skipIf(os.name == "nt", "Windows forbids control characters in filenames")
    def test_json_output_escapes_controls_and_preserves_canonical_path(self) -> None:
        with TemporaryDirectory() as directory:
            path = str(Path(directory) / "json-\x1b-\n-\r-\x07-\u202e.db")
            result = self.run_cli("db", "create", "--path", path, "--json")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("\x1b", result.stdout + result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["database_path"], str(Path(path).resolve()))

    def test_active_wal_cli_fails_closed_in_json_and_human_modes(self) -> None:
        with TemporaryDirectory() as directory:
            path = str(Path(directory) / "active-wal.db")
            created = self.run_cli("db", "create", "--path", path, "--json")
            self.assertEqual(created.returncode, 0, created.stderr)
            writer = sqlite3.connect(path, isolation_level=None)
            try:
                writer.execute("PRAGMA journal_mode = WAL")
                writer.execute("PRAGMA wal_autocheckpoint = 0")
                writer.execute("BEGIN IMMEDIATE")
                writer.execute(
                    "INSERT INTO users "
                    "(user_id, public_id, login_key, display_name, password_hash, "
                    "status, created_at_us, updated_at_us) VALUES "
                    "(1, ?, 'cli-wal', 'CLI WAL', ?, 'ACTIVE', 1, 1)",
                    ("c" * 32, "$argon2id$" + "x" * 30),
                )
                writer.commit()

                json_result = self.run_cli(
                    "system", "health", "--path", path, "--json"
                )
                self.assertEqual(json_result.returncode, 2)
                self.assertEqual(json_result.stderr, "")
                payload = json.loads(json_result.stdout)
                self.assertFalse(payload["ok"])
                self.assertEqual(
                    payload["error"]["code"], "IMMUTABLE_SNAPSHOT_UNSAFE"
                )

                human_result = self.run_cli("db", "status", "--path", path)
                self.assertEqual(human_result.returncode, 2)
                self.assertEqual(human_result.stdout, "")
                self.assertIn("IMMUTABLE_SNAPSHOT_UNSAFE", human_result.stderr)
                self.assertNotIn("Traceback", human_result.stderr)
            finally:
                writer.close()


class ArchitectureTests(unittest.TestCase):
    def test_module_boundary_audit_passes(self) -> None:
        result = subprocess.run(
            [sys.executable, "scripts/audit_module_boundaries.py"],
            cwd=PROJECT_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_ode_and_inventory_do_not_import_each_other(self) -> None:
        for root, forbidden in (("ode", "inventory"), ("inventory", "ode")):
            for path in (PROJECT_ROOT / root).rglob("*.py"):
                tree = ast.parse(path.read_text(encoding="utf-8"))
                imports = []
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        imports.extend(alias.name for alias in node.names)
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        imports.append(node.module)
                self.assertFalse(
                    any(name == forbidden or name.startswith(forbidden + ".") for name in imports),
                    path,
                )

    def test_sql_migrations_are_not_duplicated_in_python(self) -> None:
        for path in (PROJECT_ROOT / "ode").rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("CREATE TABLE ", text, path)
            self.assertNotIn("CREATE TRIGGER ", text, path)
        self.assertFalse((PROJECT_ROOT / "ode" / "migrations").exists())

    def test_no_default_users_http_or_product_database_constant(self) -> None:
        combined = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (PROJECT_ROOT / "ode").rglob("*.py")
        )
        self.assertNotIn("data/warehouse.db", combined)
        self.assertNotIn("http.server", combined)
        self.assertNotIn("default_admin", combined.lower())

    def test_context_build_does_not_create_or_migrate_database(self) -> None:
        source = (PROJECT_ROOT / "ode" / "application" / "context.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn(".create()", source)
        self.assertNotIn(".migrate", source)


if __name__ == "__main__":
    unittest.main()
