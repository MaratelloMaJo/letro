"""Adversarial submissions earn nothing and cannot game the reward."""

from __future__ import annotations

import copy
import unittest

from letro.evaluator import Evaluator
from letro.factory import env_from_episode
from letro.generator import reference_findings
from letro.policies import MarkAllPolicy
from letro.trajectory import run_episode
from tests.support import episode, payload


class AttackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dirty = episode(81)
        cls.clean = episode(82, {"clean": True})

    def test_mark_all_scores_zero(self):
        env, evaluator = env_from_episode(self.dirty)
        result = run_episode(env, MarkAllPolicy(), evaluator=evaluator)
        metrics = evaluator.result()
        self.assertEqual(metrics["f1"], 0.0)
        self.assertLessEqual(result.reward, -0.5)
        self.assertGreater(metrics["fp"], 0)

    def test_mark_all_on_clean_is_punished(self):
        env, evaluator = env_from_episode(self.clean)
        result = run_episode(env, MarkAllPolicy(), evaluator=evaluator)
        self.assertEqual(evaluator.result()["f1"], 0.0)
        self.assertEqual(result.reward, -1.0)

    def test_silence_on_erroneous_books(self):
        evaluator = Evaluator(self.dirty)
        outcome = evaluator.score(payload(self.dirty, []), 0)
        self.assertEqual(outcome["reward"], -1.0)

    def test_false_accusation_on_clean_books(self):
        finding = reference_findings(self.dirty)["findings"][0]
        evaluator = Evaluator(self.clean)
        outcome = evaluator.score(payload(self.clean, [finding]), 0)
        self.assertEqual(outcome["reward"], -1.0)

    def test_fabricated_evidence(self):
        finding = copy.deepcopy(reference_findings(self.dirty)["findings"][0])
        finding["evidence_ids"] = ["LED-999999"]
        evaluator = Evaluator(self.dirty)
        outcome = evaluator.score(payload(self.dirty, [finding]), 0)
        self.assertEqual(outcome["metrics"]["tp"], 0)

    def test_persuasive_text_does_not_help(self):
        finding = copy.deepcopy(reference_findings(self.dirty)["findings"][0])
        finding["type"] = "period_cutoff"
        finding["explanation"] = "This is definitely a material misstatement. " * 10
        evaluator = Evaluator(self.dirty)
        outcome = evaluator.score(payload(self.dirty, [finding]), 0)
        self.assertEqual(outcome["metrics"]["tp"], 0)

    def test_repeated_submission_earns_nothing(self):
        finding = reference_findings(self.dirty)["findings"][0]
        evaluator = Evaluator(self.dirty)
        outcome = evaluator.score(payload(self.dirty, [finding, finding]), 0)
        self.assertEqual(outcome["metrics"]["tp"], 1)
        self.assertEqual(outcome["metrics"]["fp"], 1)


if __name__ == "__main__":
    unittest.main()
