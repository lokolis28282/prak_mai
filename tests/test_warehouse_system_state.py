from __future__ import annotations

from contextlib import closing
import os
import sqlite3
import threading
import unittest
from unittest.mock import patch

from inventory.shared.validators import WarehouseError
from inventory.warehouse.baseline.workspace import WorkspaceError
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

    def test_stale_preview_and_resolution_requests_fail_closed(self) -> None:
        session = self.create_session()
        self.upload(session, self.workbook())
        path, stale_uploaded = self.inventory._find_session(session["public_id"])
        with closing(sqlite3.connect(path)) as db:
            db.execute(
                "UPDATE preview_sessions SET session_status='PREVIEWING' WHERE session_id=?",
                (stale_uploaded["session_id"],),
            )
            db.commit()
        with patch.object(
            self.inventory, "_find_session", return_value=(path, stale_uploaded)
        ):
            with self.assertRaisesRegex(WarehouseError, "уже выполняется"):
                self.inventory.build_preview(
                    session["public_id"],
                    self.actor,
                    correlation_id="corr_stale_preview_012345",
                )
        with closing(sqlite3.connect(path)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM preview_runs").fetchone()[0], 0)
            db.execute(
                "UPDATE preview_sessions SET session_status='UPLOADED' WHERE session_id=?",
                (stale_uploaded["session_id"],),
            )
            db.commit()

        self.inventory.build_preview(
            session["public_id"], self.actor, correlation_id="corr_ready_preview_012345"
        )
        path, stale_review = self.inventory._find_session(session["public_id"])
        row = self.inventory.preview_rows(session["public_id"])["rows"][0]
        with closing(sqlite3.connect(path)) as db:
            db.execute(
                "UPDATE preview_sessions SET session_status='REJECTED' WHERE session_id=?",
                (stale_review["session_id"],),
            )
            db.commit()
        with patch.object(
            self.inventory, "_find_session", return_value=(path, stale_review)
        ):
            with self.assertRaisesRegex(WarehouseError, "active Preview"):
                self.inventory.record_resolution(
                    session["public_id"],
                    self.actor,
                    action_code="CHOOSE_CATALOG_ITEM",
                    target_public_id="catalog:test",
                    reason="stale request must fail",
                    row_id=row["row_id"],
                    correlation_id="corr_stale_resolution_0123",
                )
        with closing(sqlite3.connect(path)) as db:
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM preview_resolutions").fetchone()[0], 0
            )
            self.assertEqual(
                db.execute("SELECT session_status FROM preview_sessions").fetchone()[0],
                "REJECTED",
            )

    def test_previewing_session_cannot_be_rejected(self) -> None:
        session = self.create_session()
        path, internal = self.inventory._find_session(session["public_id"])
        with closing(sqlite3.connect(path)) as db:
            db.execute(
                "UPDATE preview_sessions SET session_status='PREVIEWING' WHERE session_id=?",
                (internal["session_id"],),
            )
            db.commit()
        with self.assertRaisesRegex(WarehouseError, "во время Preview"):
            self.inventory.reject_session(
                session["public_id"],
                self.actor,
                correlation_id="corr_reject_running_012345",
            )
        with closing(sqlite3.connect(path)) as db:
            self.assertEqual(
                db.execute("SELECT session_status FROM preview_sessions").fetchone()[0],
                "PREVIEWING",
            )

    def test_session_creation_is_single_flight_across_process_boundary(self) -> None:
        from inventory.warehouse.baseline import service as service_module

        entered = threading.Event()
        release = threading.Event()
        outcome: list[object] = []
        original_create = service_module.create_workspace

        def blocking_create(path: object) -> object:
            entered.set()
            if not release.wait(timeout=5):
                raise AssertionError("session creation test timed out")
            return original_create(path)

        def first_request() -> None:
            try:
                outcome.append(
                    self.inventory.create_session(
                        self.actor, correlation_id="corr_create_first_012345"
                    )
                )
            except Exception as error:  # pragma: no cover - asserted below
                outcome.append(error)

        with patch.object(service_module, "create_workspace", side_effect=blocking_create):
            worker = threading.Thread(target=first_request)
            worker.start()
            self.assertTrue(entered.wait(timeout=5))
            with self.assertRaisesRegex(WorkspaceError, "другом процессе"):
                self.inventory.create_session(
                    self.actor, correlation_id="corr_create_second_01234"
                )
            release.set()
            worker.join(timeout=5)

        self.assertFalse(worker.is_alive())
        self.assertEqual(len(outcome), 1)
        self.assertIsInstance(outcome[0], dict)
        lock_path = self.state_root / ".session-create-lock.db"
        self.assertTrue(lock_path.is_file())
        if os.name != "nt":
            self.assertEqual(lock_path.stat().st_mode & 0o777, 0o600)
        with closing(sqlite3.connect(lock_path)) as db:
            self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        self.assertEqual(len(list((self.state_root / "previews").glob("*.db"))), 1)


if __name__ == "__main__":
    unittest.main()
