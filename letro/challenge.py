"""Sanitized challenge scoring for the public workbench.

The challenge surface accepts a findings payload for a labelled dev episode and
returns only aggregate metrics and per-finding match booleans. Truth stays
inside :class:`letro.evaluator.Evaluator`; no issue id, expected amount, allowed
evidence set or provenance record crosses this boundary.

Run ``python -m letro.challenge --episode ep-... --findings payload.json``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from .evaluator import Evaluator
from .generator import Episode, load_episode
from .schema import FindingError, validate_findings_payload

ROOT = Path(__file__).resolve().parents[1]
DEV_SPLIT = "dev"


def _dev_entries() -> list[dict[str, Any]]:
    path = ROOT / "episodes" / "index.json"
    if not path.exists():
        raise FindingError(
            "episodes/index.json is missing; run python scripts/build_episodes.py"
        )
    try:
        index = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FindingError("episodes/index.json is not valid JSON") from exc
    entries = index.get(DEV_SPLIT, [])
    if not isinstance(entries, list):
        raise FindingError("episodes/index.json has no dev entries")
    return entries


def load_dev_episode(episode_id: str) -> Episode:
    """Load a labelled dev episode by id; never accept a client path."""
    if not isinstance(episode_id, str) or not episode_id.strip():
        raise FindingError("episode_id is required")
    wanted = episode_id.strip()
    for entry in _dev_entries():
        if isinstance(entry, dict) and entry.get("episode_id") == wanted:
            directory = entry.get("directory")
            if not isinstance(directory, str) or not directory:
                raise FindingError("episode entry has no directory")
            candidate = (ROOT / directory).resolve()
            try:
                candidate.relative_to(ROOT.resolve())
            except ValueError as exc:
                raise FindingError("episode directory escapes the archive") from exc
            return load_episode(candidate)
    raise FindingError(f"unknown dev episode: {wanted}")


def score_submission(
    episode: Episode, payload: dict[str, Any], inspection_steps: int = 0
) -> dict[str, Any]:
    """Score a findings payload and return a truth-free summary.

    The response contains exactly ``tp``, ``fp``, ``fn``, ``precision``,
    ``recall``, ``f1``, ``reward`` and ``findings``. Each finding entry has only
    ``index`` and ``matched``.
    """
    normalized = validate_findings_payload(payload)
    if normalized["episode_id"] != episode.manifest["episode_id"]:
        raise FindingError("episode_id does not match the active episode")

    evaluator = Evaluator(episode)
    scored = evaluator.score(normalized, inspection_steps, expose=True)
    result = evaluator.last_result
    if scored.get("invalid") or result is None:
        raise FindingError("submission was rejected by the evaluator")

    matched = {item["finding_index"] for item in result.matched}
    findings = [
        {"index": index, "matched": index in matched}
        for index in range(len(normalized["findings"]))
    ]
    metrics = result.metrics()
    return {
        "tp": metrics["tp"],
        "fp": metrics["fp"],
        "fn": metrics["fn"],
        "precision": metrics["precision"],
        "recall": metrics["recall"],
        "f1": metrics["f1"],
        "reward": scored["reward"],
        "findings": findings,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m letro.challenge")
    parser.add_argument("--episode", required=True, help="labelled dev episode id")
    parser.add_argument("--findings", required=True, help="path to a JSON findings file")
    args = parser.parse_args(argv)
    try:
        episode = load_dev_episode(args.episode)
        path = Path(args.findings)
        if not path.is_file():
            raise FindingError(f"findings file not found: {args.findings}")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise FindingError("findings file is not valid JSON") from exc
        result = score_submission(episode, payload)
    except (FindingError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
