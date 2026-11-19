"""Build the ten open train and ten dev episodes.

Run from the repository root:

    python scripts/build_episodes.py

The script is deterministic: deleting ``episodes/`` and running it again
reproduces byte-identical open files. Closed ``truth.json`` and
``provenance.json`` are written next to the open files for these labelled
splits only; hidden grading uses unseen seeds.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from letro.constants import SCHEMA_VERSION  # noqa: E402
from letro.generator import generate_episode, write_episode  # noqa: E402
from letro.schema import validate_config  # noqa: E402

OPEN_FILES = (
    "manifest.json",
    "ledger.csv",
    "invoices.jsonl",
    "payments.jsonl",
    "fx.csv",
    "policy.json",
)

TRAIN_CONFIGS: list[tuple[int, dict[str, Any]]] = [
    (1001, {}),
    (1002, {"clean": True}),
    (1003, {"sizes": {"issues": 3}, "errors": {"duplicate_invoice": 2, "payment_allocation_gap": 1, "fx_rate_error": 0, "period_cutoff": 0, "composite": 0}}),
    (1004, {"sizes": {"issues": 4}, "errors": {"duplicate_invoice": 0, "payment_allocation_gap": 0, "fx_rate_error": 2, "period_cutoff": 2, "composite": 0}}),
    (1005, {"sizes": {"issues": 4}, "errors": {"duplicate_invoice": 0, "payment_allocation_gap": 0, "fx_rate_error": 0, "period_cutoff": 0, "composite": 2}}),
    (1006, {"sizes": {"issues": 2}, "errors": {"duplicate_invoice": 1, "payment_allocation_gap": 0, "fx_rate_error": 1, "period_cutoff": 0, "composite": 0}}),
    (1007, {"sizes": {"issues": 2}, "errors": {"duplicate_invoice": 0, "payment_allocation_gap": 1, "fx_rate_error": 0, "period_cutoff": 1, "composite": 0}}),
    (1008, {"clean": True, "base_currency": "USD", "sizes": {"invoices": 55, "payments": 44, "ledger_rows": 480}}),
    (1009, {"sizes": {"issues": 6}}),
    (1010, {"base_currency": "EUR", "sizes": {"issues": 4}, "errors": {"duplicate_invoice": 1, "payment_allocation_gap": 1, "fx_rate_error": 1, "period_cutoff": 1, "composite": 0}}),
]

DEV_CONFIGS: list[tuple[int, dict[str, Any]]] = [
    (2001, {"clean": True}),
    (2002, {"clean": True, "sizes": {"invoices": 60, "payments": 50, "ledger_rows": 520}}),
    (2003, {"clean": True, "base_currency": "USD"}),
    (2004, {"clean": True, "variant": 3}),
    (2005, {"clean": True, "period_days": 45, "sizes": {"ledger_rows": 420}}),
    (2006, {"sizes": {"issues": 4}, "errors": {"duplicate_invoice": 0, "payment_allocation_gap": 0, "fx_rate_error": 0, "period_cutoff": 0, "composite": 2}}),
    (2007, {"sizes": {"issues": 5}, "errors": {"duplicate_invoice": 1, "payment_allocation_gap": 0, "fx_rate_error": 0, "period_cutoff": 0, "composite": 2}}),
    (2008, {"sizes": {"issues": 6}, "errors": {"duplicate_invoice": 0, "payment_allocation_gap": 1, "fx_rate_error": 1, "period_cutoff": 0, "composite": 2}}),
    (2009, {"base_currency": "USD", "sizes": {"issues": 4}, "errors": {"duplicate_invoice": 0, "payment_allocation_gap": 0, "fx_rate_error": 0, "period_cutoff": 0, "composite": 2}}),
    (2010, {"sizes": {"issues": 5}, "errors": {"duplicate_invoice": 0, "payment_allocation_gap": 0, "fx_rate_error": 0, "period_cutoff": 1, "composite": 2}}),
]


def digest_directory(directory: Path) -> str:
    digest = hashlib.sha256()
    for name in OPEN_FILES:
        digest.update(name.encode("utf-8"))
        digest.update((directory / name).read_bytes())
    return digest.hexdigest()


def build_split(name: str, configs: list[tuple[int, dict[str, Any]]]) -> list[dict[str, Any]]:
    entries = []
    base = ROOT / "episodes" / name
    if base.exists():
        shutil.rmtree(base)
    for seed, raw in configs:
        episode = generate_episode(seed, raw)
        directory = base / episode.manifest["episode_id"]
        write_episode(episode, directory, include_closed=True)
        entries.append(
            {
                "split": name,
                "directory": f"episodes/{name}/{episode.manifest['episode_id']}",
                "episode_id": episode.manifest["episode_id"],
                "seed": seed,
                "config": validate_config(raw),
                "issues": [issue["type"] for issue in episode.truth["issues"]],
                "clean": not episode.truth["issues"],
                "ledger_rows": episode.manifest["ledger_rows"],
                "documents": episode.manifest["documents"],
                "open_files_sha256": digest_directory(directory),
            }
        )
    return entries


def main() -> int:
    train = build_split("train", TRAIN_CONFIGS)
    dev = build_split("dev", DEV_CONFIGS)
    index = {
        "schema_version": SCHEMA_VERSION,
        "generator": "scripts/build_episodes.py",
        "note": (
            "Open train/dev episodes with labelled truth.json. Hidden grading "
            "uses unseen seeds and the same generator version."
        ),
        "train": train,
        "dev": dev,
    }
    target = ROOT / "episodes" / "index.json"
    target.write_text(
        json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    for entry in train + dev:
        print(
            f"{entry['split']:5s} {entry['episode_id']} seed={entry['seed']:4d} "
            f"rows={entry['ledger_rows']:4d} docs={entry['documents']:3d} "
            f"issues={len(entry['issues'])} clean={entry['clean']}"
        )
    print(f"wrote {len(train)} train and {len(dev)} dev episodes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
