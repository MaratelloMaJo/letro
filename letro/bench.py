"""Compute envelope benchmark for the LETRO environment.

``python -m letro.bench`` measures the cost of the expensive operations behind
one agent episode, reports peak memory for a single episode against the 4 GB
limit, reports the sequential 20-episode peak separately (never against 4 GB),
checks the clean ``git archive`` artifact against the 1 GB solution limit, and
confirms episode generation is deterministic under two different
``PYTHONHASHSEED`` values.

The benchmark is descriptive: it records what the machine measured and exits
non-zero when a declared budget is breached. It does not tune performance and it
does not read ``truth.json`` into any displayed value.
"""

from __future__ import annotations

import contextlib
import io
import math
import os
import subprocess
import sys
import tempfile
import time
import tracemalloc
from dataclasses import dataclass
from itertools import cycle
from pathlib import Path
from typing import Any, Callable, Sequence

from .constants import MAX_STEPS
from .factory import env_from_episode
from .generator import generate_episode
from .trajectory import run_episode

ROOT = Path(__file__).resolve().parents[1]

# Competition limits. The 4 GB figure applies to a *single* episode at a time;
# the 20-episode figure is sequential (each episode released before the next)
# and is never compared against 4 GB.
MEMORY_LIMIT_BYTES = 4 * 1024**3  # 4 GB, single episode
ARCHIVE_LIMIT_BYTES = 1 * 1024**3  # 1 GB, clean solution archive
TIME_BUDGET_MS = 60_000.0  # 60 s per episode

_DIGEST_SEED = 4242


@dataclass
class BenchResult:
    operation: str
    p50_ms: float
    p95_ms: float
    max_ms: float
    budget_ms: float
    verdict: str


# ---------------------------------------------------------------------------
# timing


def _nearest_rank(sorted_samples: list[float], percentile: float) -> float:
    """The nearest-rank percentile over an already-sorted list of samples."""
    if not sorted_samples:
        return 0.0
    if percentile <= 0:
        return sorted_samples[0]
    if percentile >= 100:
        return sorted_samples[-1]
    rank = max(1, math.ceil(percentile / 100.0 * len(sorted_samples)))
    return sorted_samples[rank - 1]


def measure(
    operation: str,
    function: Callable[[], Any],
    repeats: int = 5,
    budget_ms: float = 60_000.0,
) -> BenchResult:
    """Time ``function`` ``repeats`` times and report the latency percentiles.

    The operation verdict is PASS when the slowest observed run stays within
    ``budget_ms``; otherwise it is FAIL. Timing uses ``time.perf_counter``.
    """
    samples: list[float] = []
    for _ in range(max(1, int(repeats))):
        started = time.perf_counter()
        function()
        samples.append((time.perf_counter() - started) * 1000.0)
    ordered = sorted(samples)
    p50 = _nearest_rank(ordered, 50)
    p95 = _nearest_rank(ordered, 95)
    peak = ordered[-1]
    return BenchResult(
        operation=operation,
        p50_ms=round(p50, 3),
        p95_ms=round(p95, 3),
        max_ms=round(peak, 3),
        budget_ms=round(float(budget_ms), 1),
        verdict="PASS" if peak <= float(budget_ms) else "FAIL",
    )


# ---------------------------------------------------------------------------
# benchmark policies and episode helper


class _StepBudgetPolicy:
    """A deterministic policy that consumes the full step budget.

    It performs ``MAX_STEPS - 1`` cheap ``list_records`` actions and then
    submits once, so a whole episode really uses ``MAX_STEPS`` environment
    steps rather than the ~12 steps the thorough policy needs to page the open
    tables once.
    """

    name = "bench_100_steps"

    def __init__(self, inspections: int = MAX_STEPS - 1) -> None:
        self._inspections = inspections
        self.reset({}, {})

    def reset(self, observation: dict[str, Any], info: dict[str, Any]) -> None:
        self._taken = 0
        self._episode_id = str(info.get("episode_id", ""))

    def act(self, observation: dict[str, Any]) -> dict[str, Any]:
        if self._taken >= self._inspections:
            return {
                "type": "submit",
                "findings": {"episode_id": self._episode_id, "findings": []},
            }
        self._taken += 1
        table = ("ledger", "invoices", "payments", "fx")[(self._taken - 1) % 4]
        return {"type": "list_records", "table": table, "cursor": 0, "limit": 50}


def _full_episode(seed: int) -> Any:
    """Generate and run one complete, ``MAX_STEPS``-long episode."""
    episode = generate_episode(seed)
    env, evaluator = env_from_episode(episode)
    policy = _StepBudgetPolicy(MAX_STEPS - 1)
    return run_episode(
        env, policy, evaluator=evaluator, max_steps=MAX_STEPS
    )


def _verify_once() -> int:
    """Run the contract verifier once, silently, and return its exit code."""
    from .verify import main as verify_main

    captured = io.StringIO()
    with contextlib.redirect_stdout(captured):
        return int(verify_main())


# ---------------------------------------------------------------------------
# operations


def run_bench(seeds: int = 5) -> list[BenchResult]:
    """Measure the per-episode budget operations and the verifier wall time.

    ``seeds`` controls how many distinct fixed seeds back each timed operation
    (a value of one still exercises every operation). Returns one ``BenchResult``
    per operation, in declaration order: generation, reset, 100_steps, verify.
    """
    count = max(1, int(seeds))
    chosen = list(range(count))

    seed_cycle = cycle(chosen)

    def generation() -> Any:
        return generate_episode(next(seed_cycle))

    episode = generate_episode(0)
    env, _evaluator = env_from_episode(episode)

    def reset_once() -> Any:
        return env.reset()

    steps: list[int] = []

    def full_episode() -> Any:
        result = _full_episode(next(seed_cycle))
        steps.append(int(result.steps))
        return result

    verify_codes: list[int] = []

    def verify_once() -> Any:
        verify_codes.append(_verify_once())
        return None

    results = [
        measure("generation", generation, repeats=count, budget_ms=TIME_BUDGET_MS),
        measure("reset", reset_once, repeats=5, budget_ms=TIME_BUDGET_MS),
        measure("100_steps", full_episode, repeats=count, budget_ms=TIME_BUDGET_MS),
        measure("verify", verify_once, repeats=1, budget_ms=TIME_BUDGET_MS),
    ]
    # The verifier is the contract gate; if it does not return 0 the bench must
    # not report the wall-time row as a clean PASS.
    if verify_codes and verify_codes[0] != 0:
        results[-1].verdict = "FAIL"
    # Honesty guard: the 100_steps operation must actually consume MAX_STEPS.
    if steps and any(value != MAX_STEPS for value in steps):
        results[2].verdict = "FAIL"
    return results


# ---------------------------------------------------------------------------
# memory and archive


def _peak_memory_bytes(episodes: int) -> int:
    """Peak traced memory across ``episodes`` run sequentially.

    Each episode is generated, run to completion and released before the next is
    built, so this measures the worst single-episode footprint plus any
    cross-episode residue. Only ``episodes == 1`` is compared to the 4 GB limit.
    """
    tracemalloc.start()
    try:
        for seed in range(max(1, int(episodes))):
            episode = generate_episode(seed)
            env, evaluator = env_from_episode(episode)
            run_episode(
                env,
                _StepBudgetPolicy(MAX_STEPS - 1),
                evaluator=evaluator,
                max_steps=MAX_STEPS,
            )
            del episode, env, evaluator
        _current, peak = tracemalloc.get_traced_memory()
        return int(peak)
    finally:
        tracemalloc.stop()


def archive_size() -> int:
    """Size in bytes of the clean ``git archive`` artifact for ``HEAD``.

    The archive is written to a temporary file so its size can be measured, then
    deleted. This is the quantity compared against the 1 GB solution limit.
    """
    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory) / "letro.zip"
        result = subprocess.run(
            ["git", "archive", "--format=zip", "--output", str(output), "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"git archive failed ({result.returncode}): {result.stderr.strip()}"
            )
        return output.stat().st_size


# ---------------------------------------------------------------------------
# determinism across hash seeds


def _generation_digest() -> tuple[str, str]:
    """Episode digest as computed in two subprocesses with different hash seeds.

    Returns ``(digest_a, digest_b)``; equality means generation does not depend
    on ``PYTHONHASHSEED``.
    """
    code = (
        "import json, hashlib\n"
        "from letro.generator import generate_episode\n"
        f"episode = generate_episode({_DIGEST_SEED})\n"
        "payload = json.dumps({'manifest': episode.manifest, "
        "'ledger': episode.ledger, 'invoices': episode.invoices, "
        "'payments': episode.payments, 'fx': episode.fx, "
        "'truth': episode.truth, 'provenance': episode.provenance}, "
        "sort_keys=True, ensure_ascii=False)\n"
        "print(hashlib.sha256(payload.encode('utf-8')).hexdigest())\n"
    )

    def digest_for(hash_seed: int) -> str:
        environment = dict(os.environ, PYTHONHASHSEED=str(hash_seed))
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"generation digest subprocess failed: {result.stderr.strip()}"
            )
        return result.stdout.strip()

    first = digest_for(0)
    second = digest_for(1)
    return first, second


# ---------------------------------------------------------------------------
# report


def _format_mib(value_bytes: int) -> str:
    return f"{value_bytes / 1024 / 1024:.2f} MiB"


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and (len(args) > 1 or not args[0].isdigit()):
        print(f"usage: python -m letro.bench [seeds] (got {args!r})")
        return 2
    seeds = int(args[0]) if args else 5

    print("LETRO compute benchmark")
    print(f"root: {ROOT}")
    print(f"python: {sys.version.split()[0]}")
    print()

    results = run_bench(seeds=seeds)
    print(f"{'operation':<13}{'p50_ms':>10}{'p95_ms':>10}{'max_ms':>10}"
          f"{'budget_ms':>12}  {'verdict':<6}")
    for result in results:
        print(
            f"{result.operation:<13}{result.p50_ms:>10.3f}{result.p95_ms:>10.3f}"
            f"{result.max_ms:>10.3f}{result.budget_ms:>12.0f}  {result.verdict:<6}"
        )
    print()

    # Record the actual step count rather than trusting the operation name.
    step_count = _full_episode(0).steps
    print(f"100_steps: consumed {step_count}/{MAX_STEPS} environment steps")

    one_peak = _peak_memory_bytes(1)
    twenty_peak = _peak_memory_bytes(20)
    memory_ok = one_peak <= MEMORY_LIMIT_BYTES
    print(
        f"memory: one-episode peak {_format_mib(one_peak)} "
        f"(limit {_format_mib(MEMORY_LIMIT_BYTES)}), verdict "
        f"{'PASS' if memory_ok else 'FAIL'}"
    )
    # Sequential figure is reported for stability; it is not compared to 4 GB.
    print(f"memory: 20-episode sequential peak {_format_mib(twenty_peak)} "
          f"(reported, not compared to the 4 GB single-episode limit)")

    size = archive_size()
    archive_ok = size <= ARCHIVE_LIMIT_BYTES
    print(
        f"archive: {size} bytes (limit {ARCHIVE_LIMIT_BYTES}), verdict "
        f"{'PASS' if archive_ok else 'FAIL'}"
    )

    first_digest, second_digest = _generation_digest()
    deterministic = bool(first_digest) and first_digest == second_digest
    print(
        f"hash seed: digest {first_digest} "
        f"({'identical' if deterministic else 'differs'} under "
        f"PYTHONHASHSEED 0 and 1)"
    )

    time_ok = all(result.verdict == "PASS" for result in results)
    failures: list[str] = []
    if not time_ok:
        failures.append("one or more timed operations exceeded its budget")
    if not memory_ok:
        failures.append("single-episode peak memory exceeded 4 GB")
    if not archive_ok:
        failures.append("clean archive exceeded 1 GB")
    if not deterministic:
        failures.append("generation differs across PYTHONHASHSEED values")

    print()
    if failures:
        for failure in failures:
            print(f"- {failure}")
        print("RESULT: FAIL")
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "BenchResult",
    "archive_size",
    "main",
    "measure",
    "run_bench",
]
