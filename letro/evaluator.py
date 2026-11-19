"""Evaluator: owns closed truth and scores submissions out of band."""

from __future__ import annotations

from typing import Any

from .matcher import MatchResult, score
from .reward import terminal_reward
from .schema import FindingError, validate_findings_payload


class Evaluator:
    """The only component that reads truth.json.

    The environment never receives this object. It receives a ``finalize``
    callback that returns the terminal signal, so an observation cannot leak
    truth by construction.
    """

    def __init__(self, episode: Any):
        self._episode = episode
        self._truth = episode.truth
        self._tolerance = int(episode.policy.get("amount_tolerance_minor", 1))
        self.last_result: MatchResult | None = None
        self.last_reward: float | None = None
        self.submissions = 0

    def rebind(self, episode: Any) -> None:
        """Attach the evaluator to a newly generated episode.

        ``make_env`` keeps one evaluator handle across ``reset(seed=...)`` so a
        training loop can read metrics without re-wiring the runner. The truth
        stays inside this object and never enters the environment.
        """
        self._episode = episode
        self._truth = episode.truth
        self._tolerance = int(episode.policy.get("amount_tolerance_minor", 1))
        self.last_result = None
        self.last_reward = None
        self.submissions = 0

    def score(
        self, payload: Any, inspection_steps: int, expose: bool = True
    ) -> dict[str, Any]:
        try:
            normalized = validate_findings_payload(payload)
            if normalized["episode_id"] != self._episode.manifest["episode_id"]:
                raise FindingError("episode_id does not match the active episode")
        except FindingError:
            self.submissions += 1
            self.last_reward = -1.0
            return {
                "reward": -1.0 if expose else 0.0,
                "invalid": True,
                "metrics": {} if not expose else {"invalid": True, "reward": -1.0},
            }

        result = score(self._truth, normalized, self._tolerance)
        reward = terminal_reward(result.f1, inspection_steps)
        self.last_result = result
        self.last_reward = reward
        self.submissions += 1
        metrics = result.metrics()
        metrics["reward"] = reward
        metrics["inspection_steps"] = inspection_steps
        return {
            "reward": reward if expose else 0.0,
            "invalid": False,
            "metrics": metrics if expose else {},
        }

    def result(self) -> dict[str, Any]:
        """Evaluator-side report; never returned by the environment."""
        if self.last_result is None:
            return {
                "episode_id": self._episode.manifest["episode_id"],
                "submitted": False,
                "reward": None,
            }
        return {
            "episode_id": self._episode.manifest["episode_id"],
            "submitted": True,
            "reward": self.last_reward,
            **self.last_result.metrics(),
        }
