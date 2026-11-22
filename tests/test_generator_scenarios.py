"""Generator scenario knobs: gap_mode, composite_scenario, feature flags.

These tests pin the behaviour the official Genesis FinTech checklist requires
the team generator to expose through documented config settings:

* gap_mode: partial (default) | missing | mixed  -- full missing allocation
  must be independently selectable (D09-D11 need at least one missing).
* composite_scenario: alternate (default) | first | second | both
  -- a pure second documented interaction scenario must be selectable (D19-D20).
* split_payment / refund / recurring booleans -- probabilistic features must be
  disableable so D02/D03/D05-style cases are deterministic, not seed-dependent.
"""

from __future__ import annotations

import unittest

from letro.generator import generate_episode
from letro.generator.audit import _expected_allocation

AR = "1100"
CASH = "1000"
SUSPENSE = "9999"


def base_errors() -> dict[str, int]:
    return {
        "duplicate_invoice": 0,
        "payment_allocation_gap": 1,
        "fx_rate_error": 0,
        "period_cutoff": 0,
        "composite": 0,
    }


def base_config(overrides: dict | None = None, composite: int = 0) -> dict:
    config = {
        "sizes": {"invoices": 30, "payments": 30, "issues": 0, "ledger_rows": 250},
        "errors": dict(base_errors(), composite=composite),
        "clean": False,
        "mode": "train",
        "variant": 0,
    }
    if overrides:
        config.update(overrides)
    return config


class GeneratorScenarioTests(unittest.TestCase):
    def gap_payment_and_invoice(self, episode):
        gap_issues = [
            i for i in episode.truth["issues"]
            if i["type"] == "payment_allocation_gap"
        ]
        self.assertEqual(len(gap_issues), 1, episode.truth["issues"])
        issue = gap_issues[0]
        payment_id = issue["affected_ids"][0]
        payment = next(
            p for p in episode.payments if p["payment_id"] == payment_id
        )
        invoice = next(
            inv for inv in episode.invoices
            if inv["invoice_id"] == payment["invoice_refs"][0]
        )
        return issue, payment, invoice

    def ar_credit_for_payment(self, episode, payment_id):
        rows = [
            r for r in episode.ledger
            if r["payment_id"] == payment_id and r["account"] == AR
            and r["credit_minor"] > 0
        ]
        return sum(r["credit_minor"] for r in rows)

    def test_gap_mode_missing_full_allocation(self):
        """gap_mode=missing removes the entire AR allocation (D09-D11)."""
        episode = generate_episode(5, base_config({"gap_mode": "missing"}))
        issue, payment, invoice = self.gap_payment_and_invoice(episode)
        full = _expected_allocation(episode, invoice, payment)
        self.assertEqual(issue["expected_amount_minor"], full)
        self.assertEqual(self.ar_credit_for_payment(episode, payment["payment_id"]), 0)
        # The full missing amount must be posted to suspense.
        suspense = [
            r for r in episode.ledger
            if r["payment_id"] == payment["payment_id"] and r["account"] == SUSPENSE
        ]
        self.assertEqual(sum(r["credit_minor"] for r in suspense), full)

    def test_gap_mode_partial_reduces_by_forty_percent(self):
        """gap_mode=partial keeps current behaviour (default)."""
        episode = generate_episode(7, base_config({"gap_mode": "partial"}))
        issue, payment, invoice = self.gap_payment_and_invoice(episode)
        full = _expected_allocation(episode, invoice, payment)
        self.assertEqual(issue["expected_amount_minor"], max(1, int(full * 0.4)))
        self.assertGreater(self.ar_credit_for_payment(episode, payment["payment_id"]), 0)

    def test_gap_mode_mixed_is_partial_or_missing(self):
        """gap_mode=mixed produces either partial or missing."""
        seen = set()
        for seed in range(1, 6):
            episode = generate_episode(seed, base_config({"gap_mode": "mixed"}))
            issues = [i for i in episode.truth["issues"]
                      if i["type"] == "payment_allocation_gap"]
            if issues:
                issue = issues[0]
                full = _expected_allocation(
                    episode,
                    next(inv for inv in episode.invoices
                         if inv["invoice_id"] == issue["affected_ids"][1]),
                    next(p for p in episode.payments
                         if p["payment_id"] == issue["affected_ids"][0]),
                )
                if issue["expected_amount_minor"] == full:
                    seen.add("missing")
                else:
                    seen.add("partial")
        self.assertTrue(seen, "mixed should produce at least one gap issue")

    def test_composite_scenario_first_is_boundary_fx(self):
        """composite_scenario=first always uses boundary_fx composite."""
        episode = generate_episode(
            11, base_config(composite=1, overrides={"composite_scenario": "first"})
        )
        scopes = [s.get("scope", "") for s in episode.provenance["steps"]]
        self.assertTrue(any("boundary_fx" in s for s in scopes), scopes)

    def test_composite_scenario_second_is_gap_cutoff(self):
        """composite_scenario=second always uses gap_cutoff composite (D19-D20)."""
        episode = generate_episode(
            11, base_config(composite=1, overrides={"composite_scenario": "second"})
        )
        scopes = [s.get("scope", "") for s in episode.provenance["steps"]]
        self.assertTrue(any("gap_cutoff" in s for s in scopes), scopes)

    def test_composite_scenario_both_uses_each_once(self):
        """composite_scenario=both uses first then second when composite=2."""
        episode = generate_episode(
            11,
            base_config(composite=2, overrides={"composite_scenario": "both"}),
        )
        scopes = [s.get("scope", "") for s in episode.provenance["steps"]]
        self.assertIn("boundary_fx_payment", scopes)
        self.assertIn("gap_cutoff_payment", scopes)

    def test_split_payment_false_no_split_payments(self):
        """split_payment=false: no invoice is paid in two parts."""
        episode = generate_episode(
            13, base_config({"split_payment": False})
        )
        by_invoice: dict[str, int] = {}
        for payment in episode.payments:
            if payment["amount_minor"] > 0:
                ref = payment["invoice_refs"][0] if payment["invoice_refs"] else None
                if ref:
                    by_invoice[ref] = by_invoice.get(ref, 0) + 1
        self.assertTrue(all(count == 1 for count in by_invoice.values()),
                        f"split payments found: {by_invoice}")

    def test_refund_false_no_negative_payments(self):
        """refund=false: no negative payment amounts."""
        episode = generate_episode(13, base_config({"refund": False}))
        for payment in episode.payments:
            self.assertGreaterEqual(payment["amount_minor"], 0)

    def test_recurring_false_no_duplicate_expense_rows(self):
        """recurring=false: no duplicate identical expense amounts."""
        episode = generate_episode(13, base_config({"recurring": False}))
        expense_rows = [
            (r["account"], r["debit_minor"], r["timestamp"][:10])
            for r in episode.ledger if r["account"] == "5000"
        ]
        self.assertEqual(len(expense_rows), len(set(expense_rows)))

    def test_new_config_keys_are_accepted(self):
        """The new config keys must not raise 'unknown config key'."""
        episode = generate_episode(
            3, base_config({
                "gap_mode": "missing",
                "composite_scenario": "second",
                "split_payment": False,
                "refund": False,
                "recurring": False,
            })
        )
        self.assertIsInstance(episode.manifest["episode_id"], str)


if __name__ == "__main__":
    unittest.main()
