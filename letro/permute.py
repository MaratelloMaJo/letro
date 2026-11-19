"""Harmless transformations: rename every ID and shuffle every record order.

The oracle answer is rebuilt by the independent reference audit over the
permuted open data, so F1 and the reward must not change.
"""

from __future__ import annotations

import copy
import hashlib
import random
from typing import Any

from .generator.audit import reference_audit
from .generator.model import Episode


def _new_ids(values: list[str], prefix: str, salt: str) -> dict[str, str]:
    unique = sorted(set(values))
    digest = hashlib.sha256(salt.encode("utf-8")).hexdigest()
    rng = random.Random(int(digest[:16], 16))
    rng.shuffle(unique)
    mapping = {}
    width = max(4, len(str(len(unique))))
    for index, value in enumerate(unique, start=1):
        mapping[value] = f"{prefix}{index:0{width}d}"
    return mapping


def permute_episode(episode: Episode, salt: str = "permutation") -> Episode:
    """Return a copy with new IDs and shuffled record order."""
    digest = hashlib.sha256(f"{episode.manifest['episode_id']}:{salt}".encode()).hexdigest()
    rng = random.Random(int(digest[:16], 16))

    invoices = copy.deepcopy(episode.invoices)
    payments = copy.deepcopy(episode.payments)
    ledger = copy.deepcopy(episode.ledger)
    fx = copy.deepcopy(episode.fx)

    invoice_map = _new_ids([item["invoice_id"] for item in invoices], "INVX-", salt)
    payment_map = _new_ids([item["payment_id"] for item in payments], "PAYX-", salt)
    row_map = _new_ids([row["row_id"] for row in ledger], "LEDX-", salt)
    invoice_doc_map = _new_ids([item["doc_id"] for item in invoices], "DOCINVX-", salt)
    payment_doc_map = _new_ids([item["doc_id"] for item in payments], "DOCPAYX-", salt)

    for item in invoices:
        item["doc_id"] = invoice_doc_map[item["doc_id"]]
        item["invoice_id"] = invoice_map[item["invoice_id"]]
    for item in payments:
        item["doc_id"] = payment_doc_map[item["doc_id"]]
        item["payment_id"] = payment_map[item["payment_id"]]
        item["invoice_refs"] = [
            invoice_map.get(ref, ref) for ref in item.get("invoice_refs", [])
        ]
    for row in ledger:
        row["row_id"] = row_map[row["row_id"]]
        if row.get("invoice_id"):
            row["invoice_id"] = invoice_map.get(row["invoice_id"], row["invoice_id"])
        if row.get("payment_id"):
            row["payment_id"] = payment_map.get(row["payment_id"], row["payment_id"])

    rng.shuffle(ledger)
    rng.shuffle(invoices)
    rng.shuffle(payments)
    rng.shuffle(fx)

    permuted = Episode(
        manifest=copy.deepcopy(episode.manifest),
        ledger=ledger,
        invoices=invoices,
        payments=payments,
        fx=fx,
        policy=copy.deepcopy(episode.policy),
        truth={"episode_id": episode.manifest["episode_id"], "issues": []},
        provenance={"episode_id": episode.manifest["episode_id"], "permutation": salt},
        config=copy.deepcopy(episode.config),
    )
    permuted.truth = {
        "episode_id": episode.manifest["episode_id"],
        "issues": reference_audit(permuted),
    }
    return permuted


def old_ids(episode: Episode) -> set[str]:
    values: set[str] = set()
    for row in episode.ledger:
        values.add(row["row_id"])
    for item in episode.invoices:
        values.add(item["doc_id"])
        values.add(item["invoice_id"])
    for item in episode.payments:
        values.add(item["doc_id"])
        values.add(item["payment_id"])
    return values


def assert_no_reused_ids(original: Episode, permuted: Episode) -> None:
    if old_ids(original) & old_ids(permuted):
        raise AssertionError("permutation reused an identifier")


__all__ = ["assert_no_reused_ids", "old_ids", "permute_episode"]
