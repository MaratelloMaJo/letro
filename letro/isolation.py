"""Isolation sentinel for the lazy environment boundary.

``python -m letro.isolation`` proves, with a real episode and a real eval-mode
environment, that a canary planted in copied truth and provenance can never
surface in any observation, info dict, error string or trajectory record —
because the environment only ever sees open data and a terminal ``finalize``
closure.

It also proves, with a real train-mode environment, that the terminal reward
is visible only on the submit step, never on an intermediate observation.

Finally, it statically parses ``letro/env.py`` and ``letro/tools.py`` and fails
if either imports ``factory``, ``evaluator``, ``generator.audit`` or ``truth``,
which keeps the lazy boundary honest.
"""

from __future__ import annotations

import ast
import copy
import sys
from pathlib import Path
from typing import Any, Sequence

from .constants import TABLES
from .factory import env_from_episode
from .generator import generate_episode
from .trajectory import TrajectoryRecorder

# A sentinel that cannot occur by chance in real financial data.
CANARY = "LETRO-CANARY-9f8a7b6c5d4e3f2a1b0c"

# Modules the lazy boundary must keep out of ``env.py`` and ``tools.py``.
_FORBIDDEN = ("evaluator", "generator.audit", "truth", "factory")


def scan_for_canary(value: Any, canary: str = CANARY) -> bool:
    """Return whether ``canary`` appears anywhere inside ``value``.

    Strings are matched by substring; dicts are scanned across both keys and
    values; lists, tuples and sets are scanned across their items. Numbers,
    booleans and ``None`` cannot carry the string sentinel.
    """
    if isinstance(value, str):
        return canary in value
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(key, str) and canary in key:
                return True
            if scan_for_canary(item, canary):
                return True
        return False
    if isinstance(value, (list, tuple, set, frozenset)):
        return any(scan_for_canary(item, canary) for item in value)
    return False


# ---------------------------------------------------------------------------
# static boundary


def _import_tokens(tree: ast.AST) -> list[str]:
    """Every module/symbol string the source imports, fully dotted."""
    tokens: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                tokens.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            prefix = "." * node.level
            if module:
                tokens.append(prefix + module)
            for alias in node.names:
                name = alias.name
                tokens.append(name)
                if module:
                    tokens.append(prefix + module + "." + name)
                else:
                    tokens.append(prefix + name)
    return tokens


def _forbidden(token: str) -> bool:
    cleaned = token.lstrip(".")
    if cleaned in ("evaluator", "factory", "truth"):
        return True
    if (
        cleaned == "generator.audit"
        or cleaned.startswith("generator.audit.")
        or cleaned.endswith(".generator.audit")
    ):
        return True
    return False


def check_static_boundary() -> list[str]:
    """Return the list of boundary violations across ``env.py`` and ``tools.py``."""
    here = Path(__file__).resolve().parent
    violations: list[str] = []
    for filename in ("env.py", "tools.py"):
        path = here / filename
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=filename)
        for token in _import_tokens(tree):
            if _forbidden(token):
                violations.append(f"{filename} imports {token}")
    return violations


# ---------------------------------------------------------------------------
# dynamic canary check


def _taint_truth(truth: dict[str, Any]) -> dict[str, Any]:
    tainted = copy.deepcopy(truth)
    tainted["canary"] = CANARY
    for issue in tainted.get("issues", []):
        if isinstance(issue, dict):
            issue["explanation"] = CANARY
    return tainted


def _taint_provenance(provenance: dict[str, Any]) -> dict[str, Any]:
    tainted = copy.deepcopy(provenance)
    tainted["canary"] = CANARY
    for step in tainted.get("steps", []):
        if isinstance(step, dict):
            step["canary"] = CANARY
    return tainted


def _train_reward_locality(seed: int) -> tuple[bool, str]:
    """The train-mode reward must show only on the terminal submit."""
    episode = generate_episode(seed, {"clean": True})
    env, _evaluator = env_from_episode(episode, mode="train")
    observation, _info = env.reset()
    if isinstance(observation, dict) and "reward" in observation:
        return False, "reward leaked into the reset observation"
    for action in (
        {"type": "list_records", "table": "ledger", "limit": 1},
        {"type": "calculator", "expression": "1+1"},
    ):
        obs, reward, terminated, truncated, _info = env.step(action)
        if terminated or truncated:
            return False, "an inspection step ended the episode"
        if reward != 0.0:
            return False, f"intermediate reward {reward} was not zero"
        if isinstance(obs, dict) and "reward" in obs:
            return False, "reward leaked into an intermediate observation"
    obs, reward, terminated, truncated, _info = env.step(
        {
            "type": "submit",
            "findings": {"episode_id": episode.manifest["episode_id"], "findings": []},
        }
    )
    if not terminated or truncated:
        return False, "submit did not terminate cleanly"
    if reward == 0.0:
        return False, "terminal reward was zero on clean silence"
    if isinstance(obs, dict) and "reward" in obs:
        return False, "reward was embedded in the submit observation"
    return True, f"terminal reward {reward} after two zero-reward steps"


def check_canary(seed: int = 1001) -> dict[str, Any]:
    """Run a maximal policy over a tainted episode and prove the canary stays hidden.

    The canary is planted in deep copies of the episode's truth and provenance;
    the environment is rebuilt from the *same* episode's open data. Every
    observation, info dict, error string, reward and trajectory record the
    policy produces is scanned for the sentinel.
    """
    episode = generate_episode(seed)
    tainted = copy.deepcopy(episode)
    tainted.truth = _taint_truth(episode.truth)
    tainted.provenance = _taint_provenance(episode.provenance)

    env, _evaluator = env_from_episode(tainted, mode="eval")
    episode_id = episode.manifest["episode_id"]
    recorder = TrajectoryRecorder()

    observed: list[Any] = []
    steps = 0

    observation, info = env.reset()
    observed.extend([observation, info])

    def drive(action: dict[str, Any]) -> None:
        nonlocal steps
        obs, reward, terminated, truncated, info = env.step(action)
        steps += 1
        observed.extend([obs, info, reward])
        last = obs.get("last_result") if isinstance(obs, dict) else None
        if isinstance(last, dict) and last.get("error") is not None:
            observed.append(last["error"])
        if isinstance(info, dict) and info.get("error") is not None:
            observed.append(info["error"])
        recorder.write(
            {
                "episode_id": episode_id,
                "step": steps,
                "action": action,
                "observation": obs,
                "reward": float(reward),
                "terminated": bool(terminated),
                "truncated": bool(truncated),
            }
        )

    # Page every table end to end.
    for table in TABLES:
        cursor: int | None = 0
        while cursor is not None:
            obs, _r, terminated, truncated, _info = env.step(
                {
                    "type": "list_records",
                    "table": table,
                    "cursor": cursor,
                    "limit": 50,
                }
            )
            steps += 1
            observed.extend([obs, _info, _r])
            recorder.write(
                {
                    "episode_id": episode_id,
                    "step": steps,
                    "action": {"type": "list_records", "table": table, "cursor": cursor},
                    "observation": obs,
                    "reward": float(_r),
                    "terminated": bool(terminated),
                    "truncated": bool(truncated),
                }
            )
            if terminated or truncated:
                cursor = None
            else:
                cursor = obs["last_result"]["result"]["next_cursor"]

    # Exercise the remaining tool types and error paths.
    if episode.ledger:
        drive({"type": "get_record", "table": "ledger", "id": episode.ledger[0]["row_id"]})
    if episode.invoices:
        drive({"type": "get_record", "table": "invoices", "id": episode.invoices[0]["invoice_id"]})
    if episode.payments:
        drive({"type": "get_record", "table": "payments", "id": episode.payments[0]["payment_id"]})
    if episode.invoices:
        drive({"type": "get_document", "doc_id": episode.invoices[0]["doc_id"]})
    if episode.payments:
        drive({"type": "get_document", "doc_id": episode.payments[0]["doc_id"]})
    drive({"type": "calculator", "expression": "2*(3+4)-5"})
    drive({"type": "drop_table"})
    drive(
        {
            "type": "submit",
            "findings": {"episode_id": episode_id, "findings": []},
        }
    )
    drive(
        {
            "type": "submit",
            "findings": {"episode_id": episode_id, "findings": []},
        }
    )

    recorder.close()

    found = any(scan_for_canary(value) for value in observed)
    found = found or any(scan_for_canary(entry) for entry in recorder.entries)

    train_ok, train_detail = _train_reward_locality(seed)
    verdict = "PASS" if (not found and train_ok) else "FAIL"

    return {
        "verdict": verdict,
        "found": found,
        "train_reward_ok": train_ok,
        "train_reward_detail": train_detail,
        "steps": steps,
        "records": len(recorder.entries),
    }


# ---------------------------------------------------------------------------
# command


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    seeds: list[int] = []
    for arg in args:
        try:
            seeds.append(int(arg))
        except ValueError:
            print(f"usage: python -m letro.isolation [seed ...] (got {arg!r})")
            return 2
    chosen = seeds or [1001]

    failed = 0
    for seed in chosen:
        report = check_canary(seed=seed)
        print(
            f"canary: {report['verdict']} (seed {seed}, found={report['found']}, "
            f"train_reward={report['train_reward_ok']})"
        )
        if report["verdict"] != "PASS":
            failed += 1

    violations = check_static_boundary()
    print(f"static boundary: {'PASS' if not violations else 'FAIL'}")
    for violation in violations:
        print(f"- {violation}")
    if violations:
        failed += 1

    print()
    if failed:
        print("RESULT: FAIL")
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CANARY",
    "check_canary",
    "check_static_boundary",
    "main",
    "scan_for_canary",
]
