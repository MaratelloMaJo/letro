"""Official Block 3 matcher, limits and reward conventions."""

from __future__ import annotations

import unittest

from letro.matcher import score
from letro.reward import terminal_reward
from letro.schema import FindingError, validate_findings_payload_strict

AVAILABLE = {"R1", "R2", "R3", "D1", "D2", "D3"}


def issue(
    issue_id="A",
    kind="duplicate_invoice",
    affected=("R1", "R2"),
    amount=10000,
    currency="KZT",
    evidence=(("D1", "D2"),),
):
    return {
        "issue_id": issue_id,
        "type": kind,
        "affected_ids": list(affected),
        "expected_amount_minor": amount,
        "currency": currency,
        "allowed_evidence_sets": [list(item) for item in evidence],
        "explanation": "reference issue",
    }


def finding(
    kind="duplicate_invoice",
    affected=("R1", "R2"),
    amount=10000,
    currency="KZT",
    evidence=("D1", "D2"),
    explanation="duplicate invoice posted twice",
):
    return {
        "type": kind,
        "affected_ids": list(affected),
        "claimed_amount_minor": amount,
        "currency": currency,
        "evidence_ids": list(evidence),
        "explanation": explanation,
    }


def run(truth, findings, *, tolerance=0, steps=10):
    result = score(
        {"issues": truth},
        {"findings": findings},
        tolerance,
        strict=True,
        available_evidence=AVAILABLE,
    )
    return result, terminal_reward(result.f1, steps, exact=True)


class OfficialMatcherTests(unittest.TestCase):
    def test_01_single_correct_finding(self):
        result, reward = run([issue()], [finding()])
        self.assertEqual((result.tp, result.fp, result.fn), (1, 0, 0))
        self.assertEqual((result.precision, result.recall, result.f1), (1.0, 1.0, 1.0))
        self.assertAlmostEqual(reward, 0.98, delta=1e-9)

    def test_02_empty_findings(self):
        result, reward = run([issue()], [])
        self.assertEqual((result.tp, result.fp, result.fn), (0, 0, 1))
        self.assertEqual((result.precision, result.recall, result.f1), (0.0, 0.0, 0.0))
        self.assertAlmostEqual(reward, -1.0, delta=1e-9)

    def test_03_empty_truth_and_empty_findings(self):
        result, reward = run([], [])
        self.assertEqual((result.tp, result.fp, result.fn), (0, 0, 0))
        self.assertEqual((result.precision, result.recall, result.f1), (0.0, 0.0, 1.0))
        self.assertAlmostEqual(reward, 0.98, delta=1e-9)

    def test_04_empty_truth_with_false_finding(self):
        result, reward = run([], [finding()])
        self.assertEqual((result.tp, result.fp, result.fn), (0, 1, 0))
        self.assertEqual(result.f1, 0.0)
        self.assertAlmostEqual(reward, -1.0, delta=1e-9)

    def test_05_duplicate_finding_is_false_positive(self):
        result, reward = run([issue()], [finding(), finding()])
        self.assertEqual((result.tp, result.fp, result.fn), (1, 1, 0))
        self.assertEqual(result.precision, 0.5)
        self.assertEqual(result.recall, 1.0)
        self.assertAlmostEqual(result.f1, 2 / 3, delta=1e-9)
        self.assertAlmostEqual(reward, 47 / 150, delta=1e-9)
        self.assertLess(reward, 0.98)

    def test_06_wrong_type_is_false_positive(self):
        result, reward = run([issue()], [finding(kind="period_cutoff")])
        self.assertEqual((result.tp, result.fp, result.fn), (0, 1, 1))
        self.assertEqual(result.f1, 0.0)
        self.assertAlmostEqual(reward, -1.0, delta=1e-9)

    def test_07_existing_unaffected_record_is_false_positive(self):
        result, _reward = run([issue()], [finding(affected=("R1", "R2", "R3"))])
        self.assertEqual((result.tp, result.fp, result.fn), (0, 1, 1))

    def test_08_amount_off_by_one_with_zero_tolerance(self):
        result, _reward = run([issue()], [finding(amount=10001)])
        self.assertEqual((result.tp, result.fp, result.fn), (0, 1, 1))

    def test_09_wrong_currency_is_false_positive(self):
        result, _reward = run([issue()], [finding(currency="USD")])
        self.assertEqual((result.tp, result.fp, result.fn), (0, 1, 1))

    def test_10_incomplete_evidence_is_false_positive(self):
        result, _reward = run([issue()], [finding(evidence=("D1",))])
        self.assertEqual((result.tp, result.fp, result.fn), (0, 1, 1))

    def test_11_missing_evidence_replaced_by_unknown_is_false_positive(self):
        result, _reward = run([issue()], [finding(evidence=("D1", "U"))])
        self.assertEqual((result.tp, result.fp, result.fn), (0, 1, 1))

    def test_12_mass_marking_attack(self):
        records = ["R1", "R2", "R3", "R4", "R5"]
        kinds = [
            "duplicate_invoice",
            "payment_allocation_gap",
            "fx_rate_error",
            "period_cutoff",
        ]
        findings = [
            finding(kind=kind, affected=(record,))
            for record in records
            for kind in kinds
        ]
        result, reward = run([issue(affected=("R1",))], findings)
        self.assertEqual((result.tp, result.fp, result.fn), (1, 19, 0))
        self.assertAlmostEqual(result.precision, 1 / 20, delta=1e-12)
        self.assertEqual(result.recall, 1.0)
        self.assertAlmostEqual(result.f1, 2 / 21, delta=1e-12)
        self.assertAlmostEqual(reward, -871 / 1050, delta=1e-9)

    def test_13_two_errors_one_correct(self):
        result, reward = run(
            [issue("A", affected=("R1",)), issue("B", affected=("R2",))],
            [finding(affected=("R1",))],
        )
        self.assertEqual((result.tp, result.fp, result.fn), (1, 0, 1))
        self.assertAlmostEqual(result.f1, 2 / 3, delta=1e-9)
        self.assertAlmostEqual(reward, 47 / 150, delta=1e-9)

    def test_14_two_errors_one_correct_one_false(self):
        result, reward = run(
            [issue("A", affected=("R1",)), issue("B", affected=("R2",))],
            [finding(affected=("R1",)), finding(affected=("R3",))],
        )
        self.assertEqual((result.tp, result.fp, result.fn), (1, 1, 1))
        self.assertEqual((result.precision, result.recall, result.f1), (0.5, 0.5, 0.5))
        self.assertAlmostEqual(reward, -0.02, delta=1e-9)

    def test_15_zero_inspection_steps(self):
        result, reward = run([issue()], [finding()], steps=0)
        self.assertEqual(result.f1, 1.0)
        self.assertAlmostEqual(reward, 1.0, delta=1e-9)

    def test_16_fifty_inspection_steps(self):
        result, reward = run([issue()], [finding()], steps=50)
        self.assertEqual(result.f1, 1.0)
        self.assertAlmostEqual(reward, 0.90, delta=1e-9)

    def test_17_hundred_inspection_steps(self):
        result, reward = run([issue()], [finding()], steps=100)
        self.assertEqual(result.f1, 1.0)
        self.assertAlmostEqual(reward, 0.80, delta=1e-9)

    def test_18_too_many_findings_is_structural_error(self):
        payload = {
            "episode_id": "e",
            "findings": [finding()] * 31,
        }
        with self.assertRaises(FindingError):
            validate_findings_payload_strict(payload)

    def test_19_too_many_evidence_ids_is_structural_error(self):
        payload = {
            "episode_id": "e",
            "findings": [finding(evidence=("D1",) * 11)],
        }
        with self.assertRaises(FindingError):
            validate_findings_payload_strict(payload)

    def test_20_explanation_over_limit_is_structural_error(self):
        payload = {
            "episode_id": "e",
            "findings": [finding(explanation="x" * 1001)],
        }
        with self.assertRaises(FindingError):
            validate_findings_payload_strict(payload)


class OfficialOpenExampleTests(unittest.TestCase):
    def test_m01_affected_repeats_are_a_set(self):
        result, _reward = run([issue()], [finding(affected=("R2", "R1", "R1"))])
        self.assertEqual((result.tp, result.fp, result.fn), (1, 0, 0))

    def test_m02_existing_unaffected_id_breaks_the_set(self):
        result, _reward = run([issue()], [finding(affected=("R1", "R2", "R3"))])
        self.assertEqual((result.tp, result.fp, result.fn), (0, 1, 1))

    def test_m03_extra_available_evidence_is_allowed(self):
        result, _reward = run([issue()], [finding(evidence=("D2", "D1", "D3"))])
        self.assertEqual((result.tp, result.fp, result.fn), (1, 0, 0))

    def test_m04_extra_unavailable_evidence_breaks_the_match(self):
        result, _reward = run([issue()], [finding(evidence=("D1", "D2", "U"))])
        self.assertEqual((result.tp, result.fp, result.fn), (0, 1, 1))

    def test_m05_evidence_limit_is_checked_before_deduplication(self):
        payload = {
            "episode_id": "e",
            "findings": [finding(evidence=("D1",) * 11)],
        }
        with self.assertRaises(FindingError):
            validate_findings_payload_strict(payload)

    def test_m06_currency_is_case_sensitive(self):
        result, _reward = run([issue()], [finding(currency="kzt")])
        self.assertEqual((result.tp, result.fp, result.fn), (0, 1, 1))

    def test_m07_zero_tolerance_by_default(self):
        result, _reward = run([issue()], [finding(amount=10001)])
        self.assertEqual((result.tp, result.fp, result.fn), (0, 1, 1))

    def test_m08_public_tolerance_boundary(self):
        result, _reward = run([issue()], [finding(amount=10001)], tolerance=1)
        self.assertEqual((result.tp, result.fp, result.fn), (1, 0, 0))
        result, _reward = run([issue()], [finding(amount=10002)], tolerance=1)
        self.assertEqual((result.tp, result.fp, result.fn), (0, 1, 1))

    def test_m09_money_must_be_json_integer(self):
        for amount in ("10000", True):
            payload = {
                "episode_id": "e",
                "findings": [finding(amount=amount)],
            }
            with self.assertRaises(FindingError):
                validate_findings_payload_strict(payload)

    def test_m10_maximum_matching_not_greedy(self):
        truth = [
            issue("A", affected=("R1",), evidence=(("D1",),)),
            issue("B", affected=("R1",), evidence=(("D2",),)),
        ]
        findings = [
            finding(affected=("R1",), evidence=("D1", "D2")),
            finding(affected=("R1",), evidence=("D1",)),
        ]
        result, _reward = run(truth, findings)
        self.assertEqual((result.tp, result.fp, result.fn), (2, 0, 0))

    def test_m11_deterministic_equal_matching(self):
        truth = [issue("A"), issue("B")]
        findings = [finding(), finding()]
        result, _reward = run(truth, findings)
        self.assertEqual((result.tp, result.fp, result.fn), (2, 0, 0))
        self.assertEqual(
            result.matched,
            [
                {"finding_index": 0, "issue_id": "A"},
                {"finding_index": 1, "issue_id": "B"},
            ],
        )

    def test_m12_identical_findings_are_not_normalized_away(self):
        result, reward = run([issue()], [finding(), finding()])
        self.assertEqual((result.tp, result.fp, result.fn), (1, 1, 0))
        self.assertAlmostEqual(result.f1, 2 / 3, delta=1e-9)
        self.assertAlmostEqual(reward, 47 / 150, delta=1e-9)


class StrictValidatorTests(unittest.TestCase):
    def test_unknown_string_type_is_accepted_by_strict_validator(self):
        payload = {
            "episode_id": "e",
            "findings": [finding(kind="not_a_declared_type")],
        }
        normalized = validate_findings_payload_strict(payload)
        self.assertEqual(
            normalized["findings"][0]["type"], "not_a_declared_type"
        )

    def test_ids_and_currency_are_not_normalized(self):
        payload = {
            "episode_id": "e",
            "findings": [
                finding(
                    affected=(" R1 ",),
                    currency="kzt",
                    evidence=(" D1 ",),
                )
            ],
        }
        normalized = validate_findings_payload_strict(payload)
        item = normalized["findings"][0]
        self.assertEqual(item["affected_ids"], [" R1 "])
        self.assertEqual(item["currency"], "kzt")
        self.assertEqual(item["evidence_ids"], [" D1 "])


if __name__ == "__main__":
    unittest.main()
