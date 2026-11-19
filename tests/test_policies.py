"""Baseline policy adapters behave deterministically and honestly."""

from __future__ import annotations

import unittest

from letro.factory import env_from_episode
from letro.policies import (
    MarkAllPolicy,
    OraclePolicy,
    RandomExplorerPolicy,
    ReconciliationPolicy,
    ThoroughPolicy,
    make_policy,
)
from letro.trajectory import run_episode
from tests.support import episode, errors, config


def run(ep, policy):
    env, evaluator = env_from_episode(ep)
    result = run_episode(env, policy, evaluator=evaluator)
    return result, evaluator.result()


class PolicyTests(unittest.TestCase):
    def test_factory(self):
        self.assertIsInstance(make_policy("reconciliation"), ReconciliationPolicy)
        self.assertIsInstance(make_policy("thorough"), ThoroughPolicy)
        self.assertIsInstance(make_policy("mark_all"), MarkAllPolicy)
        self.assertIsInstance(make_policy("random_explorer", seed=1), RandomExplorerPolicy)
        with self.assertRaises(ValueError):
            make_policy("oracle")
        with self.assertRaises(ValueError):
            make_policy("nope")

    def test_reconciliation_is_an_honest_imperfect_baseline(self):
        ep = episode(101, config(error_counts=errors(composite=2)))
        result, metrics = run(ep, ReconciliationPolicy())
        self.assertTrue(result.terminated)
        self.assertFalse(result.truncated)
        # It finds the provable duplicate / FX / cut-off issues but
        # over-reports open invoices, so it must not be perfect.
        self.assertGreater(metrics["recall"], 0.5)
        self.assertGreater(metrics["fp"], 0)
        self.assertLess(metrics["f1"], 1.0)

    def test_reconciliation_over_reports_clean_books(self):
        ep = episode(102, config(clean=True))
        result, metrics = run(ep, ReconciliationPolicy())
        self.assertTrue(result.terminated)
        self.assertEqual(metrics["tp"], 0)
        self.assertGreater(metrics["fp"], 0)
        self.assertEqual(metrics["f1"], 0.0)
        self.assertEqual(result.reward, -1.0)

    def test_thorough_reference_is_perfect(self):
        for seed, cfg in (
            (106, config(error_counts=errors(composite=2))),
            (107, config(clean=True)),
            (108, config(error_counts=errors(duplicate=1, gap=1, fx=1, cutoff=1))),
        ):
            with self.subTest(seed=seed):
                ep = episode(seed, cfg)
                result, metrics = run(ep, ThoroughPolicy())
                self.assertTrue(result.terminated)
                self.assertEqual(metrics["f1"], 1.0)
                self.assertEqual(metrics["fp"], 0)
                self.assertEqual(metrics["fn"], 0)

    def test_random_explorer_is_deterministic(self):
        ep = episode(103)
        left, left_metrics = run(ep, RandomExplorerPolicy(seed=7))
        right, right_metrics = run(ep, RandomExplorerPolicy(seed=7))
        self.assertEqual(left.steps, right.steps)
        self.assertEqual(left.reward, right.reward)
        self.assertEqual(left_metrics["f1"], right_metrics["f1"])

    def test_oracle_is_evaluator_side_and_perfect(self):
        ep = episode(104)
        result, metrics = run(ep, OraclePolicy(ep))
        self.assertEqual(result.steps, 1)
        self.assertEqual(result.reward, 1.0)
        self.assertEqual(metrics["f1"], 1.0)

    def test_mark_all_is_bad(self):
        ep = episode(105)
        result, metrics = run(ep, MarkAllPolicy())
        self.assertEqual(metrics["f1"], 0.0)
        self.assertEqual(result.reward, -1.0)


if __name__ == "__main__":
    unittest.main()
