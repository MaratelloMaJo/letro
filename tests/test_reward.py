"""The terminal reward is exactly the published formula."""

from __future__ import annotations

import math
import unittest

from letro.constants import STEP_COST
from letro.reward import terminal_reward


class RewardTests(unittest.TestCase):
    def test_formula(self):
        self.assertEqual(terminal_reward(1.0, 0), 1.0)
        self.assertEqual(terminal_reward(0.0, 0), -1.0)
        self.assertEqual(terminal_reward(1.0, 10), 0.98)
        self.assertEqual(terminal_reward(1.0, 100), 0.8)
        self.assertEqual(terminal_reward(0.5, 0), 0.0)

    def test_step_cost(self):
        difference = terminal_reward(1.0, 10) - terminal_reward(1.0, 100)
        self.assertTrue(math.isclose(difference, 90 * STEP_COST))

    def test_clipping(self):
        self.assertEqual(terminal_reward(1.0, 5000), -1.0)
        self.assertEqual(terminal_reward(0.0, 5000), -1.0)
        self.assertGreaterEqual(terminal_reward(0.0, 100), -1.0)

    def test_invalid_arguments(self):
        with self.assertRaises(TypeError):
            terminal_reward("1", 0)
        with self.assertRaises(TypeError):
            terminal_reward(1.0, 1.5)
        with self.assertRaises(TypeError):
            terminal_reward(1.0, True)
        with self.assertRaises(ValueError):
            terminal_reward(1.0, -1)


if __name__ == "__main__":
    unittest.main()
