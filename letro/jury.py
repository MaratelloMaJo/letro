"""Jury-style integration run over hidden-style episodes.

This is the harness a judge can run: 20 unseen seeds, four policy adapters, 20
permutations and 5 exact replays. It checks the contract a jury checks, not the
author's own score: every run terminates, oracle answers survive ID/order
permutation, the mark-all attack fails, clean books punish false accusations,
and no observation leaks closed truth.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .constants import MAX_STEPS
from .factory import env_from_episode
from .generator import generate_episode, reference_findings
from .invariants import check_episode
from .permute import assert_no_reused_ids, permute_episode
from .policies import MarkAllPolicy, OraclePolicy, RandomExplorerPolicy, ReconciliationPolicy
from .trajectory import TrajectoryRecorder, run_episode

CONFIGS: list[dict[str, Any]] = []


def _cfg(
    *,
    clean: bool = False,
    base: str = "KZT",
    invoices: int = 34,
    payments: int = 30,
    rows: int = 300,
    days: int = 30,
    errors: dict[str, int] | None = None,
    variant: int = 0,
) -> dict[str, Any]:
    issues = 0
    if not clean and errors:
        issues = sum(value for key, value in errors.items() if key != "composite")
        issues += 2 * errors.get("composite", 0)
    return {
        "base_currency": base,
        "period_days": days,
        "sizes": {
            "invoices": invoices,
            "payments": payments,
            "issues": issues,
            "ledger_rows": rows,
        },
        "errors": errors or {},
        "clean": clean,
        "variant": variant,
    }


def _errors(duplicate: int = 0, gap: int = 0, fx: int = 0, cutoff: int = 0, composite: int = 0):
    return {
        "duplicate_invoice": duplicate,
        "payment_allocation_gap": gap,
        "fx_rate_error": fx,
        "period_cutoff": cutoff,
        "composite": composite,
    }


def _build_configs() -> list[tuple[str, dict[str, Any]]]:
    values: list[tuple[str, dict[str, Any]]] = []
    for index in range(5):
        values.append(
            (
                "clean",
                _cfg(clean=True, base=("KZT", "USD", "EUR")[index % 3], invoices=30 + index * 4),
            )
        )
    for index in range(5):
        values.append(
            (
                "composite",
                _cfg(
                    base=("KZT", "USD")[index % 2],
                    errors=_errors(composite=3),
                    invoices=38 + index * 3,
                    rows=340 + index * 20,
                ),
            )
        )
    for index in range(10):
        values.append(
            (
                "mixed",
                _cfg(
                    base=("KZT", "USD", "EUR")[index % 3],
                    errors=_errors(
                        duplicate=1,
                        gap=1 if index % 2 == 0 else 0,
                        fx=1 if index % 3 == 0 else 0,
                        cutoff=1 if index % 4 == 0 else 0,
                        composite=1,
                    ),
                    invoices=32 + index,
                    payments=28 + index,
                    rows=300 + index * 10,
                    days=30 + (index % 3) * 5,
                ),
            )
        )
    return values


def _digest(episode: Any) -> str:
    payload = json.dumps(
        {
            "manifest": episode.manifest,
            "ledger": episode.ledger,
            "invoices": episode.invoices,
            "payments": episode.payments,
            "fx": episode.fx,
            "truth": episode.truth,
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _run(episode: Any, name: str, seed: int = 0):
    env, evaluator = env_from_episode(episode, mode="eval")
    if name == "oracle":
        policy = OraclePolicy(episode)
    elif name == "reconciliation":
        policy = ReconciliationPolicy()
    elif name == "mark_all":
        policy = MarkAllPolicy()
    else:
        policy = RandomExplorerPolicy(seed=seed)
    recorder = TrajectoryRecorder()
    result = run_episode(env, policy, recorder=recorder, evaluator=evaluator)
    return result, evaluator, recorder


def main() -> int:
    conffs = _build_configs()
    failures: list[str] = []
    rows: list[dict[str, Any]] = []
    recon_clean: list[float] = []
    oracles_perfect = 0
    permutes_ok = 0
    replays_ok = 0

    for index, (kind, config) in enumerate(conffs):
        seed = 7001 + index
        episode = generate_episode(seed, config)
        problems = check_episode(episode, config)
        if problems:
            failures.append(f"episode {seed} invariants: {problems[0]}")
        oracle_result, oracle_eval, oracle_rec = _run(episode, "oracle", seed)
        recon_result, recon_eval, recon_rec = _run(episode, "reconciliation", seed)
        mark_result, _mark_eval, _mark_rec = _run(episode, "mark_all", seed)
        random_result, _random_eval, _random_rec = _run(episode, "random_explorer", seed)

        for label, result, recorder in (
            ("oracle", oracle_result, oracle_rec),
            ("reconciliation", recon_result, recon_rec),
        ):
            if not result.terminated or result.steps > MAX_STEPS:
                failures.append(f"{label} did not termate on {seed}")
            for entry in recorder.entries:
                if entry["truncated"]:
                    failures.append(f"{label} trunced on {seed}")
                    break

        oracle_metrics = oracle_eval.result()
        if oracle_metrics.get("f1") != 1.0 or oracle_metrics.get("reward") != 1.0:
            failures.append(f"oracle imperfect on {seed}: {oracle_metrics}")
        else:
            oracles_perfect += 1
        if mark_result.metrics.get("f1", 0) > 0.2:
            failures.append(f"mark_all scored {mark_result.metrics.get('f1')} on {seed}")
        if kind == "clean":
            recon_clean.append(float(recon_result.metrics.get("f1", 0)))
            if recon_result.metrics.get("fp", 0) == 0:
                failures.append(f"naive reconciliation made no clean mistake on {seed}")

        rows.append(
            {
                "seed": seed,
                "kind": kind,
                "issues": len(episode.truth["issues"]),
                "oracle_f1": oracle_result.metrics.get("f1"),
                "oracle_reward": oracle_result.metrics.get("reward"),
                "recon_f1": recon_result.metrics.get("f1"),
                "recon_reward": recon_result.metrics.get("reward"),
                "mark_f1": mark_result.metrics.get("f1"),
                "random_f1": random_result.metrics.get("f1"),
            }
        )

        permuted = permute_episode(episode, salt=f"jury-{seed}")
        assert_no_reused_ids(episode, permuted)
        permuted_problems = check_episode(permuted, config)
        if permuted_problems:
            failures.append(f"permuted {seed} invariants: {permuted_problems[0]}")
        else:
            before, _before_eval, _before_rec = _run(episode, "oracle", seed)
            after, after_eval, _after_rec = _run(permuted, "oracle", seed)
            if (
                before.metrics.get("f1") == after.metrics.get("f1") == 1.0
                and before.metrics.get("reward") == after.metrics.get("reward") == 1.0
            ):
                permutes_ok += 1
            else:
                failures.append(f"permutation changed oracle reward on {seed}")

        if index < 5:
            again = generate_episode(seed, config)
            if _digest(episode) != _digest(again):
                failures.append(f"same seed produced different records on {seed}")
            else:
                left, _left_eval, _left_rec = _run(episode, "reconciliation", seed)
                right, _right_eval, _right_rec = _run(again, "reconciliation", seed)
                if json.dumps(left.metrics, sort_keys=True) != json.dumps(
                    right.metrics, sort_keys=True
                ) or left.reward != right.reward:
                    failures.append(f"replay changed metrics on {seed}")
                else:
                    replays_ok += 1

    print(f"{'seed':>6} {'kind':<10} {'issues':>6} {'oracle':>8} {'recon':>8} {'mark':>7} {'random':>7}")
    for row in rows:
        print(
            f"{row['seed']:>6} {row['kind']:<10} {row['issues']:>6} "
            f"{row['oracle_f1']!s:>8} {row['recon_f1']!s:>8} "
            f"{row['mark_f1']!s:>7} {row['random_f1']!s:>7}"
        )
    print()
    print(f"episodes: {len(rows)}, oracle perfect: {oracles_perfect}/{len(rows)}")
    print(f"permutations: {permutes_ok}/{len(rows)}, exact replays: {replays_ok}/5")
    print(f"clean reconciliation F1: {recon_clean}")
    print(f"failures: {len(failures)}")
    for failure in failures:
        print(f"- {failure}")
    if failures:
        print("RESULT: FAIL")
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


