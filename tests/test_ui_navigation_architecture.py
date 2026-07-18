from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent.parent


class UiNavigationArchitectureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.router = (ROOT / "static/js/router.js").read_text(encoding="utf-8")
        cls.core = (ROOT / "static/js/core.js").read_text(encoding="utf-8")
        cls.ui = (ROOT / "static/js/ui.js").read_text(encoding="utf-8")
        cls.product = (ROOT / "static/js/product.js").read_text(encoding="utf-8")
        cls.reports = (ROOT / "static/js/reports/index.js").read_text(encoding="utf-8")
        cls.work_logs = (ROOT / "static/js/reports/work_logs.js").read_text(
            encoding="utf-8"
        )
        cls.css = (ROOT / "static/css/main.css").read_text(encoding="utf-8")
        cls.review = (ROOT / "static/js/warehouse/migration_pilot.js").read_text(
            encoding="utf-8"
        )

    def test_primary_navigation_matches_product_structure(self) -> None:
        self.assertIn("nav.replaceChildren();", self.router)
        self.assertIn("nav.hidden=true", self.router)
        self.assertNotIn("const sectionNavItems", self.router)
        self.assertIn("openTask('reports', 'worklogs')", self.reports)
        self.assertIn("sections.works=[['worklogs','УВР']]", self.product)
        self.assertIn("['worklogs','УВР']", self.product)
        self.assertIn("Добро пожаловать в ODE", self.ui)

    def test_warehouse_opens_as_normal_equipment_workspace(self) -> None:
        self.assertIn("['balance','Карточки оборудования']", self.core)
        self.assertIn("openTask('warehouse','balance')", self.product)
        self.assertIn("uxBalanceSupplier", self.ui)
        self.assertIn("uxBalanceVendor", self.ui)
        self.assertIn("warehouse-summary", self.ui)
        self.assertIn("['equipment','Перемещения']", self.product)
        self.assertIn("['references','Справочники']", self.product)
        self.assertIn("disabled:Number(x.balance)<=0", self.ui)

    def test_operational_and_unfinished_modules_are_distinguished(self) -> None:
        self.assertIn("Инструменты мониторинга", self.product)
        self.assertIn("window.openMonitoringManualSearch", self.product)
        self.assertIn("reports/worklogs", self.ui)
        self.assertIn("'warehouse','works','reports','administration'", self.router)
        self.assertIn("window.loadWorkLogs = load", self.work_logs)
        self.assertNotIn("let uvrLogs", self.ui)
        self.assertNotIn("function dailyRow", self.ui)
        self.assertNotIn("dailyLogRows", self.ui)
        self.assertNotIn("Единая модель оборудования", self.product)
        self.assertIn("Администрирование ODE", self.ui)

    def test_hidden_contract_cannot_be_overridden_by_component_display(self) -> None:
        self.assertIn("[hidden]{display:none!important}", self.css)

    def test_reference_placeholders_are_not_duplicated_as_values(self) -> None:
        self.assertIn("values.filter(x=>x&&x!==placeholder)", self.ui)
        self.assertIn("xs.filter(x=>x&&x!==label)", self.ui)

    def test_equipment_card_is_shared_and_hides_technical_details_by_default(self) -> None:
        for label in (
            "Каноническое название",
            "Исходное название",
            "Part Number",
            "Текущее местоположение",
            "История приходов",
            "История расходов",
            "Работы",
            "Фотографии",
            "Документы",
            "Гарантия",
            "Комплектующие",
        ):
            self.assertIn(label, self.product)
        self.assertIn("if(response.migration&&technicalContext)", self.product)
        self.assertIn("isMigrationAdministrationContext", self.product)
        self.assertIn("userFacingHistoryText", self.product)

    def test_migration_review_is_lazy_and_administrator_only(self) -> None:
        self.assertIn("state.current_user?.role!=='admin'", self.review)
        self.assertIn("sections.administration.push(['migration_pilot','Миграция данных'])", self.review)
        self.assertIn("id==='migration_pilot'&&state.current_user?.role==='admin'", self.review)
        self.assertNotIn("sections.migration_pilot=", self.review)
        self.assertNotIn("querySelectorAll('.section-button').forEach(button=>button.hidden=true)", self.review)
        self.assertNotIn("showSection('migration_pilot')", self.review)


if __name__ == "__main__":
    unittest.main()
