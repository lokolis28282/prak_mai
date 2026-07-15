from __future__ import annotations

import unittest

from inventory.shared.validators import WarehouseError
from tests.full_inventory_support import FullInventoryFixture


class FullInventoryResolutionTest(FullInventoryFixture, unittest.TestCase):
    def setUp(self) -> None:
        self.create_fixture()

    def tearDown(self) -> None:
        self.cleanup_fixture()

    def _preview(self, rows: list[dict[str, str]]) -> dict:
        session = self.create_session()
        source = self.workbook(rows=rows)
        self.upload(session, source)
        self.inventory.build_preview(
            session["public_id"], self.actor, correlation_id="corr_preview_resolution_01"
        )
        return session

    def test_correct_value_preserves_raw_and_changes_digest_deterministically(self) -> None:
        session = self._preview([self.row(LocationCode="UNKNOWN")])
        session_id = session["public_id"]
        before = self.inventory.preview_summary(session_id)["run"]["preview_digest"]
        finding = next(
            item for item in self.inventory.preview_findings(session_id)["findings"]
            if item["code"] == "UNKNOWN_LOCATION"
        )
        self.inventory.record_resolution(
            session_id,
            self.actor,
            action_code="CORRECT_VALUE",
            reason="Исправлено по пересчёту",
            row_id=finding["row_id"],
            finding_id=finding["finding_id"],
            replacement_value="1-1",
            correlation_id="corr_resolution_correct_01",
        )
        result = self.inventory.build_preview(
            session_id, self.actor, correlation_id="corr_revalidate_correct_01"
        )
        self.assertEqual(result["session"]["session_status"], "READY_FOR_APPROVAL")
        self.assertNotEqual(result["run"]["preview_digest"], before)
        row = self.inventory.preview_rows(session_id)["rows"][0]
        self.assertEqual(row["raw"]["LocationCode"], "UNKNOWN")
        self.assertEqual(row["normalized"]["resolution_overrides"], {"LocationCode": "1-1"})
        resolutions = self.inventory.list_resolutions(session_id)["resolutions"]
        self.assertEqual(resolutions[0]["actor_user_public_id"], self.actor.actor_id)
        digest = result["run"]["preview_digest"]
        repeated = self.inventory.build_preview(
            session_id, self.actor, correlation_id="corr_revalidate_correct_02"
        )
        self.assertEqual(repeated["run"]["preview_digest"], digest)

        current_row = self.inventory.preview_rows(session_id)["rows"][0]
        self.inventory.record_resolution(
            session_id,
            self.actor,
            action_code="CORRECT_VALUE",
            reason="Уточнено после повторной проверки",
            row_id=current_row["row_id"],
            field_code="LocationCode",
            replacement_value="UNKNOWN-AGAIN",
            supersedes_resolution_id=resolutions[0]["resolution_id"],
            correlation_id="corr_resolution_correct_supersede_01",
        )
        changed = self.inventory.build_preview(
            session_id, self.actor, correlation_id="corr_revalidate_correct_03"
        )
        self.assertEqual(changed["session"]["session_status"], "REVIEW_REQUIRED")
        row = self.inventory.preview_rows(session_id)["rows"][0]
        self.assertEqual(row["raw"]["LocationCode"], "UNKNOWN")
        self.assertEqual(
            row["normalized"]["resolution_overrides"],
            {"LocationCode": "UNKNOWN-AGAIN"},
        )

    def test_row_disposition_resolves_duplicate_blockers(self) -> None:
        session = self._preview([
            self.row(RowId="A", SerialNumber="DUP", InventoryNumber="INV-DUP"),
            self.row(RowId="B", SerialNumber="dup", InventoryNumber="inv-dup"),
        ])
        session_id = session["public_id"]
        second = self.inventory.preview_rows(session_id)["rows"][1]
        self.inventory.record_resolution(
            session_id,
            self.actor,
            action_code="MARK_DUPLICATE",
            reason="Повтор той же физической единицы",
            row_id=second["row_id"],
            correlation_id="corr_resolution_duplicate_01",
        )
        result = self.inventory.build_preview(
            session_id, self.actor, correlation_id="corr_revalidate_duplicate_01"
        )
        self.assertEqual(result["session"]["blocker_count"], 0)
        self.assertEqual(result["session"]["session_status"], "READY_FOR_APPROVAL")
        second = self.inventory.preview_rows(session_id)["rows"][1]
        self.assertEqual(second["normalized"]["resolution_disposition"], "MARK_DUPLICATE")
        resolved = [
            item for item in self.inventory.preview_findings(session_id)["findings"]
            if item["source_row_number"] == 3
        ]
        self.assertTrue(resolved)
        self.assertTrue(all(item["finding_status"] == "RESOLVED" for item in resolved))

    def test_conflicting_resolution_requires_explicit_supersede_and_stale_row_fails(self) -> None:
        session = self._preview([self.row(LocationCode="UNKNOWN")])
        session_id = session["public_id"]
        row = self.inventory.preview_rows(session_id)["rows"][0]
        first = self.inventory.record_resolution(
            session_id,
            self.actor,
            action_code="EXCLUDE_ROW",
            reason="Вне scope",
            row_id=row["row_id"],
            correlation_id="corr_resolution_conflict_01",
        )["resolutions"][0]
        with self.assertRaisesRegex(WarehouseError, "RESOLUTION_CONFLICT"):
            self.inventory.record_resolution(
                session_id,
                self.actor,
                action_code="QUARANTINE_ROW",
                reason="Требует осмотра",
                row_id=row["row_id"],
                correlation_id="corr_resolution_conflict_02",
            )
        self.inventory.record_resolution(
            session_id,
            self.actor,
            action_code="QUARANTINE_ROW",
            reason="Требует осмотра",
            row_id=row["row_id"],
            supersedes_resolution_id=first["resolution_id"],
            correlation_id="corr_resolution_conflict_03",
        )
        self.inventory.build_preview(
            session_id, self.actor, correlation_id="corr_revalidate_conflict_01"
        )
        with self.assertRaisesRegex(WarehouseError, "active Preview"):
            self.inventory.record_resolution(
                session_id,
                self.actor,
                action_code="DEFER_ROW",
                reason="Устаревший row id",
                row_id=row["row_id"],
                correlation_id="corr_resolution_stale_01",
            )

    def test_all_declared_actions_are_accepted_with_required_inputs(self) -> None:
        actions = [
            "LINK_EXISTING_EQUIPMENT", "CREATE_NEW_EQUIPMENT_CANDIDATE",
            "CHOOSE_CATALOG_ITEM", "CHOOSE_TARGET_LOCATION", "CORRECT_VALUE",
            "CONFIRM_LITERAL_IDENTIFIER", "EXCLUDE_ROW", "QUARANTINE_ROW",
            "MARK_DUPLICATE", "DEFER_ROW",
        ]
        rows = [
            self.row(RowId=f"ROW-{index}", SerialNumber=f"SN-{index}", LocationCode="UNKNOWN")
            for index in range(len(actions))
        ]
        session = self._preview(rows)
        session_id = session["public_id"]
        preview_rows = self.inventory.preview_rows(session_id)["rows"]
        findings = self.inventory.preview_findings(session_id, limit=100)["findings"]
        by_row = {item["source_row_number"]: item for item in findings if item["field_code"] == "LocationCode"}
        for index, action in enumerate(actions):
            row = preview_rows[index]
            finding = by_row[row["source_row_number"]]
            kwargs = {
                "target_public_id": "1-1" if action in {
                    "LINK_EXISTING_EQUIPMENT", "CHOOSE_CATALOG_ITEM", "CHOOSE_TARGET_LOCATION"
                } else "",
                "replacement_value": "1-1" if action == "CORRECT_VALUE" else "",
            }
            self.inventory.record_resolution(
                session_id,
                self.actor,
                action_code=action,
                reason=f"Проверка {action}",
                row_id=row["row_id"],
                finding_id=finding["finding_id"] if action == "CORRECT_VALUE" else None,
                correlation_id=f"corr_all_actions_{index:02d}_1234",
                **kwargs,
            )
        self.assertEqual(self.inventory.list_resolutions(session_id)["total"], len(actions))


if __name__ == "__main__":
    unittest.main()
