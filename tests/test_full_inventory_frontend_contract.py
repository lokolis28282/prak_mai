from __future__ import annotations

import unittest
from pathlib import Path

from inventory import webapp


ROOT = Path(__file__).resolve().parents[1]


class FullInventoryFrontendContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.javascript = (ROOT / "static/js/warehouse/full_inventory.js").read_text(
            encoding="utf-8"
        )
        cls.css = (ROOT / "static/css/main.css").read_text(encoding="utf-8")

    def test_external_script_banner_and_root_are_in_final_html(self) -> None:
        self.assertIn('<script src="/static/js/warehouse/full_inventory.js"></script>', webapp.HTML)
        self.assertIn('id="warehouseSystemBanner"', webapp.HTML)
        self.assertIn('id="fullInventoryApp"', webapp.HTML)
        self.assertNotIn("<script>function createSession", webapp.HTML)

    def test_ui_uses_dom_text_rendering_and_has_no_approval_action(self) -> None:
        self.assertIn("textContent", self.javascript)
        self.assertIn("replaceChildren", self.javascript)
        self.assertNotIn("innerHTML", self.javascript)
        self.assertNotIn("/approve", self.javascript)
        self.assertNotIn("/publish", self.javascript.casefold())
        self.assertIn("candidate-rehearsal", self.javascript)
        self.assertIn("активация выполняется отдельным контролируемым этапом", self.javascript)
        for technical_term in ("FULL inventory session", "Preview rows", "Disposable baseline rehearsal"):
            self.assertNotIn(technical_term, self.javascript)
        self.assertIn("COMPATIBILITY", self.javascript.upper())

    def test_inventory_and_demo_messages_are_styled(self) -> None:
        self.assertNotIn("Показанные остатки рассчитаны", self.javascript)
        self.assertIn("banner.hidden=true", self.javascript)
        self.assertIn("DEMO", self.javascript)
        self.assertIn("disposable базе", self.javascript)
        self.assertIn("status?.posting_allowed", self.javascript)
        self.assertIn(".warehouse-system-banner", self.css)
        self.assertIn(".test-circuit-banner+.app .warehouse-system-banner", self.css)
        self.assertIn(".full-inventory-app", self.css)

    def test_baseline_timestamp_and_deferred_catalog_limit_are_explicit(self) -> None:
        self.assertIn("baseline_timestamp", self.javascript)
        self.assertIn("Автоматическое сопоставление моделей пока не выполняется", self.javascript)
        self.assertIn("Начать полную инвентаризацию", self.javascript)
        self.assertIn("Скачать XLSX для сканирования", self.javascript)
        self.assertIn("актуальные типы, наименования и полки", self.javascript)
        self.assertIn("Как сформировать фактический баланс", self.javascript)
        self.assertIn("этот список станет новым фактическим балансом", self.javascript)
        current_state = (
            ROOT / "docs/project/reviews/2026-07-16_FULL_INVENTORY_SLICE_1_CURRENT_STATE.md"
        ).read_text(encoding="utf-8")
        self.assertIn('catalog_validation: "DEFERRED"', current_state)
        self.assertIn("не связывает строки по Vendor/Model/Description", current_state)

    def test_mutating_buttons_are_single_flight_and_preview_cannot_be_rejected(self) -> None:
        self.assertIn("result.disabled=true", self.javascript)
        self.assertIn("session.session_status==='PREVIEWING'", self.javascript)


if __name__ == "__main__":
    unittest.main()
