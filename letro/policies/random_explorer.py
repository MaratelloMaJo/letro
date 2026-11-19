"""Fixed-seed random explorer baseline.

It pages through tables in a deterministic pseudo-random order, occasionally
fetches a record or evaluates arithmetic, then submits a handful of findings
built from rows it has seen. It is intentionally weak: it tests that the
environment is explorable and that noise earns a negative reward.
"""

from __future__ import annotations

import random
from typing import Any

from ..constants import TABLES
from .base import Policy


class RandomExplorerPolicy(Policy):
    name = "random_explorer"

    def __init__(self, seed: int = 0, budget: int = 14, guesses: int = 4):
        self._seed = seed
        self._budget = budget
        self._guesses = guesses
        self.reset({}, {})

    def reset(self, observation: dict[str, Any], info: dict[str, Any]) -> None:
        self._rng = random.Random(self._seed)
        self._taken = 0
        self._rows: list[dict[str, Any]] = []
        self._seen_ids: list[str] = []
        self._episode_id = str(info.get("episode_id", ""))
        self._manifest: dict[str, Any] | None = None
        self._pending: tuple[str, int, int] | None = None
        self._submitted = False

    def act(self, observation: dict[str, Any]) -> dict[str, Any]:
        if self._manifest is None and "manifest" in observation:
            self._manifest = observation["manifest"]
        last = observation.get("last_result")
        if last and last.get("ok"):
            result = last.get("result") or {}
            if isinstance(result.get("rows"), list):
                self._rows.extend(result["rows"])
                for row in result["rows"]:
                    for key in ("row_id", "doc_id", "invoice_id", "payment_id"):
                        value = row.get(key)
                        if isinstance(value, str):
                            self._seen_ids.append(value)
        if self._pending is not None and last and last.get("ok"):
            table, cursor, limit = self._pending
            total = last["result"].get("total", 0)
            if cursor + limit < total and self._taken < self._budget:
                self._pending = (table, cursor + limit, limit)
            else:
                self._pending = None
        if self._taken >= self._budget or self._submitted:
            return self._submit()
        self._taken += 1
        roll = self._rng.random()
        if roll < 0.65 or not self._seen_ids:
            if self._pending is None:
                table = self._rng.choice(TABLES)
                self._pending = (table, 0, 20)
            table, cursor, limit = self._pending
            return {"type": "list_records", "table": table, "cursor": cursor, "limit": limit}
        if roll < 0.85:
            record_id = self._rng.choice(self._seen_ids)
            table = self._rng.choice(("ledger", "invoices", "payments"))
            return {"type": "get_record", "table": table, "id": record_id}
        left = self._rng.randrange(2, 900)
        right = self._rng.randrange(2, 90)
        return {"type": "calculator", "expression": f"{left} * {right} + {left - right}"}

    def _submit(self) -> dict[str, Any]:
        self._submitted = True
        findings = []
        for row in self._rows[: self._guesses]:
            amount = int(row.get("debit_minor", 0) or row.get("credit_minor", 0) or 0)
            row_id = str(row.get("row_id", ""))
            if not row_id:
                continue
            findings.append(
                {
                    "type": self._rng.choice(
                        (
                            "duplicate_invoice",
                            "payment_allocation_gap",
                            "fx_rate_error",
                            "period_cutoff",
                        )
                    ),
                    "affected_ids": [row_id],
                    "claimed_amount_minor": amount,
                    "currency": str(row.get("currency", "KZT")),
                    "evidence_ids": [row_id],
                    "explanation": "Random exploration guess, not a verified finding.",
                }
            )
        return {
            "type": "submit",
            "findings": {"episode_id": self._episode_id, "findings": findings},
        }
