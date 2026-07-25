from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class MonitoringFrontendContractTest(unittest.TestCase):
    def test_manual_search_ui_and_api_contract_are_connected(self) -> None:
        webapp = (ROOT / "inventory" / "webapp.py").read_text(encoding="utf-8")
        product = (ROOT / "static" / "js" / "product.js").read_text(encoding="utf-8")
        ui = (ROOT / "static" / "js" / "ui.js").read_text(encoding="utf-8")
        monitoring = (ROOT / "static" / "js" / "monitoring" / "index.js").read_text(encoding="utf-8")
        css = (ROOT / "static" / "css" / "main.css").read_text(encoding="utf-8")
        self.assertIn('"/api/monitoring/status"', webapp)
        self.assertIn('"/api/monitoring/manual-search"', webapp)
        self.assertIn("monitoring-tool-launcher", product)
        self.assertIn("renderProductRoute(initialSection,initialView)", product)
        self.assertIn("subtitle:'Ручной поиск по Hostname'", ui)
        self.assertIn("'История поиска'", ui)
        self.assertIn("openMonitoringManualSearch", monitoring)
        self.assertIn("ode_monitoring_manual_search_history", monitoring)
        self.assertIn("Development mock", monitoring)
        self.assertIn(".monitoring-tool-launcher", css)
        self.assertNotIn("innerHTML", monitoring)


if __name__ == "__main__":
    unittest.main()
