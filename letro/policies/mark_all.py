"""Adversarial baseline: accuse many rows with several error types."""

from __future__ import annotations

from typing import Any

from .base import Policy


class MarkAllPolicy(Policy):
    name = "mark_all"

    def reset(self, observation: dict[str, Any], info: dict[str, Any]) -> None:
        self._episode_id = str(info.get("episode_id", ""))
        self._rows: list[dict[str, Any]] = []
        self._asked = False
        self._submitted = False

    def act(self, observation: dict[str, Any]) -> dict[str, Any]:
        if self._submitted:
            return {
                "type": "submit",
                "findings": {"episode_id": self._episode_id, "findings": []},
            }
        if not self._asked:
            self._asked = True
            return {"type": "list_records", "table": "ledger", "cursor": 0, "limit": 50}
        last = observation.get("last_result")
        if (
            not self._rows
            and last
            and last.get("ok")
            and isinstance(last.get("result", {}).get("rows"), list)
        ):
            self._rows.extend(last["result"]["rows"])
        return self._submit()

    def _submit(self) -> dict[str, Any]:
        if self._submitted:
            return {
                "type": "submit",
                "findings": {"episode_id": self._episode_id, "findings": []},
            }
        self._submitted = True
        types = (
            "duplicate_invoice",
            "payment_allocation_gap",
            "fx_rate_error",
            "period_cutoff",
        )
        findings = []
        for index, row in enumerate(self._rows[:30]):
            amount = int(row.get("debit_minor", 0) or row.get("credit_minor", 0) or 0)
            if amount <= 0:
                amount = 1
            findings.append(
                {
                    "type": types[index % len(types)],
                    "affected_ids": [row["row_id"]],
                    "claimed_amount_minor": amount,
                    "currency": str(row.get("currency", "KZT")),
                    "evidence_ids": [row["row_id"]],
                    "explanation": "Bulk accusation used as an adversarial baseline.",
                }
            )
        return {
            "type": "submit",
            "findings": {"episode_id": self._episode_id, "findings": findings},
        }
