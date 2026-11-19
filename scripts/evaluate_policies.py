"""Measure the four baseline policies on the open dev split.

The oracle is evaluator-side only: it reads closed truth to produce a perfect
answer, so its numbers prove the matcher and reward work, not that the task is
easy for an agent.
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from letro.factory import env_from_episode  # noqa: E402
from letro.generator import load_episode  # noqa: E402
from letro.policies import make_policy  # noqa: E402
from letro.trajectory import run_episode  # noqa: E402

POLICIES = ("random_explorer", "reconciliation", "thorough", "mark_all", "oracle")


def main() -> int:
    index = json.loads((ROOT / "episodes" / "index.json").read_text(encoding="utf-8"))
    entries = list(index["dev"])
    runs: list[dict[str, Any]] = []

    for entry in entries:
        episode = load_episode(ROOT / entry["directory"])
        for name in POLICIES:
            env, evaluator = env_from_episode(episode, mode="train")
            policy = make_policy(name, episode, seed=entry["seed"])
            result = run_episode(env, policy, evaluator=evaluator)
            metrics = evaluator.result()
            runs.append(
                {
                    "episode_id": entry["episode_id"],
                    "seed": entry["seed"],
                    "clean": entry["clean"],
                    "issues": len(episode.truth["issues"]),
                    "policy": name,
                    "steps": result.steps,
                    "f1": round(float(metrics.get("f1", 0.0)), 6),
                    "precision": round(float(metrics.get("precision", 0.0)), 6),
                    "recall": round(float(metrics.get("recall", 0.0)), 6),
                    "tp": int(metrics.get("tp", 0)),
                    "fp": int(metrics.get("fp", 0)),
                    "fn": int(metrics.get("fn", 0)),
                    "reward": round(float(metrics.get("reward", -1.0)), 6),
                    "terminated": result.terminated,
                    "truncated": result.truncated,
                }
            )

    summary: dict[str, Any] = {}
    for name in POLICIES:
        selected = [run for run in runs if run["policy"] == name]
        clean = [run for run in selected if run["clean"]]
        dirty = [run for run in selected if not run["clean"]]
        summary[name] = {
            "runs": len(selected),
            "mean_f1": round(statistics.fmean(run["f1"] for run in selected), 6),
            "mean_reward": round(statistics.fmean(run["reward"] for run in selected), 6),
            "mean_steps": round(statistics.fmean(run["steps"] for run in selected), 2),
            "clean_mean_f1": round(statistics.fmean(run["f1"] for run in clean), 6),
            "erroneous_mean_f1": round(statistics.fmean(run["f1"] for run in dirty), 6),
            "total_tp": sum(run["tp"] for run in selected),
            "total_fp": sum(run["fp"] for run in selected),
            "total_fn": sum(run["fn"] for run in selected),
        }

    payload = {
        "generated_by": "scripts/evaluate_policies.py",
        "split": "dev",
        "episodes": len(entries),
        "policies": summary,
        "runs": runs,
    }
    output = ROOT / "docs" / "evidence" / "policy-metrics.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    print(f"{'policy':<18}{'F1':>8}{'clean':>8}{'dirty':>8}{'reward':>9}{'steps':>7}")
    for name in POLICIES:
        item = summary[name]
        print(
            f"{name:<18}{item['mean_f1']:>8.3f}{item['clean_mean_f1']:>8.3f}"
            f"{item['erroneous_mean_f1']:>8.3f}{item['mean_reward']:>9.3f}"
            f"{item['mean_steps']:>7.1f}"
        )
    print(f"wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
