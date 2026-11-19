"""Generator fuzz: invariants, truth reproduction, and permutation stability.

Run ``python -m letro.fuzz --seeds 100`` for the full sweep, or
``python -m letro.fuzz --quick`` for the 20-seed smoke used by CI. The command
exits non-zero on the first contract violation it can report, after printing
every failure in the run.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

from .generator import generate_episode
from .generator.errors import GenerationError
from .invariants import check_clean_baseline, check_episode
from .permute import assert_no_reused_ids, permute_episode
from .presets import preset, preset_names
from .evaluator import Evaluator
from .generator import reference_findings


def _oracle_ok(episode: Any) -> tuple[bool, str]:
    evaluator = Evaluator(episode)
    outcome = evaluator.score(reference_findings(episode), 0)
    metrics = outcome.get("metrics") or {}
    if outcome.get("invalid"):
        return False, "oracle submission was invalid"
    if metrics.get("f1") != 1.0:
        return False, f"oracle F1 is {metrics.get('f1')}"
    if outcome.get("reward") != 1.0:
        return False, f"oracle reward is {outcome.get('reward')}"
    return True, ""


def _check_one(seed: int, name: str, config: dict[str, Any], permute: bool) -> list[str]:
    problems: list[str] = []
    try:
        episode = generate_episode(seed, config)
    except (GenerationError, Exception) as exc:  # noqa: BLE001 - report every failure
        return [f"generation failed: {type(exc).__name__}: {exc}"]
    problems.extend(check_episode(episode, config))
    if not problems:
        problems.extend(check_clean_baseline(episode, seed, config))
    ok, detail = _oracle_ok(episode)
    if not ok:
        problems.append(detail)
    if permute and not problems:
        try:
            permuted = permute_episode(episode, salt=f"fuzz-{seed}-{name}")
            assert_no_reused_ids(episode, permuted)
            problems.extend(check_episode(permuted, config))
            ok, detail = _oracle_ok(permuted)
            if not ok:
                problems.append(f"permuted: {detail}")
        except Exception as exc:  # noqa: BLE001
            problems.append(f"permutation failed: {type(exc).__name__}: {exc}")
    return problems


def run(
    seeds: int,
    names: list[str] | None = None,
    base_seed: int = 30000,
    permute: bool = True,
    verbose: bool = False,
    quiet: bool = False,
) -> int:
    names = names or list(preset_names())
    failures = 0
    checked = 0
    for name in names:
        config = preset(name)
        local = 0
        for offset in range(seeds):
            seed = base_seed + offset
            problems = _check_one(seed, name, config, permute)
            checked += 1
            if problems:
                failures += 1
                local += 1
                print(f"FAIL preset={name} seed={seed}")
                for problem in problems[:8]:
                    print(f"  - {problem}")
        if not quiet:
            print(f"{name}: {seeds - local}/{seeds} episodes clean")
        if verbose:
            print(f"  config={config}")
    if not quiet:
        print()
        print(f"checked {checked} episodes across {len(names)} presets; failures: {failures}")
    if failures:
        if not quiet:
            print("RESULT: FAIL")
        return 1
    if not quiet:
        print("RESULT: PASS")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m letro.fuzz")
    parser.add_argument("--seeds", type=int, default=100)
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--presets", default="")
    parser.add_argument("--base-seed", type=int, default=30000)
    parser.add_argument("--no-permute", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)
    seeds = 20 if args.quick else args.seeds
    names = [item.strip() for item in args.presets.split(",") if item.strip()]
    if not names:
        names = list(preset_names())
    for name in names:
        if name not in preset_names():
            print(f"unknown preset: {name}; choose from {', '.join(preset_names())}")
            return 2
    return run(
        seeds=seeds,
        names=names,
        base_seed=args.base_seed,
        permute=not args.no_permute,
        verbose=args.verbose,
    )


if __name__ == "__main__":
    raise SystemExit(main())
