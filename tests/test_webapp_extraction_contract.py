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
        # Пины включают cache-busting `?v={__version__}`, поэтому меняются при
        # каждом bump версии. Обновлять их допустимо, только предварительно
        # доказав, что подстановка прежней версии обратно даёт прежний хэш,
        # то есть сама разметка не изменилась.
        self.assertEqual(
            hashlib.sha256(webapp.LOGIN_HTML.encode("utf-8")).hexdigest(),
            "e44ffeacb564d8a1607ec3d5af6b36d5cbfd1d55272c4bc42ae493c233d98826",
        )
        self.assertEqual(
            hashlib.sha256(webapp.HTML.encode("utf-8")).hexdigest(),
            "fc34e17ce4ad771721b116fd76d8daf73a8a25342b3471569391b4241a28f1cd",
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

    def test_runtime_database_table_keeps_long_paths_readable(self) -> None:
        css = (ROOT / "static/css/main.css").read_text(encoding="utf-8")
        self.assertIn("runtime-database-box", webapp.HTML)
        self.assertIn("#admin .split{grid-template-columns:minmax(0,2fr)", css)
        self.assertIn("#admin .split>.box{min-width:0}", css)
        self.assertIn(
            "#admin .runtime-database-box .database-path{min-width:300px",
            css,
        )
        self.assertIn(
            "@media(max-width:950px){#admin .split{grid-template-columns:minmax(0,1fr)}",
            css,
        )

    def test_reports_ui_keeps_pnr_handover_and_viewer_contracts(self) -> None:
        form = (ROOT / "static/js/reports/form.js").read_text(encoding="utf-8")
        handover = (ROOT / "static/js/reports/handover.js").read_text(encoding="utf-8")
        work_logs = (ROOT / "static/js/reports/work_logs.js").read_text(encoding="utf-8")
        ui = (ROOT / "static/js/ui.js").read_text(encoding="utf-8")

        self.assertIn(".uvr-desc-cell, .uvr-description-field", form)
        self.assertIn("state.report_references?.[kind]", form)
        self.assertIn("openTask('reports', 'daily')", (
            ROOT / "static/js/reports/index.js"
        ).read_text(encoding="utf-8"))
        self.assertIn("window.openUvrEdit(row, load)", handover)
        self.assertIn("hidden: state.current_user.role === 'viewer'", work_logs)
        self.assertIn("byId('shiftLogForm')?.closest('.box')", ui)
        self.assertIn('label[for="workLogsCsv"],label[for="workLogsXlsx"]', ui)


if __name__ == "__main__":
    unittest.main()
