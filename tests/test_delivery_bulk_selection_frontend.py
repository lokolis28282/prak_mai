from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
WEBAPP = (ROOT / "inventory" / "webapp.py").read_text(encoding="utf-8")
UI_JS = (ROOT / "static" / "js" / "ui.js").read_text(encoding="utf-8")
PRODUCT_JS = (ROOT / "static" / "js" / "product.js").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "css" / "main.css").read_text(encoding="utf-8")


class DeliveryBulkSelectionFrontendTest(unittest.TestCase):
    def test_menu_contains_both_bulk_actions_and_accessibility_contract(self) -> None:
        self.assertIn("deliverySelectionMenu()", PRODUCT_JS)
        self.assertIn("Выбрать все','all'", PRODUCT_JS)
        self.assertIn("Выбрать только в состоянии «Ожидается»", PRODUCT_JS)
        self.assertIn("'aria-haspopup':'menu'", PRODUCT_JS)
        self.assertIn("role:'menu'", PRODUCT_JS)
        self.assertIn("role:'menuitem'", PRODUCT_JS)
        self.assertIn("event.key==='Escape'", PRODUCT_JS)
        self.assertIn("!event.target.closest?.('.delivery-select')", PRODUCT_JS)

    def test_selection_uses_one_set_for_all_pages_and_manual_checkboxes(self) -> None:
        self.assertIn("selected:new Set()", PRODUCT_JS)
        self.assertIn("/api/delivery-selection?", PRODUCT_JS)
        self.assertIn("response.all_ids", PRODUCT_JS)
        self.assertIn("response.waiting_ids", PRODUCT_JS)
        self.assertIn("checkbox.addEventListener('change'", PRODUCT_JS)
        self.assertIn("deliverySelection.selected.add(lineId)", PRODUCT_JS)
        self.assertIn("deliverySelection.selected.delete(lineId)", PRODUCT_JS)
        self.assertIn("selectedDeliveryLineIds=function()", PRODUCT_JS)
        self.assertIn("const ids=selectedDeliveryLineIds()", UI_JS)
        self.assertIn("window.clearDeliverySelection?.()", UI_JS)
        self.assertIn("await productLoadAll();\n    window.clearDeliverySelection?.();", PRODUCT_JS)

    def test_compact_backend_route_and_scoped_styles_are_present(self) -> None:
        self.assertIn('path == "/api/delivery-selection"', WEBAPP)
        self.assertIn("get_delivery_selection", WEBAPP)
        self.assertIn("#deliveryCard .delivery-select-menu", CSS)
        self.assertIn("#deliveryCard .delivery-select-trigger:focus-visible", CSS)


if __name__ == "__main__":
    unittest.main()
