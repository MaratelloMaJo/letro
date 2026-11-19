"""Matcher semantics: one-to-one, canonical ids, evidence and tolerance."""

from __future__ import annotations

import copy
import math
import unittest

from letro.generator import reference_findings
from letro.matcher import finding_matches, score
from tests.support import episode, payload


class MatcherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ep = episode(51)
        cls.issues = cls.ep.truth["issues"]
        cls.findings = reference_findings(cls.ep)["findings"]

    def test_oracle_answer(self):
        result = score(self.ep.truth, payload(self.ep, self.findings))
        self.assertEqual(result.tp, len(self.issues))
        self.assertEqual(result.fp, 0)
        self.assertEqual(result.fn, 0)
        self.assertEqual(result.f1, 1.0)

    def test_duplicate_finding_is_false_positive(self):
        doubled = [copy.deepcopy(self.findings[0]), copy.deepcopy(self.findings[0])]
        result = score(self.ep.truth, payload(self.ep, doubled))
        self.assertEqual((result.tp, result.fp, result.fn), (1, 1, len(self.issues) - 1))
        self.assertTrue(math.isclose(result.f1, 2 / (len(self.issues) + 2)))

    def test_affected_ids_are_canonical(self):
        altered = copy.deepcopy(self.findings[0])
        altered["affected_ids"].append("LED-999999")
        self.assertFalse(finding_matches(altered, self.issues[0]))
        altered = copy.deepcopy(self.findings[0])
        altered["affected_ids"] = altered["affected_ids"][:-1]
        self.assertFalse(finding_matches(altered, self.issues[0]))

    def test_evidence_must_be_complete_but_may_be_a_superset(self):
        altered = copy.deepcopy(self.findings[0])
        altered["evidence_ids"] = []
        self.assertFalse(finding_matches(altered, self.issues[0]))
        altered = copy.deepcopy(self.findings[0])
        altered["evidence_ids"] = altered["evidence_ids"] + ["LED-999999"]
        self.assertTrue(finding_matches(altered, self.issues[0]))

    def test_amount_tolerance(self):
        altered = copy.deepcopy(self.findings[0])
        altered["claimed_amount_minor"] += 1
        self.assertTrue(finding_matches(altered, self.issues[0]))
        altered["claimed_amount_minor"] += 1
        self.assertFalse(finding_matches(altered, self.issues[0]))

    def test_currency_and_type(self):
        altered = copy.deepcopy(self.findings[0])
        altered["currency"] = "USD" if altered["currency"] != "USD" else "EUR"
        self.assertFalse(finding_matches(altered, self.issues[0]))
        altered = copy.deepcopy(self.findings[0])
        altered["type"] = "period_cutoff" if altered["type"] != "period_cutoff" else "fx_rate_error"
        self.assertFalse(finding_matches(altered, self.issues[0]))

    def test_empty_semantics(self):
        clean = episode(52, {"clean": True})
        result = score(clean.truth, payload(clean, []))
        self.assertEqual((result.tp, result.fp, result.fn, result.f1), (0, 0, 0, 1.0))
        result = score(clean.truth, payload(clean, self.findings[:1]))
        self.assertEqual(result.f1, 0.0)

    def test_metrics_formula(self):
        result = score(self.ep.truth, payload(self.ep, self.findings[:2]))
        expected = 2 * result.tp / (2 * result.tp + result.fp + result.fn)
        self.assertTrue(math.isclose(result.f1, expected))
        self.assertTrue(math.isclose(result.precision, result.tp / (result.tp + result.fp)))
        self.assertTrue(math.isclose(result.recall, result.tp / (result.tp + result.fn)))


if __name__ == "__main__":
    unittest.main()
