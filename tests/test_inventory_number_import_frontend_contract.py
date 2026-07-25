from __future__ import annotations

import unittest
from pathlib import Path

from inventory import webapp


ROOT = Path(__file__).resolve().parents[1]
INVENTORY_JS = (
    ROOT / "static" / "js" / "warehouse" / "inventory.js"
).read_text(encoding="utf-8")


class InventoryNumberImportFrontendContractTest(unittest.TestCase):
    def test_runtime_html_exposes_static_import_targets(self) -> None:
        self.assertIn('id="inventoryNumberCsv"', webapp.HTML)
        self.assertIn('id="inventoryNumberImport"', webapp.HTML)
        self.assertIn(
            '<script src="/static/js/warehouse/inventory.js"></script>',
            webapp.HTML,
        )

    def test_preview_and_confirm_use_the_inventory_numbers_contract(self) -> None:
        self.assertIn("const KIND='inventory_numbers'", INVENTORY_JS)
        self.assertIn("/api/preview-csv?kind=${KIND}", INVENTORY_JS)
        self.assertIn("action:'CONFIRM_IMPORT_PREVIEW'", INVENTORY_JS)
        self.assertIn("kind:KIND,preview_id:selectedPreviewId", INVENTORY_JS)
        self.assertIn("body:file", INVENTORY_JS)

    def test_all_public_row_statuses_are_rendered_as_text(self) -> None:
        for status in (
            "SUCCESS",
            "UNCHANGED",
            "NOT_FOUND",
            "ALREADY_ASSIGNED",
            "DUPLICATE_INVENTORY_NUMBER",
            "VALIDATION_ERROR",
        ):
            self.assertIn(status, INVENTORY_JS)
        self.assertIn("renderTable({", INVENTORY_JS)
        self.assertIn("renderElement('td',{text:row.serial_number||''})", INVENTORY_JS)
        self.assertNotIn(".innerHTML", INVENTORY_JS)

    def test_confirmation_requires_server_permission_and_preview_token(self) -> None:
        self.assertIn(
            "const canConfirm=result?.can_confirm===true&&Boolean(previewId)",
            INVENTORY_JS,
        )
        self.assertIn("disabled:!canConfirm", INVENTORY_JS)
        self.assertIn("if(confirming||!previewId)return", INVENTORY_JS)
        self.assertIn("previewId=''", INVENTORY_JS)
        self.assertIn("['admin','engineer']", INVENTORY_JS)


if __name__ == "__main__":
    unittest.main()
