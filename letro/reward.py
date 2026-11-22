"""Terminal reward exactly as specified by the competition brief."""

from __future__ import annotations

from .constants import STEP_COST


def terminal_reward(
    f1: float, inspection_steps: int, *, exact: bool = False
) -> float:
    if not isinstance(f1, (int, float)):
        raise TypeError("f1 must be numeric")
    if isinstance(inspection_steps, bool) or not isinstance(inspection_steps, int):
        raise TypeError("inspection_steps must be an integer")
    if inspection_steps < 0:
        raise ValueError("inspection_steps must be non-negative")
    value = 2.0 * float(f1) - 1.0 - STEP_COST * inspection_steps
    clipped = max(-1.0, min(1.0, value))
    if exact:
        return clipped
    return round(clipped, 6)
