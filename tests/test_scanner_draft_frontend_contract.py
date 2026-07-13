from __future__ import annotations

import re
import unittest
from pathlib import Path

from inventory import webapp


ROOT = Path(__file__).resolve().parents[1]
UI_JS = (ROOT / "static" / "js" / "ui.js").read_text(encoding="utf-8")
PRODUCT_JS = (ROOT / "static" / "js" / "product.js").read_text(encoding="utf-8")


class ScannerDraftFrontendContractTest(unittest.TestCase):
    def test_runtime_html_exposes_receipt_and_issue_draft_controls(self) -> None:
        for element_id in (
            "scanReceiptBody",
            "scanReceiptCount",
            "selectAllScannedReceipts",
            "deleteSelectedReceipts",
            "clearScannedReceipts",
            "confirmScanReceipts",
            "scanIssueBody",
            "scanIssueCount",
            "selectAllScannedIssues",
            "deleteSelectedIssues",
            "clearScannedIssues",
            "confirmScanIssues",
        ):
            self.assertIn(f'id="{element_id}"', webapp.HTML)
        self.assertIn("<th>Действие</th>", webapp.HTML)
        self.assertIn('<script src="/static/js/ui.js"></script>', webapp.HTML)
        self.assertNotRegex(webapp.HTML, re.compile(r"<script(?!\s+src=)[^>]*>"))

    def test_receipt_and_issue_confirm_use_only_current_canonical_rows(self) -> None:
        self.assertIn("function confirmScannedDraft(kind)", UI_JS)
        self.assertIn("const serialNumbers=rows.map(row=>row.serial_number)", UI_JS)
        self.assertIn("serial_numbers:serialNumbers", UI_JS)
        self.assertIn("setScanDraftRows(kind,[]);renderScanDraft(kind)", UI_JS)
        self.assertIn("kind==='receipt'?'CONFIRM_SCANNED_RECEIPTS':'CONFIRM_SCANNED_ISSUES'", UI_JS)
        self.assertNotIn("DELETE_SCANNED_RECEIPTS", UI_JS)
        self.assertNotIn("DELETE_SCANNED_ISSUES", UI_JS)

    def test_all_delete_paths_render_save_and_restore_scanner_focus(self) -> None:
        for function_name in (
            "removeScannedDraftRow",
            "deleteSelectedScannedRows",
            "clearScanDraft",
        ):
            self.assertIn(f"function {function_name}", UI_JS)
        self.assertIn("renderScanDraft(kind);", UI_JS)
        self.assertIn("saveScanDraft(kind,rows)", UI_JS)
        self.assertIn("localStorage.removeItem(scanDraftStorageKey(kind))", UI_JS)
        self.assertIn("focusScanner(kind)", UI_JS)
        self.assertIn("confirm(`Удалить выбранные строки", UI_JS)
        self.assertIn("confirm(`Очистить текущий список", UI_JS)

    def test_duplicate_and_legacy_restore_are_sn_first_and_deduplicated(self) -> None:
        self.assertIn("Этот S/N уже находится в текущем списке", UI_JS)
        self.assertIn("runtime.pending.has(key)", UI_JS)
        self.assertIn("function uniqueScanDraftRows", UI_JS)
        self.assertIn("const value=JSON.parse(raw),rows=uniqueScanDraftRows", UI_JS)
        self.assertIn("ode_${kind}_draft", UI_JS)

    def test_confirm_locks_draft_and_search_modal_invalidates_stale_results(self) -> None:
        self.assertIn("runtime.confirming=true;runtime.generation+=1", UI_JS)
        self.assertIn("runtime.pending.size", UI_JS)
        self.assertIn("if(input)input.disabled=runtime.confirming", UI_JS)
        self.assertIn("clearTimeout(searchTimer);searchTimer=0;searchSequence+=1", PRODUCT_JS)
        self.assertIn("if(sequence!==searchSequence)return", PRODUCT_JS)

    def test_balance_search_hides_stale_action_rows_during_debounce(self) -> None:
        self.assertIn("const sequence=++balanceSearchSequence", PRODUCT_JS)
        self.assertIn("renderBalanceSearchState('Поиск по всей базе...',true)", PRODUCT_JS)
        self.assertIn("sequence!==balanceSearchSequence", PRODUCT_JS)
        self.assertIn("body.setAttribute('aria-busy',busy?'true':'false')", PRODUCT_JS)


if __name__ == "__main__":
    unittest.main()
