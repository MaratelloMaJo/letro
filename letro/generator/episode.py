"""Episode orchestration and file I/O."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from ..schema import validate_config, validate_manifest, validate_truth
from .company import build_company
from .errors import GenerationError, inject_errors
from .model import Episode

LEDGER_FIELDS = [
    "row_id",
    "timestamp",
    "account",
    "debit_minor",
    "credit_minor",
    "currency",
    "entity_id",
    "invoice_id",
    "payment_id",
]

FX_FIELDS = ["date", "source_currency", "target_currency", "rate"]


def generate_episode(seed: int, config: dict[str, Any] | None = None) -> Episode:
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ValueError("seed must be a non-negative integer")
    config = validate_config(config)
    episode = build_company(seed, config)
    inject_errors(episode, seed, config)
    episode.manifest["ledger_rows"] = len(episode.ledger)
    episode.manifest["documents"] = len(episode.invoices) + len(episode.payments)
    validate_manifest(episode.manifest)
    validate_truth(episode.truth)
    return episode


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=False) + "\n")


def render_open_files(episode: Episode, directory: str | Path) -> Path:
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    _write_json(root / "manifest.json", episode.manifest)
    _write_json(root / "policy.json", episode.policy)

    with (root / "ledger.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=LEDGER_FIELDS, lineterminator="\n")
        writer.writeheader()
        for row in episode.ledger:
            writer.writerow(
                {
                    **row,
                    "invoice_id": row["invoice_id"] or "",
                    "payment_id": row["payment_id"] or "",
                }
            )

    _write_jsonl(root / "invoices.jsonl", episode.invoices)
    _write_jsonl(root / "payments.jsonl", episode.payments)

    with (root / "fx.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FX_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(episode.fx)
    return root


def write_closed_files(episode: Episode, directory: str | Path) -> Path:
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    _write_json(root / "truth.json", episode.truth)
    _write_json(root / "provenance.json", episode.provenance)
    return root


def write_episode(
    episode: Episode, directory: str | Path, include_closed: bool = True
) -> Path:
    root = render_open_files(episode, directory)
    if include_closed:
        write_closed_files(episode, root)
    return root


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def load_open_data(directory: str | Path) -> dict[str, Any]:
    root = Path(directory)
    ledger = []
    with (root / "ledger.csv").open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            ledger.append(
                {
                    "row_id": row["row_id"],
                    "timestamp": row["timestamp"],
                    "account": row["account"],
                    "debit_minor": int(row["debit_minor"] or 0),
                    "credit_minor": int(row["credit_minor"] or 0),
                    "currency": row["currency"],
                    "entity_id": row["entity_id"],
                    "invoice_id": row["invoice_id"] or None,
                    "payment_id": row["payment_id"] or None,
                }
            )
    fx = []
    with (root / "fx.csv").open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            fx.append(dict(row))
    return {
        "manifest": _read_json(root / "manifest.json"),
        "policy": _read_json(root / "policy.json"),
        "ledger": ledger,
        "invoices": _read_jsonl(root / "invoices.jsonl"),
        "payments": _read_jsonl(root / "payments.jsonl"),
        "fx": fx,
    }


def load_episode(directory: str | Path, load_closed: bool = True) -> Episode:
    root = Path(directory)
    open_data = load_open_data(root)
    truth: dict[str, Any] = {
        "episode_id": open_data["manifest"]["episode_id"],
        "issues": [],
    }
    provenance: dict[str, Any] = {"steps": []}
    if load_closed and (root / "truth.json").exists():
        truth = _read_json(root / "truth.json")
    if load_closed and (root / "provenance.json").exists():
        provenance = _read_json(root / "provenance.json")
    return Episode(
        manifest=open_data["manifest"],
        ledger=open_data["ledger"],
        invoices=open_data["invoices"],
        payments=open_data["payments"],
        fx=open_data["fx"],
        policy=open_data["policy"],
        truth=truth,
        provenance=provenance,
        config={"timezone_offset": open_data["manifest"]["period_start"][-6:]},
    )


__all__ = [
    "GenerationError",
    "generate_episode",
    "load_episode",
    "load_open_data",
    "render_open_files",
    "write_closed_files",
    "write_episode",
]
