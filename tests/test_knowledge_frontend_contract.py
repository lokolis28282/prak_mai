from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class KnowledgeFrontendContractTest(unittest.TestCase):
    def test_routes_cards_form_and_responsive_styles_exist(self) -> None:
        webapp = (ROOT / "inventory" / "webapp.py").read_text(encoding="utf-8")
        core = (ROOT / "static" / "js" / "core.js").read_text(encoding="utf-8")
        ui = (ROOT / "static" / "js" / "ui.js").read_text(encoding="utf-8")
        script = (ROOT / "static" / "js" / "knowledge" / "index.js").read_text(encoding="utf-8")
        css = (ROOT / "static" / "css" / "main.css").read_text(encoding="utf-8")
        self.assertIn('id="knowledge"', webapp)
        self.assertIn('"knowledge/index.js"', webapp)
        self.assertIn("window.openKnowledgeBase=openKnowledgeBase", ui)
        self.assertIn("knowledge:[['knowledge','База знаний']]", core)
        self.assertIn("title:'База знаний'", ui)
        for text in (
            "Инструкции", "Спецификации", "Создать статью", "Прикрепленные документы",
            "content_html", "article/", "create/", "edit/", "method:'DELETE'",
            "URLSearchParams", "page_size", "tags", "monitoring-tool-launcher",
        ):
            self.assertIn(text, script)
        self.assertNotIn("innerHTML", script)
        self.assertIn(".knowledge-wiki", css)
        self.assertIn(".knowledge-filters", css)
        self.assertIn("@media(max-width:800px)", css)
        self.assertIn("grid-template-columns:1fr", css)


if __name__ == "__main__":
    unittest.main()
