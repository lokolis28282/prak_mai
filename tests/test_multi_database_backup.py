from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

from inventory.administration.multi_database_backup import REPOSITORY_ROOT
from inventory.administration.runtime_databases import (
    RuntimeDatabase,
    RuntimeDatabaseRegistry,
)
from inventory.core.application import create_application_context
from inventory.core.context import RuntimeConfig
from inventory.routes import administration as administration_routes
from inventory.service import WarehouseError, WarehouseService
from inventory.vacations.schema import VACATION_TABLES, install_vacations_schema


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class MultiDatabaseBackupTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.primary = root / "warehouse.db"
        self.solar = root / "warehouse_solar.db"
        self.vacations = root / "vacations.db"
        self.backup_root = root / "external-backups"
        self.service = WarehouseService(self.primary)
        WarehouseService(self.solar)
        install_vacations_schema(self.vacations)
        self.context = create_application_context(
            self.primary,
            service=self.service,
            configuration=RuntimeConfig(
                self.primary,
                warehouse_contour="production",
                production_db_path=self.primary,
                vacations_db_path=self.vacations,
                settings={
                    "warehouse_sites_enabled": True,
                    "solar_db_path": self.solar,
                    "backup_root": self.backup_root,
                },
            ),
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_status_is_read_only_for_three_independent_databases(self) -> None:
        before = {
            path.name: sha256(path)
            for path in (self.primary, self.solar, self.vacations)
        }
        with self.service.user_context("lokolis"):
            statuses = self.context.administration.service.runtime_database_statuses()
            capabilities = (
                self.context.administration.service.runtime_backup_capabilities()
            )

        self.assertEqual(
            {item["database_id"] for item in statuses},
            {"warehouse_ix", "warehouse_solar", "vacations"},
        )
        self.assertTrue(all(item["health"]["ok"] for item in statuses))
        self.assertTrue(all(item["last_backup"] is None for item in statuses))
        self.assertFalse(capabilities["restore"]["available"])
        self.assertEqual(
            Path(capabilities["backup_root"]).resolve(),
            self.backup_root.resolve(),
        )
        self.assertEqual(
            before,
            {
                path.name: sha256(path)
                for path in (self.primary, self.solar, self.vacations)
            },
        )
        self.assertFalse(self.backup_root.exists())

    def test_verified_backup_is_created_for_each_database_profile(self) -> None:
        solar_before = sha256(self.solar)
        vacations_before = sha256(self.vacations)
        created = []
        with self.service.user_context("lokolis"):
            for database_id in ("warehouse_ix", "warehouse_solar", "vacations"):
                created.append(
                    self.context.administration.create_runtime_database_backup(
                        database_id
                    )
                )
            listed = (
                self.context.administration.service.runtime_database_backups()
            )
            audit = self.context.administration.list_audit_entries(limit=20)

        self.assertEqual(len(created), 3)
        self.assertEqual(len(listed), 3)
        self.assertEqual(sha256(self.solar), solar_before)
        self.assertEqual(sha256(self.vacations), vacations_before)
        for backup in created:
            path = (
                self.backup_root
                / backup["database_id"]
                / backup["name"]
            )
            manifest_path = path.with_suffix(".manifest.json")
            self.assertTrue(path.is_file())
            self.assertTrue(manifest_path.is_file())
            self.assertTrue(backup["verified"])
            self.assertEqual(sha256(path), backup["sha256"])
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["database_id"], backup["database_id"])
            self.assertEqual(manifest["method"], "sqlite_backup_api")
            self.assertTrue(manifest["verification"]["ok"])
            with closing(sqlite3.connect(path)) as database:
                self.assertEqual(
                    database.execute("PRAGMA integrity_check").fetchone()[0],
                    "ok",
                )
                self.assertEqual(
                    database.execute("PRAGMA foreign_key_check").fetchall(),
                    [],
                )
        self.assertEqual(
            sum(
                row["action"] == "RUNTIME_DATABASE_BACKUP_CREATE"
                for row in audit
            ),
            3,
        )

    def test_engineer_and_viewer_cannot_read_or_create_runtime_backups(self) -> None:
        with self.service.user_context("lokolis"):
            self.service.create_user(
                "Test", "Engineer", "Engineer", "backup-engineer", "secret1", "engineer"
            )
            self.service.create_user(
                "Test", "Viewer", "Viewer", "backup-viewer", "secret2", "viewer"
            )
        for email in ("backup-engineer", "backup-viewer"):
            with self.subTest(email=email), self.service.user_context(email):
                with self.assertRaisesRegex(WarehouseError, "Недостаточно прав"):
                    self.context.administration.service.runtime_database_statuses()
                with self.assertRaisesRegex(WarehouseError, "Недостаточно прав"):
                    self.context.administration.create_runtime_database_backup(
                        "warehouse_ix"
                    )

    def test_hardlink_and_symlink_runtime_targets_are_blocked(self) -> None:
        alias = self.primary.with_name("warehouse_alias.db")
        os.link(self.primary, alias)
        registry = RuntimeDatabaseRegistry(
            (
                RuntimeDatabase(
                    "warehouse_ix",
                    "IXcellerate",
                    alias,
                    "warehouse",
                    frozenset(self.service.KEY_TABLES),
                ),
            )
        )
        self.context.administration.service.configure_runtime_databases(
            registry, backup_root=self.backup_root
        )
        with self.service.user_context("lokolis"):
            with self.assertRaisesRegex(WarehouseError, "hardlink"):
                self.context.administration.create_runtime_database_backup(
                    "warehouse_ix"
                )

        alias.unlink()
        try:
            alias.symlink_to(self.primary)
        except OSError as error:
            self.assertEqual(os.name, "nt", str(error))
            return
        with self.service.user_context("lokolis"):
            with self.assertRaisesRegex(WarehouseError, "symbolic link"):
                self.context.administration.create_runtime_database_backup(
                    "warehouse_ix"
                )

    def test_registry_rejects_two_runtime_ids_for_hardlink_aliases(self) -> None:
        alias = self.primary.with_name("warehouse_registry_alias.db")
        os.link(self.primary, alias)
        with self.assertRaisesRegex(ValueError, "разные пути"):
            RuntimeDatabaseRegistry(
                (
                    RuntimeDatabase(
                        "warehouse_ix",
                        "IXcellerate",
                        self.primary,
                        "warehouse",
                        frozenset(self.service.KEY_TABLES),
                    ),
                    RuntimeDatabase(
                        "warehouse_solar",
                        "Solar",
                        alias,
                        "warehouse",
                        frozenset(self.service.KEY_TABLES),
                    ),
                )
            )

    def test_repository_backup_root_and_legacy_restore_action_are_blocked(
        self,
    ) -> None:
        registry = RuntimeDatabaseRegistry(
            (
                RuntimeDatabase(
                    "vacations",
                    "Vacations",
                    self.vacations,
                    "vacations",
                    frozenset(VACATION_TABLES),
                ),
            )
        )
        self.context.administration.service.configure_runtime_databases(
            registry,
            backup_root=REPOSITORY_ROOT / ".forbidden-runtime-backups",
        )
        with self.service.user_context("lokolis"):
            with self.assertRaisesRegex(WarehouseError, "вне Git-репозитория"):
                self.context.administration.create_runtime_database_backup(
                    "vacations"
                )
            runtime = SimpleNamespace(app_context=self.context)
            with self.assertRaisesRegex(WarehouseError, "проверяемая подготовка"):
                administration_routes.handle_action(
                    SimpleNamespace(),
                    runtime,
                    "RESTORE_BACKUP",
                    {"filename": "old.db", "confirmed": True},
                    {"ok": True},
                )
        self.assertFalse(
            (REPOSITORY_ROOT / ".forbidden-runtime-backups").exists()
        )


if __name__ == "__main__":
    unittest.main()
