"""Deterministic seed derivation and stream isolation."""

from __future__ import annotations

import hashlib
import random
from typing import Iterable


def derive_seed(seed: int, stream: str) -> int:
    """Derive an independent 64-bit seed for a named subsystem."""
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise TypeError("seed must be an integer")
    if seed < 0:
        raise ValueError("seed must be non-negative")
    material = f"letro:v1:{seed}:{stream}".encode("utf-8")
    digest = hashlib.sha256(material).digest()
    return int.from_bytes(digest[:8], "big", signed=False)


def rng_for(seed: int, stream: str) -> random.Random:
    return random.Random(derive_seed(seed, stream))


def deterministic_id(prefix: str, number: int, width: int = 6) -> str:
    return f"{prefix}-{number:0{width}d}"


def shuffled(items: Iterable, rng: random.Random) -> list:
    values = list(items)
    rng.shuffle(values)
    return values
