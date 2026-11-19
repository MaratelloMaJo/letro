"""Policy protocol and shared helpers.

A policy only ever receives the observation returned by the environment. The
helpers below work on data the policy collected through ``list_records``; they
do not import the generator or read episode truth.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any


class Policy:
    """Minimal policy interface used by the runner and verifier."""

    name = "policy"

    def reset(self, observation: dict[str, Any], info: dict[str, Any]) -> None:
        raise NotImplementedError

    def act(self, observation: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError


def sorted_rate_lookup(rows: list[dict[str, Any]]) -> dict[tuple[str, str], list[tuple[str, Decimal]]]:
    """Group FX rows into (source, target) -> sorted [(date, rate)]."""
    grouped: dict[tuple[str, str], list[tuple[str, Decimal]]] = {}
    for row in rows:
        key = (row["source_currency"], row["target_currency"])
        grouped.setdefault(key, []).append((row["date"], Decimal(row["rate"])))
    for values in grouped.values():
        values.sort()
    return grouped


def rate_for(
    grouped: dict[tuple[str, str], list[tuple[str, Decimal]]],
    currency: str,
    base: str,
    day: str,
) -> Decimal:
    if currency == base:
        return Decimal(1)
    values = grouped.get((currency, base))
    if not values:
        raise KeyError(f"no FX rows for {currency}/{base}")
    earlier = [item for item in values if item[0] <= day]
    if earlier:
        return earlier[-1][1]
    return values[0][1]


def proportional_base(total_base: int, part: int, total: int) -> int:
    if total <= 0:
        return 0
    value = (Decimal(total_base) * Decimal(part) / Decimal(total)).quantize(
        Decimal(1), rounding=ROUND_HALF_UP
    )
    return int(value)


def inside(period_start: str, period_end: str, timestamp: str) -> bool:
    return (
        datetime.fromisoformat(period_start)
        <= datetime.fromisoformat(timestamp)
        <= datetime.fromisoformat(period_end)
    )
