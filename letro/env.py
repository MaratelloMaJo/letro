"""Gymnasium-style audit environment with a strict read-only tool surface.

Two construction styles are supported:

- ``AuditEnv(open_data)`` for a pre-built episode, used by the factory and tests.
- ``AuditEnv()`` (and ``LetroEnv()`` from :mod:`letro.lazy`) for a lazy
  environment that builds an episode on the first ``reset``. This is the shape
  a jury harness expects.

The lazy boundary keeps this module free of ``factory``, ``evaluator``,
``generator.audit`` and closed truth: ``AuditEnv._build_episode`` imports the
shared builder from :mod:`letro.lazy`, and ``LetroEnv`` itself lives there and
is re-exported through ``__getattr__`` so ``letro.env:LetroEnv`` still resolves.
"""

from __future__ import annotations

from typing import Any, Callable

from .constants import MAX_STEPS
from .reward import terminal_reward
from .schema import ActionError, validate_action
from .tools import OpenStore, ToolError, dispatch

TASK = (
    "Audit one company and one reporting period. Find material accounting "
    "issues in the open records. Investigation reward is zero; only the "
    "terminal submission is scored. Submit findings with the exact type, "
    "canonical affected_ids, claimed amount in minor units, currency and a "
    "complete evidence set. Closed truth and the seed are not observable."
)

Finalize = Callable[[Any, int], dict[str, Any]]
Provider = Callable[[int, Any], tuple[dict[str, Any], Finalize]]


class AuditEnv:
    metadata = {"name": "LETRO", "render_modes": []}

    def __init__(
        self,
        open_data: dict[str, Any] | None = None,
        finalize: Finalize | None = None,
        provider: Provider | None = None,
        expose_reward: bool = True,
        seed: int = 0,
    ):
        self._store = OpenStore(open_data) if open_data is not None else None
        self._lazy = open_data is None
        self._finalize = finalize
        self._provider = provider
        self._expose_reward = expose_reward
        self._seed = seed
        self._episode_id = (
            open_data["manifest"]["episode_id"] if open_data is not None else None
        )
        self._reset_state()

    def _build_episode(
        self, seed: int, config: dict[str, Any] | None
    ) -> tuple[dict[str, Any], Any]:
        from .lazy import build_episode

        return build_episode(seed, config, "train")

    def _reset_state(self) -> None:
        self._steps = 0
        self._inspection_steps = 0
        self._done = False
        self._truncated = False
        self._submitted = False
        self._first = True
        self._started = False
        self._last_result: dict[str, Any] | None = None

    def reset(
        self, seed: int | None = None, config: dict[str, Any] | None = None
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        use_seed = self._seed if seed is None else seed
        if self._store is None or (self._lazy and (seed is not None or config is not None)):
            open_data, finalize = self._build_episode(use_seed, config)
            self._store = OpenStore(open_data)
            self._finalize = finalize
            self._episode_id = open_data["manifest"]["episode_id"]
            self._seed = use_seed
        elif self._provider is not None and (seed is not None or config is not None):
            open_data, finalize = self._provider(use_seed, config)
            self._store = OpenStore(open_data)
            self._finalize = finalize
            self._episode_id = open_data["manifest"]["episode_id"]
            self._seed = use_seed
        self._reset_state()
        self._started = True
        return self._observation(), self._info()

    def _info(self, **extra: Any) -> dict[str, Any]:
        info = {
            "episode_id": self._episode_id,
            "steps_remaining": max(0, MAX_STEPS - self._steps),
        }
        info.update(extra)
        return info

    def _observation(self) -> dict[str, Any]:
        observation: dict[str, Any] = {
            "task": TASK,
            "budget": {
                "step": self._steps,
                "steps_remaining": max(0, MAX_STEPS - self._steps),
                "max_steps": MAX_STEPS,
            },
            "last_result": self._last_result,
        }
        if self._first:
            observation["manifest"] = self._store.manifest
            policy = self._store.policy
            observation["policy_summary"] = {
                "base_currency": policy.get("base_currency"),
                "period_start": policy.get("period_start"),
                "period_end": policy.get("period_end"),
                "rounding": policy.get("rounding"),
                "fx_rate_date_invoice": policy.get("fx_rate_date_invoice"),
                "fx_rate_date_payment": policy.get("fx_rate_date_payment"),
                "amount_tolerance_minor": policy.get("amount_tolerance_minor"),
                "evidence_rule": policy.get("evidence_rule"),
            }
            self._first = False
        return observation

    def _timeout(self) -> tuple[dict[str, Any], float, bool, bool, dict[str, Any]]:
        self._done = True
        self._truncated = True
        reward = (
            terminal_reward(0.0, self._inspection_steps)
            if self._expose_reward
            else 0.0
        )
        self._last_result = {
            "action": "timeout",
            "ok": False,
            "error": "step limit reached; the final answer is empty",
        }
        return (
            self._observation(),
            reward,
            True,
            True,
            self._info(truncated=True),
        )

    def step(
        self, action: Any
    ) -> tuple[dict[str, Any], float, bool, bool, dict[str, Any]]:
        if not self._started:
            self.reset()
        if self._done:
            return (
                self._observation(),
                0.0,
                True,
                self._truncated,
                self._info(error="episode_finished"),
            )
        if self._steps >= MAX_STEPS:
            return self._timeout()

        kind = action.get("type") if isinstance(action, dict) else None
        is_submit = kind == "submit"
        self._steps += 1

        if is_submit:
            payload = action.get("findings")
            if self._finalize is None:
                result = {"reward": -1.0, "invalid": True, "metrics": {}}
            else:
                result = self._finalize(payload, self._inspection_steps)
            self._done = True
            self._submitted = True
            invalid = bool(result.get("invalid"))
            self._last_result = {
                "action": "submit",
                "ok": not invalid,
                "error": "invalid findings structure" if invalid else None,
            }
            reward = (
                float(result.get("reward", 0.0)) if self._expose_reward else 0.0
            )
            info = self._info(submitted=True)
            if invalid:
                info["error"] = "invalid findings structure"
            metrics = result.get("metrics") or {}
            if self._expose_reward and metrics:
                info["metrics"] = metrics
            return self._observation(), reward, True, False, info

        self._inspection_steps += 1
        try:
            normalized = validate_action(action)
            result = dispatch(self._store, normalized)
            self._last_result = {
                "action": normalized["type"],
                "ok": True,
                "result": result,
            }
        except (ActionError, ToolError) as exc:
            self._last_result = {
                "action": kind if isinstance(kind, str) else "unknown",
                "ok": False,
                "error": str(exc)[:200],
            }

        if self._steps >= MAX_STEPS:
            return self._timeout()
        return self._observation(), 0.0, False, False, self._info()

    def close(self) -> None:
        return None

    def __enter__(self) -> "AuditEnv":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()


def __getattr__(name: str):
    if name == "LetroEnv":
        from .lazy import LetroEnv

        return LetroEnv
    raise AttributeError(name)


__all__ = ["AuditEnv", "LetroEnv", "TASK"]
