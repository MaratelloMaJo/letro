"""Shared matcher: one-to-one TP assignment and P/R/F1."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class MatchResult:
    tp: int
    fp: int
    fn: int
    precision: float
    recall: float
    f1: float
    matched: list[dict[str, Any]] = field(default_factory=list)
    unmatched_findings: list[int] = field(default_factory=list)
    missed_issue_ids: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    def metrics(self) -> dict[str, Any]:
        return {
            "tp": self.tp,
            "fp": self.fp,
            "fn": self.fn,
            "precision": round(self.precision, 6),
            "recall": round(self.recall, 6),
            "f1": round(self.f1, 6),
            "matched": list(self.matched),
        }


def _evidence_ok(finding: dict[str, Any], issue: dict[str, Any]) -> bool:
    evidence = set(finding.get("evidence_ids", []))
    for allowed in issue.get("allowed_evidence_sets", []):
        if set(allowed) <= evidence:
            return True
    return False


def finding_matches(
    finding: dict[str, Any], issue: dict[str, Any], tolerance_minor: int = 1
) -> bool:
    if finding.get("type") != issue.get("type"):
        return False
    if set(finding.get("affected_ids", [])) != set(issue.get("affected_ids", [])):
        return False
    if str(finding.get("currency", "")).upper() != str(issue.get("currency", "")).upper():
        return False
    try:
        delta = abs(
            int(finding.get("claimed_amount_minor", 0))
            - int(issue.get("expected_amount_minor", 0))
        )
    except (TypeError, ValueError):
        return False
    if delta > tolerance_minor:
        return False
    return _evidence_ok(finding, issue)


def _reason(finding: dict[str, Any], issue: dict[str, Any]) -> str:
    if finding.get("type") != issue.get("type"):
        return "type does not match"
    if set(finding.get("affected_ids", [])) != set(issue.get("affected_ids", [])):
        return "affected_ids are not the canonical set"
    if str(finding.get("currency", "")).upper() != str(issue.get("currency", "")).upper():
        return "currency does not match"
    if not _evidence_ok(finding, issue):
        return "no complete allowed evidence set"
    return "amount is outside tolerance"


def match(
    truth_issues: list[dict[str, Any]],
    findings: list[dict[str, Any]],
    tolerance_minor: int = 1,
) -> MatchResult:
    issue_count = len(truth_issues)
    finding_count = len(findings)
    if issue_count == 0 and finding_count == 0:
        return MatchResult(
            tp=0, fp=0, fn=0, precision=0.0, recall=0.0, f1=1.0
        )

    adjacency: list[list[int]] = []
    for finding in findings:
        adjacency.append(
            [
                index
                for index, issue in enumerate(truth_issues)
                if finding_matches(finding, issue, tolerance_minor)
            ]
        )

    issue_owner = [-1] * issue_count
    finding_owner = [-1] * finding_count

    def assign(finding_index: int, seen: list[bool]) -> bool:
        for issue_index in adjacency[finding_index]:
            if seen[issue_index]:
                continue
            seen[issue_index] = True
            if issue_owner[issue_index] == -1 or assign(
                issue_owner[issue_index], seen
            ):
                issue_owner[issue_index] = finding_index
                finding_owner[finding_index] = issue_index
                return True
        return False

    for finding_index in range(finding_count):
        assign(finding_index, [False] * issue_count)

    matched = []
    for finding_index, issue_index in enumerate(finding_owner):
        if issue_index != -1:
            matched.append(
                {
                    "finding_index": finding_index,
                    "issue_id": truth_issues[issue_index]["issue_id"],
                }
            )

    tp = len(matched)
    fp = finding_count - tp
    fn = issue_count - tp
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    if tp == 0:
        f1 = 0.0
    else:
        f1 = 2 * tp / (2 * tp + fp + fn)

    unmatched = [index for index, owner in enumerate(finding_owner) if owner == -1]
    missed = [
        truth_issues[index]["issue_id"]
        for index, owner in enumerate(issue_owner)
        if owner == -1
    ]
    reasons = []
    for finding_index in unmatched:
        finding = findings[finding_index]
        best = "no truth issue is compatible"
        if truth_issues:
            best = _reason(finding, truth_issues[0])
        reasons.append(f"finding {finding_index}: {best}")

    return MatchResult(
        tp=tp,
        fp=fp,
        fn=fn,
        precision=precision,
        recall=recall,
        f1=f1,
        matched=matched,
        unmatched_findings=unmatched,
        missed_issue_ids=missed,
        reasons=reasons,
    )


def score(
    truth: dict[str, Any],
    payload: dict[str, Any],
    tolerance_minor: int = 1,
) -> MatchResult:
    return match(
        list(truth.get("issues", [])),
        list(payload.get("findings", [])),
        tolerance_minor=tolerance_minor,
    )
