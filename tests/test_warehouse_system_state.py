from __future__ import annotations

from contextlib import closing
import sqlite3
import unittest
from unittest.mock import patch

from inventory.warehouse.baseline.xlsx_parser import FullInventoryXlsxError
from tests.full_inventory_support import FullInventoryFixture


class WarehouseSystemStateTest(FullInventoryFixture, unittest.TestCase):
    def setUp(self) -> None:
        self.create_fixture()

    def tearDown(self) -> None:
        self.cleanup_fixture()

    def test_status_transitions_and_rejected_returns_not_initialized(self) -> None:
        self.assertEqual(self.inventory.system_status()["state"], "NOT_INITIALIZED")
        session = self.create_session()
        self.assertEqual(self.inventory.system_status()["state"], "INVENTORY_IN_PROGRESS")
        uploaded = self.upload(session, self.workbook())
        self.assertEqual(uploaded["session_status"], "UPLOADED")
        self.assertEqual(self.inventory.system_status()["state"], "INVENTORY_IN_PROGRESS")
        summary = self.inventory.build_preview(
            session["public_id"], self.actor, correlation_id="corr_preview_01234567"
        )
        self.assertEqual(summary["session"]["session_status"], "READY_FOR_APPROVAL")
        self.assertEqual(self.inventory.system_status()["state"], "INVENTORY_REVIEW")
        rejected = self.inventory.reject_session(
            session["public_id"], self.actor, correlation_id="corr_reject_012345678"
        )
        self.assertEqual(rejected["session_status"], "REJECTED")
        self.assertEqual(rejected["rejection_reason"], "USER_CANCELLED")
        self.assertEqual(self.inventory.system_status()["state"], "NOT_INITIALIZED")
        path, _ = self.inventory._find_session(session["public_id"])
        with closing(sqlite3.connect(path)) as db:
            events = db.execute(
                "SELECT event_type,safe_metadata_json FROM preview_activity_events ORDER BY event_id"
            ).fetchall()
        self.assertEqual(
            [row[0] for row in events],
            [
                "SESSION_CREATED",
                "SOURCE_UPLOADED",
                "PREVIEW_STARTED",
                "PREVIEW_COMPLETED",
                "SESSION_REJECTED",
            ],
        )
        metadata = " ".join(str(row[1]).casefold() for row in events)
        for forbidden in ("password", "session_token", "filesystem", str(self.root).casefold()):
            self.assertNotIn(forbidden, metadata)

    def test_failed_or_corrupt_workspace_is_degraded(self) -> None:
        session = self.create_session()
        path, internal = self.inventory._find_session(session["public_id"])
        with closing(sqlite3.connect(path)) as db:
            db.execute(
                "UPDATE preview_sessions SET session_status='FAILED' WHERE session_id=?",
                (internal["session_id"],),
            )
            db.commit()
        status = self.inventory.system_status()
        self.assertEqual(status["state"], "DEGRADED")
        self.assertFalse(status["posting_allowed"])

    def test_previewing_and_review_required_status_mapping(self) -> None:
        session = self.create_session()
        source = self.workbook(rows=[self.row(LocationCode="Unknown Shelf")])
        self.upload(session, source)
        path, internal = self.inventory._find_session(session["public_id"])
        with closing(sqlite3.connect(path)) as db:
            db.execute(
                "UPDATE preview_sessions SET session_status='PREVIEWING' WHERE session_id=?",
                (internal["session_id"],),
            )
            db.commit()
        self.assertEqual(self.inventory.system_status()["state"], "INVENTORY_IN_PROGRESS")
        with closing(sqlite3.connect(path)) as db:
            db.execute(
                "UPDATE preview_sessions SET session_status='UPLOADED' WHERE session_id=?",
                (internal["session_id"],),
            )
            db.commit()
        result = self.inventory.build_preview(
            session["public_id"], self.actor, correlation_id="corr_review_0123456789"
        )
        self.assertEqual(result["session"]["session_status"], "REVIEW_REQUIRED")
        self.assertEqual(self.inventory.system_status()["state"], "INVENTORY_REVIEW")

    def test_preview_failure_event_is_append_only_evidence(self) -> None:
        session = self.create_session()
        self.upload(session, self.workbook())
        with patch(
            "inventory.warehouse.baseline.service.inspect_workbook",
            side_effect=FullInventoryXlsxError("controlled parser failure"),
        ):
            with self.assertRaisesRegex(FullInventoryXlsxError, "controlled parser failure"):
                self.inventory.build_preview(
                    session["public_id"],
                    self.actor,
                    correlation_id="corr_failed_0123456789",
                )
        self.assertEqual(self.inventory.system_status()["state"], "DEGRADED")
        path, internal = self.inventory._find_session(session["public_id"])
        with closing(sqlite3.connect(path)) as db:
            run = db.execute(
                "SELECT run_status,session_status,failure_code FROM preview_runs"
            ).fetchone()
            events = db.execute(
                "SELECT event_type,safe_metadata_json FROM preview_activity_events ORDER BY event_id"
            ).fetchall()
            with self.assertRaisesRegex(sqlite3.IntegrityError, "append-only"):
                db.execute(
                    "DELETE FROM preview_activity_events WHERE session_id=?",
                    (internal["session_id"],),
                )
        self.assertEqual(run, ("FAILED", "FAILED", "FULL_INVENTORY_XLSX_INVALID"))
        self.assertEqual(events[-2][0], "PREVIEW_STARTED")
        self.assertEqual(events[-1][0], "PREVIEW_FAILED")
        self.assertNotIn(str(self.root), events[-1][1])

    def test_system_status_never_claims_ready_in_slice_one(self) -> None:
        status = self.inventory.system_status()
        self.assertFalse(status["authoritative"])
        self.assertFalse(status["ready_reachable"])
        self.assertEqual(status["balance_kind"], "HISTORICAL_CALCULATION")
        self.assertIsNone(status["baseline_timestamp"])


if __name__ == "__main__":
    unittest.main()
