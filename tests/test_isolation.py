"""Isolation sentinel and lazy environment boundary."""

import unittest

from letro.env import LetroEnv
from letro.isolation import CANARY, check_canary, check_static_boundary, scan_for_canary


class IsolationTest(unittest.TestCase):
    def test_canary_is_not_observable_in_eval_mode(self):
        report = check_canary(seed=1001)
        self.assertEqual(report["verdict"], "PASS")
        self.assertFalse(report["found"])

    def test_canary_scanner_detects_nested_value(self):
        self.assertTrue(scan_for_canary({"a": [{"b": CANARY}]}))
        self.assertFalse(scan_for_canary({"a": [{"b": "clean"}]}))

    def test_env_and_tools_do_not_import_truth_or_audit(self):
        violations = check_static_boundary()
        self.assertEqual(violations, [])

    def test_letro_env_is_still_importable_from_env(self):
        env = LetroEnv(mode="eval")
        observation, info = env.reset(seed=1001)
        self.assertIn("task", observation)
        self.assertNotIn("truth", observation)
        self.assertNotIn("truth", info)


if __name__ == "__main__":
    unittest.main()
