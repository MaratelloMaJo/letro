"""Per-error-type difficulty science and the limited-information probe.

The four public baselines (including the exact ``thorough`` reference) are run
over the ten dev episodes, each submission is compared to the labelled truth per
error type with the shared matcher, and TP/FP/FN, precision, recall and F1 are
reported. Two ``LimitedPolicy`` runs (one and two pages per table) isolate the
effect of information from heuristic quality. The ``oracle`` row is
evaluator-side: it is computed directly from ``reference_findings`` and is never
instantiated as an environment policy. Clean dev episodes are counted for their
legitimate distractors so the difficulty numbers read against a dataset that
contains real negatives, not empty books.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Sequence

from .constants import ERROR_TYPES
from .factory import env_from_episode
from .generator import Episode, load_episode, reference_audit, reference_findings
from .matcher import match
from .policies import make_policy
from .policies.limited import LimitedPolicy
from .trajectory import run_episode

ROOT = Path(__file__).resolve().parents[1]
INDEX_PATH = ROOT / "episodes" / "index.json"
EVIDENCE_PATH = ROOT / "docs" / "evidence" / "difficulty.json"

# The four public adapters plus the exact reference. The oracle is computed
# evaluator-side directly from ``reference_findings``, never through the env.
POLICIES = ("random_explorer", "reconciliation", "thorough", "mark_all")
LIMITED_RUNS = (("limited_1", 1), ("limited_2", 2))
ORACLE_EXAMPLE = "evaluator-side"

DISTRACTOR_LABELS = (
    ("split_payments", "split payment"),
    ("refunds", "refund"),
    ("recurring_identical_amounts", "recurring identical amount"),
    ("open_invoices", "legitimately open invoice"),
)


@dataclass
class TypeMetric:
    policy: str
    error_type: str
    tp: int
    fp: int
    fn: int
    precision: float
    recall: float
    f1: float
    example: str


class _CapturePolicy:
    """Delegate to a policy and remember the findings it submitted."""

    def __init__(self, policy: Any) -> None:
        self._policy = policy
        self.name = str(getattr(policy, "name", "policy"))
        self.findings: list[dict[str, Any]] = []

    def reset(self, observation: dict[str, Any], info: dict[str, Any]) -> None:
        self._policy.reset(observation, info)
        self.findings = []

    def act(self, observation: dict[str, Any]) -> dict[str, Any]:
        action = self._policy.act(observation)
        if isinstance(action, dict) and action.get("type") == "submit":
            payload = action.get("findings") or {}
            self.findings = list(payload.get("findings") or [])
        return action


def _load_dev_episodes() -> list[tuple[int, Episode]]:
    index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    return [
        (int(entry["seed"]), load_episode(ROOT / entry["directory"]))
        for entry in index["dev"]
    ]


def _dev_seeds() -> dict[str, int]:
    index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    return {entry["episode_id"]: int(entry["seed"]) for entry in index["dev"]}


def _resolve(
    episodes: Sequence[Episode] | None,
) -> list[tuple[int, Episode]]:
    if episodes is None:
        return _load_dev_episodes()
    seeds = _dev_seeds()
    return [
        (seeds.get(episode.manifest["episode_id"], 0), episode)
        for episode in episodes
    ]


def _new_buckets() -> tuple[dict[str, list[int]], dict[str, dict[str, str]]]:
    totals = {kind: [0, 0, 0] for kind in ERROR_TYPES}
    examples = {kind: {"fn": "", "fp": ""} for kind in ERROR_TYPES}
    return totals, examples


def _accumulate(
    totals: dict[str, list[int]],
    examples: dict[str, dict[str, str]],
    truth_issues: list[dict[str, Any]],
    findings: list[dict[str, Any]],
) -> None:
    for kind in ERROR_TYPES:
        truth = [issue for issue in truth_issues if issue.get("type") == kind]
        reported = [item for item in findings if item.get("type") == kind]
        result = match(truth, reported)
        totals[kind][0] += result.tp
        totals[kind][1] += result.fp
        totals[kind][2] += result.fn
        if result.fn and not examples[kind]["fn"]:
            examples[kind]["fn"] = result.missed_issue_ids[0]
        if result.fp and not examples[kind]["fp"]:
            examples[kind]["fp"] = str(reported[result.unmatched_findings[0]]["type"])


def _rows(
    label: str,
    totals: dict[str, list[int]],
    examples: dict[str, dict[str, str]],
) -> list[TypeMetric]:
    rows: list[TypeMetric] = []
    for kind in ERROR_TYPES:
        tp, fp, fn = totals[kind]
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 0.0 if tp == 0 else (2 * tp) / (2 * tp + fp + fn)
        example = examples[kind]["fn"] or examples[kind]["fp"]
        if label == "oracle":
            example = ORACLE_EXAMPLE
        rows.append(
            TypeMetric(
                policy=label,
                error_type=kind,
                tp=tp,
                fp=fp,
                fn=fn,
                precision=round(precision, 6),
                recall=round(recall, 6),
                f1=round(f1, 6),
                example=example,
            )
        )
    return rows


def _run_named(name: str, pairs: list[tuple[int, Episode]]) -> list[TypeMetric]:
    totals, examples = _new_buckets()
    for seed, episode in pairs:
        env, _ = env_from_episode(episode, mode="train")
        policy = _CapturePolicy(make_policy(name, seed=seed))
        run_episode(env, policy, mode="train")
        _accumulate(
            totals,
            examples,
            list(episode.truth.get("issues", [])),
            policy.findings,
        )
    return _rows(name, totals, examples)


def _run_limited(
    label: str, max_pages: int, pairs: list[tuple[int, Episode]]
) -> list[TypeMetric]:
    totals, examples = _new_buckets()
    for _seed, episode in pairs:
        env, _ = env_from_episode(episode, mode="train")
        policy = _CapturePolicy(LimitedPolicy(max_pages))
        run_episode(env, policy, mode="train")
        _accumulate(
            totals,
            examples,
            list(episode.truth.get("issues", [])),
            policy.findings,
        )
    return _rows(label, totals, examples)


def _oracle_rows(pairs: list[tuple[int, Episode]]) -> list[TypeMetric]:
    totals, examples = _new_buckets()
    for _seed, episode in pairs:
        payload = reference_findings(episode)
        _accumulate(
            totals,
            examples,
            list(episode.truth.get("issues", [])),
            list(payload.get("findings", [])),
        )
    return _rows("oracle", totals, examples)


def collect(episodes: list[Episode] | None = None) -> list[TypeMetric]:
    """Measure per-(policy, error-type) difficulty over the dev episodes."""
    pairs = _resolve(episodes)
    resolved = [episode for _seed, episode in pairs]
    _assert_distractors(distractor_counts(resolved))

    metrics: list[TypeMetric] = []
    for name in POLICIES:
        metrics.extend(_run_named(name, pairs))
    for label, max_pages in LIMITED_RUNS:
        metrics.extend(_run_limited(label, max_pages, pairs))
    metrics.extend(_oracle_rows(pairs))
    return metrics


# --------------------------------------------------------------- distractors
def _split_payment_count(episode: Episode) -> int:
    """Invoices paid by more than one positive payment document."""
    by_invoice: dict[str, set[str]] = {}
    for payment in episode.payments:
        if payment["amount_minor"] <= 0:
            continue
        for reference in payment.get("invoice_refs") or []:
            by_invoice.setdefault(reference, set()).add(payment["payment_id"])
    return sum(1 for ids in by_invoice.values() if len(ids) >= 2)


def _refund_count(episode: Episode) -> int:
    return sum(1 for payment in episode.payments if payment["amount_minor"] < 0)


def _recurring_identical_amount_count(episode: Episode) -> int:
    """Operating-expense postings whose debit amount repeats."""
    expenses = Counter(
        row["debit_minor"]
        for row in episode.ledger
        if row["account"] == "5000" and row["debit_minor"] > 0
    )
    return sum(1 for repeats in expenses.values() if repeats > 1)


def _open_invoice_count(episode: Episode) -> int:
    """Invoices whose positive payments fall short of the issued total."""
    received: dict[str, int] = {}
    for payment in episode.payments:
        if payment["amount_minor"] > 0:
            for reference in payment.get("invoice_refs") or []:
                received[reference] = received.get(reference, 0) + int(
                    payment["amount_minor"]
                )
    return sum(
        1
        for invoice in episode.invoices
        if received.get(invoice["invoice_id"], 0) < int(invoice["total_minor"])
    )


def distractor_counts(episodes: Sequence[Episode] | None = None) -> dict[str, int]:
    """Aggregate legitimate distractors across the clean dev episodes."""
    pairs = _resolve(episodes)
    clean = [
        episode for _seed, episode in pairs if not reference_audit(episode)
    ]
    counts: dict[str, int] = {
        "split_payments": 0,
        "refunds": 0,
        "recurring_identical_amounts": 0,
        "open_invoices": 0,
        "clean_episodes": len(clean),
        "clean_audit_issues": 0,
    }
    for episode in clean:
        counts["split_payments"] += _split_payment_count(episode)
        counts["refunds"] += _refund_count(episode)
        counts["recurring_identical_amounts"] += _recurring_identical_amount_count(
            episode
        )
        counts["open_invoices"] += _open_invoice_count(episode)
        counts["clean_audit_issues"] += len(reference_audit(episode))
    return counts


def _assert_distractors(counts: dict[str, int]) -> None:
    for key, label in DISTRACTOR_LABELS:
        if counts.get(key, 0) < 1:
            raise AssertionError(
                f"clean dev episodes contain no {label}; "
                f"distractor count is {counts.get(key, 0)} (expected at least 1)"
            )
    if counts.get("clean_audit_issues", 0) != 0:
        raise AssertionError(
            f"clean dev episodes produced {counts['clean_audit_issues']} "
            "reference-audit issues; the clean audit must be zero"
        )


# ------------------------------------------------------------------ evidence
def write_evidence(metrics: list[TypeMetric], path: Path) -> Path:
    """Write metrics deterministically, sorted by policy then error type."""
    destination = Path(path)
    ordered = sorted(metrics, key=lambda item: (item.policy, item.error_type))
    payload = {
        "generated_by": "python -m letro.difficulty",
        "split": "dev",
        "metrics": [asdict(item) for item in ordered],
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return destination


# -------------------------------------------------------------------- report
def _print_table(metrics: list[TypeMetric]) -> None:
    print(
        f"{'policy':<18}{'error_type':<24}{'TP':>4}{'FP':>4}{'FN':>4}"
        f"{'P':>8}{'R':>8}{'F1':>8}  example"
    )
    for item in sorted(metrics, key=lambda row: (row.policy, row.error_type)):
        print(
            f"{item.policy:<18}{item.error_type:<24}{item.tp:>4}{item.fp:>4}"
            f"{item.fn:>4}{item.precision:>8.3f}{item.recall:>8.3f}"
            f"{item.f1:>8.3f}  {item.example}"
        )


def _print_distractors(counts: dict[str, int]) -> None:
    print("Clean-episode distractors")
    for key, label in DISTRACTOR_LABELS:
        print(f"  {label:<28} {counts[key]}")
    print(f"  {'clean episodes':<28} {counts['clean_episodes']}")
    print(f"  {'clean reference-audit issues':<28} {counts['clean_audit_issues']}")


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args:
        print(f"usage: python -m letro.difficulty (got {args!r})")
        return 2

    metrics = collect()
    counts = distractor_counts()
    path = write_evidence(metrics, EVIDENCE_PATH)
    _print_table(metrics)
    print()
    _print_distractors(counts)
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "EVIDENCE_PATH",
    "TypeMetric",
    "collect",
    "distractor_counts",
    "main",
    "write_evidence",
]
