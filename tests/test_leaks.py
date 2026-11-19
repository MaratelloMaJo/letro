"""Closed truth must not reach observations, info or trajectory logs."""

from __future__ import annotations

import unittest

from letro.factory import env_from_episode
from letro.trajectory import (
    REQUIRED_FIELDS,
    TrajectoryError,
    TrajectoryRecorder,
    forbidden_paths,
)
from tests.support import episode


class LeakTests(unittest.TestCase):
    def test_forbidden_paths(self):
        self.assertEqual(forbidden_paths({"a": {"truth": 1}}), ["$.a.truth"])
        self.assertEqual(
            forbidden_paths([{"provenance": {}, "ok": 1}]), ["$[0].provenance"]
        )
        self.assertEqual(forbidden_paths({"nested": [{"issue_id": "x"}]}), ["$.nested[0].issue_id"])

    def test_recorder_rejects_observation_leak(self):
        recorder = TrajectoryRecorder()
        entry = {
            "episode_id": "ep-1",
            "step": 1,
            "action": {"type": "list_records"},
            "observation": {"truth": {"issues": []}},
            "reward": 0.0,
            "terminated": False,
            "truncated": False,
        }
        with self.assertRaises(TrajectoryError):
            recorder.write(entry)

    def test_observation_sequence_has_no_hidden_keys(self):
        ep = episode(71)
        env, _evaluator = env_from_episode(ep)
        observation, info = env.reset()
        self.assertEqual(forbidden_paths(observation), [])
        self.assertEqual(forbidden_paths(info), [])
        for action in (
            {"type": "list_records", "table": "ledger", "limit": 2},
            {"type": "get_record", "table": "invoices", "id": ep.invoices[0]["invoice_id"]},
            {"type": "get_document", "doc_id": ep.payments[0]["doc_id"]},
            {"type": "calculator", "expression": "2+2"},
            {"type": "get_record", "table": "ledger", "id": "missing"},
        ):
            observation, _r, _t, _tr, info = env.step(action)
            self.assertEqual(forbidden_paths(observation), [])
            self.assertEqual(forbidden_paths(info), [])

    def test_recorder_entry_has_exact_fields(self):
        recorder = TrajectoryRecorder()
        entry = {
            "episode_id": "ep-1",
            "step": 1,
            "action": {},
            "observation": {},
            "reward": 0.0,
            "terminated": True,
            "truncated": False,
        }
        recorder.write(entry)
        self.assertEqual(tuple(recorder.entries[0]), REQUIRED_FIELDS)


if __name__ == "__main__":
    unittest.main()
