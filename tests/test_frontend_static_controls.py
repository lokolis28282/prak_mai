import unittest

from scripts import audit_frontend_contracts


class FrontendStaticControlsTest(unittest.TestCase):
    def test_static_buttons_are_named_bound_and_restore_is_fail_closed(self):
        button_count, violations = audit_frontend_contracts.static_control_violations()

        self.assertGreaterEqual(button_count, 50)
        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
