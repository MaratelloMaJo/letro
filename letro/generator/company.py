"""Synthetic company construction.

Builds a clean, double-entry set of books from documents, before any error is
injected. The clean books are the invariant baseline the auditor reconstructs.
"""

from __future__ import annotations

import hashlib
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from ..constants import DEFAULT_POLICY, SCHEMA_VERSION
from ..money import convert_minor, to_minor
from ..rng import deterministic_id, rng_for
from .model import (
    Episode,
    date_of,
    iso_day,
    new_row,
    proportional_base,
    rate_on,
    to_minor as _to_minor,
)

CUSTOMERS = (
    "Saryarka Retail LLP",
    "Caspian Freight JSC",
    "Orken Foods LLP",
    "Turan Metals JSC",
    "Zhetysu Services LLP",
    "Alatau Systems JSC",
    "Syrdarya Logistics LLP",
    "Mangystau Energy JSC",
    "Kokshetau Agro LLP",
    "Irtysh Digital JSC",
)

SUPPLIERS = (
    "Office Hub LLP",
    "Cloud Nine KZ LLP",
    "Astana Facilities LLP",
    "Legal Compass LLP",
    "Data Forge LLP",
)

SERVICES = (
    "Freight forwarding",
    "Warehouse handling",
    "Customs brokerage",
    "Fleet maintenance",
    "Retail display setup",
    "Regional delivery",
    "Inventory audit",
    "Packaging services",
)

EXPENSES = (
    ("Office rent", 1_850_000),
    ("Warehouse rent", 2_400_000),
    ("Payroll", 12_600_000),
    ("Cloud infrastructure", 780_000),
    ("Marketing", 1_150_000),
    ("Utilities", 430_000),
    ("Professional fees", 920_000),
    ("Insurance", 610_000),
)

BASE_START_RATES = {
    "KZT": {"USD": "472.350000", "EUR": "511.800000"},
    "USD": {"EUR": "0.923400", "KZT": "0.002117"},
    "EUR": {"USD": "1.082900", "KZT": "0.001954"},
}


def _episode_id(seed: int, variant: int) -> str:
    digest = hashlib.sha256(f"letro-episode:{seed}:{variant}".encode()).hexdigest()
    return f"ep-{digest[:10]}"


def _month_start(seed: int) -> date:
    choices = (
        date(2025, 9, 1),
        date(2025, 10, 1),
        date(2025, 11, 1),
        date(2026, 2, 1),
        date(2026, 3, 1),
        date(2026, 4, 1),
        date(2026, 5, 1),
    )
    return choices[seed % len(choices)]


def _build_fx(seed: int, config: dict[str, Any], start: date, days: int) -> list[dict[str, Any]]:
    base = config["base_currency"]
    rng = rng_for(seed, "fx")
    rows: list[dict[str, Any]] = []
    for source, start_rate in BASE_START_RATES[base].items():
        rate = Decimal(start_rate)
        cursor = start - timedelta(days=10)
        end = start + timedelta(days=days + 5)
        while cursor <= end:
            drift = Decimal(rng.randint(-30, 30)) / Decimal(10000)
            rate = (rate * (Decimal(1) + drift)).quantize(
                Decimal("0.000001"), rounding=ROUND_HALF_UP
            )
            if rate <= 0:
                rate = Decimal(start_rate)
            rows.append(
                {
                    "date": cursor.isoformat(),
                    "source_currency": source,
                    "target_currency": base,
                    "rate": f"{rate:.6f}",
                }
            )
            cursor += timedelta(days=1)
    rows.sort(key=lambda row: (row["date"], row["source_currency"]))
    return rows


def _invoice_lines(rng, currency: str) -> tuple[list[dict[str, Any]], int]:
    count = rng.choice((1, 1, 2, 3))
    lines = []
    total = 0
    for _ in range(count):
        if currency == "KZT":
            unit = rng.randrange(180_000, 4_800_000, 10_000)
        elif currency == "JPY":
            unit = rng.randrange(20_000, 600_000, 1_000)
        else:
            unit = rng.randrange(900, 42_000, 100)
        quantity = rng.randint(1, 9)
        amount = unit * quantity
        total += amount
        lines.append(
            {
                "description": rng.choice(SERVICES),
                "quantity": quantity,
                "unit_price_minor": unit,
                "amount_minor": amount,
            }
        )
    return lines, total


def _pick_currency(rng, base: str) -> str:
    roll = rng.random()
    if roll < 0.72:
        return base
    if roll < 0.9:
        return "USD" if base != "USD" else "EUR"
    return "EUR" if base != "EUR" else "USD"


def build_company(seed: int, config: dict[str, Any]) -> Episode:
    rng = rng_for(seed, "company")
    base = config["base_currency"]
    offset = config["timezone_offset"]
    days = config["period_days"]
    start = _month_start(seed) + timedelta(days=config["variant"] % 27)
    end = start + timedelta(days=days - 1)

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "episode_id": _episode_id(seed, config["variant"]),
        "base_currency": base,
        "period_start": iso_day(start, offset, end_of_day=False),
        "period_end": iso_day(end, offset, end_of_day=True),
        "timezone": "Asia/Almaty" if offset == "+05:00" else "UTC",
        "ledger_rows": 0,
        "documents": 0,
        "rounding": "half_up",
        "fx_rate_date": "invoice_date_for_documents,payment_date_for_payments",
    }
    policy = dict(DEFAULT_POLICY)
    policy.update(
        {
            "period_start": manifest["period_start"],
            "period_end": manifest["period_end"],
            "timezone": manifest["timezone"],
            "base_currency": base,
            "fx_rate_date_invoice": "invoice_date",
            "fx_rate_date_payment": "payment_date",
            "evidence_rule": "at_least_one_complete_allowed_set",
        }
    )

    fx = _build_fx(seed, config, start, days)
    episode = Episode(
        manifest=manifest,
        ledger=[],
        invoices=[],
        payments=[],
        fx=fx,
        policy=policy,
        truth={"episode_id": manifest["episode_id"], "issues": []},
        provenance={"episode_id": manifest["episode_id"], "steps": []},
        config=config,
    )

    entities = [
        {"entity_id": "E1", "name": "Altyn Holding JSC", "role": "parent"},
        {"entity_id": "E2", "name": "Altyn Logistics LLP", "role": "subsidiary"},
        {"entity_id": "E3", "name": "Altyn Trade LLP", "role": "subsidiary"},
    ]

    invoice_count = config["sizes"]["invoices"]
    issued_span = max(4, int(days * 0.68))
    for index in range(invoice_count):
        entity = entities[index % len(entities)]
        currency = _pick_currency(rng, base)
        issued_day = start + timedelta(days=rng.randint(0, issued_span))
        due_day = issued_day + timedelta(days=rng.randint(12, 45))
        lines, total = _invoice_lines(rng, currency)
        invoice_id = deterministic_id("INV", index + 1, 4)
        episode.invoices.append(
            {
                "doc_id": deterministic_id("DOC-INV", index + 1, 4),
                "invoice_id": invoice_id,
                "entity_id": entity["entity_id"],
                "customer": rng.choice(CUSTOMERS),
                "issued_at": iso_day(issued_day, offset),
                "due_at": iso_day(due_day, offset),
                "currency": currency,
                "total_minor": total,
                "line_items": lines,
            }
        )

    # Invoice postings: AR debit / revenue credit, converted at invoice date.
    row_number = 0
    ledger: list[dict[str, Any]] = []
    entries: list[list[str]] = []

    def add_entry(
        timestamp: str,
        entity_id: str,
        invoice_id: str | None,
        payment_id: str | None,
        postings: list[tuple[str, int, int]],
    ) -> list[str]:
        nonlocal row_number
        ids = []
        for account, debit, credit in postings:
            if debit == 0 and credit == 0:
                continue
            row_number += 1
            row_id = deterministic_id("LED", row_number)
            ledger.append(
                new_row(
                    row_id,
                    timestamp,
                    account,
                    debit,
                    credit,
                    base,
                    entity_id,
                    invoice_id,
                    payment_id,
                )
            )
            ids.append(row_id)
        entries.append(ids)
        return ids

    for invoice in episode.invoices:
        amount = convert_minor(
            invoice["total_minor"],
            rate_on(episode, invoice["currency"], invoice["issued_at"][:10]),
            invoice["currency"],
            base,
        )
        add_entry(
            invoice["issued_at"],
            invoice["entity_id"],
            invoice["invoice_id"],
            None,
            [("1100", amount, 0), ("4000", 0, amount)],
        )

    # Payments: full, split, partial and refunds.
    payment_target = config["sizes"]["payments"]
    payment_number = 0
    payment_plan: list[tuple[dict[str, Any], list[int]]] = []
    payable = list(episode.invoices)
    rng.shuffle(payable)
    for invoice in payable:
        if payment_number >= payment_target:
            break
        # Leave some invoices legitimately open.
        if rng.random() < 0.18:
            continue
        if (
            config.get("split_payment", True)
            and rng.random() < 0.2
            and payment_target - payment_number >= 2
        ):
            split = rng.uniform(0.35, 0.65)
            first = int(invoice["total_minor"] * split)
            parts = [first, invoice["total_minor"] - first]
            if min(parts) <= 0:
                parts = [invoice["total_minor"]]
        elif rng.random() < 0.12:
            parts = [int(invoice["total_minor"] * rng.uniform(0.4, 0.75))]
        else:
            parts = [invoice["total_minor"]]
        payment_plan.append((invoice, parts))
        payment_number += len(parts)
    if payment_number > payment_target and payment_plan:
        # Trim whole invoice plans from the end; never leave a partial plan.
        while payment_number > payment_target and len(payment_plan) > 1:
            invoice, parts = payment_plan.pop()
            payment_number -= len(parts)

    paid_invoices: list[dict[str, Any]] = []
    split_created = False
    for invoice, parts in payment_plan:
        issued_day = date.fromisoformat(invoice["issued_at"][:10])
        earliest = issued_day + timedelta(days=1)
        latest = min(
            end,
            date.fromisoformat(invoice["due_at"][:10]),
            start + timedelta(days=int(days * 0.92)),
        )
        if latest < earliest:
            latest = min(end, earliest)
        allocated_so_far = 0
        invoice_base_amount = convert_minor(
            invoice["total_minor"],
            rate_on(episode, invoice["currency"], invoice["issued_at"][:10]),
            invoice["currency"],
            base,
        )
        for part_index, part in enumerate(parts):
            payment_number += 0
            pay_seq = len(episode.payments) + 1
            payment_id = deterministic_id("PAY", pay_seq, 4)
            pay_day = earliest + timedelta(
                days=rng.randint(0, max(0, (latest - earliest).days))
            )
            timestamp = iso_day(pay_day, offset)
            episode.payments.append(
                {
                    "doc_id": deterministic_id("DOC-PAY", pay_seq, 4),
                    "payment_id": payment_id,
                    "timestamp": timestamp,
                    "currency": invoice["currency"],
                    "amount_minor": part,
                    "invoice_refs": [invoice["invoice_id"]],
                }
            )
            cash_base = convert_minor(
                part,
                rate_on(episode, invoice["currency"], pay_day.isoformat()),
                invoice["currency"],
                base,
            )
            if part_index == len(parts) - 1 and sum(parts) == invoice["total_minor"]:
                allocated_base = invoice_base_amount - allocated_so_far
            else:
                allocated_base = proportional_base(
                    invoice_base_amount, part, invoice["total_minor"]
                )
                allocated_so_far += allocated_base
            fx_delta = cash_base - allocated_base
            postings = [("1000", cash_base, 0), ("1100", 0, allocated_base)]
            if fx_delta > 0:
                postings.append(("4900", 0, fx_delta))
            elif fx_delta < 0:
                postings.append(("4900", -fx_delta, 0))
            add_entry(
                timestamp,
                invoice["entity_id"],
                invoice["invoice_id"],
                payment_id,
                postings,
            )
        if len(parts) > 1:
            split_created = True
        paid_invoices.append(invoice)

    # Force a split payment when requested and none occurred naturally.
    if config.get("force_split_payment") and not split_created and paid_invoices:
        invoice = paid_invoices[-1]
        total = invoice["total_minor"]
        first = max(1, total // 2)
        second = total - first
        if second > 0:
            issued_day = date.fromisoformat(invoice["issued_at"][:10])
            earliest = issued_day + timedelta(days=1)
            latest = min(
                end,
                date.fromisoformat(invoice["due_at"][:10]),
                start + timedelta(days=int(days * 0.92)),
            )
            if latest < earliest:
                latest = min(end, earliest)
            pay_seq = len(episode.payments) + 1
            payment_id = deterministic_id("PAY", pay_seq, 4)
            for part_index, part in enumerate([first, second]):
                pay_day = earliest + timedelta(
                    days=rng.randint(0, max(0, (latest - earliest).days))
                )
                timestamp = iso_day(pay_day, offset)
                episode.payments.append(
                    {
                        "doc_id": deterministic_id("DOC-PAY", pay_seq, 4),
                        "payment_id": payment_id,
                        "timestamp": timestamp,
                        "currency": invoice["currency"],
                        "amount_minor": part,
                        "invoice_refs": [invoice["invoice_id"]],
                    }
                )
                cash_base = convert_minor(
                    part,
                    rate_on(episode, invoice["currency"], pay_day.isoformat()),
                    invoice["currency"],
                    base,
                )
                allocated_base = proportional_base(
                    convert_minor(
                        total,
                        rate_on(episode, invoice["currency"],
                                invoice["issued_at"][:10]),
                        invoice["currency"],
                        base,
                    ),
                    part,
                    total,
                )
                fx_delta = cash_base - allocated_base
                postings = [("1000", cash_base, 0), ("1100", 0, allocated_base)]
                if fx_delta > 0:
                    postings.append(("4900", 0, fx_delta))
                elif fx_delta < 0:
                    postings.append(("4900", -fx_delta, 0))
                add_entry(
                    timestamp,
                    invoice["entity_id"],
                    invoice["invoice_id"],
                    payment_id,
                    postings,
                )
            split_created = True

    # Refunds: negative payments, revenue reversal against cash.
    refund_candidates = list(paid_invoices)
    rng.shuffle(refund_candidates)
    refund_created = False
    for invoice in refund_candidates[: min(3, len(refund_candidates))]:
        if not config.get("refund", True) or rng.random() < 0.5:
            continue
        pay_seq = len(episode.payments) + 1
        payment_id = deterministic_id("PAY", pay_seq, 4)
        issued_day = date.fromisoformat(invoice["issued_at"][:10])
        refund_day = min(end, issued_day + timedelta(days=rng.randint(8, 40)))
        amount = -int(invoice["total_minor"] * rng.uniform(0.05, 0.2))
        if amount == 0:
            continue
        timestamp = iso_day(refund_day, offset)
        episode.payments.append(
            {
                "doc_id": deterministic_id("DOC-PAY", pay_seq, 4),
                "payment_id": payment_id,
                "timestamp": timestamp,
                "currency": invoice["currency"],
                "amount_minor": amount,
                "invoice_refs": [invoice["invoice_id"]],
            }
        )
        cash_base = convert_minor(
            -amount,
            rate_on(episode, invoice["currency"], refund_day.isoformat()),
            invoice["currency"],
            base,
        )
        add_entry(
            timestamp,
            invoice["entity_id"],
            invoice["invoice_id"],
            payment_id,
            [("4000", cash_base, 0), ("1000", 0, cash_base)],
        )
        refund_created = True

    # Force a refund when requested and none occurred naturally.
    if config.get("force_refund") and not refund_created and paid_invoices:
        invoice = paid_invoices[-1]
        amount = -max(1, int(invoice["total_minor"] * 0.1))
        pay_seq = len(episode.payments) + 1
        payment_id = deterministic_id("PAY", pay_seq, 4)
        issued_day = date.fromisoformat(invoice["issued_at"][:10])
        refund_day = min(end, issued_day + timedelta(days=15))
        timestamp = iso_day(refund_day, offset)
        episode.payments.append(
            {
                "doc_id": deterministic_id("DOC-PAY", pay_seq, 4),
                "payment_id": payment_id,
                "timestamp": timestamp,
                "currency": invoice["currency"],
                "amount_minor": amount,
                "invoice_refs": [invoice["invoice_id"]],
            }
        )
        cash_base = convert_minor(
            -amount,
            rate_on(episode, invoice["currency"], refund_day.isoformat()),
            invoice["currency"],
            base,
        )
        add_entry(
            timestamp,
            invoice["entity_id"],
            invoice["invoice_id"],
            payment_id,
            [("4000", cash_base, 0), ("1000", 0, cash_base)],
        )
        refund_created = True

    # Recurring operating expenses, including legitimate identical amounts.
    if config.get("recurring", True):
        for index, (label, amount) in enumerate(EXPENSES):
            for repeat in range(1 + (index % 2)):
                exp_day = start + timedelta(days=min(days - 1, 2 + index * 2 + repeat * 11))
                timestamp = iso_day(exp_day, offset)
                add_entry(
                    timestamp,
                    entities[(index + repeat) % len(entities)]["entity_id"],
                    None,
                    None,
                    [("5000", amount, 0), ("1000", 0, amount)],
                )

    # Fill to the requested row count with ordinary operating entries.
    filler = 0
    while len(ledger) < max(200, int(config["sizes"]["ledger_rows"] * 0.85)):
        filler += 1
        exp_day = start + timedelta(days=(filler * 7) % max(1, days))
        timestamp = iso_day(exp_day, offset)
        amount = 95_000 + (filler % 11) * 17_500
        add_entry(
            timestamp,
            entities[filler % len(entities)]["entity_id"],
            None,
            None,
            [("5000", amount, 0), ("1000", 0, amount)],
        )

    episode.ledger = ledger
    episode.entries = entries
    manifest["ledger_rows"] = len(ledger)
    manifest["documents"] = len(episode.invoices) + len(episode.payments)
    return episode
