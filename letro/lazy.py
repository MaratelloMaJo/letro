"""Lazy environment boundary.

This module is the only place a lazy environment builds an episode. It may
import :mod:`letro.factory`; :mod:`letro.env` must not. The shared
:func:`build_episode` helper returns the two things a lazy reset actually
needs — the open data and the terminal ``finalize`` closure — and never the
evaluator, closed truth or provenance, so a lazy environment cannot leak truth
by construction.
"""

from __future__ import annotations

from typing import Any

from .env import AuditEnv


def build_episode(
    seed: int, config: dict[str, Any] | None, mode: str
) -> tuple[dict[str, Any], Any]:
    """Build an episode's open data and finalize closure for a lazy reset.

    ``factory._build`` returns ``(episode, evaluator, finalize)``; only the
    open data and the finalize closure cross into the environment. The
    evaluator and the closed truth it wraps stay here.
    """
    from .factory import _build

    episode, _evaluator, finalize = _build(seed, config, mode)
    return episode.open_data(), finalize


class LetroEnv(AuditEnv):
    """Lazy env: ``LetroEnv().reset(seed=..., config=...)`` builds an episode."""

    metadata = {"name": "LETRO", "render_modes": []}

    def __init__(
        self,
        mode: str = "train",
        seed: int = 0,
        config: dict[str, Any] | None = None,
    ):
        super().__init__(
            open_data=None,
            finalize=None,
            provider=None,
            expose_reward=(mode == "train"),
            seed=seed,
        )
        self._mode = mode
        self._config = config

    def _build_episode(
        self, seed: int, config: dict[str, Any] | None
    ) -> tuple[dict[str, Any], Any]:
        use_config = self._config if config is None else config
        return build_episode(seed, use_config, self._mode)


__all__ = ["LetroEnv", "build_episode"]
