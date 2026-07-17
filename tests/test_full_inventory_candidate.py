from __future__ import annotations

import hashlib
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import unittest

from inventory.shared.validators import WarehouseError
from baseline_rehearsal import validate_candidate
from inventory.warehouse.baseline.models import ActorSnapshot
from tests.full_inventory_support import FullInventoryFixture


class FullInventoryCandidateTest(FullInventoryFixture, unittest.TestCase):
    def setUp(self) -> None:
        self.create_fixture()
        self.admin = ActorSnapshot("legacy-user:1", "Тестовый Администратор", "admin")

    def tearDown(self) -> None:
        self.cleanup_fixture()

    def _ready_session(self) -> dict:
        session = self.create_session()
        source = self.workbook(rows=[self.row()])
        self.upload(session, source)
        self.inventory.build_preview(
            session["public_id"], self.actor, correlation_id="corr_candidate_preview_01"
        )
        row = self.inventory.preview_rows(session["public_id"])["rows"][0]
        for action, target in (
            ("CHOOSE_CATALOG_ITEM", "catalog:new:server"),
            ("CREATE_NEW_EQUIPMENT_CANDIDATE", ""),
        ):
            self.inventory.record_resolution(
                session["public_id"], self.actor, action_code=action,
                target_public_id=target, reason="Подтверждено для rehearsal",
                row_id=row["row_id"], correlation_id=f"corr_candidate_{action}_01",
            )
        self.inventory.build_preview(
            session["public_id"], self.actor, correlation_id="corr_candidate_revalidate_01"
        )
        return session

    def test_baseline_rehearsal_has_clean_cold_import(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "from baseline_rehearsal import build_candidate, validate_candidate",
            ],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_candidate_requires_explicit_catalog_and_equipment_decisions(self) -> None:
        session = self.create_session()
        source = self.workbook(rows=[self.row()])
        self.upload(session, source)
        self.inventory.build_preview(
            session["public_id"], self.actor, correlation_id="corr_candidate_missing_01"
        )
        with self.assertRaisesRegex(WarehouseError, "CHOOSE_CATALOG_ITEM"):
            self.inventory.build_candidate_rehearsal(
                session["public_id"], self.admin, correlation_id="corr_candidate_build_missing_01"
            )

    def test_candidate_is_target_schema_active_and_projection_exact(self) -> None:
        session = self._ready_session()
        before = hashlib.sha256(self.db_path.read_bytes()).hexdigest()
        report = self.inventory.build_candidate_rehearsal(
            session["public_id"], self.admin, correlation_id="corr_candidate_build_01"
        )
        self.assertEqual(report["status"], "REHEARSAL_READY")
        self.assertFalse(report["publish_available"])
        self.assertEqual(report["snapshot_item_count"], 1)
        self.assertEqual(report["projection_difference_count"], 0)
        candidate = self.state_root / "candidates" / report["candidate_file"]
        verified = validate_candidate(candidate)
        if os.name != "nt":
            self.assertEqual(verified["permissions"], "0o600")
        with closing(sqlite3.connect(candidate)) as db:
            self.assertEqual(db.execute("PRAGMA application_id").fetchone()[0], 0x4F444531)
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 8)
            self.assertEqual(db.execute("SELECT balance_state FROM app_state").fetchone()[0], "ACTIVE")
            self.assertEqual(db.execute("SELECT count(*) FROM legacy_history_events").fetchone()[0], 0)
        self.assertEqual(hashlib.sha256(self.db_path.read_bytes()).hexdigest(), before)
        self.assertFalse(any(Path(str(candidate) + suffix).exists() for suffix in ("-wal", "-shm", "-journal")))

    def test_candidate_build_is_idempotent_and_engineer_cannot_approve_rehearsal(self) -> None:
        session = self._ready_session()
        with self.assertRaisesRegex(WarehouseError, "admin"):
            self.inventory.build_candidate_rehearsal(
                session["public_id"], self.actor, correlation_id="corr_candidate_denied_01"
            )
        first = self.inventory.build_candidate_rehearsal(
            session["public_id"], self.admin, correlation_id="corr_candidate_idempotent_01"
        )
        second = self.inventory.build_candidate_rehearsal(
            session["public_id"], self.admin, correlation_id="corr_candidate_idempotent_02"
        )
        self.assertEqual(first["sha256"], second["sha256"])

    @unittest.skipIf(os.name == "nt", "requires POSIX symlink support")
    def test_candidate_output_symlink_is_rejected_without_touching_target(self) -> None:
        session = self._ready_session()
        digest = self.inventory.preview_summary(session["public_id"])["run"][
            "preview_digest"
        ]
        candidates = self.state_root / "candidates"
        candidates.mkdir(parents=True)
        victim = self.root / "must-not-be-created.db"
        os.symlink(victim, candidates / f"{digest}.db")

        with self.assertRaisesRegex(WarehouseError, "symlink"):
            self.inventory.build_candidate_rehearsal(
                session["public_id"],
                self.admin,
                correlation_id="corr_candidate_symlink_0123",
            )
        self.assertFalse(victim.exists())


if __name__ == "__main__":
    unittest.main()
