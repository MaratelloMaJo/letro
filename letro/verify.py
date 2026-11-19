"""One-command verification for the LETRO environment.

Run ``python -m letro.verify`` from the repository root. The command checks the
four scored technical criteria with 20 checks each, scores the five engineering
criteria, prints a table and exits non-zero when anything fails.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .constants import (
    AMOUNT_TOLERANCE_MINOR,
    ERROR_TYPES,
    MAX_STEPS,
    SCHEMA_VERSION,
    STEP_COST,
)
from .evaluator import Evaluator
from .factory import env_from_episode
from .generator import generate_episode, load_episode, reference_audit, reference_findings
from .generator.company import build_company
from .generator.model import entry_balanced
from .matcher import finding_matches, score
from .permute import assert_no_reused_ids, permute_episode
from .policies import MarkAllPolicy, OraclePolicy, ReconciliationPolicy
from .reward import terminal_reward
from .schema import validate_config, validate_manifest, validate_truth
from .tools import ToolError, calculate
from .trajectory import (
    TrajectoryError,
    forbidden_paths,
    run_episode,
    validate_trajectory_file,
)

ROOT = Path(__file__).resolve().parents[1]
OPEN_FILES = (
    "manifest.json",
    "ledger.csv",
    "invoices.jsonl",
    "payments.jsonl",
    "fx.csv",
    "policy.json",
)

_EPISODES: dict[tuple[int, str], Any] = {}


@dataclass
class Check:
    name: str
    passed: bool
    detail: str = ""


# ---------------------------------------------------------------------------
# helpers


def _episode(seed: int, config: dict[str, Any] | None = None):
    key = (seed, json.dumps(config or {}, sort_keys=True))
    if key not in _EPISODES:
        _EPISODES[key] = generate_episode(seed, config)
    return _EPISODES[key]


def _run(checks: list[Check], name: str, function: Callable[[], Any]) -> None:
    try:
        value = function()
        if isinstance(value, tuple):
            passed, detail = bool(value[0]), str(value[1])
        else:
            passed, detail = bool(value), ""
    except Exception as exc:  # a verifier crash is a failed check, not a stack trace
        passed, detail = False, f"{type(exc).__name__}: {exc}"
    checks.append(Check(name=name, passed=passed, detail=detail[:400]))


def _payload(episode: Any, findings: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "episode_id": episode.manifest["episode_id"],
        "findings": findings,
    }


def _errors(
    duplicate: int = 0,
    gap: int = 0,
    fx: int = 0,
    cutoff: int = 0,
    composite: int = 0,
) -> dict[str, int]:
    return {
        "duplicate_invoice": duplicate,
        "payment_allocation_gap": gap,
        "fx_rate_error": fx,
        "period_cutoff": cutoff,
        "composite": composite,
    }


def _config(
    *,
    errors: dict[str, int] | None = None,
    clean: bool = False,
    base: str = "KZT",
    invoices: int = 34,
    payments: int = 30,
    rows: int = 300,
    days: int = 30,
    variant: int = 0,
) -> dict[str, Any]:
    return {
        "base_currency": base,
        "period_days": days,
        "sizes": {
            "invoices": invoices,
            "payments": payments,
            "issues": 12 if errors else 0,
            "ledger_rows": rows,
        },
        "errors": errors or _errors(),
        "clean": clean,
        "variant": variant,
    }


def _signature(issue: dict[str, Any]) -> tuple[str, tuple[str, ...], int, str]:
    return (
        issue["type"],
        tuple(sorted(issue["affected_ids"])),
        int(issue["expected_amount_minor"]),
        issue["currency"],
    )


def _expected_issue_count(config: dict[str, Any]) -> int:
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


def _open_ids(episode: Any) -> set[str]:
    ids = {row["row_id"] for row in episode.ledger}
    for invoice in episode.invoices:
        ids.add(invoice["invoice_id"])
        ids.add(invoice["doc_id"])
    for payment in episode.payments:
        ids.add(payment["payment_id"])
        ids.add(payment["doc_id"])
    return ids


def _balanced(episode: Any) -> tuple[bool, str]:
    debits = sum(row["debit_minor"] for row in episode.ledger)
    credits = sum(row["credit_minor"] for row in episode.ledger)
    if debits != credits:
        return False, f"ledger imbalance {debits - credits} minor units"
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
            return False, f"unbalanced journal group {key[0]} by {debit - credit}"
    return True, ""


def _clean_books(seed: int, config: dict[str, Any]) -> tuple[bool, str]:
    clean = build_company(seed, validate_config(config))
    by_id = {row["row_id"]: row for row in clean.ledger}
    for entry in clean.entries:
        if not entry_balanced([by_id[row_id] for row_id in entry]):
            return False, "pre-injection journal entry is not balanced"
    return True, f"{len(clean.entries)} clean entries"


def _iso(value: str) -> bool:
    parsed = datetime.fromisoformat(value)
    return parsed.tzinfo is not None


def _evidence_semantics(episode: Any, issue: dict[str, Any]) -> tuple[bool, str]:
    """An evidence set must let an auditor re-derive the issue without truth."""
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
                return True, ""
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
                return True, ""
        elif kind == "fx_rate_error":
            has_doc = any(value in invoices or value in payments for value in ids)
            has_amount = any(
                value in ledger
                and (ledger[value]["debit_minor"] or ledger[value]["credit_minor"])
                for value in ids
            )
            if has_doc and has_amount:
                return True, ""
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
                return True, ""
    return False, f"{issue['issue_id']} ({kind}) evidence is not independently sufficient"


def _episode_check(
    episode: Any,
    *,
    seed: int,
    config: dict[str, Any],
    expected: int,
) -> tuple[bool, str]:
    validate_manifest(episode.manifest)
    validate_truth(episode.truth)
    if episode.manifest["episode_id"] != episode.truth["episode_id"]:
        return False, "episode_id mismatch between manifest and truth"
    if episode.manifest["ledger_rows"] != len(episode.ledger):
        return False, "manifest ledger_rows does not match the ledger"
    documents = len(episode.invoices) + len(episode.payments)
    if episode.manifest["documents"] != documents:
        return False, "manifest documents does not match the files"

    ok, detail = _balanced(episode)
    if not ok:
        return False, detail
    ok, detail = _clean_books(seed, config)
    if not ok:
        return False, detail
    issues = list(episode.truth["issues"])
    if len(issues) != expected:
        return False, f"truth has {len(issues)} issues, configured {expected}"
    recomputed = reference_audit(episode)
    if sorted(map(_signature, recomputed)) != sorted(map(_signature, issues)):
        return False, "independent audit does not reproduce truth"

    valid = _open_ids(episode)
    for issue in issues:
        if int(issue["expected_amount_minor"]) <= AMOUNT_TOLERANCE_MINOR:
            return False, f"{issue['issue_id']} amount is not material"
        if not set(issue["affected_ids"]) <= valid:
            return False, f"{issue['issue_id']} has unknown affected ids"
        sets = issue.get("allowed_evidence_sets") or []
        if not sets:
            return False, f"{issue['issue_id']} has no allowed evidence set"
        if not any(values and len(values) <= 10 and set(values) <= valid for values in sets):
            return False, f"{issue['issue_id']} evidence does not resolve"
        ok, detail = _evidence_semantics(episode, issue)
        if not ok:
            return False, detail
    for value in [episode.manifest["period_start"], episode.manifest["period_end"]]:
        if not _iso(value):
            return False, "period boundary is not ISO-8601 with an offset"
    for row in episode.ledger:
        if not _iso(row["timestamp"]):
            return False, "ledger timestamp is not ISO-8601 with an offset"
        if not isinstance(row["debit_minor"], int) or not isinstance(
            row["credit_minor"], int
        ):
            return False, "ledger money is not an integer minor unit"
    return True, f"{len(episode.ledger)} rows, {documents} docs, {len(issues)} issues"


def _digest(directory: Path) -> str:
    digest = hashlib.sha256()
    for name in OPEN_FILES:
        digest.update(name.encode("utf-8"))
        # The digest attests content, not the checkout's line-ending style.
        digest.update((directory / name).read_bytes().replace(b"\r\n", b"\n"))
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# criterion 1: contract and isolation


def criterion_contract() -> list[Check]:
    checks: list[Check] = []
    base = _episode(9101)

    def reset_contract():
        env, _evaluator = env_from_episode(base)
        observation, info = env.reset()
        assert isinstance(observation, dict) and isinstance(info, dict)
        assert observation["task"]
        assert observation["manifest"]["episode_id"] == info["episode_id"]
        assert observation["budget"]["steps_remaining"] == MAX_STEPS
        assert set(observation["policy_summary"]) >= {
            "base_currency",
            "period_start",
            "period_end",
            "amount_tolerance_minor",
        }
        return True, "manifest, policy summary and budget present"

    _run(checks, "reset_contract", reset_contract)

    def step_contract():
        env, _evaluator = env_from_episode(base)
        env.reset()
        result = env.step({"type": "list_records", "table": "ledger", "limit": 3})
        assert isinstance(result, tuple) and len(result) == 5
        observation, reward, terminated, truncated, info = result
        assert isinstance(observation, dict)
        assert isinstance(reward, float)
        assert isinstance(terminated, bool) and isinstance(truncated, bool)
        assert isinstance(info, dict)
        return True, "five values with the documented types"

    _run(checks, "step_contract", step_contract)

    def observation_isolation():
        env, _evaluator = env_from_episode(base)
        observation, info = env.reset()
        leaks = forbidden_paths(observation) + forbidden_paths(info)
        assert not leaks, f"leaked {sorted(set(leaks))}"
        return True, "no truth keys in observation or info"

    _run(checks, "observation_isolation", observation_isolation)

    def info_isolation():
        env, _evaluator = env_from_episode(base)
        env.reset()
        _obs, _r, _t, _tr, info = env.step(
            {"type": "list_records", "table": "invoices", "limit": 2}
        )
        text = json.dumps(info, ensure_ascii=False)
        for key in ("truth", "provenance", "issue_id", "expected_amount_minor"):
            assert key not in text, key
        return True, "info carries only budget diagnostics"

    _run(checks, "info_isolation", info_isolation)

    def json_safety():
        env, _evaluator = env_from_episode(base)
        observation, info = env.reset()
        json.dumps(observation, allow_nan=False)
        json.dumps(info, allow_nan=False)
        observation, _r, _t, _tr, info = env.step(
            {"type": "calculator", "expression": "2*(3+4)-5"}
        )
        json.dumps(observation, allow_nan=False)
        json.dumps(info, allow_nan=False)
        return True, "observations and info are strict JSON"

    _run(checks, "json_safety", json_safety)

    def pagination():
        env, _evaluator = env_from_episode(base)
        env.reset()
        seen: list[str] = []
        cursor: int | None = 0
        pages = 0
        while cursor is not None:
            observation, _r, _t, _tr, _i = env.step(
                {
                    "type": "list_records",
                    "table": "ledger",
                    "cursor": cursor,
                    "limit": 50,
                }
            )
            page = observation["last_result"]
            assert page["ok"], page
            result = page["result"]
            assert len(result["rows"]) <= 50
            seen.extend(row["row_id"] for row in result["rows"])
            cursor = result["next_cursor"]
            pages += 1
            assert pages < 100
        expected = {row["row_id"] for row in base.ledger}
        assert set(seen) == expected and len(seen) == len(expected)
        return True, f"{pages} pages covered {len(expected)} rows once"

    _run(checks, "pagination", pagination)

    def pagination_bounds():
        env, _evaluator = env_from_episode(base)
        _o, info = env.reset()
        before = info["steps_remaining"]
        observation, _r, terminated, _tr, info = env.step(
            {"type": "list_records", "table": "ledger", "limit": 51}
        )
        assert not terminated
        assert observation["last_result"]["ok"] is False
        assert len(observation["last_result"]["error"]) <= 200
        assert info["steps_remaining"] == before - 1
        return True, "limit 51 is rejected and costs one step"

    _run(checks, "pagination_bounds", pagination_bounds)

    def record_lookup():
        env, _evaluator = env_from_episode(base)
        env.reset()
        row = base.ledger[0]
        observation, _r, _t, _tr, _i = env.step(
            {"type": "get_record", "table": "ledger", "id": row["row_id"]}
        )
        assert observation["last_result"]["result"] == row
        invoice = base.invoices[0]
        for identifier in (invoice["invoice_id"], invoice["doc_id"]):
            observation, _r, _t, _tr, _i = env.step(
                {"type": "get_record", "table": "invoices", "id": identifier}
            )
            assert observation["last_result"]["result"] == invoice
        return True, "ledger and invoice records resolve by id"

    _run(checks, "record_lookup", record_lookup)

    def document_lookup():
        env, _evaluator = env_from_episode(base)
        env.reset()
        invoice = base.invoices[0]
        payment = base.payments[0]
        observation, _r, _t, _tr, _i = env.step(
            {"type": "get_document", "doc_id": invoice["doc_id"]}
        )
        assert observation["last_result"]["result"] == invoice
        observation, _r, _t, _tr, _i = env.step(
            {"type": "get_document", "doc_id": payment["doc_id"]}
        )
        assert observation["last_result"]["result"] == payment
        return True, "invoice and payment documents resolve"

    _run(checks, "document_lookup", document_lookup)

    def calculator_ok():
        assert calculate("2*(3+4)-5") == "9"
        assert calculate("0.1+0.2") == "0.3"
        assert calculate("10/4") == "2.5"
        return True, "arithmetic is exact decimal"

    _run(checks, "calculator_ok", calculator_ok)

    def calculator_rejects():
        expressions = (
            "__import__('os')",
            "open('secret.txt')",
            "2**8",
            "1/0",
            "[1, 2, 3]",
            "a + b",
        )
        for expression in expressions:
            try:
                calculate(expression)
            except ToolError as exc:
                assert len(str(exc)) <= 200
            else:
                raise AssertionError(f"accepted {expression!r}")
        return True, "code, names, powers and division by zero are rejected"

    _run(checks, "calculator_rejects", calculator_rejects)

    def invalid_table():
        env, _evaluator = env_from_episode(base)
        _o, info = env.reset()
        before = info["steps_remaining"]
        observation, _r, terminated, _tr, info = env.step(
            {"type": "list_records", "table": "secrets"}
        )
        assert not terminated
        assert observation["last_result"]["ok"] is False
        assert len(observation["last_result"]["error"]) <= 200
        assert info["steps_remaining"] == before - 1
        return True, "unknown table gives a bounded error"

    _run(checks, "invalid_table", invalid_table)

    def invalid_record():
        env, _evaluator = env_from_episode(base)
        env.reset()
        for action in (
            {"type": "get_record", "table": "ledger", "id": "LED-999999"},
            {"type": "get_document", "doc_id": "DOC-999999"},
        ):
            observation, _r, terminated, _tr, _i = env.step(action)
            assert not terminated
            assert observation["last_result"]["ok"] is False
            assert len(observation["last_result"]["error"]) <= 200
        return True, "unknown ids give bounded errors"

    _run(checks, "invalid_record", invalid_record)

    def invalid_action():
        env, _evaluator = env_from_episode(base)
        _o, info = env.reset()
        before = info["steps_remaining"]
        for action in ({"type": "drop_table"}, "not an action"):
            observation, _r, terminated, _tr, info = env.step(action)
            assert not terminated
            assert observation["last_result"]["ok"] is False
            assert len(observation["last_result"]["error"]) <= 200
        assert info["steps_remaining"] == before - 2
        return True, "invalid action shapes are bounded and cost steps"

    _run(checks, "invalid_action", invalid_action)

    def submit_terminates():
        clean = _episode(9102, {"clean": True})
        env, evaluator = env_from_episode(clean)
        env.reset()
        observation, reward, terminated, truncated, info = env.step(
            {
                "type": "submit",
                "findings": {
                    "episode_id": clean.manifest["episode_id"],
                    "findings": [],
                },
            }
        )
        assert terminated is True and truncated is False
        assert reward == 1.0
        assert info["submitted"] is True
        assert evaluator.submissions == 1
        return True, "valid submission terminates with the terminal reward"

    _run(checks, "submit_terminates", submit_terminates)

    def submit_after_done():
        clean = _episode(9102, {"clean": True})
        env, evaluator = env_from_episode(clean)
        env.reset()
        action = {
            "type": "submit",
            "findings": {"episode_id": clean.manifest["episode_id"], "findings": []},
        }
        env.step(action)
        observation, reward, terminated, _tr, info = env.step(action)
        assert terminated is True
        assert reward == 0.0
        assert info.get("error") == "episode_finished"
        assert evaluator.submissions == 1
        return True, "a finished episode cannot be scored twice"

    _run(checks, "submit_after_done", submit_after_done)

    def reset_isolation():
        env, _evaluator = env_from_episode(_episode(9101))
        env.reset()
        env.step({"type": "list_records", "table": "ledger", "limit": 4})
        env.step({"type": "calculator", "expression": "1+1"})
        observation, info = env.reset()
        assert observation["budget"]["step"] == 0
        assert info["steps_remaining"] == MAX_STEPS
        fresh, _r, _t, _tr, _i = env.step(
            {"type": "list_records", "table": "ledger", "limit": 4}
        )
        assert len(fresh["last_result"]["result"]["rows"]) == 4
        return True, "reset clears step budget and tool state"

    _run(checks, "reset_isolation", reset_isolation)

    def eval_hides_reward():
        env, evaluator = env_from_episode(_episode(9101), mode="eval")
        env.reset()
        payload = reference_findings(_episode(9101))
        observation, reward, terminated, _tr, info = env.step(
            {"type": "submit", "findings": payload}
        )
        assert terminated is True
        assert reward == 0.0
        assert "metrics" not in info
        text = json.dumps(observation, ensure_ascii=False)
        assert "f1" not in text and "precision" not in text
        assert evaluator.last_reward == 1.0
        return True, "evaluation mode hides reward and diagnostics"

    _run(checks, "eval_hides_reward", eval_hides_reward)

    def observation_minimal():
        env, _evaluator = env_from_episode(_episode(9101))
        observation, _info = env.reset()
        assert len(json.dumps(observation, ensure_ascii=False)) < 6000
        assert "ledger" not in observation and "invoices" not in observation
        observation, _r, _t, _tr, _i = env.step(
            {"type": "list_records", "table": "ledger", "limit": 1}
        )
        result = observation["last_result"]["result"]
        assert len(result["rows"]) == 1
        assert result["total"] == len(_episode(9101).ledger)
        return True, "only the requested page is returned"

    _run(checks, "observation_minimal", observation_minimal)

    def manifest_contract():
        episode = _episode(9101)
        validate_manifest(episode.manifest)
        validate_truth(episode.truth)
        assert episode.manifest["schema_version"] == SCHEMA_VERSION
        assert episode.manifest["ledger_rows"] == len(episode.ledger)
        assert episode.manifest["documents"] == len(episode.invoices) + len(
            episode.payments
        )
        assert _iso(episode.manifest["period_start"])
        assert _iso(episode.manifest["period_end"])
        return True, "manifest, counts and ISO offsets are consistent"

    _run(checks, "manifest_contract", manifest_contract)
    return checks


# ---------------------------------------------------------------------------
# criterion 2: data and truth

HIDDEN_CONFIGS = [
    _config(clean=True),
    _config(errors=_errors(duplicate=2, gap=1)),
    _config(errors=_errors(fx=2, cutoff=2)),
    _config(errors=_errors(composite=2)),
    _config(errors=_errors(duplicate=1, fx=1)),
    _config(errors=_errors(gap=1, cutoff=1)),
    _config(errors=_errors(duplicate=1, gap=1, fx=1, cutoff=1)),
    _config(errors=_errors(duplicate=1, composite=1)),
    _config(clean=True, base="USD", invoices=55, payments=44, rows=480),
    _config(
        errors=_errors(duplicate=2, gap=2, fx=2, cutoff=2),
        invoices=60,
        payments=50,
        rows=600,
    ),
]


def criterion_data(dev_entries: list[dict[str, Any]]) -> list[Check]:
    checks: list[Check] = []
    for index, config in enumerate(HIDDEN_CONFIGS):
        seed = 9201 + index

        def check(seed=seed, config=config):
            episode = _episode(seed, config)
            return _episode_check(
                episode,
                seed=seed,
                config=config,
                expected=_expected_issue_count(config),
            )

        _run(checks, f"hidden_episode_{index + 1:02d}", check)

    for entry in dev_entries:
        directory = ROOT / entry["directory"]

        def check(entry=entry, directory=directory):
            episode = load_episode(directory)
            if episode.manifest["episode_id"] != entry["episode_id"]:
                return False, "index episode_id does not match the directory"
            actual = _digest(directory)
            if actual != entry["open_files_sha256"]:
                return False, "open files do not match the recorded digest"
            return _episode_check(
                episode,
                seed=entry["seed"],
                config=entry["config"],
                expected=_expected_issue_count(entry["config"]),
            )

        _run(checks, f"dev_episode_{entry['episode_id']}", check)
    return checks


# ---------------------------------------------------------------------------
# criterion 3: reward reliability


def criterion_reward() -> list[Check]:
    checks: list[Check] = []
    episode = _episode(9301)
    issues = list(episode.truth["issues"])
    findings = reference_findings(episode)["findings"]
    clean = _episode(9302, {"clean": True})

    def oracle_perfect():
        result = score(episode.truth, _payload(episode, findings))
        assert result.tp == len(issues)
        assert result.fp == 0 and result.fn == 0
        assert math.isclose(result.f1, 1.0)
        return True, f"{len(issues)} matched issues"

    _run(checks, "oracle_perfect", oracle_perfect)

    def oracle_reward():
        evaluator = Evaluator(episode)
        outcome = evaluator.score(reference_findings(episode), 0)
        assert outcome["reward"] == 1.0
        return True, "full answer at zero cost earns 1.0"

    _run(checks, "oracle_reward", oracle_reward)

    def clean_silence():
        result = score(clean.truth, _payload(clean, []))
        assert result.f1 == 1.0
        evaluator = Evaluator(clean)
        assert evaluator.score(_payload(clean, []), 0)["reward"] == 1.0
        return True, "silence on clean books is correct"

    _run(checks, "clean_silence", clean_silence)

    def clean_false_accusation():
        result = score(clean.truth, _payload(clean, copy.deepcopy(findings[:1])))
        assert result.f1 == 0.0 and result.fp == 1
        evaluator = Evaluator(clean)
        assert evaluator.score(_payload(clean, findings[:1]), 0)["reward"] == -1.0
        return True, "a false accusation on clean books scores 0"

    _run(checks, "clean_false_accusation", clean_false_accusation)

    def erroneous_silence():
        result = score(episode.truth, _payload(episode, []))
        assert result.f1 == 0.0 and result.fn == len(issues)
        evaluator = Evaluator(episode)
        assert evaluator.score(_payload(episode, []), 0)["reward"] == -1.0
        return True, "silence on erroneous books scores 0"

    _run(checks, "erroneous_silence", erroneous_silence)

    def duplicate_finding():
        doubled = [copy.deepcopy(findings[0]), copy.deepcopy(findings[0])]
        result = score(episode.truth, _payload(episode, doubled))
        assert result.tp == 1 and result.fp == 1 and result.fn == len(issues) - 1
        expected_f1 = 2 / (len(issues) + 2)
        assert math.isclose(result.f1, expected_f1)
        return True, "a repeated finding earns nothing extra"

    _run(checks, "duplicate_finding", duplicate_finding)

    def wrong_type():
        altered = copy.deepcopy(findings[0])
        altered["type"] = next(
            kind for kind in ERROR_TYPES if kind != altered["type"]
        )
        assert not finding_matches(altered, issues[0])
        return True, "a wrong type cannot match"

    _run(checks, "wrong_type", wrong_type)

    def affected_superset():
        altered = copy.deepcopy(findings[0])
        altered["affected_ids"] = altered["affected_ids"] + ["LED-999999"]
        result = score(episode.truth, _payload(episode, [altered]))
        assert result.tp == 0
        return True, "extra affected ids break canonical equality"

    _run(checks, "affected_superset", affected_superset)

    def affected_subset():
        altered = copy.deepcopy(findings[0])
        altered["affected_ids"] = altered["affected_ids"][:-1]
        result = score(episode.truth, _payload(episode, [altered]))
        assert result.tp == 0
        return True, "a missing affected id cannot match"

    _run(checks, "affected_subset", affected_subset)

    def evidence_missing():
        altered = copy.deepcopy(findings[0])
        altered["evidence_ids"] = []
        result = score(episode.truth, _payload(episode, [altered]))
        assert result.tp == 0
        return True, "no evidence means no match"

    _run(checks, "evidence_missing", evidence_missing)

    def evidence_superset():
        altered = copy.deepcopy(findings[0])
        altered["evidence_ids"] = altered["evidence_ids"] + ["LED-999999"]
        result = score(episode.truth, _payload(episode, [altered]))
        assert result.tp == 1
        return True, "a superset containing the full set still matches"

    _run(checks, "evidence_superset", evidence_superset)

    def evidence_fabricated():
        altered = copy.deepcopy(findings[0])
        altered["evidence_ids"] = ["LED-999999"]
        result = score(episode.truth, _payload(episode, [altered]))
        assert result.tp == 0
        return True, "fabricated evidence cannot match"

    _run(checks, "evidence_fabricated", evidence_fabricated)

    def amount_plus_one():
        altered = copy.deepcopy(findings[0])
        altered["claimed_amount_minor"] += 1
        assert finding_matches(altered, issues[0])
        return True, "one minor unit is inside tolerance"

    _run(checks, "amount_plus_one", amount_plus_one)

    def amount_plus_two():
        altered = copy.deepcopy(findings[0])
        altered["claimed_amount_minor"] += 2
        assert not finding_matches(altered, issues[0])
        return True, "two minor units are outside tolerance"

    _run(checks, "amount_plus_two", amount_plus_two)

    def currency_mismatch():
        altered = copy.deepcopy(findings[0])
        altered["currency"] = "USD" if altered["currency"] != "USD" else "EUR"
        assert not finding_matches(altered, issues[0])
        return True, "a wrong currency cannot match"

    _run(checks, "currency_mismatch", currency_mismatch)

    def mark_all():
        env, evaluator = env_from_episode(episode)
        result = run_episode(env, MarkAllPolicy(), evaluator=evaluator)
        metrics = evaluator.result()
        assert metrics["f1"] <= 0.2
        assert result.reward <= -0.5
        return True, f"F1 {metrics['f1']}, reward {result.reward}"

    _run(checks, "mark_all_attack", mark_all)

    def step_cost():
        cheap = terminal_reward(1.0, 10)
        expensive = terminal_reward(1.0, 100)
        assert math.isclose(cheap - expensive, 90 * STEP_COST)
        return True, "step cost separates equal answers by 0.002 per step"

    _run(checks, "step_cost", step_cost)

    def clipping():
        assert terminal_reward(1.0, 0) == 1.0
        assert terminal_reward(0.0, 0) == -1.0
        assert terminal_reward(1.0, 5000) == -1.0
        assert terminal_reward(0.5, 100) >= -1.0
        return True, "reward is clipped to [-1, 1]"

    _run(checks, "reward_clipping", clipping)

    def malformed_submission():
        evaluator = Evaluator(episode)
        outcome = evaluator.score(
            {
                "episode_id": episode.manifest["episode_id"],
                "findings": [{"type": "not_a_type"}],
            },
            0,
        )
        assert outcome["invalid"] is True and outcome["reward"] == -1.0
        return True, "malformed findings terminate with -1"

    _run(checks, "malformed_submission", malformed_submission)

    def metric_formulas():
        result = score(episode.truth, _payload(episode, findings))
        expected_p = result.tp / (result.tp + result.fp)
        expected_r = result.tp / (result.tp + result.fn)
        expected_f1 = 2 * result.tp / (2 * result.tp + result.fp + result.fn)
        assert math.isclose(result.precision, expected_p)
        assert math.isclose(result.recall, expected_r)
        assert math.isclose(result.f1, expected_f1)
        partial = score(episode.truth, _payload(episode, findings[:2]))
        assert partial.tp == 2 and partial.fn == len(issues) - 2
        return True, "P/R/F1 follow the specified formulas"

    _run(checks, "metric_formulas", metric_formulas)
    return checks


# ---------------------------------------------------------------------------
# criterion 4: reproducibility and generalization

REPLAY_CONFIGS = [
    _config(errors=_errors(duplicate=1, gap=1, fx=1, cutoff=1, composite=1)),
    _config(errors=_errors(duplicate=2, gap=1)),
    _config(errors=_errors(fx=2, cutoff=2)),
    _config(errors=_errors(composite=2)),
    _config(clean=True),
    _config(errors=_errors(duplicate=1, gap=1, fx=1, cutoff=1), days=45),
    _config(errors=_errors(duplicate=1, fx=1, composite=1)),
    _config(errors=_errors(gap=1, cutoff=1, composite=1)),
    _config(errors=_errors(duplicate=1, fx=1), base="USD"),
    _config(errors=_errors(gap=1, cutoff=1), base="EUR"),
]


def _digest_episode(episode: Any) -> str:
    payload = json.dumps(
        {
            "manifest": episode.manifest,
            "ledger": episode.ledger,
            "invoices": episode.invoices,
            "payments": episode.payments,
            "fx": episode.fx,
            "truth": episode.truth,
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _reconciliation_result(episode: Any) -> Any:
    env, evaluator = env_from_episode(episode)
    return run_episode(env, ReconciliationPolicy(), evaluator=evaluator)


def _oracle_result(episode: Any) -> Any:
    env, evaluator = env_from_episode(episode)
    return run_episode(env, OraclePolicy(episode), evaluator=evaluator)


def criterion_reproducibility() -> list[Check]:
    checks: list[Check] = []
    for index, config in enumerate(REPLAY_CONFIGS):
        seed = 9501 + index

        def replay(seed=seed, config=config):
            first = generate_episode(seed, config)
            second = generate_episode(seed, config)
            if _digest_episode(first) != _digest_episode(second):
                return False, "the same seed produced different records"
            left = _reconciliation_result(first)
            right = _reconciliation_result(second)
            if left.steps != right.steps or left.reward != right.reward:
                return False, "the same actions produced different steps or reward"
            if json.dumps(left.metrics, sort_keys=True) != json.dumps(
                right.metrics, sort_keys=True
            ):
                return False, "the same actions produced different metrics"
            return True, f"{left.steps} steps, F1 {left.metrics.get('f1')}"

        _run(checks, f"exact_replay_{index + 1:02d}", replay)

    for index, config in enumerate(REPLAY_CONFIGS):
        seed = 9601 + index

        def permutation(seed=seed, config=config):
            original = generate_episode(seed, config)
            permuted = permute_episode(original, salt=f"verify-{seed}")
            assert_no_reused_ids(original, permuted)
            if permuted.manifest["episode_id"] != original.manifest["episode_id"]:
                return False, "permutation changed the episode identity"
            if len(permuted.truth["issues"]) != len(original.truth["issues"]):
                return False, "permutation changed the number of issues"
            before = _oracle_result(original)
            after = _oracle_result(permuted)
            if before.reward != after.reward or before.metrics.get("f1") != after.metrics.get(
                "f1"
            ):
                return False, "permutation changed the oracle answer or reward"
            original_check = _reconciliation_result(original)
            permuted_check = _reconciliation_result(permuted)
            if original_check.metrics != permuted_check.metrics:
                return False, "permutation changed the baseline metrics"
            if original_check.steps != permuted_check.steps:
                return False, "permutation changed the baseline step count"
            return True, f"all ids renamed, F1 {after.metrics.get('f1')} preserved"

        _run(checks, f"permutation_{index + 1:02d}", permutation)
    return checks


# ---------------------------------------------------------------------------
# criterion 5: engineering


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _has_limitations(text: str) -> bool:
    marker = None
    for candidate in ("## Limitations", "# Limitations", "Limitations\n"):
        if candidate in text:
            marker = candidate
            break
    if marker is None:
        return False
    tail = text.split(marker, 1)[1]
    bullets = [line for line in tail.splitlines() if line.strip().startswith(("-", "*"))]
    return len(bullets) >= 3


def criterion_engineering() -> list[tuple[str, int, str]]:
    readme = _text(ROOT / "README.md")
    dockerfile = _text(ROOT / "Dockerfile")
    design = _text(ROOT / "DESIGN.md")
    index_path = ROOT / "episodes" / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {}

    criteria: list[tuple[str, int, str]] = []

    one_command = 1 if (ROOT / "letro" / "verify.py").exists() else 0
    if one_command and "python -m letro.verify" in readme and "letro.verify" in dockerfile:
        one_command = 2
    criteria.append(
        (
            "one-command launch",
            one_command,
            "python -m letro.verify is documented and the image runs it",
        )
    )

    versions = 0
    if SCHEMA_VERSION:
        versions += 1
    entries = list(index.get("train", [])) + list(index.get("dev", []))
    if (
        index.get("schema_version") == SCHEMA_VERSION
        and entries
        and all(entry.get("config", {}).get("schema_version") == SCHEMA_VERSION for entry in entries)
    ):
        versions += 1
    criteria.append(
        (
            "config versions",
            versions,
            f"{len(entries)} indexed episodes, schema {SCHEMA_VERSION}",
        )
    )

    trajectory_points = 0
    summary: dict[str, Any] = {}
    summary_path = ROOT / "trajectories" / "summary.json"
    if summary_path.exists():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    try:
        report = validate_trajectory_file(ROOT / "trajectories" / "trajectories.jsonl")
    except TrajectoryError as exc:
        report = {"error": str(exc)}
    if "error" not in report:
        trajectory_points = 1
        policies = {run.get("policy") for run in summary.get("runs", [])}
        if report.get("runs", 0) >= 20 and len(policies) >= 2:
            trajectory_points = 2
    criteria.append(
        (
            "trajectory logs",
            trajectory_points,
            f"{report.get('records', 0)} records, {report.get('runs', 0)} runs",
        )
    )

    failure_points = 1 if (ROOT / "docs" / "FAILURE-ANALYSIS.md").exists() else 0
    evidence_path = ROOT / "docs" / "evidence" / "policy-metrics.json"
    if failure_points and evidence_path.exists():
        analysis = _text(ROOT / "docs" / "FAILURE-ANALYSIS.md")
        if any(char.isdigit() for char in analysis) and "F1" in analysis:
            failure_points = 2
    criteria.append(
        (
            "measured failure analysis",
            failure_points,
            "policy metrics and measured failure modes",
        )
    )

    limitation_points = 1 if ("Limitations" in readme or "Limitations" in design) else 0
    if limitation_points and (_has_limitations(readme) or _has_limitations(design)):
        limitation_points = 2
    criteria.append(
        (
            "honest limitations",
            limitation_points,
            "explicit limitations section",
        )
    )
    return criteria


# ---------------------------------------------------------------------------
# report


def _score(checks: list[Check], weight: float) -> float:
    if not checks:
        return 0.0
    return weight * sum(1 for check in checks if check.passed) / len(checks)


def main() -> int:
    print("LETRO verification")
    print(f"root: {ROOT}")
    print(f"schema: {SCHEMA_VERSION}, python: {sys.version.split()[0]}")
    print()

    contract = criterion_contract()
    index_path = ROOT / "episodes" / "index.json"
    if not index_path.exists():
        print("episodes/index.json is missing; run python scripts/build_episodes.py")
        return 2
    index = json.loads(index_path.read_text(encoding="utf-8"))
    dev_entries = list(index.get("dev", []))
    data = criterion_data(dev_entries)
    reward = criterion_reward()
    reproducibility = criterion_reproducibility()
    engineering = criterion_engineering()

    rows = [
        ("Contract and isolation", contract, 25.0),
        ("Data and truth", data, 25.0),
        ("Reward reliability", reward, 25.0),
        ("Reproducibility and generalization", reproducibility, 15.0),
    ]
    total = 0.0
    print(f"{'criterion':<34}{'checks':>10}{'score':>10}")
    for name, checks, weight in rows:
        passed = sum(1 for check in checks if check.passed)
        value = _score(checks, weight)
        total += value
        print(f"{name:<34}{passed:>5}/{len(checks):<4}{value:>10.2f}")

    engineering_points = sum(points for _name, points, _detail in engineering)
    total += engineering_points
    print(f"{'Engineering and explanation':<34}{engineering_points:>5}/10  {float(engineering_points):>10.2f}")
    print("-" * 54)
    print(f"{'TOTAL':<34}{'':>10}{total:>10.2f}")
    print()

    failures = [
        (name, check)
        for name, checks, _weight in rows
        for check in checks
        if not check.passed
    ]
    if failures:
        print("FAILED CHECKS")
        for name, check in failures:
            print(f"- {name} / {check.name}: {check.detail}")
        print()
    if engineering_points < 10:
        print("ENGINEERING POINTS NOT EARNED")
        for name, points, detail in engineering:
            if points < 2:
                print(f"- {name} ({points}/2): {detail}")
        print()

    if failures or engineering_points < 10:
        print("RESULT: FAIL")
        return 1
    print("RESULT: PASS (all 100 checks and engineering criteria)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
