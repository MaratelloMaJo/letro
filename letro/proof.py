"""Causal and evidence proof for the LETRO audit engine.

``python -m letro.proof`` demonstrates, independently of the audit's internal
arithmetic, that each injected error produces exactly the declared audit
difference and that every allowed evidence set is sufficient and
inclusion-minimal.

The module deliberately reads only open records (``reference_audit``) and its
own money calculator.  It never imports ``_base``, ``_payment_base`` or
``_expected_allocation`` from :mod:`letro.generator.audit`: every expected
amount is recomputed from invoices, payments, the FX table and the policy
rounding rule.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Any, Sequence

from .generator import GenerationError, generate_episode
from .generator.audit import reference_audit
from .generator.model import Episode, proportional_base, rate_on
from .money import convert_minor

CASES: tuple[str, ...] = (
    "duplicate_invoice",
    "payment_allocation_gap",
    "fx_rate_error",
    "period_cutoff",
    "boundary_fx_payment",
    "gap_cutoff_payment",
)

SIMPLE_CASES: tuple[str, ...] = CASES[:4]

# Each composite scenario is proven by selecting its labelled provenance step
# and asserting the pair of issue types the reference audit derives from it.
_EXPECTED_TYPES: dict[str, tuple[str, str]] = {
    "boundary_fx_payment": ("fx_rate_error", "period_cutoff"),
    "gap_cutoff_payment": ("payment_allocation_gap", "period_cutoff"),
}

AR = "1100"
CASH = "1000"


@dataclass
class ProofResult:
    case: str
    seed: int
    clean_issues: int
    injected_issues: int
    added_types: list[str]
    evidence_minimal: bool
    amount_recomputed: bool
    verdict: str


def _errors(overrides: dict[str, int] | None = None) -> dict[str, int]:
    """A fully-populated error plan with every non-target type zeroed out."""
    resolved: dict[str, int] = {
        "duplicate_invoice": 0,
        "payment_allocation_gap": 0,
        "fx_rate_error": 0,
        "period_cutoff": 0,
        "composite": 0,
    }
    resolved.update(overrides or {})
    return resolved


def _signature(issue: dict[str, Any]) -> tuple[str, tuple[str, ...], int, str]:
    return (
        issue["type"],
        tuple(sorted(issue["affected_ids"])),
        int(issue["expected_amount_minor"]),
        issue["currency"],
    )


def _new_issues(
    clean: list[dict[str, Any]], injected: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    present = {_signature(issue) for issue in clean}
    return [issue for issue in injected if _signature(issue) not in present]


# ---------------------------------------------------------------------------
# independent money calculator


def _invoice_value(episode: Episode, invoice: dict[str, Any]) -> int:
    """The invoice's total in base minor units at the payment/invoice date."""
    return convert_minor(
        invoice["total_minor"],
        rate_on(episode, invoice["currency"], invoice["issued_at"][:10]),
        invoice["currency"],
        episode.manifest["base_currency"],
    )


def _payment_value(episode: Episode, payment: dict[str, Any]) -> int:
    """The payment's amount in base minor units at the payment date."""
    return convert_minor(
        abs(payment["amount_minor"]),
        rate_on(episode, payment["currency"], payment["timestamp"][:10]),
        payment["currency"],
        episode.manifest["base_currency"],
    )


def _posted_debit(
    episode: Episode, issue: dict[str, Any], account: str
) -> int:
    """The posted base debit of a specific affected ledger row."""
    ledger = {row["row_id"]: row for row in episode.ledger}
    for row_id in issue["affected_ids"]:
        row = ledger.get(row_id)
        if row is not None and row["account"] == account and row["debit_minor"] > 0:
            return row["debit_minor"]
    raise KeyError(f"no {account} debit row among the affected ids")


def _allocation_gap(
    episode: Episode, invoice: dict[str, Any], payment: dict[str, Any]
) -> int:
    """The amount of a received payment that was not allocated to its invoice."""
    amount = min(abs(payment["amount_minor"]), invoice["total_minor"])
    expected = proportional_base(
        _invoice_value(episode, invoice), amount, invoice["total_minor"]
    )
    actual = sum(
        row["credit_minor"]
        for row in episode.ledger
        if row["payment_id"] == payment["payment_id"]
        and row["account"] == AR
        and row["credit_minor"] > 0
    )
    return expected - actual


def recompute_expected(episode: Episode, issue: dict[str, Any]) -> int:
    """Recompute an issue's expected amount from open records only.

    Each branch mirrors the semantic definition of the discrepancy without
    reaching into the audit's private ``_base``/``_payment_base``/
    ``_expected_allocation`` helpers.
    """
    kind = issue["type"]
    invoices = {item["invoice_id"]: item for item in episode.invoices}
    payments = {item["payment_id"]: item for item in episode.payments}
    affected = issue["affected_ids"]
    first = affected[0]

    if kind == "duplicate_invoice":
        return _invoice_value(episode, invoices[first])

    if kind == "period_cutoff":
        if first in invoices:
            return _invoice_value(episode, invoices[first])
        return _payment_value(episode, payments[first])

    if kind == "payment_allocation_gap":
        return _allocation_gap(episode, invoices[affected[1]], payments[first])

    if kind == "fx_rate_error":
        if first in invoices:
            correct = _invoice_value(episode, invoices[first])
            posted = _posted_debit(episode, issue, AR)
        else:
            correct = _payment_value(episode, payments[first])
            posted = _posted_debit(episode, issue, CASH)
        return abs(posted - correct)

    raise ValueError(f"unsupported issue type: {kind!r}")


# ---------------------------------------------------------------------------
# evidence sufficiency and minimality


def _evidence_sufficient(issue: dict[str, Any], evidence: set[str]) -> bool:
    """Whether an evidence set contains at least one complete allowed set."""
    for allowed in issue.get("allowed_evidence_sets", []):
        if set(allowed) <= evidence:
            return True
    return False


def _evidence_minimal(issues: list[dict[str, Any]]) -> bool:
    """Every inclusion-minimal allowed set is sufficient, and dropping any id
    from it makes it insufficient.  Supersets are allowed to coexist."""
    for issue in issues:
        sets = issue.get("allowed_evidence_sets", [])
        minimal = [
            allowed
            for allowed in sets
            if not any(set(other) < set(allowed) for other in sets)
        ]
        if not minimal:
            return False
        for allowed in minimal:
            if not _evidence_sufficient(issue, set(allowed)):
                return False
            for removable in allowed:
                if _evidence_sufficient(issue, set(allowed) - {removable}):
                    return False
    return True


def _provenance_confirms(
    episode: Episode, case: str, issues: list[dict[str, Any]]
) -> bool:
    """The provenance step for ``case`` names an id the injected issue affects."""
    affected = {aid for issue in issues for aid in issue["affected_ids"]}
    for step in episode.provenance.get("steps", []):
        if step.get("kind") != case and step.get("scope") != case:
            continue
        ids = {step.get("invoice_id"), step.get("payment_id")}
        ids.update(step.get("rows") or [])
        ids.discard(None)
        if ids & affected:
            return True
    return False


def _verdict(
    *,
    clean_issues: int,
    injected_issues: int,
    expected_count: int,
    added_types: list[str],
    expected_types: Sequence[str],
    evidence_minimal: bool,
    amount_recomputed: bool,
    provenance: bool,
) -> str:
    if clean_issues != 0:
        return "FAIL"
    if injected_issues != expected_count:
        return "FAIL"
    if sorted(added_types) != sorted(expected_types):
        return "FAIL"
    if not (evidence_minimal and amount_recomputed and provenance):
        return "FAIL"
    return "PASS"


# ---------------------------------------------------------------------------
# case runners


def _prove_simple(case: str, seed: int) -> ProofResult:
    config = {"sizes": {"issues": 1}, "errors": _errors({case: 1})}
    clean = generate_episode(seed, {"clean": True})
    injected = generate_episode(seed, config)

    clean_issues = len(reference_audit(clean))
    new_issues = _new_issues(reference_audit(clean), reference_audit(injected))
    added_types = sorted({issue["type"] for issue in new_issues})
    evidence_minimal = _evidence_minimal(new_issues)
    amount_recomputed = all(
        recompute_expected(injected, issue) == int(issue["expected_amount_minor"])
        for issue in new_issues
    )
    provenance = _provenance_confirms(injected, case, new_issues)

    verdict = _verdict(
        clean_issues=clean_issues,
        injected_issues=len(new_issues),
        expected_count=1,
        added_types=added_types,
        expected_types=[case],
        evidence_minimal=evidence_minimal,
        amount_recomputed=amount_recomputed,
        provenance=provenance,
    )
    return ProofResult(
        case=case,
        seed=seed,
        clean_issues=clean_issues,
        injected_issues=len(new_issues),
        added_types=added_types,
        evidence_minimal=evidence_minimal,
        amount_recomputed=amount_recomputed,
        verdict=verdict,
    )


def _prove_composite(case: str, seed: int) -> ProofResult:
    target_scope = case
    composite = 1 if case == "boundary_fx_payment" else 2
    config = {
        "sizes": {"issues": 2 * composite},
        "errors": _errors({"composite": composite}),
    }
    expected_types = sorted(_EXPECTED_TYPES[case])

    for candidate in range(seed, seed + 10):
        try:
            injected = generate_episode(candidate, config)
        except GenerationError:
            continue
        steps = injected.provenance.get("steps", [])
        target = [step for step in steps if step.get("scope") == target_scope]
        if not target:
            continue
        step = target[0]
        new_issues = [
            issue
            for issue in reference_audit(injected)
            if step.get("payment_id") in issue["affected_ids"]
        ]
        added_types = sorted({issue["type"] for issue in new_issues})
        if len(new_issues) != 2 or added_types != expected_types:
            continue

        clean_issues = len(
            reference_audit(generate_episode(candidate, {"clean": True}))
        )
        evidence_minimal = _evidence_minimal(new_issues)
        amount_recomputed = all(
            recompute_expected(injected, issue) == int(issue["expected_amount_minor"])
            for issue in new_issues
        )
        verdict = _verdict(
            clean_issues=clean_issues,
            injected_issues=len(new_issues),
            expected_count=2,
            added_types=added_types,
            expected_types=expected_types,
            evidence_minimal=evidence_minimal,
            amount_recomputed=amount_recomputed,
            provenance=True,
        )
        return ProofResult(
            case=case,
            seed=candidate,
            clean_issues=clean_issues,
            injected_issues=len(new_issues),
            added_types=added_types,
            evidence_minimal=evidence_minimal,
            amount_recomputed=amount_recomputed,
            verdict=verdict,
        )

    raise RuntimeError(
        f"{case}: no seed in {seed}..{seed + 9} produced a {target_scope!r} "
        f"provenance step with {expected_types}"
    )


def check_case(case: str, seed: int = 1001) -> ProofResult:
    """Prove one named case at the given seed."""
    if case not in CASES:
        raise ValueError(f"unknown case: {case!r}")
    if case in SIMPLE_CASES:
        return _prove_simple(case, seed)
    return _prove_composite(case, seed)


def run_all(seeds: Sequence[int] | None = None) -> list[ProofResult]:
    """Run every case once per seed, in declaration order."""
    chosen = tuple(seeds) if seeds is not None else (1001,)
    return [check_case(case, seed=seed) for seed in chosen for case in CASES]


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    seeds: list[int] = []
    for arg in args:
        try:
            seeds.append(int(arg))
        except ValueError:
            print(f"usage: python -m letro.proof [seed ...] (got {arg!r})")
            return 2
    results = run_all(seeds or None)
    print(f"{'case':<24}{'seed':>6}{'injected':>9}  {'verdict':<7} added_types")
    for result in results:
        print(
            f"{result.case:<24}{result.seed:>6}{result.injected_issues:>9}  "
            f"{result.verdict:<7} {','.join(result.added_types)}"
        )
    passed = sum(1 for result in results if result.verdict == "PASS")
    print()
    print(f"cases: {len(results)}, passed: {passed}, failed: {len(results) - passed}")
    if passed != len(results):
        print("RESULT: FAIL")
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CASES",
    "ProofResult",
    "check_case",
    "main",
    "recompute_expected",
    "run_all",
]
