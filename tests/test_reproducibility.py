"""Replay and harmless transformations preserve answers and rewards."""

from __future__ import annotations

import hashlib
import json
import unittest

from letro.factory import env_from_episode
from letro.generator import generate_episode
from letro.permute import assert_no_reused_ids, permute_episode
from letro.policies import OraclePolicy, ReconciliationPolicy, ThoroughPolicy
from letro.trajectory import run_episode
from tests.support import config, errors


def digest(ep) -> str:
    payload = json.dumps(
        {
            "manifest": ep.manifest,
            "ledger": ep.ledger,
            "invoices": ep.invoices,
            "payments": ep.payments,
            "fx": ep.fx,
            "truth": ep.truth,
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def oracle(ep):
    env, evaluator = env_from_episode(ep)
    result = run_episode(env, OraclePolicy(ep), evaluator=evaluator)
    return result, evaluator.result()


def reconciliation(ep):
    env, evaluator = env_from_episode(ep)
    result = run_episode(env, ReconciliationPolicy(), evaluator=evaluator)
    return result, evaluator.result()


class ReproducibilityTests(unittest.TestCase):
    def test_exact_replay(self):
        cfg = config(error_counts=errors(duplicate=1, gap=1, fx=1, cutoff=1, composite=1))
        first = generate_episode(91, cfg)
        second = generate_episode(91, cfg)
        self.assertEqual(digest(first), digest(second))
        left, left_metrics = reconciliation(first)
        right, right_metrics = reconciliation(second)
        self.assertEqual(left.steps, right.steps)
        self.assertEqual(left.reward, right.reward)
        self.assertEqual(left_metrics, right_metrics)

    def test_permutation_renames_every_id(self):
        original = generate_episode(92, config(error_counts=errors(duplicate=1, fx=1)))
        permuted = permute_episode(original, salt="unit")
        assert_no_reused_ids(original, permuted)
        self.assertEqual(permuted.manifest["episode_id"], original.manifest["episode_id"])
        self.assertEqual(len(permuted.truth["issues"]), len(original.truth["issues"]))

    def test_permutation_preserves_oracle_answer_and_reward(self):
        original = generate_episode(93, config(error_counts=errors(duplicate=1, gap=1, fx=1, cutoff=1)))
        permuted = permute_episode(original, salt="unit")
        before, before_metrics = oracle(original)
        after, after_metrics = oracle(permuted)
        self.assertEqual(before.reward, after.reward)
        self.assertEqual(before_metrics["f1"], after_metrics["f1"])
        self.assertEqual(after_metrics["f1"], 1.0)

    def test_reconciliation_survives_permutation(self):
        original = generate_episode(
            94, config(error_counts=errors(duplicate=2, gap=1, composite=1))
        )
        permuted = permute_episode(original, salt="unit")
        _before, before_metrics = reconciliation(original)
        _after, after_metrics = reconciliation(permuted)
        self.assertEqual(before_metrics, after_metrics)

    def test_thorough_survives_permutation(self):
        original = generate_episode(
            96, config(error_counts=errors(duplicate=1, gap=1, fx=1, cutoff=1))
        )
        permuted = permute_episode(original, salt="unit")
        env, evaluator = env_from_episode(permuted)
        run_episode(env, ThoroughPolicy(), evaluator=evaluator)
        self.assertEqual(evaluator.result()["f1"], 1.0)

    def test_reconciliation_survives_permutation_with_clean_books(self):
        original = generate_episode(95, config(clean=True))
        permuted = permute_episode(original, salt="unit")
        _before, before_metrics = reconciliation(original)
        _after, after_metrics = reconciliation(permuted)
        self.assertEqual(before_metrics, after_metrics)


if __name__ == "__main__":
    unittest.main()
