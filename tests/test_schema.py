"""Public schemas reject bad input without echoing hidden data."""

from __future__ import annotations

import unittest

from letro.schema import (
    ActionError,
    ConfigError,
    FindingError,
    validate_action,
    validate_config,
    validate_findings_payload,
    validate_manifest,
    validate_truth,
)


def finding(**overrides):
    value = {
        "type": "duplicate_invoice",
        "affected_ids": ["INV-0001"],
        "claimed_amount_minor": 100,
        "currency": "KZT",
        "evidence_ids": ["LED-000001"],
        "explanation": "",
    }
    value.update(overrides)
    return value


class ConfigTests(unittest.TestCase):
    def test_defaults(self):
        config = validate_config(None)
        self.assertEqual(config["base_currency"], "KZT")
        self.assertEqual(config["errors"]["duplicate_invoice"], 1)
        self.assertGreaterEqual(config["sizes"]["ledger_rows"], 200)

    def test_clean_zeroes_errors(self):
        config = validate_config({"clean": True})
        self.assertTrue(config["clean"])
        self.assertEqual(sum(config["errors"].values()), 0)

    def test_rejects_unknown_and_out_of_range(self):
        with self.assertRaises(ConfigError):
            validate_config({"unknown": 1})
        with self.assertRaises(ConfigError):
            validate_config({"sizes": {"ledger_rows": 100}})
        with self.assertRaises(ConfigError):
            validate_config({"sizes": {"invoices": 5, "payments": 0}})
        with self.assertRaises(ConfigError):
            validate_config({"errors": {"duplicate_invoice": 13}})

    def test_manifest(self):
        manifest = {
            "schema_version": "1.0.0",
            "episode_id": "ep-1",
            "base_currency": "KZT",
            "period_start": "2026-01-01T00:00:00+05:00",
            "period_end": "2026-01-30T23:59:59+05:00",
            "timezone": "Asia/Almaty",
            "ledger_rows": 10,
            "documents": 20,
            "rounding": "half_up",
            "fx_rate_date": "invoice_date",
        }
        validate_manifest(manifest)
        with self.assertRaises(ConfigError):
            validate_manifest({key: value for key, value in manifest.items() if key != "rounding"})


class ActionTests(unittest.TestCase):
    def test_valid_actions_are_normalized(self):
        self.assertEqual(
            validate_action(
                {"type": "list_records", "table": "ledger", "cursor": 0, "limit": 50}
            )["limit"],
            50,
        )
        self.assertEqual(
            validate_action({"type": "calculator", "expression": "1+1"})["expression"],
            "1+1",
        )

    def test_bounds(self):
        with self.assertRaises(ActionError):
            validate_action({"type": "list_records", "table": "ledger", "limit": 51})
        with self.assertRaises(ActionError):
            validate_action({"type": "list_records", "table": "ledger", "limit": 0})
        with self.assertRaises(ActionError):
            validate_action({"type": "list_records", "table": "secrets"})
        with self.assertRaises(ActionError):
            validate_action({"type": "get_record", "table": "ledger", "id": ""})
        with self.assertRaises(ActionError):
            validate_action({"type": "calculator", "expression": "1" * 201})
        with self.assertRaises(ActionError):
            validate_action({"type": "drop"})
        with self.assertRaises(ActionError):
            validate_action("not an action")


class FindingTests(unittest.TestCase):
    def test_valid_payload(self):
        payload = validate_findings_payload(
            {"episode_id": "ep-1", "findings": [finding()]}
        )
        self.assertEqual(payload["findings"][0]["currency"], "KZT")

    def test_limits(self):
        with self.assertRaises(FindingError):
            validate_findings_payload(
                {"episode_id": "ep-1", "findings": [finding() for _ in range(31)]}
            )
        with self.assertRaises(FindingError):
            validate_findings_payload(
                {
                    "episode_id": "ep-1",
                    "findings": [finding(evidence_ids=[f"LED-{i:06d}" for i in range(11)])],
                }
            )
        with self.assertRaises(FindingError):
            validate_findings_payload(
                {
                    "episode_id": "ep-1",
                    "findings": [finding(explanation="x" * 1001)],
                }
            )

    def test_structure(self):
        with self.assertRaises(FindingError):
            validate_findings_payload({"episode_id": "ep-1", "findings": "nope"})
        with self.assertRaises(FindingError):
            validate_findings_payload({"episode_id": "ep-1", "findings": [finding(type="bad")]})
        with self.assertRaises(FindingError):
            validate_findings_payload({"episode_id": "ep-1", "findings": [finding(affected_ids=[])]})
        with self.assertRaises(FindingError):
            validate_findings_payload(
                {"episode_id": "ep-1", "findings": [finding(claimed_amount_minor=True)]}
            )
        with self.assertRaises(FindingError):
            validate_findings_payload(
                {"episode_id": "ep-1", "findings": [finding(currency="BTC")]}
            )

    def test_truth_shape(self):
        validate_truth({"episode_id": "ep-1", "issues": []})
        with self.assertRaises(ConfigError):
            validate_truth({"episode_id": "ep-1", "issues": [{"type": "duplicate_invoice"}]})
        with self.assertRaises(ConfigError):
            validate_truth({"issues": "nope"})


if __name__ == "__main__":
    unittest.main()
