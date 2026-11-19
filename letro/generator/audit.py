"""Independent reference audit over open records only.

The audit is the proof that every truth issue is discoverable and sufficient
from the files an agent can see. It deliberately does not read truth.json.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from ..money import convert_minor
from ..rng import deterministic_id
from .model import Episode, proportional_base, rate_on

AR = "1100"
REVENUE = "4000"
CASH = "1000"
FX = "4900"
SUSPENSE = "9999"


def _invoice_index(episode: Episode) -> dict[str, dict[str, Any]]:
    return {invoice["invoice_id"]: invoice for invoice in episode.invoices}


def _payment_index(episode: Episode) -> dict[str, dict[str, Any]]:
    return {payment["payment_id"]: payment for payment in episode.payments}


def _base(episode: Episode, invoice: dict[str, Any]) -> int:
    return convert_minor(
        invoice["total_minor"],
        rate_on(episode, invoice["currency"], invoice["issued_at"][:10]),
        invoice["currency"],
        episode.manifest["base_currency"],
    )


def _payment_base(episode: Episode, payment: dict[str, Any]) -> int:
    return convert_minor(
        abs(payment["amount_minor"]),
        rate_on(episode, payment["currency"], payment["timestamp"][:10]),
        payment["currency"],
        episode.manifest["base_currency"],
    )


def _expected_allocation(
    episode: Episode, invoice: dict[str, Any], payment: dict[str, Any]
) -> int:
    amount = min(abs(payment["amount_minor"]), invoice["total_minor"])
    return proportional_base(_base(episode, invoice), amount, invoice["total_minor"])


def _inside(episode: Episode, timestamp: str) -> bool:
    start = datetime.fromisoformat(episode.manifest["period_start"])
    end = datetime.fromisoformat(episode.manifest["period_end"])
    moment = datetime.fromisoformat(timestamp)
    return start <= moment <= end


def _rows(episode: Episode, **filters: Any) -> list[dict[str, Any]]:
    result = []
    for row in episode.ledger:
        if all(row.get(key) == value for key, value in filters.items()):
            result.append(row)
    return result


def _issue(
    kind: str,
    affected: list[str],
    amount: int,
    currency: str,
    evidence_sets: list[list[str]],
    explanation: str,
) -> dict[str, Any]:
    unique_affected = list(dict.fromkeys(affected))
    cleaned_sets: list[list[str]] = []
    for evidence in evidence_sets:
        values = list(dict.fromkeys(evidence))
        if values and values not in cleaned_sets and len(values) <= 10:
            cleaned_sets.append(values)
    return {
        "type": kind,
        "affected_ids": unique_affected,
        "expected_amount_minor": int(amount),
        "currency": currency,
        "allowed_evidence_sets": cleaned_sets,
        "explanation": explanation,
    }


def reference_audit(episode: Episode) -> list[dict[str, Any]]:
    """Return every discrepancy derivable from open data."""
    base = episode.manifest["base_currency"]
    tolerance = int(episode.policy.get("amount_tolerance_minor", 1))
    invoices = _invoice_index(episode)
    payments = _payment_index(episode)
    issues: list[dict[str, Any]] = []

    # 1. Duplicate invoice postings: more than one AR debit per invoice.
    for invoice_id, invoice in invoices.items():
        ar_rows = [
            row
            for row in episode.ledger
            if row["invoice_id"] == invoice_id
            and row["account"] == AR
            and row["debit_minor"] > 0
        ]
        ar_rows.sort(key=lambda row: (row["timestamp"], row["row_id"]))
        if len(ar_rows) <= 1:
            continue
        expected = _base(episode, invoice)
        extra_rows = ar_rows[1:]
        for extra in extra_rows:
            revenue_rows = [
                row
                for row in episode.ledger
                if row["invoice_id"] == invoice_id
                and row["account"] == REVENUE
                and row["credit_minor"] > 0
                and row["timestamp"] == extra["timestamp"]
                and row["credit_minor"] == extra["debit_minor"]
            ]
            affected = [invoice_id, extra["row_id"]] + [
                row["row_id"] for row in revenue_rows
            ]
            evidence = [invoice_id, extra["row_id"]] + [
                row["row_id"] for row in revenue_rows
            ]
            issues.append(
                _issue(
                    "duplicate_invoice",
                    affected,
                    extra["debit_minor"],
                    base,
                    [evidence, [invoice_id, extra["row_id"]]],
                    "The invoice is posted more than once; the extra posting "
                    "inflates receivables and revenue.",
                )
            )

    # 2. Payment received but not fully allocated to its invoice.
    for payment_id, payment in payments.items():
        if payment["amount_minor"] <= 0:
            continue
        refs = payment.get("invoice_refs") or []
        if not refs or refs[0] not in invoices:
            continue
        invoice = invoices[refs[0]]
        expected_alloc = _expected_allocation(episode, invoice, payment)
        ar_rows = [
            row
            for row in episode.ledger
            if row["payment_id"] == payment_id
            and row["account"] == AR
            and row["credit_minor"] > 0
        ]
        actual_alloc = sum(row["credit_minor"] for row in ar_rows)
        gap = expected_alloc - actual_alloc
        if gap <= tolerance:
            continue
        cash_rows = [
            row
            for row in episode.ledger
            if row["payment_id"] == payment_id and row["account"] == CASH
        ]
        suspense_rows = [
            row
            for row in episode.ledger
            if row["payment_id"] == payment_id and row["account"] == SUSPENSE
        ]
        affected = (
            [payment_id, invoice["invoice_id"]]
            + [row["row_id"] for row in cash_rows]
            + [row["row_id"] for row in ar_rows]
            + [row["row_id"] for row in suspense_rows]
        )
        evidence = (
            [payment_id, invoice["invoice_id"]]
            + [row["row_id"] for row in cash_rows]
            + [row["row_id"] for row in ar_rows]
        )
        issues.append(
            _issue(
                "payment_allocation_gap",
                affected,
                gap,
                base,
                [evidence, evidence + [row["row_id"] for row in suspense_rows]],
                "The payment covers the invoice but part of the receipt was not "
                "allocated; receivables stay overstated.",
            )
        )

    # 3. FX conversion mismatch on invoice and payment postings.
    for invoice_id, invoice in invoices.items():
        expected = _base(episode, invoice)
        for row in episode.ledger:
            if (
                row["invoice_id"] != invoice_id
                or row["account"] != AR
                or row["debit_minor"] <= 0
            ):
                continue
            delta = abs(row["debit_minor"] - expected)
            if delta <= tolerance:
                continue
            revenue_rows = [
                other
                for other in episode.ledger
                if other["invoice_id"] == invoice_id
                and other["account"] == REVENUE
                and other["timestamp"] == row["timestamp"]
            ]
            affected = [invoice_id, row["row_id"]] + [
                other["row_id"] for other in revenue_rows
            ]
            issues.append(
                _issue(
                    "fx_rate_error",
                    affected,
                    delta,
                    base,
                    [affected, [invoice_id, row["row_id"]]],
                    "The posted base amount does not match the policy FX rate for "
                    "the invoice date.",
                )
            )

    for payment_id, payment in payments.items():
        if payment["amount_minor"] <= 0:
            continue
        expected = _payment_base(episode, payment)
        cash_rows = [
            row
            for row in episode.ledger
            if row["payment_id"] == payment_id
            and row["account"] == CASH
            and row["debit_minor"] > 0
        ]
        for row in cash_rows:
            delta = abs(row["debit_minor"] - expected)
            if delta <= tolerance:
                continue
            fx_rows = [
                other
                for other in episode.ledger
                if other["payment_id"] == payment_id and other["account"] == FX
            ]
            ar_rows = [
                other
                for other in episode.ledger
                if other["payment_id"] == payment_id and other["account"] == AR
            ]
            affected = (
                [payment_id, row["row_id"]]
                + [other["row_id"] for other in fx_rows]
                + [other["row_id"] for other in ar_rows]
            )
            issues.append(
                _issue(
                    "fx_rate_error",
                    affected,
                    delta,
                    base,
                    [affected, [payment_id, row["row_id"]]],
                    "The cash receipt was converted at a rate that does not match "
                    "the policy date for the payment.",
                )
            )

    # 4. Entries posted outside the reporting period while the document is inside.
    for invoice_id, invoice in invoices.items():
        if not _inside(episode, invoice["issued_at"]):
            continue
        ar_rows = [
            row
            for row in episode.ledger
            if row["invoice_id"] == invoice_id
            and row["account"] == AR
            and row["debit_minor"] > 0
        ]
        outside = [row for row in ar_rows if not _inside(episode, row["timestamp"])]
        if not outside:
            continue
        revenue_rows = [
            row
            for row in episode.ledger
            if row["invoice_id"] == invoice_id
            and row["account"] == REVENUE
            and row["timestamp"] == outside[0]["timestamp"]
        ]
        affected = (
            [invoice_id]
            + [row["row_id"] for row in outside]
            + [row["row_id"] for row in revenue_rows]
        )
        issues.append(
            _issue(
                "period_cutoff",
                affected,
                _base(episode, invoice),
                base,
                [affected, [invoice_id, outside[0]["row_id"]]],
                "The invoice belongs to the reporting period but its posting sits "
                "outside the period boundary.",
            )
        )

    for payment_id, payment in payments.items():
        if payment["amount_minor"] <= 0:
            continue
        if not _inside(episode, payment["timestamp"]):
            continue
        cash_rows = [
            row
            for row in episode.ledger
            if row["payment_id"] == payment_id
            and row["account"] == CASH
            and row["debit_minor"] > 0
        ]
        outside = [row for row in cash_rows if not _inside(episode, row["timestamp"])]
        if not outside:
            continue
        ar_rows = [
            row
            for row in episode.ledger
            if row["payment_id"] == payment_id and row["account"] == AR
        ]
        affected = (
            [payment_id]
            + [row["row_id"] for row in outside]
            + [row["row_id"] for row in ar_rows]
        )
        issues.append(
            _issue(
                "period_cutoff",
                affected,
                _payment_base(episode, payment),
                base,
                [affected, [payment_id, outside[0]["row_id"]]],
                "The payment belongs to the reporting period but its posting sits "
                "outside the period boundary.",
            )
        )

    issues.sort(
        key=lambda issue: (
            issue["type"],
            tuple(issue["affected_ids"]),
            issue["expected_amount_minor"],
        )
    )
    for index, issue in enumerate(issues, start=1):
        issue["issue_id"] = deterministic_id("ISS", index, 4)
    return issues


def reference_findings(episode: Episode) -> dict[str, Any]:
    """Turn the reference audit into a valid oracle submission."""
    findings = []
    for issue in reference_audit(episode):
        evidence = []
        if issue["allowed_evidence_sets"]:
            evidence = issue["allowed_evidence_sets"][0][:10]
        findings.append(
            {
                "type": issue["type"],
                "affected_ids": list(issue["affected_ids"]),
                "claimed_amount_minor": issue["expected_amount_minor"],
                "currency": issue["currency"],
                "evidence_ids": evidence,
                "explanation": (
                    "Derived by reconciling open documents, ledger postings, the "
                    "FX table and the period policy."
                ),
            }
        )
    return {"episode_id": episode.manifest["episode_id"], "findings": findings}
