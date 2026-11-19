"""Optional Gymnasium registration.

Gymnasium is not a dependency. The environment works through the plain
``reset``/``step`` contract without it. If a user has Gymnasium installed, this
module registers ``LetroEnv-v0`` for tooling that expects ``gym.make``.
"""

from __future__ import annotations


def register() -> str:
    try:
        import gymnasium
        from gymnasium.envs.registration import register as gym_register
    except ImportError as exc:
        raise RuntimeError(
            "gymnasium is optional and is not installed; use letro.env.LetroEnv directly"
        ) from exc
    gym_register(
        id="LetroEnv-v0",
        entry_point="letro.env:LetroEnv",
        max_episode_steps=100,
    )
    return "LetroEnv-v0"


__all__ = ["register"]
