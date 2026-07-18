from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from inventory.db import (
    initialize,
    install_knowledge_schema,
    install_reports_uvr_schema,
)


ROOT = Path(__file__).resolve().parent.parent


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def create_promoted_fixture(path: Path) -> None:
    with closing(sqlite3.connect(path)) as db:
        db.executescript(
            """
            PRAGMA foreign_keys=ON;
            CREATE TABLE migration_full_marker(id INTEGER PRIMARY KEY);
            CREATE TABLE users(
                id INTEGER PRIMARY KEY, first_name TEXT NOT NULL DEFAULT '',
                last_name TEXT NOT NULL DEFAULT '', email TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE reference_values(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL, name TEXT NOT NULL COLLATE NOCASE,
                is_active INTEGER NOT NULL DEFAULT 1,
                UNIQUE(kind, name)
            );
            INSERT INTO reference_values(kind,name) VALUES ('task_type','Работа');
            CREATE TABLE work_logs(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                work_date TEXT NOT NULL, task_source TEXT NOT NULL,
                task_type TEXT NOT NULL, task_number TEXT NOT NULL,
                description TEXT NOT NULL, status TEXT NOT NULL,
                comment TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE audit_log(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_date TEXT NOT NULL DEFAULT '', action TEXT NOT NULL,
                entity_type TEXT NOT NULL, entity_id INTEGER,
                author TEXT NOT NULL DEFAULT '', details TEXT NOT NULL DEFAULT ''
            );
            """
        )
        db.commit()


class RuntimeModuleMigrationTest(unittest.TestCase):
    def test_normal_startup_does_not_mutate_promoted_database(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / "warehouse.db"
            create_promoted_fixture(database)
            before = digest(database)
            self.assertFalse(initialize(database))
            self.assertEqual(digest(database), before)
            with closing(sqlite3.connect(database)) as db:
                tables = {str(row[0]) for row in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )}
            self.assertNotIn("knowledge_articles", tables)

    def test_explicit_installers_are_idempotent_and_preserve_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / "warehouse.db"
            create_promoted_fixture(database)
            for _ in range(2):
                install_reports_uvr_schema(database)
                install_knowledge_schema(database)
            with closing(sqlite3.connect(database)) as db:
                columns = {str(row[1]) for row in db.execute("PRAGMA table_info(work_logs)")}
                tables = {str(row[0]) for row in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )}
                section_count = int(db.execute(
                    "SELECT count(*) FROM reference_values WHERE kind='work_log_section'"
                ).fetchone()[0])
                integrity = str(db.execute("PRAGMA integrity_check").fetchone()[0])
                foreign_keys = db.execute("PRAGMA foreign_key_check").fetchall()
            self.assertTrue({"section", "needs_review"} <= columns)
            self.assertTrue({
                "knowledge_articles", "knowledge_attachments", "knowledge_article_tags",
            } <= tables)
            self.assertGreater(section_count, 20)
            self.assertEqual(integrity, "ok")
            self.assertEqual(foreign_keys, [])

    def test_migration_cli_creates_external_backups_and_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database = root / "warehouse.db"
            backup = root / "external-backup"
            create_promoted_fixture(database)
            result = subprocess.run(
                [
                    sys.executable, str(ROOT / "scripts" / "migrate_runtime_modules.py"),
                    "--db", str(database), "--backup-dir", str(backup), "--apply",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads(
                (backup / "runtime-modules-migration-manifest.json").read_text(encoding="utf-8")
            )
            self.assertTrue(manifest["after"]["reports_ready"])
            self.assertTrue(manifest["after"]["knowledge_ready"])
            self.assertEqual(manifest["after"]["integrity_check"], "ok")
            self.assertEqual(manifest["after"]["foreign_key_violations"], 0)
            byte_copy = Path(manifest["backups"]["byte_copy"])
            self.assertEqual(digest(byte_copy), manifest["before"]["sha256"])


if __name__ == "__main__":
    unittest.main()
