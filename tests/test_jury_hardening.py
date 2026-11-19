"""Tests for the lazy env, presets, invariants and fuzz smoke."""

from __future__ import annotations

import unittest

from letro.env import AuditEnv, LetroEnv
from letro.factory import env_from_episode
from letro.fuzz import run
from letro.generator import generate_episode
from letro.invariants import check_episode
from letro.presets import preset, preset_names


class HardeningTests(unittest.TestCase):
    def test_zero_arg_env_builds_episode(self):
        env = AuditEnv()
        observation, info = env.reset(seed=1001, config={"clean": True})
        self.assertIn("manifest", observation)
        self.assertEqual(info["steps_remaining"], 100)
        self.assertEqual(observation["budget"]["step"], 0)
        self.assertGreater(observation["manifest"]["ledger_rows"], 0)

    def test_letro_env_builds_episode(self):
        env = LetroEnv(mode="eval")
        observation, info = env.reset(seed=1001, config={"clean": True})
        self.assertEqual(info["episode_id"], observation["manifest"]["episode_id"])
        self.assertEqual(info["steps_remaining"], 100)

    def test_lazy_reset_with_new_seed_rebuilds(self):
        env = AuditEnv()
        first, _info = env.reset(seed=1001, config={"clean": True})
        second, _info = env.reset(seed=1002, config={"clean": True})
        self.assertNotEqual(
            first["manifest"]["episode_id"], second["manifest"]["episode_id"]
        )

    def test_step_before_reset(self):
        env = LetroEnv()
        observation, reward, terminated, truncated, _info = env.step(
            {"type": "list_records", "table": "ledger", "limit": 1}
        )
        self.assertEqual(reward, 0.0)
        self.assertFalse(terminated)
        self.assertFalse(truncated)
        self.assertEqual(observation["budget"]["step"], 1)
        self.assertEqual(len(observation["last_result"]["result"]["rows"]), 1)

    def test_eval_hides_reward(self):
        episode = generate_episode(1001, {"clean": True})
        env, evaluator = env_from_episode(episode, mode="eval")
        observation, _info = env.reset()
        _obs, reward, terminated, truncated, info = env.step(
            {
                "type": "submit",
                "findings": {
                    "episode_id": observation["manifest"]["episode_id"],
                    "findings": [],
                },
            }
        )
        self.assertEqual(reward, 0.0)
        self.assertTrue(terminated)
        self.assertFalse(truncated)
        self.assertNotIn("metrics", info)
        self.assertEqual(evaluator.last_reward, 1.0)

    def test_presets_are_inside_contract(self):
        for name in preset_names():
            config = preset(name)
            episode = generate_episode(11, config)
            self.assertEqual(check_episode(episode, config), [], name)
            self.assertGreaterEqual(len(episode.ledger), 200)
            self.assertLessEqual(len(episode.ledger), 2000)
            documents = len(episode.invoices) + len(episode.payments)
            self.assertGreaterEqual(documents, 20)
            self.assertLessEqual(documents, 200)
            self.assertLessEqual(len(episode.truth["issues"]), 12)

    def test_invariants_detect_imbalance(self):
        episode = generate_episode(12)
        episode.ledger[0]["debit_minor"] += 1
        problems = check_episode(episode)
        self.assertGreaterEqual(len(problems), 1)

    def test_invariants_detect_missing_evidence(self):
        episode = generate_episode(13)
        episode.truth["issues"][0]["allowed_evidence_sets"] = []
        problems = check_episode(episode)
        self.assertGreaterEqual(len(problems), 1)

    def test_fuzz_smoke(self):
        self.assertEqual(run(seeds=2, names=["default", "clean"], permute=True), 0)

    def test_gym_is_optional(self):
        from letro.gym import register

        try:
            import gymnasium  # noqa: F401
        except ImportError:
            with self.assertRaises(RuntimeError):
                register()
        else:
            self.assertEqual(register(), "LetroEnv-v0")


if __name__ == "__main__":
    unittest.main()
