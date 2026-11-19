"""Episode runner and trajectory recording.

Every record has exactly the fields required by the brief:
``episode_id, step, action, observation, reward, terminated, truncated``.
Closed truth never enters a trajectory; observations are scanned for forbidden
keys before they are written.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .constants import FORBIDDEN_OBSERVATION_KEYS, MAX_STEPS


class TrajectoryError(RuntimeError):
    """A trajectory violates the logging contract."""


def forbidden_paths(value: Any, path: str = "$") -> list[str]:
    """Return every location in ``value`` whose key is hidden truth."""
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key in FORBIDDEN_OBSERVATION_KEYS:
                found.append(f"{path}.{key}")
            found.extend(forbidden_paths(item, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(forbidden_paths(item, f"{path}[{index}]"))
    return found


def _json_safe(value: Any) -> None:
    try:
        json.dumps(value, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise TrajectoryError(f"trajectory value is not JSON-safe: {exc}") from exc


@dataclass
class RunResult:
    episode_id: str
    policy: str
    mode: str
    steps: int
    reward: float
    terminated: bool
    truncated: bool
    metrics: dict[str, Any] = field(default_factory=dict)
    evaluator_reward: float | None = None
    elapsed_seconds: float = 0.0


class TrajectoryRecorder:
    """Append-only JSONL recorder with a leak guard."""

    def __init__(self, path: str | Path | None = None, mode: str = "w"):
        self.path = Path(path) if path is not None else None
        self.entries: list[dict[str, Any]] = []
        self._handle = None
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._handle = self.path.open(mode, encoding="utf-8", newline="\n")

    def write(self, entry: dict[str, Any]) -> None:
        leaks = forbidden_paths(entry.get("observation", {}))
        if leaks:
            raise TrajectoryError(f"observation leaks hidden keys: {leaks[:3]}")
        _json_safe(entry)
        self.entries.append(entry)
        if self._handle is not None:
            self._handle.write(json.dumps(entry, ensure_ascii=False, allow_nan=False) + "\n")
            self._handle.flush()

    def close(self) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None

    def __enter__(self) -> "TrajectoryRecorder":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()


def run_episode(
    env: Any,
    policy: Any,
    recorder: TrajectoryRecorder | None = None,
    evaluator: Any = None,
    mode: str = "train",
    max_steps: int = MAX_STEPS,
) -> RunResult:
    started = time.perf_counter()
    observation, info = env.reset()
    policy.reset(observation, info)
    episode_id = str(info.get("episode_id", ""))
    terminated = False
    truncated = False
    reward = 0.0
    steps = 0
    for step in range(1, max_steps + 1):
        action = policy.act(observation)
        observation, reward, terminated, truncated, info = env.step(action)
        steps = step
        if recorder is not None:
            recorder.write(
                {
                    "episode_id": episode_id,
                    "step": step,
                    "action": action,
                    "observation": observation,
                    "reward": float(reward),
                    "terminated": bool(terminated),
                    "truncated": bool(truncated),
                }
            )
        if terminated or truncated:
            break
    metrics: dict[str, Any] = {}
    if evaluator is not None:
        report = evaluator.result()
        metrics = {key: value for key, value in report.items() if key != "episode_id"}
    elif isinstance(info, dict) and isinstance(info.get("metrics"), dict):
        metrics = dict(info["metrics"])
    return RunResult(
        episode_id=episode_id,
        policy=str(getattr(policy, "name", "policy")),
        mode=mode,
        steps=steps,
        reward=float(reward),
        terminated=bool(terminated),
        truncated=bool(truncated),
        metrics=metrics,
        evaluator_reward=None if evaluator is None else evaluator.last_reward,
        elapsed_seconds=round(time.perf_counter() - started, 6),
    )


REQUIRED_FIELDS = (
    "episode_id",
    "step",
    "action",
    "observation",
    "reward",
    "terminated",
    "truncated",
)


def validate_trajectory_file(path: str | Path) -> dict[str, Any]:
    """Validate a JSONL trajectory file against the logging contract."""
    source = Path(path)
    if not source.exists():
        raise TrajectoryError("trajectory file does not exist")
    records = 0
    episodes: dict[str, int] = {}
    current: dict[str, int] = {}
    finished: dict[str, bool] = {}
    runs = 0
    with source.open("r", encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError as exc:
                raise TrajectoryError(f"line {number} is not valid JSON") from exc
            if not isinstance(entry, dict):
                raise TrajectoryError(f"line {number} is not an object")
            if tuple(entry.keys()) != REQUIRED_FIELDS:
                raise TrajectoryError(
                    f"line {number} fields are {sorted(entry)}; expected {list(REQUIRED_FIELDS)}"
                )
            leaks = forbidden_paths(entry.get("observation", {}))
            if leaks:
                raise TrajectoryError(
                    f"line {number} observation leaks hidden keys: {leaks[:3]}"
                )
            episode_id = entry["episode_id"]
            if not isinstance(episode_id, str) or not episode_id:
                raise TrajectoryError(f"line {number} has no episode_id")
            step = entry["step"]
            if isinstance(step, bool) or not isinstance(step, int) or step < 1:
                raise TrajectoryError(f"line {number} has an invalid step")
            if step == 1:
                if not finished.get(episode_id, True):
                    raise TrajectoryError(
                        f"line {number} starts a new run before the previous one ended"
                    )
                current[episode_id] = 1
                finished[episode_id] = False
                runs += 1
            else:
                expected = current.get(episode_id, 0) + 1
                if step != expected:
                    raise TrajectoryError(
                        f"line {number} breaks step order for {episode_id}: "
                        f"{step} != {expected}"
                    )
                if finished.get(episode_id):
                    raise TrajectoryError(f"line {number} continues a finished episode")
                current[episode_id] = step
            if entry["terminated"] or entry["truncated"]:
                finished[episode_id] = True
            episodes[episode_id] = episodes.get(episode_id, 0) + 1
            records += 1
    if records == 0:
        raise TrajectoryError("trajectory file is empty")
    if not all(finished.values()):
        raise TrajectoryError("one or more episodes never terminate")
    return {
        "records": records,
        "episodes": len(episodes),
        "runs": runs,
        "steps": episodes,
    }


__all__ = [
    "REQUIRED_FIELDS",
    "RunResult",
    "TrajectoryError",
    "TrajectoryRecorder",
    "forbidden_paths",
    "run_episode",
    "validate_trajectory_file",
]
