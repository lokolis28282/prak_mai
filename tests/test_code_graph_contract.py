import unittest
from pathlib import PurePosixPath

from inventory import __version__
from scripts import generate_code_graph


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


if __name__ == "__main__":
    unittest.main()
