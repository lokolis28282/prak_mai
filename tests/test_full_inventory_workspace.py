from __future__ import annotations

from contextlib import closing
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from inventory.warehouse.baseline.workspace import (
    APPLICATION_ID,
    SCHEMA_VERSION,
    WorkspaceError,
    create_workspace,
    migrate_workspace,
    verify_workspace,
)


ROOT = Path(__file__).resolve().parents[1]


class FullInventoryWorkspaceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_fresh_v2_create_integrity_fk_and_permissions(self) -> None:
        path = self.root / "fresh.db"
        result = create_workspace(path)
        self.assertEqual(result["application_id"], APPLICATION_ID)
        self.assertEqual(result["user_version"], SCHEMA_VERSION)
        self.assertEqual(result["integrity_check"], "ok")
        self.assertEqual(result["foreign_key_check"], 0)
        if os.name != "nt":
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_v1_to_v2_repeated_migration_matches_fresh_manifest(self) -> None:
        fresh = create_workspace(self.root / "fresh.db")
        v1 = self.root / "v1.db"
        with closing(sqlite3.connect(v1)) as db:
            db.executescript(
                (ROOT / "docs/architecture/ddl/preview_workspace_schema.sql").read_text(
                    encoding="utf-8"
                )
            )
        migrated = migrate_workspace(v1)
        repeated = migrate_workspace(v1)
        self.assertEqual(migrated["schema_fingerprint"], fresh["schema_fingerprint"])
        self.assertEqual(repeated["schema_fingerprint"], fresh["schema_fingerprint"])

    def test_invalid_version_fails_closed(self) -> None:
        path = self.root / "invalid.db"
        create_workspace(path)
        with closing(sqlite3.connect(path)) as db:
            db.execute("PRAGMA user_version=99")
        with self.assertRaisesRegex(WorkspaceError, "Unsupported"):
            migrate_workspace(path)

    def test_session_and_run_guards_and_activity_are_append_only(self) -> None:
        path = self.root / "guards.db"
        create_workspace(path)
        with closing(sqlite3.connect(path)) as db:
            db.execute("PRAGMA foreign_keys=ON")
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute(
                    """INSERT INTO preview_activity_events(
                           session_id,event_type,actor_id,actor_display_snapshot,
                           actor_role_snapshot,occurred_at,correlation_id,safe_metadata_json
                       ) VALUES ('missing','SESSION_CREATED','a','A','engineer',1,
                                 'corr_0123456789abc','{}')"""
                )
            with self.assertRaisesRegex(sqlite3.IntegrityError, "session does not exist"):
                db.execute(
                    """INSERT INTO preview_runs(
                           run_id,session_id,attempt,session_status,run_status,
                           source_object_key,source_sha256,source_size_bytes,
                           template_version,parser_version,schema_version,
                           reference_fingerprint,observed_ledger_head,freeze_token_hash
                       ) VALUES ('run','missing',1,'DRAFT','QUEUED',
                                 'source_object_key_1',zeroblob(32),1,'1.0','p','2',
                                 zeroblob(32),0,zeroblob(32))"""
                )
            db.execute(
                """INSERT INTO preview_sessions(
                       session_id,public_id,session_type,session_status,
                       warehouse_scope_raw,compatibility_mapping_version,
                       counted_by_raw,count_started_at,count_finished_at,
                       created_actor_id,created_actor_display,created_actor_role,
                       created_at,updated_at
                   ) VALUES ('s','s','FULL','DRAFT','','COMPATIBILITY_V1_DATACENTER_SHELF',
                             '','','','a','A','engineer',1,1)"""
            )
            db.execute(
                """INSERT INTO preview_activity_events(
                       session_id,event_type,actor_id,actor_display_snapshot,
                       actor_role_snapshot,occurred_at,correlation_id,safe_metadata_json
                   ) VALUES ('s','SESSION_CREATED','a','A','engineer',1,
                             'corr_0123456789abc','{}')"""
            )
            with self.assertRaisesRegex(sqlite3.IntegrityError, "append-only"):
                db.execute("UPDATE preview_activity_events SET actor_id='b'")
            with self.assertRaisesRegex(sqlite3.IntegrityError, "append-only"):
                db.execute("DELETE FROM preview_activity_events")
        self.assertEqual(verify_workspace(path)["foreign_key_check"], 0)


if __name__ == "__main__":
    unittest.main()
