"""Ninety-second scripted proof demo.

Run ``python scripts/demo.py``. Five deterministic sections show, in order,
that the reference audit is silent on clean books, that a naive baseline
over-accuses, that the thorough policy finds every issue with resolvable
evidence, that renaming and shuffling records changes nothing, and that the
twelve red-team attacks stay inside their bounds.

The demo is offline and uses no model, network or GPU. It reads only the
labelled dev episodes and the public tool surface.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from letro.factory import env_from_episode  # noqa: E402
from letro.generator import load_episode, reference_audit  # noqa: E402
from letro.permute import permute_episode  # noqa: E402
from letro.policies import ReconciliationPolicy, ThoroughPolicy  # noqa: E402
from letro.redteam import run_all  # noqa: E402
from letro.tools import OpenStore, ToolError  # noqa: E402
from letro.trajectory import TrajectoryRecorder, run_episode  # noqa: E402

SECTIONS = (
    "clean books",
    "naive reconciliation",
    "thorough audit",
    "permutation",
    "red team",
)

CLEAN_EPISODE = "ep-b545af7e17"
ERROR_EPISODE = "ep-0dc0a85bf7"
RED_TEAM_SEEDS = (1001,)


def story() -> list[str]:
    """Return the section titles in the order :func:`main` prints them."""
    return list(SECTIONS)


def _load(episode_id: str) -> Any:
    index = json.loads((ROOT / "episodes" / "index.json").read_text(encoding="utf-8"))
    for entry in index["dev"]:
        if entry["episode_id"] == episode_id:
            return load_episode(ROOT / entry["directory"])
    raise SystemExit(f"episode {episode_id} is not in the dev split")


def _header(number: int, title: str) -> None:
    print()
    print(f"{number}. {title}")
    print("-" * (len(title) + 3))


def _run(episode: Any, policy: Any) -> tuple[Any, Any, Any]:
    env, evaluator = env_from_episode(episode, mode="train")
    recorder = TrajectoryRecorder()
    result = run_episode(env, policy, recorder=recorder, evaluator=evaluator)
    return result, evaluator, recorder


def _submission(recorder: Any) -> list[dict[str, Any]]:
    for entry in recorder.entries:
        action = entry.get("action") or {}
        if action.get("type") == "submit":
            payload = action.get("findings") or {}
            return list(payload.get("findings") or [])
    return []


def _resolve(store: Any, identifier: str) -> tuple[str | None, dict[str, Any] | None]:
    for table in ("ledger", "invoices", "payments"):
        try:
            return table, store.get_record(table, identifier)
        except ToolError:
            continue
    try:
        return "documents", store.get_document(identifier)
    except ToolError:
        return None, None


def _record_line(table: str, record: dict[str, Any]) -> str:
    if table == "ledger":
        return (
            f"ledger row {record['row_id']} account={record['account']} "
            f"debit={record['debit_minor']} credit={record['credit_minor']} "
            f"{record['currency']} at {record['timestamp']}"
        )
    if table == "invoices":
        return (
            f"invoice {record['invoice_id']} total={record['total_minor']} "
            f"{record['currency']} issued {record['issued_at']}"
        )
    if table == "payments":
        return (
            f"payment {record['payment_id']} amount={record['amount_minor']} "
            f"{record['currency']} at {record['timestamp']}"
        )
    return f"{table} {record}"


def _clean_books() -> bool:
    _header(1, SECTIONS[0])
    episode = _load(CLEAN_EPISODE)
    issues = reference_audit(episode)
    print(f"episode       {episode.manifest['episode_id']}")
    print(f"period        {episode.manifest['period_start'][:10]} .. {episode.manifest['period_end'][:10]}")
    print(f"ledger rows   {episode.manifest['ledger_rows']}")
    print(f"reference audit returns {len(issues)} issues")
    ok = len(issues) == 0
    print(f"verdict       {'PASS' if ok else 'FAIL'}")
    return ok


def _naive_reconciliation() -> tuple[bool, float]:
    _header(2, SECTIONS[1])
    episode = _load(ERROR_EPISODE)
    result, evaluator, recorder = _run(episode, ReconciliationPolicy())
    metrics = evaluator.result()
    findings = _submission(recorder)
    unmatched = list(evaluator.last_result.unmatched_findings) if evaluator.last_result else []
    print(f"episode       {episode.manifest['episode_id']}")
    print(
        f"F1 {metrics.get('f1')}  reward {result.reward}  "
        f"steps {result.steps}  FP {metrics.get('fp')}  FN {metrics.get('fn')}"
    )
    print(f"false accusations (first 3 of {len(unmatched)}):")
    for index in unmatched[:3]:
        finding = findings[index]
        print(
            f"  - {finding['type']} affected={finding['affected_ids']} "
            f"amount={finding['claimed_amount_minor']} {finding['currency']}"
        )
    ok = bool(unmatched) and float(metrics.get("f1") or 0.0) < 1.0
    print(f"verdict       {'PASS' if ok else 'FAIL'} (the naive rule over-accuses)")
    return ok, float(metrics.get("f1") or 0.0)


def _thorough_audit() -> tuple[bool, Any, float, float]:
    _header(3, SECTIONS[2])
    episode = _load(ERROR_EPISODE)
    result, evaluator, recorder = _run(episode, ThoroughPolicy())
    metrics = evaluator.result()
    findings = _submission(recorder)
    print(f"episode       {episode.manifest['episode_id']}")
    print(
        f"F1 {metrics.get('f1')}  reward {result.reward}  "
        f"steps {result.steps}  FP {metrics.get('fp')}  FN {metrics.get('fn')}"
    )
    ok = bool(findings) and float(metrics.get("f1") or 0.0) == 1.0
    if findings:
        finding = findings[0]
        print(f"finding       {finding['type']}")
        print(f"  affected    {finding['affected_ids']}")
        print(f"  amount      {finding['claimed_amount_minor']} {finding['currency']}")
        print(f"  evidence    {finding['evidence_ids']}")
        store = OpenStore(episode.open_data())
        for identifier in finding["evidence_ids"]:
            table, record = _resolve(store, identifier)
            if record is None:
                print(f"    {identifier} -> unresolved")
                ok = False
            else:
                print(f"    {identifier} -> {_record_line(table, record)}")
    print(f"verdict       {'PASS' if ok else 'FAIL'}")
    return ok, episode, float(metrics.get("f1") or 0.0), float(result.reward)


def _permutation(episode: Any, baseline_f1: float, baseline_reward: float) -> bool:
    _header(4, SECTIONS[3])
    permuted = permute_episode(episode, "demo")
    result, evaluator, _recorder = _run(permuted, ThoroughPolicy())
    metrics = evaluator.result()
    f1 = float(metrics.get("f1") or 0.0)
    print(f"original      F1 {baseline_f1}  reward {baseline_reward}")
    print(f"permuted      F1 {f1}  reward {result.reward}")
    ok = f1 == baseline_f1 and float(result.reward) == baseline_reward
    print(f"verdict       {'PASS' if ok else 'FAIL'} (renaming and shuffling change nothing)")
    return ok


def _red_team() -> bool:
    _header(5, SECTIONS[4])
    results = run_all(list(RED_TEAM_SEEDS))
    print(f"{'attack':<20}{'reward':>10}{'bound':>10}  verdict")
    for result in results:
        print(
            f"{result.attack:<20}{result.reward:>10.4f}"
            f"{result.bound:>10.4f}  {result.verdict}"
        )
    ok = all(result.verdict == "PASS" for result in results)
    print(f"verdict       {'PASS' if ok else 'FAIL'} ({len(results)} attacks)")
    return ok


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args:
        print("usage: python scripts/demo.py")
        return 2
    print("LETRO ninety-second scripted demo")
    print("=" * 31)
    outcomes: list[bool] = []
    outcomes.append(_clean_books())
    naive_ok, naive_f1 = _naive_reconciliation()
    outcomes.append(naive_ok)
    thorough_ok, episode, thorough_f1, thorough_reward = _thorough_audit()
    outcomes.append(thorough_ok)
    better = naive_f1 < thorough_f1
    outcomes.append(better)
    print()
    print(
        f"comparison    naive F1 {naive_f1} < thorough F1 {thorough_f1}: "
        f"{'PASS' if better else 'FAIL'}"
    )
    outcomes.append(_permutation(episode, thorough_f1, thorough_reward))
    outcomes.append(_red_team())
    passed = all(outcomes)
    print()
    print(f"RESULT: {'PASS' if passed else 'FAIL'}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
