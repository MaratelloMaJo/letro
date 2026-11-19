"""The shipped verifier's technical criteria must all pass."""

from __future__ import annotations

import unittest

from letro.verify import (
    criterion_contract,
    criterion_data,
    criterion_reproducibility,
    criterion_reward,
)


class VerifyTests(unittest.TestCase):
    def assert_all(self, checks):
        failed = [f"{check.name}: {check.detail}" for check in checks if not check.passed]
        self.assertFalse(failed, "\n".join(failed))

    def test_contract(self):
        self.assert_all(criterion_contract())

    def test_data(self):
        self.assert_all(criterion_data([]))

    def test_reward(self):
        self.assert_all(criterion_reward())

    def test_reproducibility(self):
        self.assert_all(criterion_reproducibility())


if __name__ == "__main__":
    unittest.main()
