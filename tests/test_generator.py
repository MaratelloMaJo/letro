"""Generator invariants: balance, determinism, truth and evidence."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from letro.generator import (
    generate_episode,
    load_episode,
    reference_audit,
    write_episode,
)
from tests.support import config, episode, errors


def digest(ep) -> str:
    payload = json.dumps(
        {
            "manifest": ep.manifest,
            "ledger": ep.ledger,
            "invoices": ep.invoices,
            "payments": ep.payments,
            "fx": ep.fx,
            "truth": ep.truth,
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def balanced(ep) -> tuple[int, int]:
    return (
        sum(row["debit_minor"] for row in ep.ledger),
        sum(row["credit_minor"] for row in ep.ledger),
    )


class GeneratorTests(unittest.TestCase):
    def test_same_seed_is_identical(self):
        left = generate_episode(41, config(error_counts=errors(duplicate=1, fx=1)))
        right = generate_episode(41, config(error_counts=errors(duplicate=1, fx=1)))
        self.assertEqual(digest(left), digest(right))

    def test_clean_books_have_no_issues(self):
        ep = episode(42, config(clean=True))
        self.assertEqual(ep.truth["issues"], [])
        self.assertEqual(reference_audit(ep), [])
        self.assertEqual(balanced(ep)[0], balanced(ep)[1])

    def test_each_error_type_is_independent(self):
        short = {
            "duplicate_invoice": "duplicate",
            "payment_allocation_gap": "gap",
            "fx_rate_error": "fx",
            "period_cutoff": "cutoff",
        }
        for kind in (
            "duplicate_invoice",
            "payment_allocation_gap",
            "fx_rate_error",
            "period_cutoff",
        ):
            with self.subTest(kind=kind):
                counts = errors(**{short[kind]: 1})
                ep = generate_episode(43, config(error_counts=counts))
                self.assertEqual([issue["type"] for issue in ep.truth["issues"]], [kind])
                self.assertEqual(
                    sorted(map(str, reference_audit(ep))),
                    sorted(map(str, ep.truth["issues"])),
                )

    def test_composite_has_two_interacting_issues(self):
        ep = generate_episode(44, config(error_counts=errors(composite=1)))
        self.assertEqual(len(ep.truth["issues"]), 2)
        self.assertLessEqual(
            {issue["type"] for issue in ep.truth["issues"]},
            {"fx_rate_error", "period_cutoff", "payment_allocation_gap"},
        )

    def test_ledger_stays_balanced_after_injection(self):
        ep = generate_episode(
            45,
            config(error_counts=errors(duplicate=1, gap=1, fx=1, cutoff=1, composite=1)),
        )
        debits, credits = balanced(ep)
        self.assertEqual(debits, credits)
        groups: dict[tuple, list[int]] = {}
        for row in ep.ledger:
            key = (row["timestamp"], row["entity_id"], row["invoice_id"], row["payment_id"])
            pair = groups.setdefault(key, [0, 0])
            pair[0] += row["debit_minor"]
            pair[1] += row["credit_minor"]
        self.assertTrue(all(debit == credit for debit, credit in groups.values()))

    def test_truth_evidence_resolves_in_open_data(self):
        ep = episode(46)
        valid = {row["row_id"] for row in ep.ledger}
        for invoice in ep.invoices:
            valid.update((invoice["invoice_id"], invoice["doc_id"]))
        for payment in ep.payments:
            valid.update((payment["payment_id"], payment["doc_id"]))
        for issue in ep.truth["issues"]:
            self.assertTrue(issue["allowed_evidence_sets"])
            self.assertTrue(any(set(values) <= valid for values in issue["allowed_evidence_sets"]))
            self.assertTrue(set(issue["affected_ids"]) <= valid)

    def test_open_files_round_trip(self):
        ep = episode(47)
        with tempfile.TemporaryDirectory() as directory:
            write_episode(ep, directory)
            loaded = load_episode(Path(directory))
        self.assertEqual(loaded.manifest, ep.manifest)
        self.assertEqual(loaded.truth, ep.truth)
        self.assertEqual(loaded.ledger, ep.ledger)
        self.assertEqual(loaded.invoices, ep.invoices)
        self.assertEqual(loaded.payments, ep.payments)

    def test_counts_and_limits(self):
        ep = episode(48)
        self.assertEqual(ep.manifest["ledger_rows"], len(ep.ledger))
        self.assertEqual(
            ep.manifest["documents"], len(ep.invoices) + len(ep.payments)
        )
        self.assertGreaterEqual(len(ep.ledger), 200)
        self.assertLessEqual(len(ep.ledger), 2000)
        self.assertGreaterEqual(len(ep.invoices) + len(ep.payments), 20)


if __name__ == "__main__":
    unittest.main()
