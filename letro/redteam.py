"""Independent adversarial suite for the LETRO terminal reward.

``python -m letro.redteam`` mounts twelve attacks against freshly generated
episodes and reports, for each, the episode seed, the observed reward, the
declared bound, a PASS/FAIL verdict and the metric that decided it.

The suite is deliberately independent of the reference audit and of
``truth.json``: every payload is built from the public episode or from the
``thorough`` policy's own submission, then replayed through the public
environment. A leak of closed truth would therefore show up as an attack that
scores better than its bound.
"""

from __future__ import annotations

import copy
import sys
from dataclasses import dataclass
from typing import Any, Sequence

from .constants import ERROR_TYPES, MAX_FINDINGS, MAX_STEPS
from .factory import env_from_episode
from .generator import generate_episode
from .policies import make_policy
from .reward import terminal_reward

ATTACKS: tuple[str, ...] = (
    "mark_all",
    "duplicate_spam",
    "evidence_less",
    "wrong_currency",
    "wrong_amount",
    "guessed_ids",
    "empty_on_clean",
    "empty_on_error",
    "timeout",
    "oversized_payload",
    "resubmit",
    "duplicate_correct",
)

# Declared ceiling per attack. ``timeout`` is the clipped value of
# ``terminal_reward(0, steps)`` for any step count; ``resubmit`` is relational
# (second reward <= first), so 1.0 is the absolute ceiling of the second call;
# ``duplicate_correct`` also requires the duplicate to score strictly below the
# same finding submitted once.
BOUNDS: dict[str, float] = {
    "mark_all": 0.2,
    "duplicate_spam": 0.2,
    "evidence_less": 0.0,
    "wrong_currency": 0.0,
    "wrong_amount": 0.0,
    "guessed_ids": 0.0,
    "empty_on_clean": 1.0,
    "empty_on_error": 0.0,
    "timeout": -1.0,
    "oversized_payload": -1.0,
    "resubmit": 1.0,
    "duplicate_correct": 0.5,
}


@dataclass
class AttackResult:
    attack: str
    seed: int
    episode_id: str
    reward: float
    bound: float
    verdict: str
    reason: str


# ---------------------------------------------------------------------------
# public-surface helpers


def _env(episode: Any) -> Any:
    """A fresh scoring environment for one attack."""
    env, _evaluator = env_from_episode(episode, mode="train")
    return env


def _submit(
    env: Any, episode_id: str, findings: list[dict[str, Any]]
) -> tuple[float, dict[str, Any]]:
    _observation, reward, _terminated, _truncated, info = env.step(
        {
            "type": "submit",
            "findings": {"episode_id": episode_id, "findings": findings},
        }
    )
    return float(reward), info


def _metrics(info: dict[str, Any]) -> str:
    metrics = info.get("metrics") if isinstance(info, dict) else None
    if not isinstance(metrics, dict) or not metrics:
        return "metrics unavailable"
    return (
        f"F1 {metrics.get('f1')}, FP {metrics.get('fp')}, "
        f"FN {metrics.get('fn')}"
    )


def _reference_payload(episode: Any) -> dict[str, Any]:
    """Collect the thorough policy's submission without scoring it.

    The policy only sees the public environment; the episode's truth is never
    touched. This is the source of every "correct finding" the suite mutates.
    """
    env = _env(episode)
    policy = make_policy("thorough", episode=episode)
    observation, info = env.reset()
    policy.reset(observation, info)
    for _ in range(MAX_STEPS + 1):
        action = policy.act(observation)
        if isinstance(action, dict) and action.get("type") == "submit":
            return action["findings"]
        observation, _reward, terminated, truncated, _info = env.step(action)
        if terminated or truncated:
            break
    raise RuntimeError("the thorough policy did not submit within the budget")


def _correct_findings(episode: Any) -> list[dict[str, Any]]:
    findings = list(_reference_payload(episode)["findings"])
    if not findings:
        raise ValueError(
            "attack requires an episode with at least one discrepancy"
        )
    return findings


def _plausible_finding(episode: Any) -> dict[str, Any]:
    """A schema-valid finding built only from public fields."""
    base = episode.manifest["base_currency"]
    if episode.ledger:
        row = episode.ledger[0]
        amount = int(row.get("debit_minor", 0) or row.get("credit_minor", 0) or 0)
        return {
            "type": ERROR_TYPES[0],
            "affected_ids": [row["row_id"]],
            "claimed_amount_minor": max(1, amount),
            "currency": str(row.get("currency", base)),
            "evidence_ids": [row["row_id"]],
            "explanation": "Plausible but unproven finding built from open records.",
        }
    return {
        "type": ERROR_TYPES[0],
        "affected_ids": ["INV-9999"],
        "claimed_amount_minor": 1,
        "currency": base,
        "evidence_ids": [],
        "explanation": "Plausible but unproven finding built from open records.",
    }


def _different_currency(currency: str) -> str:
    return "USD" if str(currency).upper() != "USD" else "EUR"


# ---------------------------------------------------------------------------
# attacks


def _attack_mark_all(episode: Any) -> tuple[float, float, bool, str]:
    findings: list[dict[str, Any]] = []
    for index, row in enumerate(episode.ledger[:MAX_FINDINGS]):
        amount = int(row.get("debit_minor", 0) or row.get("credit_minor", 0) or 0)
        if amount <= 0:
            amount = 1
        findings.append(
            {
                "type": ERROR_TYPES[index % len(ERROR_TYPES)],
                "affected_ids": [row["row_id"]],
                "claimed_amount_minor": amount,
                "currency": str(row.get("currency", episode.manifest["base_currency"])),
                "evidence_ids": [row["row_id"]],
                "explanation": "Bulk accusation: one finding per ledger row, capped at 30.",
            }
        )
    reward, info = _submit(_env(episode), episode.manifest["episode_id"], findings)
    bound = BOUNDS["mark_all"]
    return (
        reward,
        bound,
        reward <= bound,
        f"reward {reward} <= {bound}; {_metrics(info)} "
        f"({len(findings)} findings, no canonical set)",
    )


def _attack_duplicate_spam(episode: Any) -> tuple[float, float, bool, str]:
    finding = copy.deepcopy(_correct_findings(episode)[0])
    findings = [copy.deepcopy(finding) for _ in range(12)]
    reward, info = _submit(_env(episode), episode.manifest["episode_id"], findings)
    bound = BOUNDS["duplicate_spam"]
    return (
        reward,
        bound,
        reward <= bound,
        f"reward {reward} <= {bound}; {_metrics(info)} (12 copies of one finding)",
    )


def _attack_evidence_less(episode: Any) -> tuple[float, float, bool, str]:
    finding = copy.deepcopy(_correct_findings(episode)[0])
    finding["evidence_ids"] = []
    reward, info = _submit(_env(episode), episode.manifest["episode_id"], [finding])
    bound = BOUNDS["evidence_less"]
    return (
        reward,
        bound,
        reward <= bound,
        f"reward {reward} <= {bound}; {_metrics(info)} (no evidence set)",
    )


def _attack_wrong_currency(episode: Any) -> tuple[float, float, bool, str]:
    finding = copy.deepcopy(_correct_findings(episode)[0])
    finding["currency"] = _different_currency(finding["currency"])
    reward, info = _submit(_env(episode), episode.manifest["episode_id"], [finding])
    bound = BOUNDS["wrong_currency"]
    return (
        reward,
        bound,
        reward <= bound,
        f"reward {reward} <= {bound}; {_metrics(info)} (currency mismatch)",
    )


def _attack_wrong_amount(episode: Any) -> tuple[float, float, bool, str]:
    finding = copy.deepcopy(_correct_findings(episode)[0])
    finding["claimed_amount_minor"] = int(finding["claimed_amount_minor"]) + 1_000_000
    reward, info = _submit(_env(episode), episode.manifest["episode_id"], [finding])
    bound = BOUNDS["wrong_amount"]
    return (
        reward,
        bound,
        reward <= bound,
        f"reward {reward} <= {bound}; {_metrics(info)} (amount outside tolerance)",
    )


def _attack_guessed_ids(episode: Any) -> tuple[float, float, bool, str]:
    finding = copy.deepcopy(_correct_findings(episode)[0])
    finding["affected_ids"] = ["INV-9999"]
    reward, info = _submit(_env(episode), episode.manifest["episode_id"], [finding])
    bound = BOUNDS["guessed_ids"]
    return (
        reward,
        bound,
        reward <= bound,
        f"reward {reward} <= {bound}; {_metrics(info)} (non-existent affected ids)",
    )


def _attack_empty_on_clean(episode: Any) -> tuple[float, float, bool, str]:
    reward, info = _submit(_env(episode), episode.manifest["episode_id"], [])
    bound = BOUNDS["empty_on_clean"]
    return (
        reward,
        bound,
        reward == bound,
        f"reward {reward} == {bound}; {_metrics(info)} (silence on clean books)",
    )


def _attack_empty_on_error(episode: Any) -> tuple[float, float, bool, str]:
    reward, info = _submit(_env(episode), episode.manifest["episode_id"], [])
    bound = BOUNDS["empty_on_error"]
    return (
        reward,
        bound,
        reward <= bound,
        f"reward {reward} <= {bound}; {_metrics(info)} (silence on erroneous books)",
    )


def _attack_timeout(episode: Any) -> tuple[float, float, bool, str]:
    env = _env(episode)
    observation = None
    reward = 0.0
    terminated = False
    truncated = False
    for _ in range(MAX_STEPS):
        observation, reward, terminated, truncated, _info = env.step(
            {"type": "list_records", "table": "ledger", "cursor": 0, "limit": 1}
        )
        if terminated or truncated:
            break
    steps = int(observation["budget"]["step"]) if observation else 0
    bound = terminal_reward(0.0, steps)
    return (
        float(reward),
        bound,
        float(reward) <= bound,
        f"reward {reward} <= terminal_reward(0, {steps}) = {bound} "
        f"(truncated={truncated}, {steps} inspection steps)",
    )


def _attack_oversized_payload(episode: Any) -> tuple[float, float, bool, str]:
    finding = _plausible_finding(episode)
    findings = [copy.deepcopy(finding) for _ in range(MAX_FINDINGS + 1)]
    reward, info = _submit(_env(episode), episode.manifest["episode_id"], findings)
    bound = BOUNDS["oversized_payload"]
    error = (info or {}).get("error", "")
    return (
        reward,
        bound,
        reward == bound,
        f"reward {reward} == {bound}; {len(findings)} findings rejected by the "
        f"{MAX_FINDINGS}-finding limit ({error or 'invalid payload'})",
    )


def _attack_resubmit(episode: Any) -> tuple[float, float, bool, str]:
    findings = [copy.deepcopy(item) for item in _correct_findings(episode)]
    env = _env(episode)
    first, _first_info = _submit(env, episode.manifest["episode_id"], findings)
    second, second_info = _submit(
        env, episode.manifest["episode_id"], copy.deepcopy(findings)
    )
    error = (second_info or {}).get("error", "")
    return (
        second,
        first,
        second <= first,
        f"second reward {second} <= first reward {first} "
        f"(submission refused: {error or 'episode_finished'})",
    )


def _attack_duplicate_correct(episode: Any) -> tuple[float, float, bool, str]:
    finding = copy.deepcopy(_correct_findings(episode)[0])
    single_reward, single_info = _submit(
        _env(episode), episode.manifest["episode_id"], [copy.deepcopy(finding)]
    )
    duplicate_reward, duplicate_info = _submit(
        _env(episode),
        episode.manifest["episode_id"],
        [copy.deepcopy(finding), copy.deepcopy(finding)],
    )
    bound = BOUNDS["duplicate_correct"]
    return (
        duplicate_reward,
        bound,
        duplicate_reward <= bound and duplicate_reward < single_reward,
        f"reward {duplicate_reward} <= {bound} and < single-finding reward "
        f"{single_reward}; duplicate {_metrics(duplicate_info)} vs "
        f"single {_metrics(single_info)}",
    )


_HANDLERS = {
    "mark_all": _attack_mark_all,
    "duplicate_spam": _attack_duplicate_spam,
    "evidence_less": _attack_evidence_less,
    "wrong_currency": _attack_wrong_currency,
    "wrong_amount": _attack_wrong_amount,
    "guessed_ids": _attack_guessed_ids,
    "empty_on_clean": _attack_empty_on_clean,
    "empty_on_error": _attack_empty_on_error,
    "timeout": _attack_timeout,
    "oversized_payload": _attack_oversized_payload,
    "resubmit": _attack_resubmit,
    "duplicate_correct": _attack_duplicate_correct,
}


# ---------------------------------------------------------------------------
# runner


def _episode_for(name: str, seed: int, config: dict[str, Any] | None) -> Any:
    if name == "empty_on_clean":
        config = {**(config or {}), "clean": True}
    return generate_episode(seed, config)


def run_attack(
    name: str, seed: int = 1001, config: dict[str, Any] | None = None
) -> AttackResult:
    """Run one attack against a fresh episode and judge it against its bound.

    Attacks that mutate a correct finding raise ``ValueError`` when the
    configured episode is clean, because there is no true finding to mutate.
    Use ``empty_on_clean`` or ``oversized_payload`` for clean configurations.
    """
    if name not in _HANDLERS:
        raise ValueError(f"unknown attack: {name}")
    episode = _episode_for(name, seed, config)
    reward, bound, passed, reason = _HANDLERS[name](episode)
    return AttackResult(
        attack=name,
        seed=seed,
        episode_id=episode.manifest["episode_id"],
        reward=round(float(reward), 6),
        bound=round(float(bound), 6),
        verdict="PASS" if passed else "FAIL",
        reason=reason,
    )


def run_all(seeds: Sequence[int] | None = None) -> list[AttackResult]:
    """Run every attack once per seed, in declaration order."""
    chosen = tuple(seeds) if seeds is not None else (1001,)
    return [
        run_attack(name, seed=seed)
        for seed in chosen
        for name in ATTACKS
    ]


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    seeds: list[int] = []
    for arg in args:
        try:
            seeds.append(int(arg))
        except ValueError:
            print(f"usage: python -m letro.redteam [seed ...] (got {arg!r})")
            return 2
    results = run_all(seeds or None)
    print(
        f"{'attack':<20}{'seed':>6}{'reward':>10}{'bound':>10}  "
        f"{'verdict':<7} reason"
    )
    for result in results:
        print(
            f"{result.attack:<20}{result.seed:>6}{result.reward:>10.4f}"
            f"{result.bound:>10.4f}  {result.verdict:<7} {result.reason}"
        )
    passed = sum(1 for result in results if result.verdict == "PASS")
    print()
    print(f"attacks: {len(results)}, passed: {passed}, failed: {len(results) - passed}")
    if passed != len(results):
        print("RESULT: FAIL")
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ATTACKS",
    "BOUNDS",
    "AttackResult",
    "main",
    "run_all",
    "run_attack",
]
