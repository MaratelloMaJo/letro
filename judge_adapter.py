"""Official Genesis FinTech judge adapter for LETRO.

The jury imports this module from the repository root and uses only the three
entry points below.  The adapter translates the jury's canonical names into the
internal LETRO environment; it does not generate a different task or choose
actions for a policy.

Working directory: repository root.
Launch check: ``python -c "import judge_adapter"``.
"""

from __future__ import annotations

import time
from typing import Any

from letro.constants import MAX_STEPS
from letro.env import TASK
from letro.factory import env_from_episode
from letro.generator import generate_episode as _generate_episode
from letro.generator import load_episode, write_episode
from letro.matcher import available_evidence_ids, score
from letro.reward import terminal_reward
from letro.schema import FindingError, validate_findings_payload_strict

INVALID_SCORE = {
    "tp": None,
    "fp": None,
    "fn": None,
    "precision": None,
    "recall": None,
    "f1": None,
    "return": -1,
}


def generate_episode(seed: int, config: dict, output_dir: str) -> None:
    """Write one complete episode (open data + closed truth/provenance)."""
    config = config if isinstance(config, dict) else {}
    team_config = config.get("team_config")
    if not isinstance(team_config, dict):
        team_config = {
            key: value
            for key, value in config.items()
            if key not in ("mode", "episode_dir", "team_config")
        }
    episode = _generate_episode(seed, team_config)
    write_episode(episode, output_dir, include_closed=True)


class JudgeEnv:
    """Canonical environment exposed to a jury policy.

    The object holds only the public environment.  Truth stays in the evaluator
    closure created by ``env_from_episode``; it is never stored on this object.
    """

    def __init__(self) -> None:
        self._env = None
        self._episode_id: str | None = None
        self._closed = False
        self._first = True
        self._deadline: float | None = None

    def reset(
        self, seed: int | None = None, config: dict[str, Any] | None = None
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        config = config if isinstance(config, dict) else {}
        mode = config.get("mode", "train")
        if mode == "closed":
            directory = config.get("episode_dir")
            if not isinstance(directory, str) or not directory:
                raise ValueError("closed reset requires episode_dir")
            episode = load_episode(directory, load_closed=True)
            env, _evaluator = env_from_episode(
                episode, mode="eval", strict=True
            )
            self._closed = True
        else:
            team_config = config.get("team_config")
            if not isinstance(team_config, dict):
                team_config = {
                    key: value
                    for key, value in config.items()
                    if key not in ("mode", "episode_dir", "team_config")
                }
            episode = _generate_episode(seed or 0, team_config)
            env, _evaluator = env_from_episode(
                episode, mode="train", strict=True
            )
            self._closed = False

        self._env = env
        self._episode_id = episode.manifest["episode_id"]
        self._env.reset()
        self._first = True
        self._deadline = time.monotonic() + 60.0
        return self._canonical_observation(), self._info()

    def step(
        self, action: dict[str, Any]
    ) -> tuple[dict[str, Any], float, bool, bool, dict[str, Any]]:
        if self._env is None:
            raise RuntimeError("reset must be called before step")

        if (
            self._deadline is not None
            and time.monotonic() > self._deadline
            and not self._env._done
        ):
            _observation, reward, _terminated, _truncated, info = (
                self._env.truncate()
            )
            if self._closed:
                info = {
                    key: value
                    for key, value in info.items()
                    if key not in ("metrics", "reward")
                }
            return (
                self._canonical_observation(),
                float(reward),
                True,
                True,
                info,
            )

        if self._env._done:
            return (
                {
                    "result": None,
                    "error": {
                        "code": "episode_finished",
                        "message": "episode is already finished",
                    },
                    "remaining_steps": self._remaining(),
                },
                0.0,
                True,
                bool(self._env._truncated),
                self._info(error="episode_finished"),
            )

        internal = self._translate(action)
        observation, reward, terminated, truncated, info = self._env.step(internal)
        if self._closed:
            info = {
                key: value
                for key, value in info.items()
                if key not in ("metrics", "reward")
            }
        return (
            self._canonical_observation(),
            float(reward),
            bool(terminated),
            bool(truncated),
            info,
        )

    def _translate(self, action: Any) -> dict[str, Any]:
        if not isinstance(action, dict):
            return {"type": "__adapter_error__"}
        name = action.get("name")
        args = action.get("args")
        if not isinstance(args, dict):
            args = {}
        if name == "list_records":
            cursor = args.get("cursor", None)
            if cursor is None:
                cursor = 0
            elif isinstance(cursor, str):
                try:
                    cursor = int(cursor)
                except ValueError:
                    cursor = -1
            return {
                "type": "list_records",
                "table": args.get("table"),
                "cursor": cursor,
                "limit": args.get("limit", 50),
            }
        if name == "get_record":
            return {
                "type": "get_record",
                "table": args.get("table"),
                "id": args.get("id"),
            }
        if name == "get_document":
            return {"type": "get_document", "doc_id": args.get("doc_id")}
        if name == "calculator":
            return {"type": "calculator", "expression": args.get("expression")}
        if name == "submit":
            findings = args.get("findings")
            if isinstance(findings, dict) and self._episode_id:
                findings = dict(findings)
                findings.setdefault("episode_id", self._episode_id)
            return {"type": "submit", "findings": findings}
        return {"type": name if isinstance(name, str) else "__adapter_error__"}

    def _remaining(self) -> int:
        return max(0, MAX_STEPS - (self._env._steps if self._env else 0))

    def _canonical_observation(self) -> dict[str, Any]:
        if self._first:
            self._first = False
            return {
                "task": TASK,
                "manifest": self._env._store.manifest,
                "policy": self._env._store.policy,
                "remaining_steps": self._remaining(),
            }

        last = self._env._last_result or {}
        result: Any = None
        error: dict[str, Any] | None = None
        if last.get("ok"):
            result = last.get("result")
            action = last.get("action")
            if action == "list_records" and isinstance(result, dict):
                next_cursor = result.get("next_cursor")
                result = {
                    "records": result.get("rows", []),
                    "next_cursor": (
                        None if next_cursor is None else str(next_cursor)
                    ),
                }
            elif action == "calculator" and isinstance(result, dict):
                result = result.get("result")
            elif action == "submit":
                result = {"accepted": True}
        elif last:
            if last.get("action") == "timeout":
                code = "time_limit"
            elif last.get("action") == "submit":
                code = "invalid_findings"
            else:
                code = "tool_error"
            error = {
                "code": code,
                "message": str(last.get("error") or "action failed")[:200],
            }
        return {
            "result": result,
            "error": error,
            "remaining_steps": self._remaining(),
        }

    def _info(self, **extra: Any) -> dict[str, Any]:
        if self._env is None:
            info: dict[str, Any] = {
                "episode_id": self._episode_id,
                "steps_remaining": MAX_STEPS,
            }
        else:
            info = dict(self._env._info())
        info.update(extra)
        return info

    def close(self) -> None:
        if self._env is not None:
            self._env.close()

    def __enter__(self) -> "JudgeEnv":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()


def make_env() -> JudgeEnv:
    return JudgeEnv()


def score_episode(
    episode_dir: str, findings: dict, inspection_steps: int
) -> dict[str, Any]:
    """Judge-side scoring of one submission against one closed episode."""
    try:
        episode = load_episode(episode_dir, load_closed=True)
        if not isinstance(findings, dict):
            raise FindingError("findings must be an object")
        payload = dict(findings)
        payload.setdefault("episode_id", episode.manifest["episode_id"])
        normalized = validate_findings_payload_strict(payload)
        if normalized["episode_id"] != episode.manifest["episode_id"]:
            raise FindingError("episode_id does not match the episode")
        tolerance = int(episode.policy.get("amount_tolerance_minor", 1))
        result = score(
            episode.truth,
            normalized,
            tolerance,
            strict=True,
            available_evidence=available_evidence_ids(episode.open_data()),
        )
        reward = terminal_reward(result.f1, inspection_steps, exact=True)
        return {
            "tp": result.tp,
            "fp": result.fp,
            "fn": result.fn,
            "precision": result.precision,
            "recall": result.recall,
            "f1": result.f1,
            "return": reward,
        }
    except (FindingError, OSError, TypeError, ValueError):
        return dict(INVALID_SCORE)


__all__ = [
    "JudgeEnv",
    "available_evidence_ids",
    "generate_episode",
    "make_env",
    "score_episode",
]
