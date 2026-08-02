import unittest

from scripts import audit_documentation


class DocumentationContractTest(unittest.TestCase):
    def test_repository_documentation_contract(self):
        paths, violations = audit_documentation.audit()

        self.assertGreater(len(paths), 100)
        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
