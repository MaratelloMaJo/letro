import unittest

from letro.proof import CASES, check_case, run_all


class ProofTest(unittest.TestCase):
    def test_simple_cases_add_one_issue(self):
        for case in ("duplicate_invoice", "payment_allocation_gap",
                     "fx_rate_error", "period_cutoff"):
            result = check_case(case, seed=1001)
            self.assertEqual(result.verdict, "PASS", case)
            self.assertEqual(result.clean_issues, 0, case)
            self.assertEqual(result.injected_issues, 1, case)
            self.assertEqual(result.added_types, [case], case)
            self.assertTrue(result.evidence_minimal, case)
            self.assertTrue(result.amount_recomputed, case)

    def test_composites_add_two_issues(self):
        for case in ("boundary_fx_payment", "gap_cutoff_payment"):
            result = check_case(case, seed=1001)
            self.assertEqual(result.verdict, "PASS", case)
            self.assertEqual(result.injected_issues, 2, case)
            self.assertEqual(len(result.added_types), 2, case)

    def test_run_all_covers_every_case(self):
        results = run_all([1001])
        self.assertEqual({item.case for item in results}, set(CASES))
        self.assertTrue(all(item.verdict == "PASS" for item in results))

    def test_proof_does_not_import_audit_arithmetic(self):
        import pathlib
        source = pathlib.Path("letro/proof.py").read_text(encoding="utf-8")
        for helper in ("_base", "_payment_base", "_expected_allocation"):
            self.assertNotIn(f"import {helper}", source)
            self.assertNotIn(f"from letro.generator.audit import {helper}", source)
