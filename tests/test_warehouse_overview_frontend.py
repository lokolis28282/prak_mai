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
        self.assertNotIn("const popularTypes=rows.slice()", PRODUCT_JS)
        self.assertNotIn("Популярные типы", PRODUCT_JS)
        self.assertNotIn("warehouse-type-group", PRODUCT_JS)
        self.assertIn("Текущий баланс склада", PRODUCT_JS)
        self.assertIn("totalQuantity", PRODUCT_JS)
        self.assertIn("складских позиций", PRODUCT_JS)
        self.assertIn("Ошибки учёта", PRODUCT_JS)
        self.assertIn("Данные для уточнения", PRODUCT_JS)
        self.assertNotIn("Проблемные списания", PRODUCT_JS)
        self.assertIn("!Number(row.is_opening_balance||0)", PRODUCT_JS)
        self.assertIn("Дата не указана", PRODUCT_JS)
        self.assertIn("Нажмите на категорию или тип, чтобы открыть готовую выборку в остатках.", PRODUCT_JS)
        self.assertNotIn("state.warehouse_system?.provisional", PRODUCT_JS)
        self.assertNotIn("активации полной инвентаризации", PRODUCT_JS)
        self.assertNotIn("будет пересчитан от нового baseline", PRODUCT_JS)
        self.assertNotIn("Исторические складские данные", PRODUCT_JS)
        self.assertIn("['balance','Остатки']", PRODUCT_JS)
        self.assertIn("Складские позиции", PRODUCT_JS)
        self.assertNotIn("Всё оборудование — одним взглядом", PRODUCT_JS)
        for category in (
            "Трансиверы", "Память", "Накопители",
            "Адаптеры и контроллеры", "Комплектующие", "Кабели",
            "Кабельные сборки", "Другое оборудование",
        ):
            with self.subTest(category=category):
                self.assertIn(category, PRODUCT_JS)
                self.assertIn(category, UI_JS)

    def test_balance_exposes_type_filter_and_sorting(self) -> None:
        self.assertIn("id:'uxBalanceType'", UI_JS)
        self.assertIn("id:'uxBalanceSort'", UI_JS)
        self.assertIn("item_type:'Тип'", UI_JS)
        self.assertIn("balanceSortOptionLabel", UI_JS)
        self.assertIn("sort_by:sort[0]", UI_JS)
        self.assertIn("balanceSortKeys", UI_JS)
        self.assertIn("setBalanceSort(key)", UI_JS)
        self.assertIn("id:'uxBalanceStock'", UI_JS)
        self.assertIn("balancePageOffset", PRODUCT_JS)
        self.assertIn("warehouseStockTree", PRODUCT_JS)
        self.assertIn("const BALANCE_CHUNK_SIZE=100", PRODUCT_JS)
        self.assertIn("installBalanceInfiniteScroll", PRODUCT_JS)
        self.assertNotIn("Страница ${page}", PRODUCT_JS)
        self.assertIn("table-sort", CSS)
        self.assertIn("balance-filter-field", UI_JS)
        self.assertIn("balanceFilterSummary", UI_JS)
        self.assertIn("'Любой остаток','positive'", UI_JS)

    def test_hidden_balance_table_is_not_eagerly_rendered(self) -> None:
        self.assertIn("!balanceView.classList.contains('active')", UI_JS)
        self.assertIn("body?.replaceChildren();", UI_JS)
        self.assertIn("view==='balance')renderSimpleBalance()", PRODUCT_JS)
        self.assertIn("balanceBody?.childElementCount", PRODUCT_JS)

    def test_hidden_reference_and_history_tables_are_not_eagerly_rendered(self) -> None:
        self.assertIn("view&&!view.classList.contains('active')", UI_JS)
        self.assertIn("root&&!root.classList.contains('active')", UI_JS)
        self.assertIn("section==='warehouse'&&view==='references'", PRODUCT_JS)
        self.assertIn("['journal','Все события']", PRODUCT_JS)
        self.assertIn("(section==='warehouse'||section==='reports')&&view==='journal'", PRODUCT_JS)

    def test_warehouse_history_has_distinct_empty_and_error_states(self) -> None:
        self.assertIn("Складские операции пока отсутствуют.", UI_JS)
        self.assertIn("Не удалось загрузить историю складских операций.", UI_JS)
        self.assertIn("console.error('Warehouse history rendering failed',error)", UI_JS)

    def test_header_uses_session_display_name_without_fixed_engineer(self) -> None:
        self.assertIn("function currentUserDisplayName", UI_JS)
        self.assertIn("user.display_name", UI_JS)
        self.assertIn(".profile-actions #currentUser{max-width:320px", CSS)
        self.assertIn("overflow-wrap:anywhere", CSS)
        self.assertNotIn("Мерненко Александр", UI_JS)
        self.assertNotIn("Александр Мерненко", UI_JS)

    def test_receipt_scenario_cards_keep_only_action_titles(self) -> None:
        receipt_cards = UI_JS.split(
            "function rebuildScenarioCards()", 1
        )[1].split(
            "const issue=document.getElementById('issue')", 1
        )[0]
        for title in (
            "Сканировать оборудование",
            "Ручное добавление",
            "Принять кабели",
            "Импорт поставки",
        ):
            self.assertIn(title, receipt_cards)
        self.assertNotIn("<span>", receipt_cards)
        self.assertNotIn("Партия с серийными номерами", receipt_cards)
        self.assertIn("scenario-icon", UI_JS)
        self.assertIn("renderSvgIcon(icons[icon])", UI_JS)
        for emoji in ("📷", "✍", "📦", "📁", "📋", "🧵"):
            self.assertNotIn(emoji, UI_JS)

    def test_issue_scenarios_do_not_leak_unselected_forms(self) -> None:
        self.assertIn("title:'Импорт расхода'", UI_JS)
        self.assertIn("nodes:[issueImport,bulk,issuePreview]", UI_JS)
        self.assertIn("nodes:[manualIssueHeading,manualIssueHint,manualIssue]", UI_JS)
        self.assertIn("issueProblemBox.hidden=!unmatchedIssues.length", UI_JS)
        self.assertIn("querySelector(':scope > .task-hint')?.setAttribute('hidden','')", UI_JS)

    def test_data_quality_uses_one_selected_group_instead_of_all_large_tables(self) -> None:
        self.assertIn("activeProblemKind", UI_JS)
        self.assertIn("selectProblemKind", UI_JS)
        self.assertIn("problem-summary-card", UI_JS)
        self.assertIn("PROBLEM_PAGE_SIZE=50", UI_JS)
        self.assertIn("changeProblemPage", UI_JS)
        self.assertNotIn("обычно ту, где меньше данных", UI_JS)


if __name__ == "__main__":
    unittest.main()
