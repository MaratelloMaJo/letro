"""Evaluator-side oracle adapter.

Per the brief, the oracle is allowed to read closed truth. It exists only in
the verification harness and never ships as an agent-visible policy: the
environment never receives the episode or its truth.
"""

from __future__ import annotations

from typing import Any

from ..generator import Episode, reference_findings
from .base import Policy


class OraclePolicy(Policy):
    name = "oracle"

    def __init__(self, episode: Episode):
        self._episode = episode
        self._payload = reference_findings(episode)

    def reset(self, observation: dict[str, Any], info: dict[str, Any]) -> None:
        return None

    def act(self, observation: dict[str, Any]) -> dict[str, Any]:
        return {"type": "submit", "findings": self._payload}
