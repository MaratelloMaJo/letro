"""Environment factory keeping closed truth outside the environment object."""

from __future__ import annotations

from typing import Any

from .env import AuditEnv
from .evaluator import Evaluator
from .generator import Episode, generate_episode


def _build(
    seed: int,
    config: dict[str, Any] | None = None,
    mode: str = "train",
    strict: bool = False,
) -> tuple[Episode, Evaluator, Any]:
    """Build an episode, its evaluator and the finalize closure.

    The environment only ever receives the closure; truth stays with the
    evaluator. This is the single place a lazy environment builds an episode.
    """
    episode = generate_episode(seed, config)
    evaluator = Evaluator(episode, strict=strict)
    expose = mode == "train"

    def finalize(payload: Any, inspection_steps: int) -> dict[str, Any]:
        return evaluator.score(payload, inspection_steps, expose=expose)

    return episode, evaluator, finalize


def env_from_episode(
    episode: Episode, mode: str = "train", *, strict: bool = False
) -> tuple[AuditEnv, Evaluator]:
    evaluator = Evaluator(episode, strict=strict)
    expose = mode == "train"

    def finalize(payload: Any, inspection_steps: int) -> dict[str, Any]:
        return evaluator.score(payload, inspection_steps, expose=expose)

    env = AuditEnv(
        episode.open_data(),
        finalize=finalize,
        expose_reward=expose,
    )
    return env, evaluator


def make_env(
    seed: int,
    config: dict[str, Any] | None = None,
    mode: str = "train",
    *,
    strict: bool = False,
) -> tuple[AuditEnv, Episode, Evaluator]:
    episode = generate_episode(seed, config)
    evaluator = Evaluator(episode, strict=strict)
    expose = mode == "train"

    def finalize(payload: Any, inspection_steps: int) -> dict[str, Any]:
        return evaluator.score(payload, inspection_steps, expose=expose)

    def provider(new_seed: int, new_config: dict[str, Any] | None):
        new_episode = generate_episode(new_seed, new_config)
        evaluator.rebind(new_episode)
        return new_episode.open_data(), finalize

    env = AuditEnv(
        episode.open_data(),
        finalize=finalize,
        provider=provider,
        expose_reward=expose,
        seed=seed,
    )
    return env, episode, evaluator


__all__ = ["env_from_episode", "make_env"]
