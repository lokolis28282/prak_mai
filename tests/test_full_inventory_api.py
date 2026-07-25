from __future__ import annotations

import io
import json
import unittest
from urllib.parse import urlencode
from zipfile import ZipFile

from inventory.core.application import create_application_context
from inventory.webapp import make_handler
from inventory.warehouse.baseline.models import ActorSnapshot
from tests.full_inventory_support import FullInventoryFixture


class _Headers(dict[str, str]):
    def get(self, name: str, default: str = "") -> str:
        return super().get(name, default)


class FullInventoryApiTest(FullInventoryFixture, unittest.TestCase):
    def setUp(self) -> None:
        self.create_fixture()
        self.context = create_application_context(
            self.db_path,
            service=self.legacy_service,
            warehouse_contour="production",
            full_inventory_state_root=self.state_root,
        )
        self.handler_type = make_handler(self.context)

    def tearDown(self) -> None:
        self.cleanup_fixture()

    def call_post(
        self,
        path: str,
        body: bytes = b"{}",
        *,
        headers: dict[str, str] | None = None,
        role: str = "admin",
    ) -> tuple[int, dict]:
        handler = self.handler_type.__new__(self.handler_type)
        handler.path = path
        handler.rfile = io.BytesIO(body)
        handler.headers = _Headers({
            "Content-Length": str(len(body)),
            "Content-Type": "application/json",
            **(headers or {}),
        })
        handler._send_json = lambda status, payload: setattr(
            handler, "captured", (status, payload)
        )
        with self.legacy_service.user_context(
            "lokolis", role_override=None if role == "admin" else role
        ):
            handler._do_POST()
        return handler.captured

    def call_get(self, path: str) -> tuple[int, dict]:
        handler = self.handler_type.__new__(self.handler_type)
        handler.path = path
        handler.headers = _Headers({})
        handler._send_json = lambda status, payload: setattr(
            handler, "captured", (status, payload)
        )
        with self.legacy_service.user_context("lokolis"):
            handler._do_GET()
        return handler.captured

    def call_get_download(self, path: str) -> tuple[int, dict[str, str], bytes]:
        handler = self.handler_type.__new__(self.handler_type)
        handler.path = path
        handler.headers = _Headers({})
        handler.wfile = io.BytesIO()
        captured_headers: dict[str, str] = {}
        handler.send_response = lambda status: setattr(handler, "captured_status", status)
        handler.send_header = lambda name, value: captured_headers.__setitem__(name, value)
        handler.end_headers = lambda: None
        with self.legacy_service.user_context("lokolis"):
            handler._do_GET()
        return handler.captured_status, captured_headers, handler.wfile.getvalue()

    def test_authenticated_operator_downloads_scan_first_reference_template(self) -> None:
        status, headers, body = self.call_get_download(
            "/api/full-inventory/template.xlsx"
        )
        self.assertEqual(status, 200)
        self.assertEqual(
            headers["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        self.assertIn("ODE_FULL_INVENTORY_v1.xlsx", headers["Content-Disposition"])
        with ZipFile(io.BytesIO(body)) as archive:
            workbook_xml = archive.read("xl/workbook.xml").decode("utf-8")
            inventory_xml = archive.read("xl/worksheets/sheet2.xml").decode("utf-8")
        for sheet in ("Manifest", "Inventory", "Инструкция", "Справочник", "Номенклатура"):
            self.assertIn(sheet, workbook_xml)
        self.assertRegex(inventory_xml, r'<c r="A1"[^>]*>.*SerialNumber')

    def test_status_create_upload_preview_and_pagination(self) -> None:
        status, payload = self.call_get("/api/warehouse/system-status")
        self.assertEqual(status, 200)
        self.assertFalse(payload["authoritative"])
        self.assertTrue(payload["provisional"])
        self.assertTrue(payload["posting_allowed"])
        self.assertEqual(payload["balance_kind"], "PROVISIONAL_HISTORICAL")
        self.assertIsNone(payload["baseline_timestamp"])
        status, created = self.call_post("/api/full-inventory/sessions")
        self.assertEqual(status, 201)
        session_id = created["session"]["public_id"]
        source = self.workbook()
        body = source.read_bytes()
        status, uploaded = self.call_post(
            "/api/full-inventory/upload?" + urlencode({"session_id": session_id}),
            body,
            headers={
                "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "X-Filename": "inventory.xlsx",
            },
        )
        self.assertEqual(status, 200, uploaded)
        status, preview = self.call_post(
            "/api/full-inventory/preview",
            json.dumps({"session_id": session_id}).encode(),
        )
        self.assertEqual(status, 200, preview)
        self.assertFalse(preview["approval_available"])
        self.assertEqual(preview["catalog_validation"], "DEFERRED")
        status, active_status = self.call_get("/api/warehouse/system-status")
        self.assertEqual(status, 200)
        self.assertIsNone(active_status["baseline_timestamp"])
        self.assertTrue(active_status["posting_allowed"])
        for endpoint, key in (("rows", "rows"), ("findings", "findings")):
            status, page = self.call_get(
                f"/api/full-inventory/{endpoint}?" + urlencode({"session_id": session_id, "limit": 10})
            )
            self.assertEqual(status, 200)
            self.assertIn(key, page)

    def test_viewer_can_read_status_but_cannot_create(self) -> None:
        status, payload = self.call_get("/api/warehouse/system-status")
        self.assertEqual(status, 200)
        self.assertIn("state", payload)
        with self.assertRaisesRegex(Exception, "Недостаточно прав"):
            self.call_post("/api/full-inventory/sessions", role="viewer")

    def test_production_warehouse_mutation_reaches_business_validation(self) -> None:
        status, payload = self.call_post(
            "/api/action",
            json.dumps({"action": "STOCK_RECEIPT"}).encode(),
        )
        self.assertEqual(status, 400)
        self.assertNotEqual(payload.get("code"), "WAREHOUSE_NOT_INITIALIZED")

    def test_resolution_revalidate_and_candidate_rehearsal_api(self) -> None:
        session = self.create_session()
        source = self.workbook(rows=[self.row(LocationCode="UNKNOWN")])
        self.upload(session, source)
        self.inventory.build_preview(
            session["public_id"], self.actor, correlation_id="corr_api_resolution_preview_01"
        )
        finding = next(
            item for item in self.inventory.preview_findings(session["public_id"])["findings"]
            if item["code"] == "UNKNOWN_LOCATION"
        )
        status, payload = self.call_post(
            "/api/full-inventory/resolutions",
            json.dumps({
                "session_id": session["public_id"], "row_id": finding["row_id"],
                "finding_id": finding["finding_id"], "action_code": "CORRECT_VALUE",
                "replacement_value": "1-1", "reason": "API correction",
            }).encode(),
        )
        self.assertEqual(status, 201, payload)
        status, listed = self.call_get(
            "/api/full-inventory/resolutions?" + urlencode({"session_id": session["public_id"]})
        )
        self.assertEqual(status, 200)
        self.assertEqual(listed["total"], 1)
        row = self.inventory.preview_rows(session["public_id"])["rows"][0]
        admin = ActorSnapshot("legacy-user:1", "Тестовый Администратор", "admin")
        for action, target in (
            ("CHOOSE_CATALOG_ITEM", "catalog:new:server"),
            ("CREATE_NEW_EQUIPMENT_CANDIDATE", ""),
        ):
            self.inventory.record_resolution(
                session["public_id"], admin, action_code=action, target_public_id=target,
                reason="API candidate", row_id=row["row_id"],
                correlation_id=f"corr_api_candidate_{action}_01",
            )
        status, revalidated = self.call_post(
            "/api/full-inventory/revalidate",
            json.dumps({"session_id": session["public_id"]}).encode(),
        )
        self.assertEqual(status, 200, revalidated)
        self.assertEqual(revalidated["session"]["session_status"], "READY_FOR_APPROVAL")
        status, candidate = self.call_post(
            "/api/full-inventory/candidate-rehearsal",
            json.dumps({"session_id": session["public_id"]}).encode(),
        )
        self.assertEqual(status, 201, candidate)
        self.assertEqual(candidate["status"], "REHEARSAL_READY")
        self.assertFalse(candidate["publish_available"])


if __name__ == "__main__":
    unittest.main()
