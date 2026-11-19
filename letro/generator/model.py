"""Shared episode model and money/rate helpers for the generator."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from ..money import convert_minor, from_minor, to_minor


@dataclass
class Episode:
    manifest: dict[str, Any]
    ledger: list[dict[str, Any]]
    invoices: list[dict[str, Any]]
    payments: list[dict[str, Any]]
    fx: list[dict[str, Any]]
    policy: dict[str, Any]
    truth: dict[str, Any]
    provenance: dict[str, Any]
    config: dict[str, Any]
    entries: list[list[str]] = field(default_factory=list)

    def open_data(self) -> dict[str, Any]:
        return {
            "manifest": self.manifest,
            "ledger": self.ledger,
            "invoices": self.invoices,
            "payments": self.payments,
            "fx": self.fx,
            "policy": self.policy,
        }


def parse_offset(offset: str) -> timezone:
    sign = 1
    text = offset.strip()
    if text.startswith("-"):
        sign = -1
        text = text[1:]
    elif text.startswith("+"):
        text = text[1:]
    hours, minutes = text.split(":")
    return timezone(sign * timedelta(hours=int(hours), minutes=int(minutes)))


def iso_day(day: date, offset: str, end_of_day: bool = False) -> str:
    tz = parse_offset(offset)
    if end_of_day:
        moment = datetime(day.year, day.month, day.day, 23, 59, 59, tzinfo=tz)
    else:
        moment = datetime(day.year, day.month, day.day, 9, 0, 0, tzinfo=tz)
    return moment.isoformat()


def date_of(timestamp: str) -> str:
    return timestamp[:10]


def fx_map(fx_rows: list[dict[str, Any]]) -> dict[tuple[str, str, str], str]:
    return {
        (row["source_currency"], row["target_currency"], row["date"]): row["rate"]
        for row in fx_rows
    }


def rate_on(
    episode: Episode, currency: str, day: str
) -> Decimal:
    base = episode.manifest["base_currency"]
    if currency == base:
        return Decimal(1)
    mapping = fx_map(episode.fx)
    key = (currency, base, day)
    if key in mapping:
        return Decimal(mapping[key])
    # Deterministic fallback: nearest earlier available date.
    candidates = sorted(
        row["date"]
        for row in episode.fx
        if row["source_currency"] == currency and row["target_currency"] == base
    )
    earlier = [value for value in candidates if value <= day]
    if not earlier:
        raise KeyError(f"no FX rate for {currency} on {day}")
    return Decimal(mapping[(currency, base, earlier[-1])])


def invoice_base(episode: Episode, invoice: dict[str, Any]) -> int:
    rate = rate_on(episode, invoice["currency"], invoice["issued_at"][:10])
    return convert_minor(
        invoice["total_minor"], rate, invoice["currency"], episode.manifest["base_currency"]
    )


def payment_base(episode: Episode, payment: dict[str, Any]) -> int:
    rate = rate_on(episode, payment["currency"], payment["timestamp"][:10])
    return convert_minor(
        abs(payment["amount_minor"]), rate, payment["currency"], episode.manifest["base_currency"]
    )


def proportional_base(total_base: int, part: int, total: int) -> int:
    if total <= 0:
        return 0
    value = (Decimal(total_base) * Decimal(part) / Decimal(total)).quantize(
        Decimal(1), rounding=ROUND_HALF_UP
    )
    return int(value)


def new_row(
    row_id: str,
    timestamp: str,
    account: str,
    debit_minor: int,
    credit_minor: int,
    currency: str,
    entity_id: str,
    invoice_id: str | None,
    payment_id: str | None,
) -> dict[str, Any]:
    return {
        "row_id": row_id,
        "timestamp": timestamp,
        "account": account,
        "debit_minor": debit_minor,
        "credit_minor": credit_minor,
        "currency": currency,
        "entity_id": entity_id,
        "invoice_id": invoice_id,
        "payment_id": payment_id,
    }


def entry_balanced(rows: list[dict[str, Any]]) -> bool:
    debits = sum(row["debit_minor"] for row in rows)
    credits = sum(row["credit_minor"] for row in rows)
    return debits == credits


__all__ = [
    "Episode",
    "date_of",
    "entry_balanced",
    "fx_map",
    "invoice_base",
    "iso_day",
    "new_row",
    "parse_offset",
    "payment_base",
    "proportional_base",
    "rate_on",
    "to_minor",
    "from_minor",
]
