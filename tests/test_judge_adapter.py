"""Official judge adapter contract: generation, closed reset and canonical actions."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import judge_adapter
from letro.constants import MAX_STEPS
from letro.generator import load_episode


class JudgeAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.directory = Path(cls._tmp.name) / "episode"
        judge_adapter.generate_episode(
            21,
            {
                "sizes": {"issues": 1},
                "errors": {
                    "duplicate_invoice": 1,
                    "payment_allocation_gap": 0,
                    "fx_rate_error": 0,
                    "period_cutoff": 0,
                    "composite": 0,
                },
            },
            str(cls.directory),
        )
        cls.episode = load_episode(cls.directory)
        cls.truth_issue = cls.episode.truth["issues"][0]
        cls.correct_finding = {
            "type": cls.truth_issue["type"],
            "affected_ids": list(cls.truth_issue["affected_ids"]),
            "claimed_amount_minor": cls.truth_issue["expected_amount_minor"],
            "currency": cls.truth_issue["currency"],
            "evidence_ids": list(cls.truth_issue["allowed_evidence_sets"][0]),
            "explanation": "duplicate invoice posted twice",
        }

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def make_closed_env(self):
        env = judge_adapter.make_env()
        env.reset(
            21,
            {
                "mode": "closed",
                "episode_dir": str(self.directory),
                "team_config": {},
            },
        )
        return env

    def test_generate_episode_writes_open_and_closed_files(self):
        for name in (
            "manifest.json",
            "policy.json",
            "ledger.csv",
            "invoices.jsonl",
            "payments.jsonl",
            "fx.csv",
            "truth.json",
            "provenance.json",
        ):
            self.assertTrue((self.directory / name).exists(), name)

    def test_closed_reset_loads_exact_episode_and_first_observation(self):
        env = self.make_closed_env()
        observation, info = env.reset(
            21,
            {
                "mode": "closed",
                "episode_dir": str(self.directory),
                "team_config": {},
            },
        )
        self.assertEqual(
            set(observation), {"task", "manifest", "policy", "remaining_steps"}
        )
        self.assertEqual(
            observation["manifest"]["episode_id"],
            self.episode.manifest["episode_id"],
        )
        self.assertEqual(observation["remaining_steps"], MAX_STEPS)
        self.assertEqual(info["episode_id"], self.episode.manifest["episode_id"])

        def keys(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    yield key
                    yield from keys(item)
            elif isinstance(value, list):
                for item in value:
                    yield from keys(item)

        self.assertNotIn("truth", set(keys(observation)))
        self.assertNotIn("provenance", set(keys(observation)))

    def test_reset_restarts_the_same_episode(self):
        env = self.make_closed_env()
        env.step({"name": "list_records", "args": {"table": "ledger", "limit": 1}})
        observation, _info = env.reset(
            21,
            {
                "mode": "closed",
                "episode_dir": str(self.directory),
                "team_config": {},
            },
        )
        self.assertEqual(observation["remaining_steps"], MAX_STEPS)
        self.assertEqual(
            observation["manifest"]["episode_id"],
            self.episode.manifest["episode_id"],
        )

    def test_list_records_returns_canonical_page(self):
        env = self.make_closed_env()
        observation, reward, terminated, truncated, _info = env.step(
            {"name": "list_records", "args": {"table": "ledger", "limit": 5}}
        )
        result = observation["result"]
        self.assertLessEqual(len(result["records"]), 5)
        self.assertIsInstance(result["records"][0], dict)
        self.assertTrue(
            result["next_cursor"] is None
            or isinstance(result["next_cursor"], str)
        )
        self.assertEqual(reward, 0.0)
        self.assertFalse(terminated)
        self.assertFalse(truncated)
        self.assertEqual(
            set(observation), {"result", "error", "remaining_steps"}
        )

    def test_calculator_returns_decimal_string(self):
        env = self.make_closed_env()
        observation, *_ = env.step(
            {"name": "calculator", "args": {"expression": "0.1+0.2"}}
        )
        self.assertEqual(observation["result"], "0.3")

    def test_get_record_and_get_document(self):
        env = self.make_closed_env()
        row = self.episode.ledger[0]
        observation, *_ = env.step(
            {
                "name": "get_record",
                "args": {"table": "ledger", "id": row["row_id"]},
            }
        )
        self.assertEqual(observation["result"]["row_id"], row["row_id"])
        invoice = self.episode.invoices[0]
        observation, *_ = env.step(
            {"name": "get_document", "args": {"doc_id": invoice["doc_id"]}}
        )
        self.assertEqual(observation["result"]["doc_id"], invoice["doc_id"])

    def test_unknown_action_is_bounded_and_costs_a_step(self):
        env = self.make_closed_env()
        observation, reward, terminated, truncated, _info = env.step(
            {"name": "drop_table", "args": {}}
        )
        self.assertIsNone(observation["result"])
        self.assertIsInstance(observation["error"], dict)
        self.assertEqual(observation["error"]["code"], "tool_error")
        self.assertLessEqual(len(observation["error"]["message"]), 200)
        self.assertEqual(observation["remaining_steps"], MAX_STEPS - 1)
        self.assertEqual(reward, 0.0)
        self.assertFalse(terminated)
        self.assertFalse(truncated)

    def test_submit_accepts_valid_findings_and_hides_closed_reward(self):
        env = self.make_closed_env()
        observation, reward, terminated, truncated, info = env.step(
            {
                "name": "submit",
                "args": {"findings": {"findings": [self.correct_finding]}},
            }
        )
        self.assertEqual(observation["result"], {"accepted": True})
        self.assertIsNone(observation["error"])
        self.assertEqual(reward, 0.0)
        self.assertTrue(terminated)
        self.assertFalse(truncated)
        self.assertTrue(info.get("submitted"))

    def test_wall_clock_timeout_truncates_with_empty_findings(self):
        env = self.make_closed_env()
        env._deadline = 0.0
        observation, reward, terminated, truncated, info = env.step(
            {"name": "list_records", "args": {"table": "ledger", "limit": 1}}
        )
        self.assertIsNone(observation["result"])
        self.assertEqual(observation["error"]["code"], "time_limit")
        self.assertEqual(reward, 0.0)
        self.assertTrue(terminated)
        self.assertTrue(truncated)
        self.assertTrue(info.get("truncated"))

    def test_adapter_pagination_reaches_all_rows(self):
        env = self.make_closed_env()
        seen: list[str] = []
        cursor = None
        while True:
            observation, *_ = env.step(
                {
                    "name": "list_records",
                    "args": {
                        "table": "ledger",
                        "limit": 50,
                        "cursor": cursor,
                    },
                }
            )
            page = observation["result"]
            seen.extend(row["row_id"] for row in page["records"])
            cursor = page["next_cursor"]
            if cursor is None:
                break
        self.assertEqual(len(seen), len(set(seen)))
        self.assertEqual(len(seen), len(self.episode.ledger))

    def test_score_episode_test_1(self):
        result = judge_adapter.score_episode(
            str(self.directory),
            {
                "episode_id": self.episode.manifest["episode_id"],
                "findings": [self.correct_finding],
            },
            10,
        )
        self.assertEqual(result["tp"], 1)
        self.assertEqual(result["fp"], 0)
        self.assertEqual(result["fn"], 0)
        self.assertAlmostEqual(result["precision"], 1.0)
        self.assertAlmostEqual(result["recall"], 1.0)
        self.assertAlmostEqual(result["f1"], 1.0)
        self.assertAlmostEqual(result["return"], 0.98, places=9)

    def test_score_episode_invalid_structure(self):
        result = judge_adapter.score_episode(
            str(self.directory),
            {"episode_id": self.episode.manifest["episode_id"], "findings": [{}] * 31},
            10,
        )
        self.assertEqual(
            result,
            {
                "tp": None,
                "fp": None,
                "fn": None,
                "precision": None,
                "recall": None,
                "f1": None,
                "return": -1,
            },
        )


if __name__ == "__main__":
    unittest.main()
