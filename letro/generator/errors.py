"""Error injection: four independent types plus two interacting scenarios.

Every mutation keeps each journal entry balanced. Truth is not written by hand;
it is derived by the independent reference audit after injection, so the closed
answer can never describe something the open records do not prove.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from ..money import convert_minor
from ..rng import rng_for
from .audit import reference_audit
from .model import Episode, iso_day, parse_offset, proportional_base, rate_on


class GenerationError(RuntimeError):
    """The generator produced data its own audit cannot explain."""


AR = "1100"
REVENUE = "4000"
CASH = "1000"
FX = "4900"
SUSPENSE = "9999"


def _next_number(episode: Episode, prefix: str, field: str) -> int:
    highest = 0
    for row in episode.ledger:
        value = row.get(field)
        if isinstance(value, str) and value.startswith(prefix + "-"):
            try:
                highest = max(highest, int(value.rsplit("-", 1)[1]))
            except ValueError:
                continue
    return highest + 1


def _new_row_id(episode: Episode) -> str:
    return f"LED-{_next_number(episode, 'LED', 'row_id'):06d}"


def _new_payment_id(episode: Episode) -> str:
    highest = 0
    for payment in episode.payments:
        try:
            highest = max(highest, int(payment["payment_id"].rsplit("-", 1)[1]))
        except (KeyError, ValueError):
            continue
    return f"PAY-{highest + 1:04d}"


def _add_row(episode: Episode, **values: Any) -> dict[str, Any]:
    row = {
        "row_id": _new_row_id(episode),
        "timestamp": values["timestamp"],
        "account": values["account"],
        "debit_minor": int(values.get("debit_minor", 0)),
        "credit_minor": int(values.get("credit_minor", 0)),
        "currency": episode.manifest["base_currency"],
        "entity_id": values["entity_id"],
        "invoice_id": values.get("invoice_id"),
        "payment_id": values.get("payment_id"),
    }
    episode.ledger.append(row)
    return row


def _base(episode: Episode, invoice: dict[str, Any]) -> int:
    return convert_minor(
        invoice["total_minor"],
        rate_on(episode, invoice["currency"], invoice["issued_at"][:10]),
        invoice["currency"],
        episode.manifest["base_currency"],
    )


def _payment_base(episode: Episode, payment: dict[str, Any]) -> int:
    return convert_minor(
        abs(payment["amount_minor"]),
        rate_on(episode, payment["currency"], payment["timestamp"][:10]),
        payment["currency"],
        episode.manifest["base_currency"],
    )


def _offset(episode: Episode) -> str:
    return episode.config["timezone_offset"]


def _inside(episode: Episode, timestamp: str) -> bool:
    start = datetime.fromisoformat(episode.manifest["period_start"])
    end = datetime.fromisoformat(episode.manifest["period_end"])
    return start <= datetime.fromisoformat(timestamp) <= end


def _shift(timestamp: str, days: int) -> str:
    return (datetime.fromisoformat(timestamp) + timedelta(days=days)).isoformat()


def _shift_within(episode: Episode, timestamp: str, days: int) -> str:
    shifted = _shift(timestamp, days)
    if _inside(episode, shifted):
        return shifted
    return _shift(timestamp, -days)


def _invoice_rows(episode: Episode, invoice_id: str) -> tuple[list, list]:
    ar_rows = [
        row
        for row in episode.ledger
        if row["invoice_id"] == invoice_id
        and row["account"] == AR
        and row["debit_minor"] > 0
    ]
    revenue_rows = [
        row
        for row in episode.ledger
        if row["invoice_id"] == invoice_id
        and row["account"] == REVENUE
        and row["credit_minor"] > 0
        and row["timestamp"] == (ar_rows[0]["timestamp"] if ar_rows else None)
    ]
    return ar_rows, revenue_rows


def _foreign_rate_error(episode: Episode, currency: str, day: str, amount_minor: int) -> tuple[int, int, str]:
    """Find a nearby day whose converted amount differs measurably."""
    correct = convert_minor(
        amount_minor,
        rate_on(episode, currency, day),
        currency,
        episode.manifest["base_currency"],
    )
    date = datetime.fromisoformat(day + "T09:00:00")
    for step in (1, 2, 3, 4, 5, 6, 7):
        candidate_day = (date - timedelta(days=step)).date().isoformat()
        wrong = convert_minor(
            amount_minor,
            rate_on(episode, currency, candidate_day),
            currency,
            episode.manifest["base_currency"],
        )
        if abs(wrong - correct) > 5:
            return wrong, correct, candidate_day
    for step in (1, 2, 3, 4, 5, 6, 7):
        candidate_day = (date + timedelta(days=step)).date().isoformat()
        wrong = convert_minor(
            amount_minor,
            rate_on(episode, currency, candidate_day),
            currency,
            episode.manifest["base_currency"],
        )
        if abs(wrong - correct) > 5:
            return wrong, correct, candidate_day
    raise GenerationError("could not find a measurably different FX rate")


def _candidates(episode: Episode, rng, used: set[str], foreign: bool | None = None):
    values = []
    for invoice in episode.invoices:
        if invoice["invoice_id"] in used:
            continue
        ar_rows, revenue_rows = _invoice_rows(episode, invoice["invoice_id"])
        if len(ar_rows) != 1 or len(revenue_rows) != 1:
            continue
        is_foreign = invoice["currency"] != episode.manifest["base_currency"]
        if foreign is not None and is_foreign != foreign:
            continue
        values.append(invoice)
    rng.shuffle(values)
    return values


def _inject_duplicate(episode: Episode, rng, used: set[str]) -> dict[str, Any] | None:
    for invoice in _candidates(episode, rng, used):
        ar_rows, revenue_rows = _invoice_rows(episode, invoice["invoice_id"])
        ar, revenue = ar_rows[0], revenue_rows[0]
        timestamp = _shift_within(episode, ar["timestamp"], 1)
        duplicate_ar = _add_row(
            episode,
            timestamp=timestamp,
            account=AR,
            debit_minor=ar["debit_minor"],
            entity_id=invoice["entity_id"],
            invoice_id=invoice["invoice_id"],
        )
        duplicate_revenue = _add_row(
            episode,
            timestamp=timestamp,
            account=REVENUE,
            credit_minor=revenue["credit_minor"],
            entity_id=invoice["entity_id"],
            invoice_id=invoice["invoice_id"],
        )
        used.add(invoice["invoice_id"])
        return {
            "kind": "duplicate_invoice",
            "invoice_id": invoice["invoice_id"],
            "rows": [duplicate_ar["row_id"], duplicate_revenue["row_id"]],
        }
    return None


def _inject_gap(episode: Episode, rng, used: set[str]) -> dict[str, Any] | None:
    base = episode.manifest["base_currency"]
    payments = [
        payment
        for payment in episode.payments
        if payment["amount_minor"] > 0
        and payment["payment_id"] not in used
        and payment["currency"] == base
        and payment["invoice_refs"]
    ]
    rng.shuffle(payments)
    for payment in payments:
        invoice = next(
            (
                item
                for item in episode.invoices
                if item["invoice_id"] == payment["invoice_refs"][0]
            ),
            None,
        )
        if invoice is None or invoice["invoice_id"] in used:
            continue
        ar_rows = [
            row
            for row in episode.ledger
            if row["payment_id"] == payment["payment_id"]
            and row["account"] == AR
            and row["credit_minor"] > 0
        ]
        if len(ar_rows) != 1:
            continue
        ar = ar_rows[0]
        gap = max(1, int(ar["credit_minor"] * 0.4))
        ar["credit_minor"] -= gap
        suspense = _add_row(
            episode,
            timestamp=ar["timestamp"],
            account=SUSPENSE,
            credit_minor=gap,
            entity_id=invoice["entity_id"],
            invoice_id=invoice["invoice_id"],
            payment_id=payment["payment_id"],
        )
        used.add(payment["payment_id"])
        used.add(invoice["invoice_id"])
        return {
            "kind": "payment_allocation_gap",
            "payment_id": payment["payment_id"],
            "invoice_id": invoice["invoice_id"],
            "gap_minor": gap,
            "suspense_row": suspense["row_id"],
        }
    return None


def _inject_fx_invoice(episode: Episode, rng, used: set[str]) -> dict[str, Any] | None:
    for invoice in _candidates(episode, rng, used, foreign=True):
        ar_rows, revenue_rows = _invoice_rows(episode, invoice["invoice_id"])
        ar, revenue = ar_rows[0], revenue_rows[0]
        wrong, correct, wrong_day = _foreign_rate_error(
            episode, invoice["currency"], invoice["issued_at"][:10], invoice["total_minor"]
        )
        if wrong == correct:
            continue
        ar["debit_minor"] = wrong
        revenue["credit_minor"] = wrong
        used.add(invoice["invoice_id"])
        return {
            "kind": "fx_rate_error",
            "scope": "invoice",
            "invoice_id": invoice["invoice_id"],
            "rows": [ar["row_id"], revenue["row_id"]],
            "correct_minor": correct,
            "wrong_minor": wrong,
            "wrong_rate_day": wrong_day,
        }
    return None


def _inject_fx_payment(episode: Episode, rng, used: set[str]) -> dict[str, Any] | None:
    base = episode.manifest["base_currency"]
    payments = [
        payment
        for payment in episode.payments
        if payment["amount_minor"] > 0
        and payment["currency"] != base
        and payment["payment_id"] not in used
    ]
    rng.shuffle(payments)
    for payment in payments:
        cash_rows = [
            row
            for row in episode.ledger
            if row["payment_id"] == payment["payment_id"]
            and row["account"] == CASH
            and row["debit_minor"] > 0
        ]
        fx_rows = [
            row
            for row in episode.ledger
            if row["payment_id"] == payment["payment_id"] and row["account"] == FX
        ]
        if len(cash_rows) != 1 or len(fx_rows) != 1:
            continue
        cash = cash_rows[0]
        fx = fx_rows[0]
        signed_fx = fx["credit_minor"] - fx["debit_minor"]
        correct = cash["debit_minor"]
        date = datetime.fromisoformat(payment["timestamp"])
        chosen = None
        for step in range(1, 8):
            candidate_day = (date - timedelta(days=step)).date().isoformat()
            wrong = convert_minor(
                payment["amount_minor"],
                rate_on(episode, payment["currency"], candidate_day),
                payment["currency"],
                base,
            )
            if wrong < correct - 5:
                chosen = (wrong, candidate_day)
                break
        if chosen is None:
            continue
        wrong, wrong_day = chosen
        delta = wrong - correct
        cash["debit_minor"] = wrong
        new_signed = signed_fx + delta
        fx["credit_minor"] = max(new_signed, 0)
        fx["debit_minor"] = max(-new_signed, 0)
        used.add(payment["payment_id"])
        return {
            "kind": "fx_rate_error",
            "scope": "payment",
            "payment_id": payment["payment_id"],
            "rows": [cash["row_id"], fx["row_id"]],
            "correct_minor": correct,
            "wrong_minor": wrong,
            "wrong_rate_day": wrong_day,
        }
    return None


def _inject_cutoff(episode: Episode, rng, used: set[str]) -> dict[str, Any] | None:
    invoices = [
        invoice
        for invoice in _candidates(episode, rng, used)
        if not any(
            row["invoice_id"] == invoice["invoice_id"] and row["payment_id"]
            for row in episode.ledger
        )
    ]
    if not invoices:
        invoices = _candidates(episode, rng, used)
    for invoice in invoices:
        ar_rows, revenue_rows = _invoice_rows(episode, invoice["invoice_id"])
        if len(ar_rows) != 1:
            continue
        outside = _shift(episode.manifest["period_end"], 2)
        for row in ar_rows + revenue_rows:
            row["timestamp"] = outside
        used.add(invoice["invoice_id"])
        return {
            "kind": "period_cutoff",
            "scope": "invoice",
            "invoice_id": invoice["invoice_id"],
            "rows": [row["row_id"] for row in ar_rows + revenue_rows],
            "posted_at": outside,
        }
    return None


def _create_partial_payment(
    episode: Episode,
    invoice: dict[str, Any],
    fraction: float,
    timestamp: str,
) -> tuple[dict[str, Any], list[dict[str, Any]], int, int]:
    amount = max(1, int(invoice["total_minor"] * fraction))
    if amount >= invoice["total_minor"]:
        amount = invoice["total_minor"] - 1
    payment_id = _new_payment_id(episode)
    payment = {
        "doc_id": f"DOC-{payment_id}",
        "payment_id": payment_id,
        "timestamp": timestamp,
        "currency": invoice["currency"],
        "amount_minor": amount,
        "invoice_refs": [invoice["invoice_id"]],
    }
    episode.payments.append(payment)
    cash = convert_minor(
        amount,
        rate_on(episode, invoice["currency"], timestamp[:10]),
        invoice["currency"],
        episode.manifest["base_currency"],
    )
    allocated = proportional_base(_base(episode, invoice), amount, invoice["total_minor"])
    signed_fx = cash - allocated
    rows = [
        _add_row(
            episode,
            timestamp=timestamp,
            account=CASH,
            debit_minor=cash,
            entity_id=invoice["entity_id"],
            invoice_id=invoice["invoice_id"],
            payment_id=payment_id,
        ),
        _add_row(
            episode,
            timestamp=timestamp,
            account=AR,
            credit_minor=allocated,
            entity_id=invoice["entity_id"],
            invoice_id=invoice["invoice_id"],
            payment_id=payment_id,
        ),
    ]
    if signed_fx:
        rows.append(
            _add_row(
                episode,
                timestamp=timestamp,
                account=FX,
                credit_minor=max(signed_fx, 0),
                debit_minor=max(-signed_fx, 0),
                entity_id=invoice["entity_id"],
                invoice_id=invoice["invoice_id"],
                payment_id=payment_id,
            )
        )
    return payment, rows, cash, allocated


def _composite_boundary_fx(episode: Episode, rng, used: set[str]) -> dict[str, Any] | None:
    foreign = [
        invoice
        for invoice in _candidates(episode, rng, used, foreign=True)
        if not any(
            row["invoice_id"] == invoice["invoice_id"] and row["payment_id"]
            for row in episode.ledger
        )
    ]
    if not foreign:
        return _composite_gap_cutoff(episode, rng, used)
    invoice = foreign[0]
    timestamp = episode.manifest["period_end"]
    payment, rows, cash, allocated = _create_partial_payment(
        episode, invoice, 0.6, timestamp
    )
    cash_row = next(row for row in rows if row["account"] == CASH)
    fx_row = next((row for row in rows if row["account"] == FX), None)
    if fx_row is None:
        # Without an FX row the two errors cannot interact; fall back.
        episode.ledger = [row for row in episode.ledger if row["row_id"] not in {r["row_id"] for r in rows}]
        episode.payments = [item for item in episode.payments if item["payment_id"] != payment["payment_id"]]
        return _composite_gap_cutoff(episode, rng, used)

    date = datetime.fromisoformat(timestamp)
    chosen = None
    for step in range(1, 8):
        candidate_day = (date - timedelta(days=step)).date().isoformat()
        wrong = convert_minor(
            payment["amount_minor"],
            rate_on(episode, payment["currency"], candidate_day),
            payment["currency"],
            episode.manifest["base_currency"],
        )
        if wrong < cash - 5:
            chosen = (wrong, candidate_day)
            break
    if chosen is None:
        return _composite_gap_cutoff(episode, rng, used)
    wrong, wrong_day = chosen
    delta = wrong - cash
    cash_row["debit_minor"] = wrong
    signed_fx = fx_row["credit_minor"] - fx_row["debit_minor"] + delta
    fx_row["credit_minor"] = max(signed_fx, 0)
    fx_row["debit_minor"] = max(-signed_fx, 0)
    outside = _shift(timestamp, 1)
    for row in rows:
        row["timestamp"] = outside
    used.add(invoice["invoice_id"])
    used.add(payment["payment_id"])
    return {
        "kind": "composite",
        "scope": "boundary_fx_payment",
        "invoice_id": invoice["invoice_id"],
        "payment_id": payment["payment_id"],
        "rows": [row["row_id"] for row in rows],
        "wrong_rate_day": wrong_day,
        "posted_at": outside,
    }


def _composite_gap_cutoff(episode: Episode, rng, used: set[str]) -> dict[str, Any] | None:
    base = episode.manifest["base_currency"]
    invoices = [
        invoice
        for invoice in _candidates(episode, rng, used, foreign=False)
        if invoice["currency"] == base
        and not any(
            row["invoice_id"] == invoice["invoice_id"] and row["payment_id"]
            for row in episode.ledger
        )
    ]
    if not invoices:
        return None
    invoice = invoices[0]
    timestamp = episode.manifest["period_end"]
    payment, rows, cash, allocated = _create_partial_payment(
        episode, invoice, 0.6, timestamp
    )
    ar_row = next(row for row in rows if row["account"] == AR)
    gap = max(1, int(allocated * 0.4))
    ar_row["credit_minor"] -= gap
    suspense = _add_row(
        episode,
        timestamp=timestamp,
        account=SUSPENSE,
        credit_minor=gap,
        entity_id=invoice["entity_id"],
        invoice_id=invoice["invoice_id"],
        payment_id=payment["payment_id"],
    )
    rows.append(suspense)
    outside = _shift(timestamp, 1)
    for row in rows:
        row["timestamp"] = outside
    used.add(invoice["invoice_id"])
    used.add(payment["payment_id"])
    return {
        "kind": "composite",
        "scope": "gap_cutoff_payment",
        "invoice_id": invoice["invoice_id"],
        "payment_id": payment["payment_id"],
        "rows": [row["row_id"] for row in rows],
        "gap_minor": gap,
        "posted_at": outside,
    }


def inject_errors(episode: Episode, seed: int, config: dict[str, Any]) -> list[dict[str, Any]]:
    """Apply configured errors and derive truth from the reference audit."""
    if config.get("clean"):
        issues = reference_audit(episode)
        if issues:
            raise GenerationError(
                f"clean episode produced {len(issues)} audit issues"
            )
        episode.truth = {
            "episode_id": episode.manifest["episode_id"],
            "issues": [],
        }
        return []

    rng = rng_for(seed, "errors")
    used: set[str] = set()
    steps: list[dict[str, Any]] = []
    errors = config["errors"]

    plan: list[tuple[str, Any]] = []
    for _ in range(errors.get("duplicate_invoice", 0)):
        plan.append(("duplicate_invoice", _inject_duplicate))
    for _ in range(errors.get("payment_allocation_gap", 0)):
        plan.append(("payment_allocation_gap", _inject_gap))
    for _ in range(errors.get("fx_rate_error", 0)):
        plan.append(("fx_rate_error", None))
    for _ in range(errors.get("period_cutoff", 0)):
        plan.append(("period_cutoff", _inject_cutoff))
    for _ in range(errors.get("composite", 0)):
        plan.append(("composite", None))

    fx_counter = 0
    composite_counter = 0
    for kind, function in plan:
        step = None
        if kind == "duplicate_invoice":
            step = function(episode, rng, used)
        elif kind == "payment_allocation_gap":
            step = function(episode, rng, used)
        elif kind == "fx_rate_error":
            fx_counter += 1
            step = _inject_fx_invoice(episode, rng, used)
            if step is None:
                step = _inject_fx_payment(episode, rng, used)
        elif kind == "period_cutoff":
            step = function(episode, rng, used)
        elif kind == "composite":
            composite_counter += 1
            if composite_counter % 2 == 1:
                step = _composite_boundary_fx(episode, rng, used)
            else:
                step = _composite_gap_cutoff(episode, rng, used)
            if step is None:
                step = _composite_gap_cutoff(episode, rng, used)
            if step is None:
                step = _composite_boundary_fx(episode, rng, used)
        if step is None:
            raise GenerationError(f"could not inject configured {kind}")
        steps.append(step)

    issues = reference_audit(episode)
    expected = sum(
        errors.get(key, 0)
        for key in (
            "duplicate_invoice",
            "payment_allocation_gap",
            "fx_rate_error",
            "period_cutoff",
        )
    ) + 2 * errors.get("composite", 0)
    if len(issues) != expected:
        found = [issue["type"] for issue in issues]
        raise GenerationError(
            f"audit found {len(issues)} issues, expected {expected}: {found}"
        )
    episode.truth = {
        "episode_id": episode.manifest["episode_id"],
        "issues": issues,
    }
    episode.provenance = {
        "episode_id": episode.manifest["episode_id"],
        "seed_fingerprint": f"{seed}:{config['variant']}",
        "steps": steps,
    }
    return steps
