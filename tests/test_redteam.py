import unittest

from letro.redteam import ATTACKS, BOUNDS, run_attack, run_all


class RedteamTest(unittest.TestCase):
    def test_bounds_cover_every_attack(self):
        self.assertEqual(set(BOUNDS), set(ATTACKS))
        self.assertEqual(len(ATTACKS), 12)

    def test_mark_all_is_bounded(self):
        result = run_attack("mark_all", seed=1001)
        self.assertEqual(result.verdict, "PASS")
        self.assertTrue(result.reward <= 0.2)

    def test_empty_on_clean_scores_one(self):
        result = run_attack("empty_on_clean", seed=1001)
        self.assertEqual(result.verdict, "PASS")
        self.assertAlmostEqual(result.reward, 1.0)

    def test_evidence_less_is_bounded(self):
        result = run_attack("evidence_less", seed=1001)
        self.assertTrue(result.reward <= 0.0)

    def test_duplicate_correct_is_bounded(self):
        result = run_attack("duplicate_correct", seed=1001)
        self.assertTrue(result.reward <= 0.5)

    def test_run_all_returns_one_result_per_attack(self):
        results = run_all([1001])
        self.assertEqual(len(results), len(ATTACKS))
        self.assertTrue(all(item.verdict == "PASS" for item in results))
