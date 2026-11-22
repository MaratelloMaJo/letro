"""Difficulty science and limited-information probe."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from letro.difficulty import TypeMetric, collect, write_evidence
from letro.factory import env_from_episode
from letro.policies.limited import LimitedPolicy
from letro.trajectory import run_episode
from tests.support import episode


class DifficultyTest(unittest.TestCase):
    def test_collect_reports_every_policy_and_type(self):
        metrics = collect()
        policies = {item.policy for item in metrics}
        types = {item.error_type for item in metrics}
        self.assertIn("reconciliation", policies)
        self.assertIn("thorough", policies)
        self.assertIn("payment_allocation_gap", types)
        self.assertTrue(all(0.0 <= item.f1 <= 1.0 for item in metrics))

    def test_limited_policy_stops_after_page_budget(self):
        policy = LimitedPolicy(max_pages=1)
        self.assertEqual(policy.name, "limited")
        self.assertEqual(policy.max_pages, 1)

    def test_thorough_policy_still_reads_all_pages(self):
        policy = __import__("letro.policies", fromlist=["ThoroughPolicy"]).ThoroughPolicy()
        self.assertIsNone(policy.max_pages)


class LimitedPolicyBehaviourTest(unittest.TestCase):
    def test_page_budget_changes_how_much_is_read(self):
        ep = episode(501)
        env_one, _ = env_from_episode(ep)
        one = run_episode(env_one, LimitedPolicy(max_pages=1))
        env_two, _ = env_from_episode(ep)
        two = run_episode(env_two, LimitedPolicy(max_pages=2))
        self.assertTrue(one.terminated)
        self.assertTrue(two.terminated)
        # One page for each of the four tables plus the submit.
        self.assertEqual(one.steps, 5)
        self.assertGreater(two.steps, one.steps)

    def test_limited_is_exported_but_not_a_scored_baseline(self):
        import letro.policies as policies

        self.assertIn("LimitedPolicy", policies.__all__)
        self.assertNotIn("limited", policies.POLICY_NAMES)
        with self.assertRaises(ValueError):
            policies.make_policy("limited")


class EvidenceTest(unittest.TestCase):
    def test_write_evidence_is_sorted_and_deterministic(self):
        metrics = [
            TypeMetric(
                policy="thorough",
                error_type="fx_rate_error",
                tp=1,
                fp=0,
                fn=0,
                precision=1.0,
                recall=1.0,
                f1=1.0,
                example="",
            ),
            TypeMetric(
                policy="limited_1",
                error_type="duplicate_invoice",
                tp=0,
                fp=2,
                fn=1,
                precision=0.0,
                recall=0.0,
                f1=0.0,
                example="duplicate_invoice",
            ),
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "difficulty.json"
            write_evidence(metrics, path)
            first = path.read_bytes()
            write_evidence(list(reversed(metrics)), path)
            self.assertEqual(first, path.read_bytes())
        payload = json.loads(first)
        keys = [(item["policy"], item["error_type"]) for item in payload["metrics"]]
        self.assertEqual(keys, sorted(keys))
        self.assertEqual(len(payload["metrics"]), 2)

    def test_collect_marks_oracle_evaluator_side(self):
        metrics = collect()
        oracle = [item for item in metrics if item.policy == "oracle"]
        self.assertTrue(oracle)
        self.assertTrue(all(item.example == "evaluator-side" for item in oracle))
