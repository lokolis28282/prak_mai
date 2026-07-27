from __future__ import annotations

import hashlib
import inspect
from pathlib import Path
import unittest

from inventory import __version__, webapp


ROOT = Path(__file__).resolve().parents[1]


class WebappExtractionContractTest(unittest.TestCase):
    def test_webapp_is_a_thin_http_shell(self) -> None:
        source = (ROOT / "inventory/webapp.py").read_text(encoding="utf-8")
        self.assertLessEqual(len(source.splitlines()), 1_000)
        self.assertNotIn("<!doctype html>", source)
        self.assertNotIn("app_context.reports.", source)
        self.assertNotIn("app_context.monitoring.", source)
        self.assertNotIn("app_context.knowledge.", source)

    def test_all_domain_route_modules_are_wired(self) -> None:
        source = inspect.getsource(webapp.make_handler)
        for module in (
            "administration_routes",
            "reports_routes",
            "warehouse_routes",
            "monitoring_routes",
            "knowledge_routes",
            "vacations_routes",
        ):
            with self.subTest(module=module):
                self.assertIn(f"{module}.handle_", source)
        for filename in (
            "administration.py",
            "reports.py",
            "warehouse.py",
            "monitoring.py",
            "knowledge.py",
            "vacations.py",
        ):
            with self.subTest(filename=filename):
                self.assertTrue((ROOT / "inventory/routes" / filename).is_file())

    def test_templates_are_external_and_runtime_html_matches_release(self) -> None:
        template_source = (
            ROOT / "inventory/templates/webapp.py"
        ).read_text(encoding="utf-8")
        self.assertIn("<!doctype html>", template_source)
        self.assertIn('id="warehouseStockTree"', webapp.HTML)
        self.assertIn('id="knowledge"', webapp.HTML)
        self.assertIn(
            f'href="/static/css/main.css?v={__version__}"',
            webapp.HTML,
        )
        self.assertIn(
            f'src="/static/js/product.js?v={__version__}"',
            webapp.HTML,
        )
        self.assertEqual(
            hashlib.sha256(webapp.LOGIN_HTML.encode("utf-8")).hexdigest(),
            "d5b644eaf2250b8889a0b2feae3bc38eda890208c3f980726ae69f1637190535",
        )
        self.assertEqual(
            hashlib.sha256(webapp.HTML.encode("utf-8")).hexdigest(),
            "5e33000bc9d8c37b8945289936a7270536c4dce43dd10acf6bccca5d385a0d53",
        )

    def test_routes_and_templates_do_not_own_business_sql(self) -> None:
        route_paths = list((ROOT / "inventory/routes").glob("*.py"))
        for path in route_paths:
            source = path.read_text(encoding="utf-8").upper()
            with self.subTest(path=path.name):
                for token in (
                    "SELECT ",
                    "INSERT INTO ",
                    "UPDATE USERS ",
                    "DELETE FROM ",
                    "SQLITE3.CONNECT",
                ):
                    self.assertNotIn(token, source)
        template_source = (
            ROOT / "inventory/templates/webapp.py"
        ).read_text(encoding="utf-8").casefold()
        self.assertNotIn("sqlite3.connect", template_source)


if __name__ == "__main__":
    unittest.main()
