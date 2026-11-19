"""Shared fixtures for the LETRO test suite."""

from __future__ import annotations

from typing import Any

from letro.generator import generate_episode

_CACHE: dict[tuple[int, str], Any] = {}


def errors(
    duplicate: int = 0,
    gap: int = 0,
    fx: int = 0,
    cutoff: int = 0,
    composite: int = 0,
) -> dict[str, int]:
    return {
        "duplicate_invoice": duplicate,
        "payment_allocation_gap": gap,
        "fx_rate_error": fx,
        "period_cutoff": cutoff,
        "composite": composite,
    }


def config(
    *,
    error_counts: dict[str, int] | None = None,
    clean: bool = False,
    base: str = "KZT",
    invoices: int = 34,
    payments: int = 30,
    rows: int = 300,
    days: int = 30,
    variant: int = 0,
) -> dict[str, Any]:
    return {
        "base_currency": base,
        "period_days": days,
        "sizes": {
            "invoices": invoices,
            "payments": payments,
            "issues": 12 if error_counts else 0,
            "ledger_rows": rows,
        },
        "errors": error_counts or errors(),
        "clean": clean,
        "variant": variant,
    }


def episode(seed: int, cfg: dict[str, Any] | None = None) -> Any:
    key = (seed, repr(sorted((cfg or {}).items())))
    if key not in _CACHE:
        _CACHE[key] = generate_episode(seed, cfg)
    return _CACHE[key]


def payload(ep: Any, findings: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "episode_id": ep.manifest["episode_id"],
        "findings": findings,
    }
