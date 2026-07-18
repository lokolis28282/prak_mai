from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
UI_JS = (ROOT / "static" / "js" / "ui.js").read_text(encoding="utf-8")
PRODUCT_JS = (ROOT / "static" / "js" / "product.js").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "css" / "main.css").read_text(encoding="utf-8")


class WarehouseOverviewFrontendTest(unittest.TestCase):
    def test_warehouse_opens_on_overview_with_clickable_type_cards(self) -> None:
        self.assertIn("openTask('warehouse','overview')", PRODUCT_JS)
        self.assertIn("state.warehouse_type_summary||[]", PRODUCT_JS)
        self.assertIn("openWarehouseBalance(category,row.item_type)", PRODUCT_JS)
        self.assertIn("warehouse-type-card", CSS)
        self.assertIn("state.warehouse_system?.authoritative", PRODUCT_JS)
        self.assertIn("Исторические складские данные", PRODUCT_JS)
        self.assertIn("Фактический баланс появится", PRODUCT_JS)

    def test_balance_exposes_type_filter_and_sorting(self) -> None:
        self.assertIn("id:'uxBalanceType'", UI_JS)
        self.assertIn("id:'uxBalanceSort'", UI_JS)
        self.assertIn("['item_type:asc','По типу']", UI_JS)
        self.assertIn("sort_by:sort[0]", UI_JS)
        self.assertIn("balanceSortKeys", UI_JS)
        self.assertIn("setBalanceSort(key)", UI_JS)
        self.assertIn("id:'uxBalanceStock'", UI_JS)
        self.assertIn("balancePageOffset", PRODUCT_JS)
        self.assertIn("response.has_more", PRODUCT_JS)
        self.assertIn("table-sort", CSS)


if __name__ == "__main__":
    unittest.main()
