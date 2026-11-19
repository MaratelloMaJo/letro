"""Naive reconciliation baseline.

This is deliberately a simple auditor, not the reference solution. It pages
every open table, converts amounts with the published FX rates and applies four
straightforward rules:

1. an invoice with more than one receivable debit is reported as a duplicate;
2. a receivable debit that disagrees with the invoice-date rate is an FX error;
3. a document inside the period whose posting sits outside it is a cut-off;
4. **any invoice that still shows an open balance is reported as an
   unallocated payment**, with the remaining balance as the amount.

Rule 4 is the deliberate simplification. Real books legitimately contain open
and part-paid invoices, and a true allocation gap belongs to one payment rather
than to the invoice balance. The baseline therefore over-reports clean companies
and mis-states the amount behind a part-paid invoice. ``ThoroughPolicy`` keeps
the exact reference arithmetic for comparison.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from ..constants import TABLES
from ..money import convert_minor
from .base import Policy, inside, rate_for, sorted_rate_lookup

AR = "1100"
REVENUE = "4000"
CASH = "1000"


class ReconciliationPolicy(Policy):
    name = "reconciliation"

    def __init__(self) -> None:
        self.reset({}, {})

    def reset(self, observation: dict[str, Any], info: dict[str, Any]) -> None:
        self._tables: dict[str, list[dict[str, Any]]] = {name: [] for name in TABLES}
        self._order = list(TABLES)
        self._table_index = 0
        self._cursor = 0
        self._pending_table: str | None = None
        self._episode_id = str(info.get("episode_id", ""))
        self._manifest: dict[str, Any] | None = None
        self._policy: dict[str, Any] = {}
        self._submitted = False
        self._collected = False

    # ------------------------------------------------------------------ loop
    def act(self, observation: dict[str, Any]) -> dict[str, Any]:
        if self._manifest is None and "manifest" in observation:
            self._manifest = observation["manifest"]
        if not self._policy and "policy_summary" in observation:
            self._policy = dict(observation["policy_summary"])

        last = observation.get("last_result")
        if last is not None:
            if last.get("ok") and last.get("action") == "list_records":
                result = last.get("result") or {}
                table = self._pending_table
                if table in self._tables:
                    self._tables[table].extend(result.get("rows", []))
                    next_cursor = result.get("next_cursor")
                    if next_cursor is None:
                        self._advance_table()
                    else:
                        self._cursor = int(next_cursor)
            elif not last.get("ok") and self._pending_table is not None:
                self._advance_table()

        if self._collected:
            return self._submit()
        table = self._order[self._table_index] if self._table_index < len(self._order) else None
        if table is None:
            self._collected = True
            return self._submit()
        self._pending_table = table
        return {
            "type": "list_records",
            "table": table,
            "cursor": self._cursor,
            "limit": 50,
        }

    def _advance_table(self) -> None:
        self._table_index += 1
        self._cursor = 0
        self._pending_table = None
        if self._table_index >= len(self._order):
            self._collected = True

    # -------------------------------------------------------------- analysis
    def _submit(self) -> dict[str, Any]:
        if self._submitted:
            return {
                "type": "submit",
                "findings": {"episode_id": self._episode_id, "findings": []},
            }
        self._submitted = True
        return {
            "type": "submit",
            "findings": {
                "episode_id": self._episode_id,
                "findings": self._findings()[:30],
            },
        }

    def _findings(self) -> list[dict[str, Any]]:
        if self._manifest is None:
            return []
        base = self._manifest["base_currency"]
        start = self._manifest["period_start"]
        end = self._manifest["period_end"]
        tolerance = int(self._policy.get("amount_tolerance_minor", 1))
        ledger = self._tables["ledger"]
        invoices = {item["invoice_id"]: item for item in self._tables["invoices"]}
        payments = {item["payment_id"]: item for item in self._tables["payments"]}
        rates = sorted_rate_lookup(self._tables["fx"])

        def rate(currency: str, day: str) -> Decimal:
            return rate_for(rates, currency, base, day)

        def invoice_base(invoice: dict[str, Any]) -> int:
            return convert_minor(
                invoice["total_minor"],
                rate(invoice["currency"], invoice["issued_at"][:10]),
                invoice["currency"],
                base,
            )

        def payment_base(payment: dict[str, Any]) -> int:
            return convert_minor(
                abs(payment["amount_minor"]),
                rate(payment["currency"], payment["timestamp"][:10]),
                payment["currency"],
                base,
            )

        def evidence(values: list[str]) -> list[str]:
            unique = list(dict.fromkeys(value for value in values if value))
            return unique[:10]

        def build(
            kind: str,
            affected: list[str],
            amount: int,
            allowed: list[list[str]],
            explanation: str,
        ) -> dict[str, Any]:
            sets = []
            for item in allowed:
                cleaned = evidence(item)
                if cleaned and cleaned not in sets:
                    sets.append(cleaned)
            return {
                "type": kind,
                "affected_ids": list(dict.fromkeys(affected)),
                "claimed_amount_minor": int(amount),
                "currency": base,
                "evidence_ids": sets[0] if sets else [],
                "explanation": explanation,
            }

        findings: list[dict[str, Any]] = []

        # 1. Duplicate invoice postings.
        for invoice_id, invoice in invoices.items():
            ar_rows = [
                row
                for row in ledger
                if row["invoice_id"] == invoice_id
                and row["account"] == AR
                and row["debit_minor"] > 0
            ]
            ar_rows.sort(key=lambda row: (row["timestamp"], row["row_id"]))
            if len(ar_rows) <= 1:
                continue
            revenue_rows = [
                row
                for row in ledger
                if row["invoice_id"] == invoice_id
                and row["account"] == REVENUE
                and row["credit_minor"] > 0
            ]
            revenue_rows.sort(key=lambda row: (row["timestamp"], row["row_id"]))
            extra = ar_rows[1]
            affected = (
                [invoice_id]
                + [row["row_id"] for row in ar_rows]
                + [row["row_id"] for row in revenue_rows]
            )
            findings.append(
                build(
                    "duplicate_invoice",
                    affected,
                    extra["debit_minor"],
                    [affected, [invoice_id, extra["row_id"]]],
                    "The invoice is posted more than once; the extra entry "
                    "inflates receivables and revenue.",
                )
            )

        # 2. Naive rule: every open invoice balance looks like a gap.
        for invoice_id, invoice in invoices.items():
            ar_rows = [
                row
                for row in ledger
                if row["invoice_id"] == invoice_id
                and row["account"] == AR
                and row["debit_minor"] > 0
            ]
            credits = sum(
                row["credit_minor"]
                for row in ledger
                if row["invoice_id"] == invoice_id and row["account"] == AR
            )
            balance = invoice_base(invoice) - credits
            if balance <= tolerance:
                continue
            cash_rows = [
                row
                for row in ledger
                if row["invoice_id"] == invoice_id and row["account"] == CASH
            ]
            affected = (
                [invoice_id]
                + [row["row_id"] for row in cash_rows]
                + [row["row_id"] for row in ar_rows]
            )
            findings.append(
                build(
                    "payment_allocation_gap",
                    affected,
                    balance,
                    [affected, [invoice_id]],
                    "The invoice still shows an open balance; part of the "
                    "receipt looks unallocated.",
                )
            )

        # 3. FX conversion mismatches.
        for invoice_id, invoice in invoices.items():
            expected = invoice_base(invoice)
            for row in ledger:
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
                    for other in ledger
                    if other["invoice_id"] == invoice_id
                    and other["account"] == REVENUE
                    and other["timestamp"] == row["timestamp"]
                ]
                affected = [invoice_id, row["row_id"]] + [
                    other["row_id"] for other in revenue_rows
                ]
                findings.append(
                    build(
                        "fx_rate_error",
                        affected,
                        delta,
                        [affected, [invoice_id, row["row_id"]]],
                        "The posted base amount does not match the invoice-date "
                        "rate required by the policy.",
                    )
                )

        for payment_id, payment in payments.items():
            if payment["amount_minor"] <= 0:
                continue
            expected = payment_base(payment)
            cash_rows = [
                row
                for row in ledger
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
                    for other in ledger
                    if other["payment_id"] == payment_id and other["account"] == "4900"
                ]
                ar_rows = [
                    other
                    for other in ledger
                    if other["payment_id"] == payment_id and other["account"] == AR
                ]
                affected = (
                    [payment_id, row["row_id"]]
                    + [other["row_id"] for other in fx_rows]
                    + [other["row_id"] for other in ar_rows]
                )
                findings.append(
                    build(
                        "fx_rate_error",
                        affected,
                        delta,
                        [affected, [payment_id, row["row_id"]]],
                        "The cash receipt was converted at a rate that does not "
                        "match the payment-date policy.",
                    )
                )

        # 4. Reporting-period cut-off.
        for invoice_id, invoice in invoices.items():
            if not inside(start, end, invoice["issued_at"]):
                continue
            ar_rows = [
                row
                for row in ledger
                if row["invoice_id"] == invoice_id
                and row["account"] == AR
                and row["debit_minor"] > 0
            ]
            outside = [row for row in ar_rows if not inside(start, end, row["timestamp"])]
            if not outside:
                continue
            revenue_rows = [
                row
                for row in ledger
                if row["invoice_id"] == invoice_id
                and row["account"] == REVENUE
                and row["timestamp"] == outside[0]["timestamp"]
            ]
            affected = (
                [invoice_id]
                + [row["row_id"] for row in outside]
                + [row["row_id"] for row in revenue_rows]
            )
            findings.append(
                build(
                    "period_cutoff",
                    affected,
                    invoice_base(invoice),
                    [affected, [invoice_id, outside[0]["row_id"]]],
                    "The invoice belongs to the period but its posting sits "
                    "outside the period boundary.",
                )
            )

        for payment_id, payment in payments.items():
            if payment["amount_minor"] <= 0:
                continue
            if not inside(start, end, payment["timestamp"]):
                continue
            cash_rows = [
                row
                for row in ledger
                if row["payment_id"] == payment_id
                and row["account"] == CASH
                and row["debit_minor"] > 0
            ]
            outside = [row for row in cash_rows if not inside(start, end, row["timestamp"])]
            if not outside:
                continue
            ar_rows = [
                row for row in ledger if row["payment_id"] == payment_id and row["account"] == AR
            ]
            affected = (
                [payment_id]
                + [row["row_id"] for row in outside]
                + [row["row_id"] for row in ar_rows]
            )
            findings.append(
                build(
                    "period_cutoff",
                    affected,
                    payment_base(payment),
                    [affected, [payment_id, outside[0]["row_id"]]],
                    "The payment belongs to the period but its posting sits "
                    "outside the period boundary.",
                )
            )

        unique: list[dict[str, Any]] = []
        seen: set[tuple[Any, ...]] = set()
        for finding in findings:
            key = (
                finding["type"],
                tuple(finding["affected_ids"]),
                finding["claimed_amount_minor"],
            )
            if key in seen:
                continue
            seen.add(key)
            unique.append(finding)
        return unique
