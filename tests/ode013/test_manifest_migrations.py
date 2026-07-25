from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from ode.application.errors import MigrationError
from ode.infrastructure.migrations import MigrationRunner, load_schema_manifest
from ode.infrastructure.paths import DDL_ROOT, MANIFEST_PATH
from tests.ode013.support import config, copy_ddl


class ManifestMigrationTests(unittest.TestCase):
    def test_manifest_parses_and_checksums_are_exact(self) -> None:
        manifest = load_schema_manifest()
        self.assertEqual(manifest.schema_version, 8)
        self.assertEqual(manifest.expected_migration_count, 8)
        self.assertEqual(
            manifest.approved_schema_hash,
            "143bb0ae16c68c1fcd653ecc94adc62464746fed738ebfa47749057380f7f0cb",
        )
        for migration in manifest.migrations:
            self.assertEqual(
                hashlib.sha256((DDL_ROOT / migration.file).read_bytes()).hexdigest(),
                migration.sha256,
            )

    def test_two_clean_builds_have_identical_approved_schema_hash(self) -> None:
        with TemporaryDirectory() as directory:
            reports = [
                MigrationRunner(config(Path(directory) / f"build-{number}.db")).create()
                for number in (1, 2)
            ]
            self.assertEqual(
                reports[0].verification.schema_hash,
                reports[1].verification.schema_hash,
            )
            self.assertEqual(
                reports[0].verification.schema_hash,
                "143bb0ae16c68c1fcd653ecc94adc62464746fed738ebfa47749057380f7f0cb",
            )

    def test_clean_create_registry_versions_permissions_and_proofs(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "clean.db"
            result = MigrationRunner(config(path)).create()
            if os.name != "nt":
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(result.verification.integrity_result, "ok")
            self.assertEqual(result.verification.foreign_key_violations, 0)
            connection = sqlite3.connect(path)
            try:
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 8)
                self.assertEqual(
                    connection.execute("PRAGMA application_id").fetchone()[0],
                    1329874225,
                )
                self.assertEqual(
                    connection.execute("SELECT count(*) FROM schema_migrations").fetchone()[0],
                    8,
                )
            finally:
                connection.close()
            self.assertEqual(list(path.parent.glob(f"{path.name}-*")), [])

    def test_existing_target_is_rejected_without_change(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "existing.db"
            path.write_bytes(b"existing")
            with self.assertRaises(MigrationError) as caught:
                MigrationRunner(config(path)).create()
            self.assertEqual(caught.exception.code, "DATABASE_ALREADY_EXISTS")
            self.assertEqual(path.read_bytes(), b"existing")

    def test_missing_and_extra_files_are_rejected(self) -> None:
        for mutation, expected_counts in (("missing", (1, 0)), ("extra", (0, 1))):
            with self.subTest(mutation=mutation), TemporaryDirectory() as directory:
                root = Path(directory) / "ddl"
                copy_ddl(DDL_ROOT, root)
                if mutation == "missing":
                    (root / "V008__audit_and_operations.sql").unlink()
                else:
                    (root / "V009__unexpected.sql").write_text("SELECT 1;", encoding="utf-8")
                runner = MigrationRunner(
                    config(Path(directory) / "target.db"), ddl_root=root
                )
                with self.assertRaises(MigrationError) as caught:
                    runner.validate_sources()
                self.assertEqual(caught.exception.code, "MIGRATION_SET_MISMATCH")
                self.assertEqual(
                    (
                        caught.exception.body.details["missing_count"],
                        caught.exception.body.details["extra_count"],
                    ),
                    expected_counts,
                )

    def test_reordered_duplicate_and_wrong_checksum_are_rejected(self) -> None:
        for mutation, expected in (
            ("reordered", "MIGRATION_ORDER_MISMATCH"),
            ("duplicate", "DUPLICATE_MIGRATION_VERSION"),
            ("checksum", "SCHEMA_MIGRATION_CHECKSUM_MISMATCH"),
        ):
            with self.subTest(mutation=mutation), TemporaryDirectory() as directory:
                manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
                if mutation == "reordered":
                    manifest["migrations"][0], manifest["migrations"][1] = (
                        manifest["migrations"][1],
                        manifest["migrations"][0],
                    )
                elif mutation == "duplicate":
                    manifest["migrations"][1]["version"] = 1
                else:
                    manifest["migrations"][0]["sha256"] = "0" * 64
                manifest_path = Path(directory) / "manifest.json"
                manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
                runner = MigrationRunner(
                    config(Path(directory) / "target.db"), manifest_path=manifest_path
                )
                with self.assertRaises(MigrationError) as caught:
                    runner.validate_sources()
                self.assertEqual(caught.exception.code, expected)

    @unittest.skipIf(os.name == "nt", "requires POSIX symlink support")
    def test_dangling_migration_source_is_typed(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory) / "ddl"
            copy_ddl(DDL_ROOT, root)
            source = root / "V001__system_and_security.sql"
            source.unlink()
            source.symlink_to(Path(directory) / "missing.sql")
            runner = MigrationRunner(
                config(Path(directory) / "target.db"), ddl_root=root
            )
            with self.assertRaises(MigrationError) as caught:
                runner.validate_sources()
            self.assertEqual(caught.exception.code, "MIGRATION_SOURCE_READ_FAILED")
            self.assertEqual(caught.exception.body.details["version"], 1)
            self.assertEqual(
                caught.exception.body.details["failure_type"], "FileNotFoundError"
            )
            self.assertIsInstance(caught.exception.__cause__, FileNotFoundError)

    def test_target_parent_creation_failure_is_typed_and_leaves_no_candidate(self) -> None:
        with TemporaryDirectory() as directory:
            parent_file = Path(directory) / "parent-is-file"
            parent_file.write_text("occupied", encoding="utf-8")
            target = parent_file / "target.db"
            runner = MigrationRunner(config(target))
            with self.assertRaises(MigrationError) as caught:
                runner.create()
            self.assertEqual(caught.exception.code, "DATABASE_CREATE_FAILED")
            self.assertEqual(caught.exception.body.details["failure_type"], "FileExistsError")
            self.assertIsInstance(caught.exception.__cause__, FileExistsError)
            self.assertFalse(target.exists())
            self.assertEqual(list(Path(directory).glob(".*.candidate-*")), [])

    def test_failed_migration_deletes_candidate_and_leaves_no_target(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory) / "ddl"
            copy_ddl(DDL_ROOT, root)
            broken = root / "V008__audit_and_operations.sql"
            broken.write_text(broken.read_text(encoding="utf-8") + "\nINVALID SQL;\n", encoding="utf-8")
            manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
            manifest["migrations"][-1]["sha256"] = hashlib.sha256(broken.read_bytes()).hexdigest()
            manifest_path = Path(directory) / "manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            target = Path(directory) / "target.db"
            with self.assertRaises(MigrationError):
                MigrationRunner(
                    config(target), ddl_root=root, manifest_path=manifest_path
                ).create()
            self.assertFalse(target.exists())
            self.assertEqual(list(target.parent.glob(".*.candidate-*")), [])

    def test_interrupted_migration_deletes_candidate_and_leaves_no_target(self) -> None:
        with TemporaryDirectory() as directory:
            target = Path(directory) / "interrupted.db"
            runner = MigrationRunner(config(target))
            with patch.object(runner, "_verify_connection", side_effect=KeyboardInterrupt):
                with self.assertRaises(KeyboardInterrupt):
                    runner.create()
            self.assertFalse(target.exists())
            self.assertEqual(list(target.parent.glob(".*.candidate-*")), [])


if __name__ == "__main__":
    unittest.main()
