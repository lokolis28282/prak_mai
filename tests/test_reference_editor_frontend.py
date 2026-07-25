from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
JAVASCRIPT = (ROOT / "static/js/administration/references.js").read_text(encoding="utf-8")


class ReferenceEditorFrontendTest(unittest.TestCase):
    def test_engineer_gets_a_small_operational_editor(self) -> None:
        self.assertIn("state.current_user?.role==='engineer'", JAVASCRIPT)
        for label in ("Значение", "Состояние", "Использование", "Действие"):
            self.assertIn(label, JAVASCRIPT)
        self.assertIn("Добавить значение", JAVASCRIPT)
        self.assertIn("Отключение не удаляет старые операции", JAVASCRIPT)
        self.assertIn("operatorDomains", JAVASCRIPT)
        self.assertIn("!operator||operatorDomains.has", JAVASCRIPT)

    def test_model_parent_is_selected_from_known_vendors(self) -> None:
        self.assertIn("referenceParentOptions", JAVASCRIPT)
        self.assertIn("value.domain_key==='vendor'", JAVASCRIPT)
        self.assertIn("selected==='model'", JAVASCRIPT)
        self.assertNotIn("Parent (для модели — вендор)", JAVASCRIPT)
        self.assertNotIn("Создать pending proposal", JAVASCRIPT)


if __name__ == "__main__":
    unittest.main()
