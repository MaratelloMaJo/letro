"""Limited-information probe for the difficulty science.

``LimitedPolicy`` is a :class:`~letro.policies.thorough.ThoroughPolicy` that
stops paging each table after ``max_pages`` pages. It keeps the exact analysis
arithmetic and only varies how much of each table it has seen, so the gap it
measures is attributable to information, not to a weaker heuristic.
"""

from __future__ import annotations

from .thorough import ThoroughPolicy


class LimitedPolicy(ThoroughPolicy):
    name = "limited"

    def __init__(self, max_pages: int = 1) -> None:
        super().__init__(max_pages=max_pages)


__all__ = ["LimitedPolicy"]
