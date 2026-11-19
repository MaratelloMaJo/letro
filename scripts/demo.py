"""Scripted demo: one composite dev episode plus one clean episode.

Run ``python scripts/demo.py``. No model, network or GPU is involved. The
thorough reference policy investigates the files exactly through the public
tools, then submits findings with evidence.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from letro.factory import env_from_episode  # noqa: E402
from letro.generator import load_episode  # noqa: E402
from letro.policies import ThoroughPolicy  # noqa: E402
from letro.trajectory import TrajectoryRecorder, run_episode  # noqa: E402


def _entry(episode_id: str) -> dict:
    index = json.loads((ROOT / "episodes" / "index.json").read_text(encoding="utf-8"))
    for entry in index["dev"]:
        if entry["episode_id"] == episode_id:
            return entry
    raise SystemExit(f"episode {episode_id} is not in the dev split")


def _run(episode_id: str) -> None:
    entry = _entry(episode_id)
    episode = load_episode(ROOT / entry["directory"])
    env, evaluator = env_from_episode(episode, mode="train")
    observation, info = env.reset()
    print(f"episode {episode_id}")
    print(f"  period   {observation['manifest']['period_start']} .. {observation['manifest']['period_end']}")
    print(f"  base     {observation['manifest']['base_currency']}")
    print(f"  records  {observation['manifest']['ledger_rows']} ledger rows, {observation['manifest']['documents']} documents")
    print(f"  task     {observation['task'][:96]}...")
    print(f"  steps    {info['steps_remaining']} available")

    recorder = TrajectoryRecorder()
    result = run_episode(env, ThoroughPolicy(), recorder=recorder, evaluator=evaluator)
    metrics = evaluator.result()
    actions = Counter(
        "submit" if entry["action"].get("type") == "submit" else entry["action"].get("type")
        for entry in recorder.entries
    )
    print(f"  actions  {actions.get('list_records', 0)} list, "
          f"{actions.get('get_record', 0)} get, {actions.get('calculator', 0)} calc, "
          f"{actions.get('submit', 0)} submit")
    print(
        "  result   "
        f"TP={metrics.get('tp')} FP={metrics.get('fp')} FN={metrics.get('fn')} "
        f"P={metrics.get('precision')} R={metrics.get('recall')} F1={metrics.get('f1')} "
        f"reward={result.reward}"
    )
    print()


def main() -> int:
    print("LETRO scripted demo")
    print("===================")
    print()
    _run("ep-0dc0a85bf7")
    _run("ep-b545af7e17")
    print("Both runs used only list_records/get_record/get_document/calculator/submit.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
