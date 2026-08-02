import struct
import unittest
from pathlib import Path
from pathlib import PurePosixPath

from inventory import __version__
from scripts import generate_code_graph


ROOT = Path(__file__).resolve().parents[1]


class CodeGraphContractTest(unittest.TestCase):
    def test_graph_uses_runtime_version_and_extracted_web_layers(self):
        model = generate_code_graph.build_model()
        groups = {node["id"]: node["group"] for node in model["nodes"]}

        self.assertEqual(model["version"], __version__)
        self.assertEqual(groups["inventory.routes.warehouse"], "routes")
        self.assertEqual(groups["inventory.templates.webapp"], "templates")

    def test_frontend_ids_use_repository_posix_paths(self):
        model = generate_code_graph.build_model()
        frontend_ids = [
            node["id"]
            for node in model["nodes"]
            if node["group"] == "frontend"
        ]

        self.assertIn("static/js/ui.js", frontend_ids)
        self.assertTrue(
            all(str(PurePosixPath(node_id)) == node_id for node_id in frontend_ids)
        )
        self.assertTrue(all("\\" not in node_id for node_id in frontend_ids))

    def test_all_node_labels_use_repository_posix_paths(self):
        model = generate_code_graph.build_model()
        labels = [node["label"] for node in model["nodes"]]

        self.assertIn("inventory/administration/multi_database_backup.py", labels)
        self.assertTrue(all("\\" not in label for label in labels))

    def test_current_graph_visuals_are_versioned_and_linked(self):
        expected_name = f"ode-code-graph-{__version__}.png"
        expected_path = generate_code_graph.snapshot_output()
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        graph_doc = (ROOT / "docs/CODEBASE_GRAPH.md").read_text(encoding="utf-8")
        architecture_svg = (
            ROOT / "docs/assets/ode-architecture-graph.svg"
        ).read_text(encoding="utf-8")

        self.assertEqual(expected_path.name, expected_name)
        self.assertIn(expected_name, readme)
        self.assertIn(expected_name, graph_doc)
        self.assertIn(f"ODE {__version__}", architecture_svg)
        self.assertTrue(expected_path.is_file())
        with expected_path.open("rb") as handle:
            self.assertEqual(handle.read(8), b"\x89PNG\r\n\x1a\n")
            self.assertEqual(handle.read(4), b"\x00\x00\x00\r")
            self.assertEqual(handle.read(4), b"IHDR")
            width, height = struct.unpack(">II", handle.read(8))
        self.assertEqual((width, height), (2048, 1152))


if __name__ == "__main__":
    unittest.main()
