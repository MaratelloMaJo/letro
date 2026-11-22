"""Policy adapters required by the competition brief."""

from __future__ import annotations

from typing import Any

from ..generator import Episode
from .base import Policy
from .limited import LimitedPolicy
from .mark_all import MarkAllPolicy
from .oracle import OraclePolicy
from .random_explorer import RandomExplorerPolicy
from .reconciliation import ReconciliationPolicy
from .thorough import ThoroughPolicy

# The four adapters required by the brief. ``thorough`` is an additional
# exact reference used by the demo and as an upper bound.
POLICY_NAMES = ("random_explorer", "reconciliation", "mark_all", "oracle")


def make_policy(
    name: str, episode: Episode | None = None, seed: int = 0, **kwargs: Any
) -> Policy:
    if name == "random_explorer":
        return RandomExplorerPolicy(seed=seed, **kwargs)
    if name == "reconciliation":
        return ReconciliationPolicy()
    if name == "thorough":
        return ThoroughPolicy()
    if name == "mark_all":
        return MarkAllPolicy()
    if name == "oracle":
        if episode is None:
            raise ValueError("oracle policy requires an episode")
        return OraclePolicy(episode)
    raise ValueError(f"unknown policy: {name}")


__all__ = [
    "LimitedPolicy",
    "MarkAllPolicy",
    "OraclePolicy",
    "POLICY_NAMES",
    "Policy",
    "RandomExplorerPolicy",
    "ReconciliationPolicy",
    "ThoroughPolicy",
    "make_policy",
]
