"""Trajectory logs match the required schema and reject hidden truth."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from letro.factory import env_from_episode
from letro.policies import RandomExplorerPolicy, ReconciliationPolicy
from letro.trajectory import (
    REQUIRED_FIELDS,
    TrajectoryError,
    TrajectoryRecorder,
    run_episode,
    validate_trajectory_file,
)
from tests.support import episode


class TrajectoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ep = episode(111)

    def test_recorded_file_validates(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trajectories.jsonl"
            env, evaluator = env_from_episode(self.ep)
            with TrajectoryRecorder(path) as recorder:
                run_episode(env, ReconciliationPolicy(), recorder=recorder, evaluator=evaluator)
            report = validate_trajectory_file(path)
            self.assertEqual(report["episodes"], 1)
            self.assertEqual(report["runs"], 1)
            self.assertGreater(report["records"], 1)
            first = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(tuple(first), REQUIRED_FIELDS)

    def test_multiple_runs_of_one_episode(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trajectories.jsonl"
            with TrajectoryRecorder(path) as recorder:
                for policy in (ReconciliationPolicy(), RandomExplorerPolicy(seed=3)):
                    env, evaluator = env_from_episode(self.ep)
                    run_episode(env, policy, recorder=recorder, evaluator=evaluator)
            report = validate_trajectory_file(path)
            self.assertEqual(report["episodes"], 1)
            self.assertEqual(report["runs"], 2)

    def test_bad_step_order_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.jsonl"
            base = {
                "episode_id": "ep-1",
                "action": {},
                "observation": {},
                "reward": 0.0,
                "terminated": False,
                "truncated": False,
            }
            with path.open("w", encoding="utf-8") as handle:
                handle.write(json.dumps({**base, "step": 1}) + "\n")
                handle.write(json.dumps({**base, "step": 3}) + "\n")
            with self.assertRaises(TrajectoryError):
                validate_trajectory_file(path)

    def test_unterminated_file_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "open.jsonl"
            entry = {
                "episode_id": "ep-1",
                "step": 1,
                "action": {},
                "observation": {},
                "reward": 0.0,
                "terminated": False,
                "truncated": False,
            }
            path.write_text(json.dumps(entry) + "\n", encoding="utf-8")
            with self.assertRaises(TrajectoryError):
                validate_trajectory_file(path)


if __name__ == "__main__":
    unittest.main()
