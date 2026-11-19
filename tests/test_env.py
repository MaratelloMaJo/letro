"""Environment contract: reset, step, tools, limits and isolation."""

from __future__ import annotations

import json
import unittest

from letro.constants import MAX_STEPS
from letro.factory import env_from_episode, make_env
from letro.generator import generate_episode, reference_findings
from tests.support import episode, payload


class EnvironmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ep = episode(61)

    def make(self, ep=None, mode="train"):
        return env_from_episode(ep or self.ep, mode=mode)

    def test_reset_observation(self):
        env, _evaluator = self.make()
        observation, info = env.reset()
        self.assertEqual(info["episode_id"], self.ep.manifest["episode_id"])
        self.assertEqual(observation["budget"]["steps_remaining"], MAX_STEPS)
        self.assertIn("policy_summary", observation)
        self.assertNotIn("ledger", observation)

    def test_step_tuple_and_pagination(self):
        env, _evaluator = self.make()
        env.reset()
        seen = []
        cursor = 0
        while cursor is not None:
            observation, reward, terminated, truncated, info = env.step(
                {
                    "type": "list_records",
                    "table": "ledger",
                    "cursor": cursor,
                    "limit": 50,
                }
            )
            self.assertIsInstance(reward, float)
            self.assertFalse(terminated or truncated)
            page = observation["last_result"]["result"]
            self.assertLessEqual(len(page["rows"]), 50)
            seen.extend(row["row_id"] for row in page["rows"])
            cursor = page["next_cursor"]
        self.assertEqual(set(seen), {row["row_id"] for row in self.ep.ledger})

    def test_invalid_action_is_bounded_and_costs_a_step(self):
        env, _evaluator = self.make()
        _observation, info = env.reset()
        before = info["steps_remaining"]
        observation, _r, terminated, _tr, info = env.step({"type": "drop_table"})
        self.assertFalse(terminated)
        self.assertFalse(observation["last_result"]["ok"])
        self.assertLessEqual(len(observation["last_result"]["error"]), 200)
        self.assertEqual(info["steps_remaining"], before - 1)

    def test_submit_terminates(self):
        clean = episode(62, {"clean": True})
        env, evaluator = self.make(clean)
        env.reset()
        _observation, reward, terminated, truncated, info = env.step(
            {"type": "submit", "findings": payload(clean, [])}
        )
        self.assertTrue(terminated)
        self.assertFalse(truncated)
        self.assertEqual(reward, 1.0)
        self.assertTrue(info["submitted"])
        self.assertEqual(evaluator.submissions, 1)

    def test_submit_after_finish_does_not_rescore(self):
        env, evaluator = self.make()
        env.reset()
        action = {"type": "submit", "findings": reference_findings(self.ep)}
        env.step(action)
        _observation, reward, terminated, _tr, info = env.step(action)
        self.assertTrue(terminated)
        self.assertEqual(reward, 0.0)
        self.assertEqual(info.get("error"), "episode_finished")
        self.assertEqual(evaluator.submissions, 1)

    def test_timeout_truncates_with_empty_answer(self):
        env, _evaluator = self.make()
        env.reset()
        for _ in range(MAX_STEPS - 1):
            _o, _r, terminated, truncated, _i = env.step(
                {"type": "calculator", "expression": "1+1"}
            )
            self.assertFalse(terminated or truncated)
        observation, reward, terminated, truncated, info = env.step(
            {"type": "calculator", "expression": "1+1"}
        )
        self.assertTrue(terminated and truncated)
        self.assertTrue(info["truncated"])
        self.assertEqual(reward, -1.0)
        self.assertEqual(observation["last_result"]["action"], "timeout")

    def test_eval_mode_hides_reward(self):
        env, evaluator = self.make(mode="eval")
        env.reset()
        _observation, reward, terminated, _tr, info = env.step(
            {"type": "submit", "findings": reference_findings(self.ep)}
        )
        self.assertTrue(terminated)
        self.assertEqual(reward, 0.0)
        self.assertNotIn("metrics", info)
        self.assertEqual(evaluator.last_reward, 1.0)

    def test_reset_clears_state(self):
        env, _evaluator = self.make()
        env.reset()
        env.step({"type": "list_records", "table": "ledger", "limit": 3})
        observation, info = env.reset()
        self.assertEqual(observation["budget"]["step"], 0)
        self.assertEqual(info["steps_remaining"], MAX_STEPS)
        observation, _r, _t, _tr, _i = env.step(
            {"type": "list_records", "table": "ledger", "limit": 3}
        )
        self.assertEqual(len(observation["last_result"]["result"]["rows"]), 3)

    def test_observations_are_json_and_clean(self):
        env, _evaluator = self.make()
        observation, info = env.reset()
        json.dumps(observation, allow_nan=False)
        json.dumps(info, allow_nan=False)
        text = json.dumps(observation, ensure_ascii=False)
        self.assertNotIn("expected_amount_minor", text)
        self.assertNotIn("allowed_evidence_sets", text)

    def test_make_env_rebinds_evaluator_on_seeded_reset(self):
        env, first, evaluator = make_env(63, {"clean": True})
        env.reset()
        env.step({"type": "submit", "findings": payload(first, [])})
        self.assertEqual(evaluator.result()["episode_id"], first.manifest["episode_id"])
        self.assertEqual(evaluator.last_reward, 1.0)

        second = generate_episode(64, {"clean": True})
        _observation, info = env.reset(seed=64, config={"clean": True})
        self.assertEqual(info["episode_id"], second.manifest["episode_id"])
        self.assertEqual(
            evaluator.result()["episode_id"], second.manifest["episode_id"]
        )
        _observation, reward, terminated, _tr, _info = env.step(
            {"type": "submit", "findings": payload(second, [])}
        )
        self.assertTrue(terminated)
        self.assertEqual(reward, 1.0)
        self.assertEqual(evaluator.last_reward, 1.0)


if __name__ == "__main__":
    unittest.main()
