"""Record reproducible trajectories for the shipped baseline policies.

    python scripts/record_trajectories.py

Writes ``trajectories/trajectories.jsonl`` with the exact fields required by
the brief and ``trajectories/summary.json`` with measured outcomes. Only open
information is ever written: the oracle policy is intentionally excluded here
because its answers derive from closed truth.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from letro.factory import env_from_episode  # noqa: E402
from letro.generator import load_episode  # noqa: E402
from letro.policies import make_policy  # noqa: E402
from letro.trajectory import (  # noqa: E402
    TrajectoryRecorder,
    run_episode,
    validate_trajectory_file,
)

RUNS = [
    ("train", "reconciliation"),
    ("train", "random_explorer"),
    ("dev", "reconciliation"),
    ("dev", "thorough"),
]


def main() -> int:
    index = json.loads((ROOT / "episodes" / "index.json").read_text(encoding="utf-8"))
    target = ROOT / "trajectories" / "trajectories.jsonl"
    if target.exists():
        target.unlink()
    summary = {"runs": []}
    with TrajectoryRecorder(target, mode="w") as recorder:
        for split, policy_name in RUNS:
            for entry in index[split]:
                episode = load_episode(ROOT / entry["directory"], load_closed=True)
                env, evaluator = env_from_episode(episode, mode="train")
                policy = make_policy(policy_name, episode=episode, seed=entry["seed"])
                result = run_episode(env, policy, recorder=recorder, evaluator=evaluator)
                summary["runs"].append(
                    {
                        "split": split,
                        "policy": policy_name,
                        "episode_id": result.episode_id,
                        "steps": result.steps,
                        "terminated": result.terminated,
                        "truncated": result.truncated,
                        "f1": result.metrics.get("f1"),
                        "precision": result.metrics.get("precision"),
                        "recall": result.metrics.get("recall"),
                        "tp": result.metrics.get("tp"),
                        "fp": result.metrics.get("fp"),
                        "fn": result.metrics.get("fn"),
                        "reward": result.evaluator_reward,
                    }
                )
    report = validate_trajectory_file(target)
    summary["validation"] = report
    summary_path = ROOT / "trajectories" / "summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    for run in summary["runs"]:
        print(
            f"{run['split']:5s} {run['policy']:14s} {run['episode_id']} "
            f"steps={run['steps']:3d} f1={run['f1']} reward={run['reward']}"
        )
    print(f"{report['records']} records across {report['episodes']} episodes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
