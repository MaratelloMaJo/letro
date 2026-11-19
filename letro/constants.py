"""Project-wide constants fixed by the competition brief."""

from __future__ import annotations

SCHEMA_VERSION = "1.0.0"

MAX_STEPS = 100
MAX_PAGE = 50
MAX_FINDINGS = 30
MAX_EVIDENCE_IDS = 10
MAX_EXPLANATION_CHARS = 1000
MAX_CALC_EXPRESSION_CHARS = 200
MAX_LEDGER_ROWS = 2000
MIN_LEDGER_ROWS = 200
MAX_DOCUMENTS = 200
MIN_DOCUMENTS = 20
MAX_ISSUES = 12
AMOUNT_TOLERANCE_MINOR = 1
STEP_COST = 0.002

ERROR_TYPES = (
    "duplicate_invoice",
    "payment_allocation_gap",
    "fx_rate_error",
    "period_cutoff",
)

TABLES = ("ledger", "invoices", "payments", "fx")

ACCOUNTS = {
    "cash": "1000",
    "ar": "1100",
    "ap": "2000",
    "deferred": "2100",
    "revenue": "4000",
    "service_revenue": "4100",
    "fx_gain_loss": "4900",
    "expenses": "5000",
    "tax": "5100",
    "suspense": "9999",
}

ACCOUNT_NAMES = {
    "1000": "Cash",
    "1100": "Accounts Receivable",
    "2000": "Accounts Payable",
    "2100": "Deferred Revenue",
    "4000": "Revenue",
    "4100": "Service Revenue",
    "4900": "FX Gain/Loss",
    "5000": "Operating Expenses",
    "5100": "Taxes",
    "9999": "Suspense",
}

CURRENCY_DECIMALS = {
    "KZT": 2,
    "USD": 2,
    "EUR": 2,
    "GBP": 2,
    "JPY": 0,
}

DEFAULT_POLICY = {
    "fx_rate_date": "invoice_date",
    "period_start_inclusive": True,
    "period_end_inclusive": True,
    "rounding": "half_up",
    "amount_tolerance_minor": AMOUNT_TOLERANCE_MINOR,
}

# Hidden keys that must never appear in an agent observation or trajectory.
FORBIDDEN_OBSERVATION_KEYS = frozenset(
    {
        "truth",
        "truth.json",
        "provenance",
        "provenance.json",
        "issue_id",
        "expected_amount_minor",
        "allowed_evidence_sets",
        "affected_ids",
        "hidden_truth",
        "answer_key",
    }
)
