import unittest

from inventory import __version__
from scripts import generate_code_graph


class CodeGraphContractTest(unittest.TestCase):
    def test_graph_uses_runtime_version_and_extracted_web_layers(self):
        model = generate_code_graph.build_model()
        groups = {node["id"]: node["group"] for node in model["nodes"]}

        self.assertEqual(model["version"], __version__)
        self.assertEqual(groups["inventory.routes.warehouse"], "routes")
        self.assertEqual(groups["inventory.templates.webapp"], "templates")


if __name__ == "__main__":
    unittest.main()
