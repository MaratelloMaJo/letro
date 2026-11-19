"""Named configuration presets used by the jury runner, fuzz and docs.

A preset is a plain config dictionary accepted by ``generate_episode``. The
``default`` preset is the competition configuration; ``hard`` and
``hard_composite`` raise document count, period length and issue count while
keeping every value inside the published contract.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

PRESETS: dict[str, dict[str, Any]] = {
    "default": {},
    "hard": {
        "base_currency": "USD",
        "period_days": 45,
        "sizes": {
            "invoices": 90,
            "payments": 80,
            "issues": 12,
            "ledger_rows": 900,
        },
        "errors": {
            "duplicate_invoice": 2,
            "payment_allocation_gap": 2,
            "fx_rate_error": 2,
            "period_cutoff": 2,
            "composite": 2,
        },
    },
    "hard_composite": {
        "base_currency": "USD",
        "period_days": 45,
        "sizes": {
            "invoices": 90,
            "payments": 80,
            "issues": 12,
            "ledger_rows": 900,
        },
        "errors": {
            "duplicate_invoice": 1,
            "payment_allocation_gap": 1,
            "fx_rate_error": 1,
            "period_cutoff": 1,
            "composite": 4,
        },
    },
    "clean": {
        "clean": True,
        "sizes": {
            "invoices": 50,
            "payments": 45,
            "issues": 0,
            "ledger_rows": 420,
        },
    },
    "wide": {
        "base_currency": "EUR",
        "period_days": 30,
        "sizes": {
            "invoices": 60,
            "payments": 50,
            "issues": 8,
            "ledger_rows": 600,
        },
        "errors": {
            "duplicate_invoice": 1,
            "payment_allocation_gap": 1,
            "fx_rate_error": 1,
            "period_cutoff": 1,
            "composite": 2,
        },
    },
}


def preset(name: str) -> dict[str, Any]:
    if name not in PRESETS:
        raise KeyError(f"unknown preset: {name}")
    return deepcopy(PRESETS[name])


def preset_names() -> tuple[str, ...]:
    return tuple(PRESETS)


__all__ = ["PRESETS", "preset", "preset_names"]
