"""Independent invariant checks over a generated episode.

The checks here are intentionally written without importing ``letro.verify`` so
that the fuzz harness and the verifier are two independent readers of the same
contract. They answer the question a jury asks: are the books balanced, does the
declared truth match an audit of the open records, and can every evidence set be
resolved and re-derived from those records?
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .constants import AMOUNT_TOLERANCE_MINOR, CURRENCY_DECIMALS, ERROR_TYPES
from .generator.audit import reference_audit
from .generator.model import entry_balanced
from .schema import validate_config, validate_manifest, validate_truth


def _signature(issue: dict[str, Any]) -> tuple[str, tuple[str, ...], int, str]:
    return (
        issue["type"],
        tuple(sorted(issue["affected_ids"])),
        int(issue["expected_amount_minor"]),
        issue["currency"],
    )


def _expected_count(config: dict[str, Any]) -> int:
    resolved = validate_config(config)
    if resolved["clean"]:
        return 0
    errors = resolved["errors"]
    return (
        errors["duplicate_invoice"]
        + errors["payment_allocation_gap"]
        + errors["fx_rate_error"]
        + errors["period_cutoff"]
        + 2 * errors["composite"]
    )


def _iso_with_offset(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _open_ids(episode: Any) -> set[str]:
    ids = {row["row_id"] for row in episode.ledger}
    for invoice in episode.invoices:
        ids.add(invoice["invoice_id"])
        ids.add(invoice["doc_id"])
    for payment in episode.payments:
        ids.add(payment["payment_id"])
        ids.add(payment["doc_id"])
    return ids


def _balance(episode: Any) -> list[str]:
    problems: list[str] = []
    debits = sum(row["debit_minor"] for row in episode.ledger)
    credits = sum(row["credit_minor"] for row in episode.ledger)
    if debits != credits:
        problems.append(f"ledger is out of balance by {debits - credits} minor units")
    groups: dict[tuple[Any, ...], list[int]] = {}
    for row in episode.ledger:
        key = (
            row["timestamp"],
            row["entity_id"],
            row["invoice_id"],
            row["payment_id"],
        )
        pair = groups.setdefault(key, [0, 0])
        pair[0] += row["debit_minor"]
        pair[1] += row["credit_minor"]
    for key, (debit, credit) in groups.items():
        if debit != credit:
            problems.append(
                f"journal group {key[0]} is out of balance by {debit - credit}"
            )
    return problems


def _evidence(episode: Any, issue: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    ledger = {row["row_id"]: row for row in episode.ledger}
    invoices = {item["invoice_id"]: item for item in episode.invoices}
    payments = {item["payment_id"]: item for item in episode.payments}
    start = datetime.fromisoformat(episode.manifest["period_start"])
    end = datetime.fromisoformat(episode.manifest["period_end"])
    kind = issue["type"]
    for values in issue.get("allowed_evidence_sets", []):
        ids = list(values)
        if kind == "duplicate_invoice":
            invoice_ids = [value for value in ids if value in invoices]
            ar_rows = [
                value
                for value in ids
                if value in ledger
                and ledger[value]["account"] == "1100"
                and ledger[value]["debit_minor"] > 0
                and invoice_ids
                and ledger[value]["invoice_id"] == invoice_ids[0]
            ]
            if invoice_ids and len(set(ar_rows)) >= 2:
                return []
        elif kind == "payment_allocation_gap":
            has_payment = any(value in payments for value in ids)
            has_invoice = any(value in invoices for value in ids)
            has_ar = any(
                value in ledger
                and ledger[value]["account"] == "1100"
                and ledger[value]["credit_minor"] > 0
                for value in ids
            )
            has_cash = any(
                value in ledger
                and ledger[value]["account"] == "1000"
                and ledger[value]["debit_minor"] > 0
                for value in ids
            )
            if has_payment and has_invoice and has_ar and has_cash:
                return []
        elif kind == "fx_rate_error":
            has_doc = any(value in invoices or value in payments for value in ids)
            has_amount = any(
                value in ledger
                and (ledger[value]["debit_minor"] or ledger[value]["credit_minor"])
                for value in ids
            )
            if has_doc and has_amount:
                return []
        elif kind == "period_cutoff":
            has_doc = any(value in invoices or value in payments for value in ids)
            has_outside = False
            for value in ids:
                row = ledger.get(value)
                if row is None:
                    continue
                moment = datetime.fromisoformat(row["timestamp"])
                if not (start <= moment <= end):
                    has_outside = True
            if has_doc and has_outside:
                return []
    problems.append(f"{issue['issue_id']} ({kind}) evidence is not sufficient")
    return problems


def check_episode(
    episode: Any, config: dict[str, Any] | None = None
) -> list[str]:
    """Return a list of contract violations; an empty list means the episode is valid."""
    problems: list[str] = []
    try:
        validate_manifest(episode.manifest)
    except Exception as exc:
        problems.append(f"manifest: {exc}")
    try:
        validate_truth(episode.truth)
    except Exception as exc:
        problems.append(f"truth: {exc}")
    if episode.manifest.get("episode_id") != episode.truth.get("episode_id"):
        problems.append("manifest and truth episode_id differ")
    if episode.manifest.get("ledger_rows") != len(episode.ledger):
        problems.append("manifest ledger_rows does not match the ledger")
    documents = len(episode.invoices) + len(episode.payments)
    if episode.manifest.get("documents") != documents:
        problems.append("manifest documents does not match the files")

    problems.extend(_balance(episode))

    ids: set[str] = set()
    for table, values, key in (
        ("ledger", episode.ledger, "row_id"),
        ("invoices", episode.invoices, "invoice_id"),
        ("payments", episode.payments, "payment_id"),
    ):
        for row in values:
            value = row.get(key)
            if value in ids:
                problems.append(f"duplicate id {value} in {table}")
            ids.add(value)
    valid = _open_ids(episode)
    for row in episode.ledger:
        if not _iso_with_offset(row.get("timestamp")):
            problems.append(f"{row.get('row_id')} timestamp lacks an offset")
        if not isinstance(row.get("debit_minor"), int) or not isinstance(
            row.get("credit_minor"), int
        ):
            problems.append(f"{row.get('row_id')} money is not integer minor units")
        if row.get("currency") not in CURRENCY_DECIMALS:
            problems.append(f"{row.get('row_id')} has an unknown currency")
        if row.get("invoice_id") is not None and row["invoice_id"] not in valid:
            problems.append(f"{row['row_id']} references an unknown invoice")
        if row.get("payment_id") is not None and row["payment_id"] not in valid:
            problems.append(f"{row['row_id']} references an unknown payment")

    if not _iso_with_offset(episode.manifest.get("period_start")):
        problems.append("period_start lacks an offset")
    if not _iso_with_offset(episode.manifest.get("period_end")):
        problems.append("period_end lacks an offset")

    issues = list(episode.truth.get("issues", []))
    if config is not None:
        expected = _expected_count(config)
        if len(issues) != expected:
            problems.append(f"truth has {len(issues)} issues, configured {expected}")
    for issue in issues:
        if issue.get("type") not in ERROR_TYPES:
            problems.append(f"{issue.get('issue_id')} has an unknown type")
        if int(issue.get("expected_amount_minor", 0)) <= AMOUNT_TOLERANCE_MINOR:
            problems.append(f"{issue.get('issue_id')} amount is not material")
        if not set(issue.get("affected_ids", [])) <= valid:
            problems.append(f"{issue.get('issue_id')} has unknown affected ids")
        sets = issue.get("allowed_evidence_sets") or []
        if not sets:
            problems.append(f"{issue.get('issue_id')} has no evidence set")
        elif not any(
            values and len(values) <= 10 and set(values) <= valid for values in sets
        ):
            problems.append(f"{issue.get('issue_id')} evidence does not resolve")
        else:
            problems.extend(_evidence(episode, issue))

    try:
        recomputed = reference_audit(episode)
    except Exception as exc:
        problems.append(f"reference audit crashed: {exc}")
    else:
        if sorted(map(_signature, recomputed)) != sorted(map(_signature, issues)):
            problems.append("independent audit does not reproduce truth")
    return problems


def check_clean_baseline(episode: Any, seed: int, config: dict[str, Any]) -> list[str]:
    """Re-build the company before injection and check every journal entry balances."""
    from .generator.company import build_company

    clean = build_company(seed, validate_config(config))
    by_id = {row["row_id"]: row for row in clean.ledger}
    problems = []
    for entry in clean.entries:
        rows = [by_id[row_id] for row_id in entry if row_id in by_id]
        if not entry_balanced(rows):
            problems.append("a pre-injection journal entry is not balanced")
    return problems


__all__ = ["check_clean_baseline", "check_episode"]
