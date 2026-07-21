from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
WEBAPP = (ROOT / "inventory" / "webapp.py").read_text(encoding="utf-8")
UI_JS = (ROOT / "static" / "js" / "ui.js").read_text(encoding="utf-8")
PRODUCT_JS = (ROOT / "static" / "js" / "product.js").read_text(encoding="utf-8")
TREE_JS = (ROOT / "static" / "js" / "warehouse" / "stock_tree.js").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "css" / "main.css").read_text(encoding="utf-8")


class WarehouseStockTreeFrontendTest(unittest.TestCase):
    def test_tree_markup_and_lazy_endpoint_are_wired(self) -> None:
        self.assertIn('id="warehouseStockTree"', WEBAPP)
        self.assertIn('aria-label="Дерево складских остатков"', WEBAPP)
        self.assertIn('"warehouse/stock_tree.js"', WEBAPP)
        self.assertIn('/api/warehouse-stock-tree', WEBAPP)
        self.assertIn('/api/data?include_balance=0', UI_JS)
        self.assertIn("window.warehouseStockTree?.attach()", PRODUCT_JS)

    def test_tree_has_lazy_paging_cache_and_independent_expansion(self) -> None:
        self.assertIn("const PAGE_SIZE=100", TREE_JS)
        self.assertIn("const cache=new Map(),expanded=new Set(),pending=new Map()", TREE_JS)
        self.assertIn("expanded.has(node.id)", TREE_JS)
        self.assertIn("cache.has(node.id)", TREE_JS)
        self.assertIn("on:{click:event=>{event.stopPropagation();toggle(node)}}", TREE_JS)
        self.assertIn("loadChildren(parent,true)", TREE_JS)
        self.assertIn("response.node_count", TREE_JS)
        self.assertIn("Показать ещё", TREE_JS)
        self.assertIn("requestGeneration!==generation", TREE_JS)

    def test_search_filters_export_and_states_are_integrated(self) -> None:
        self.assertIn("event?.target?.id==='balanceQuery'?320:0", TREE_JS)
        self.assertIn("query&&Number(total.positions)<=50", TREE_JS)
        self.assertIn("По заданным условиям складские позиции не найдены", TREE_JS)
        self.assertIn("Не удалось загрузить складские позиции", TREE_JS)
        self.assertIn("Загрузка складских групп", TREE_JS)
        self.assertIn("'/export/balance.csv?'", TREE_JS)

    def test_accessibility_totals_and_actions_are_preserved(self) -> None:
        self.assertIn("'aria-expanded'", TREE_JS)
        self.assertIn("aria-label", TREE_JS)
        self.assertIn("Общий итог", TREE_JS)
        self.assertIn("node.has_children&&node.next_level", TREE_JS)
        self.assertIn("warehouse-stock-tree-terminal", TREE_JS)
        self.assertNotIn("openPositionCard", TREE_JS)
        self.assertNotIn("selectForIssue", TREE_JS)
        self.assertNotIn("positionMeta", TREE_JS)
        self.assertNotIn("Открыть карточку", TREE_JS)
        self.assertNotIn("Списать", TREE_JS)
        self.assertNotIn("S/N:", TREE_JS)
        self.assertNotIn("Действия", TREE_JS)
        self.assertIn('<th>Группа</th><th>Позиций</th><th>В наличии</th>', WEBAPP)

    def test_new_styles_are_scoped_and_mobile_layout_is_bounded(self) -> None:
        marker = "/* Lazy warehouse balance tree."
        tree_css = CSS.split(marker, 1)[1]
        rules = [part.strip() for part in tree_css.split("}") if "{" in part]
        selectors = [part.split("{", 1)[0].strip() for part in rules]
        for selector in selectors:
            if selector.startswith("@") or selector in {"to"}:
                continue
            with self.subTest(selector=selector):
                self.assertTrue(
                    all("#balance .warehouse-stock-tree" in item for item in selector.split(",")),
                    selector,
                )
        self.assertIn("max-width:560px", tree_css)
        self.assertIn("min-width:0", tree_css)
        self.assertIn("overflow-wrap:anywhere", tree_css)


if __name__ == "__main__":
    unittest.main()
