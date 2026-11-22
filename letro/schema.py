"""Schema validation for configs, manifests, actions, findings and truth.

Errors are deliberately bounded: they name the violated rule but never echo
hidden truth values or file contents.
"""

from __future__ import annotations

from typing import Any

from .constants import (
    ERROR_TYPES,
    MAX_DOCUMENTS,
    MAX_EVIDENCE_IDS,
    MAX_EXPLANATION_CHARS,
    MAX_FINDINGS,
    MAX_ISSUES,
    MAX_LEDGER_ROWS,
    MAX_PAGE,
    MIN_DOCUMENTS,
    MIN_LEDGER_ROWS,
    SCHEMA_VERSION,
    TABLES,
)
from .money import MoneyError, currency_decimals


class ConfigError(ValueError):
    """Invalid episode configuration."""


class ActionError(ValueError):
    """Invalid or unknown action."""


class FindingError(ValueError):
    """Structurally invalid findings payload."""


DEFAULT_CONFIG: dict[str, Any] = {
    "schema_version": SCHEMA_VERSION,
    "base_currency": "KZT",
    "period_days": 30,
    "timezone_offset": "+05:00",
    "sizes": {
        "invoices": 40,
        "payments": 36,
        "issues": 6,
        "ledger_rows": 320,
    },
    "errors": {
        "duplicate_invoice": 1,
        "payment_allocation_gap": 1,
        "fx_rate_error": 1,
        "period_cutoff": 1,
        "composite": 1,
    },
    "clean": False,
    "mode": "train",
    "variant": 0,
}


def _require_int(value: object, name: str, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"{name} must be an integer")
    if value < low or value > high:
        raise ConfigError(f"{name} must be between {low} and {high}")
    return value


def _require_str(value: object, name: str, max_len: int = 64) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{name} must be a non-empty string")
    if len(value) > max_len:
        raise ConfigError(f"{name} is too long")
    return value.strip()


def validate_config(config: dict[str, Any] | None) -> dict[str, Any]:
    """Merge config over defaults and validate ranges."""
    merged = {
        **DEFAULT_CONFIG,
        "sizes": dict(DEFAULT_CONFIG["sizes"]),
        "errors": dict(DEFAULT_CONFIG["errors"]),
    }
    if config is None:
        config = {}
    if not isinstance(config, dict):
        raise ConfigError("config must be an object")

    for key in ("sizes", "errors"):
        if key in config:
            if not isinstance(config[key], dict):
                raise ConfigError(f"{key} must be an object")
            merged[key].update(config[key])

    for key, value in config.items():
        if key in ("sizes", "errors"):
            continue
        if key not in DEFAULT_CONFIG:
            raise ConfigError(f"unknown config key: {key}")
        merged[key] = value

    if merged.get("schema_version") != SCHEMA_VERSION:
        raise ConfigError("unsupported schema_version")

    merged["base_currency"] = _require_str(
        merged["base_currency"], "base_currency", 3
    ).upper()
    try:
        currency_decimals(merged["base_currency"])
    except MoneyError as exc:
        raise ConfigError("base_currency is not supported") from exc

    merged["timezone_offset"] = _require_str(
        merged["timezone_offset"], "timezone_offset", 6
    )
    merged["period_days"] = _require_int(merged["period_days"], "period_days", 1, 366)
    merged["variant"] = _require_int(merged["variant"], "variant", 0, 10_000)

    sizes = merged["sizes"]
    _require_int(sizes.get("invoices"), "sizes.invoices", 5, 120)
    _require_int(sizes.get("payments"), "sizes.payments", 0, 200)
    _require_int(sizes.get("issues"), "sizes.issues", 0, MAX_ISSUES)
    _require_int(sizes.get("ledger_rows"), "sizes.ledger_rows", 0, MAX_LEDGER_ROWS)

    errors = merged["errors"]
    for key in ("duplicate_invoice", "payment_allocation_gap", "fx_rate_error",
                "period_cutoff", "composite"):
        _require_int(errors.get(key), f"errors.{key}", 0, MAX_ISSUES)
    simple_total = sum(
        errors.get(key, 0)
        for key in ("duplicate_invoice", "payment_allocation_gap",
                    "fx_rate_error", "period_cutoff")
    )
    if simple_total + 2 * errors.get("composite", 0) > MAX_ISSUES:
        raise ConfigError("configured errors exceed the issue limit")
    if merged.get("clean"):
        for key in (
            "duplicate_invoice",
            "payment_allocation_gap",
            "fx_rate_error",
            "period_cutoff",
            "composite",
        ):
            errors[key] = 0
    if merged.get("mode") not in ("train", "eval", "verify"):
        raise ConfigError("mode must be train, eval or verify")

    ledger_rows = sizes.get("ledger_rows", 0)
    if ledger_rows and ledger_rows < MIN_LEDGER_ROWS:
        raise ConfigError(f"sizes.ledger_rows must be 0 or at least {MIN_LEDGER_ROWS}")
    if ledger_rows > MAX_LEDGER_ROWS:
        raise ConfigError(f"sizes.ledger_rows must be at most {MAX_LEDGER_ROWS}")
    if sizes.get("invoices", 0) + sizes.get("payments", 0) > MAX_DOCUMENTS:
        raise ConfigError(f"documents must be at most {MAX_DOCUMENTS}")
    if sizes.get("invoices", 0) + sizes.get("payments", 0) < MIN_DOCUMENTS:
        raise ConfigError(f"documents must be at least {MIN_DOCUMENTS}")

    return merged


def validate_manifest(manifest: dict[str, Any]) -> None:
    if not isinstance(manifest, dict):
        raise ConfigError("manifest must be an object")
    required = {
        "schema_version",
        "episode_id",
        "base_currency",
        "period_start",
        "period_end",
        "timezone",
        "ledger_rows",
        "documents",
        "rounding",
        "fx_rate_date",
    }
    missing = required - set(manifest)
    if missing:
        raise ConfigError(f"manifest is missing keys: {sorted(missing)}")
    if manifest["schema_version"] != SCHEMA_VERSION:
        raise ConfigError("manifest schema_version is unsupported")
    if not isinstance(manifest["ledger_rows"], int):
        raise ConfigError("manifest ledger_rows must be an integer")
    if not isinstance(manifest["documents"], int):
        raise ConfigError("manifest documents must be an integer")
    if manifest["ledger_rows"] > MAX_LEDGER_ROWS:
        raise ConfigError("manifest ledger_rows exceeds the limit")
    if manifest["documents"] > MAX_DOCUMENTS:
        raise ConfigError("manifest documents exceeds the limit")


def validate_action(action: Any) -> dict[str, Any]:
    """Validate an agent action and return a normalized copy."""
    if not isinstance(action, dict):
        raise ActionError("action must be a JSON object")
    kind = action.get("type")
    if not isinstance(kind, str):
        raise ActionError("action.type is required")

    if kind == "list_records":
        table = action.get("table")
        if table not in TABLES:
            raise ActionError("unknown table")
        cursor = action.get("cursor", 0)
        limit = action.get("limit", MAX_PAGE)
        if isinstance(cursor, bool) or not isinstance(cursor, int) or cursor < 0:
            raise ActionError("cursor must be a non-negative integer")
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise ActionError("limit must be an integer")
        if limit < 1 or limit > MAX_PAGE:
            raise ActionError(f"limit must be between 1 and {MAX_PAGE}")
        return {"type": kind, "table": table, "cursor": cursor, "limit": limit}

    if kind == "get_record":
        table = action.get("table")
        if table not in TABLES:
            raise ActionError("unknown table")
        record_id = action.get("id")
        if not isinstance(record_id, str) or not record_id.strip():
            raise ActionError("id must be a non-empty string")
        if len(record_id) > 64:
            raise ActionError("id is too long")
        return {"type": kind, "table": table, "id": record_id.strip()}

    if kind == "get_document":
        doc_id = action.get("doc_id")
        if not isinstance(doc_id, str) or not doc_id.strip():
            raise ActionError("doc_id must be a non-empty string")
        if len(doc_id) > 64:
            raise ActionError("doc_id is too long")
        return {"type": kind, "doc_id": doc_id.strip()}

    if kind == "calculator":
        expression = action.get("expression")
        if not isinstance(expression, str) or not expression.strip():
            raise ActionError("expression must be a non-empty string")
        if len(expression) > 200:
            raise ActionError("expression is too long")
        return {"type": kind, "expression": expression}

    if kind == "submit":
        return validate_findings_payload(action.get("findings"))

    raise ActionError(f"unknown action type: {kind}")


def validate_findings_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise FindingError("findings must be an object")
    episode_id = payload.get("episode_id")
    if not isinstance(episode_id, str) or not episode_id.strip():
        raise FindingError("episode_id is required")
    findings = payload.get("findings")
    if not isinstance(findings, list):
        raise FindingError("findings must be an array")
    if len(findings) > MAX_FINDINGS:
        raise FindingError(f"at most {MAX_FINDINGS} findings are allowed")

    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(findings):
        if not isinstance(item, dict):
            raise FindingError(f"finding {index} must be an object")
        kind = item.get("type")
        if kind not in ERROR_TYPES:
            raise FindingError(f"finding {index} has an unknown type")
        affected = item.get("affected_ids")
        if not isinstance(affected, list) or not affected:
            raise FindingError(f"finding {index} requires affected_ids")
        if len(affected) > 20:
            raise FindingError(f"finding {index} has too many affected_ids")
        ids = []
        for value in affected:
            if not isinstance(value, str) or not value.strip() or len(value) > 64:
                raise FindingError(f"finding {index} has an invalid affected id")
            ids.append(value.strip())
        amount = item.get("claimed_amount_minor")
        if isinstance(amount, bool) or not isinstance(amount, int):
            raise FindingError(
                f"finding {index} requires integer claimed_amount_minor"
            )
        if amount < 0:
            raise FindingError(f"finding {index} amount must be non-negative")
        currency = item.get("currency")
        if not isinstance(currency, str):
            raise FindingError(f"finding {index} requires currency")
        try:
            currency_decimals(currency)
        except MoneyError as exc:
            raise FindingError(f"finding {index} has an unsupported currency") from exc
        evidence = item.get("evidence_ids", [])
        if not isinstance(evidence, list):
            raise FindingError(f"finding {index} evidence_ids must be an array")
        if len(evidence) > MAX_EVIDENCE_IDS:
            raise FindingError(
                f"finding {index} exceeds {MAX_EVIDENCE_IDS} evidence ids"
            )
        evidence_ids = []
        for value in evidence:
            if not isinstance(value, str) or not value.strip() or len(value) > 64:
                raise FindingError(f"finding {index} has an invalid evidence id")
            evidence_ids.append(value.strip())
        explanation = item.get("explanation", "")
        if not isinstance(explanation, str):
            raise FindingError(f"finding {index} explanation must be a string")
        if len(explanation) > MAX_EXPLANATION_CHARS:
            raise FindingError(
                f"finding {index} explanation exceeds {MAX_EXPLANATION_CHARS} chars"
            )
        normalized.append(
            {
                "type": kind,
                "affected_ids": ids,
                "claimed_amount_minor": amount,
                "currency": currency.upper(),
                "evidence_ids": evidence_ids,
                "explanation": explanation,
            }
        )
    return {"episode_id": episode_id.strip(), "findings": normalized}


def validate_findings_payload_strict(payload: Any) -> dict[str, Any]:
    """Validate the official jury's findings contract without normalization.

    Unlike :func:`validate_findings_payload`, this keeps IDs and currency
    exactly as submitted and accepts an unknown string type.  An unknown type
    is structurally valid but cannot match a truth issue, so it becomes a false
    positive rather than a whole-submit error.
    """
    if not isinstance(payload, dict):
        raise FindingError("findings must be an object")
    episode_id = payload.get("episode_id")
    if not isinstance(episode_id, str) or not episode_id:
        raise FindingError("episode_id is required")
    findings = payload.get("findings")
    if not isinstance(findings, list):
        raise FindingError("findings must be an array")
    if len(findings) > MAX_FINDINGS:
        raise FindingError(f"at most {MAX_FINDINGS} findings are allowed")

    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(findings):
        if not isinstance(item, dict):
            raise FindingError(f"finding {index} must be an object")
        kind = item.get("type")
        if not isinstance(kind, str) or not kind:
            raise FindingError(f"finding {index} requires a type")
        affected = item.get("affected_ids")
        if not isinstance(affected, list) or not affected:
            raise FindingError(f"finding {index} requires affected_ids")
        if len(affected) > 20:
            raise FindingError(f"finding {index} has too many affected_ids")
        ids = []
        for value in affected:
            if not isinstance(value, str) or not value or len(value) > 64:
                raise FindingError(f"finding {index} has an invalid affected id")
            ids.append(value)
        amount = item.get("claimed_amount_minor")
        if isinstance(amount, bool) or not isinstance(amount, int):
            raise FindingError(
                f"finding {index} requires integer claimed_amount_minor"
            )
        if amount < 0:
            raise FindingError(f"finding {index} amount must be non-negative")
        currency = item.get("currency")
        if not isinstance(currency, str) or not currency:
            raise FindingError(f"finding {index} requires currency")
        evidence = item.get("evidence_ids", [])
        if not isinstance(evidence, list):
            raise FindingError(f"finding {index} evidence_ids must be an array")
        if len(evidence) > MAX_EVIDENCE_IDS:
            raise FindingError(
                f"finding {index} exceeds {MAX_EVIDENCE_IDS} evidence ids"
            )
        evidence_ids = []
        for value in evidence:
            if not isinstance(value, str) or not value or len(value) > 64:
                raise FindingError(f"finding {index} has an invalid evidence id")
            evidence_ids.append(value)
        explanation = item.get("explanation", "")
        if not isinstance(explanation, str):
            raise FindingError(f"finding {index} explanation must be a string")
        if len(explanation) > MAX_EXPLANATION_CHARS:
            raise FindingError(
                f"finding {index} explanation exceeds {MAX_EXPLANATION_CHARS} chars"
            )
        normalized.append(
            {
                "type": kind,
                "affected_ids": ids,
                "claimed_amount_minor": amount,
                "currency": currency,
                "evidence_ids": evidence_ids,
                "explanation": explanation,
            }
        )
    return {"episode_id": episode_id, "findings": normalized}


def validate_truth(truth: Any) -> None:
    if not isinstance(truth, dict):
        raise ConfigError("truth must be an object")
    issues = truth.get("issues")
    if not isinstance(issues, list):
        raise ConfigError("truth.issues must be an array")
    if len(issues) > MAX_ISSUES:
        raise ConfigError("truth exceeds the issue limit")
    seen = set()
    for index, issue in enumerate(issues):
        if not isinstance(issue, dict):
            raise ConfigError(f"truth issue {index} must be an object")
        for key in (
            "issue_id",
            "type",
            "affected_ids",
            "expected_amount_minor",
            "currency",
            "allowed_evidence_sets",
        ):
            if key not in issue:
                raise ConfigError(f"truth issue {index} is missing {key}")
        if issue["type"] not in ERROR_TYPES:
            raise ConfigError(f"truth issue {index} has an unknown type")
        if issue["issue_id"] in seen:
            raise ConfigError("truth issue ids must be unique")
        seen.add(issue["issue_id"])
        if not isinstance(issue["affected_ids"], list) or not issue["affected_ids"]:
            raise ConfigError(f"truth issue {index} requires affected_ids")
        if (
            isinstance(issue["expected_amount_minor"], bool)
            or not isinstance(issue["expected_amount_minor"], int)
            or issue["expected_amount_minor"] < 0
        ):
            raise ConfigError(f"truth issue {index} has an invalid amount")
        try:
            currency_decimals(issue["currency"])
        except MoneyError as exc:
            raise ConfigError(f"truth issue {index} currency is invalid") from exc
        sets = issue["allowed_evidence_sets"]
        if not isinstance(sets, list) or not sets:
            raise ConfigError(f"truth issue {index} requires evidence sets")
        for evidence_set in sets:
            if not isinstance(evidence_set, list) or not evidence_set:
                raise ConfigError(
                    f"truth issue {index} has an empty evidence set"
                )
            if len(evidence_set) > MAX_EVIDENCE_IDS:
                raise ConfigError(
                    f"truth issue {index} evidence set exceeds the limit"
                )
