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


def available_evidence_ids(open_data: dict[str, Any]) -> set[str]:
    """Every ID a policy can reach through get_record/get_document."""
    ids: set[str] = set()
    for row in open_data.get("ledger", []):
        if row.get("row_id"):
            ids.add(row["row_id"])
    for invoice in open_data.get("invoices", []):
        for key in ("doc_id", "invoice_id"):
            if invoice.get(key):
                ids.add(invoice[key])
    for payment in open_data.get("payments", []):
        for key in ("doc_id", "payment_id"):
            if payment.get(key):
                ids.add(payment[key])
    return ids


def _evidence_ok(
    finding: dict[str, Any],
    issue: dict[str, Any],
    available_evidence: set[str] | None = None,
) -> bool:
    evidence = set(finding.get("evidence_ids", []))
    if available_evidence is not None and not evidence <= available_evidence:
        return False
    for allowed in issue.get("allowed_evidence_sets", []):
        if set(allowed) <= evidence:
            return True
    return False


def finding_matches(
    finding: dict[str, Any],
    issue: dict[str, Any],
    tolerance_minor: int = 1,
    *,
    strict: bool = False,
    available_evidence: set[str] | None = None,
) -> bool:
    if finding.get("type") != issue.get("type"):
        return False
    if set(finding.get("affected_ids", [])) != set(issue.get("affected_ids", [])):
        return False
    if strict:
        if finding.get("currency") != issue.get("currency"):
            return False
    elif (
        str(finding.get("currency", "")).upper()
        != str(issue.get("currency", "")).upper()
    ):
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
    return _evidence_ok(
        finding,
        issue,
        available_evidence if strict else None,
    )


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


def _maximum_matching_size(
    adjacency: list[list[int]],
    issue_count: int,
    finding_count: int,
    blocked_issues: set[int],
    blocked_findings: set[int],
) -> int:
    owner = [-1] * issue_count

    def assign(finding_index: int, seen: list[bool]) -> bool:
        for issue_index in adjacency[finding_index]:
            if issue_index in blocked_issues or seen[issue_index]:
                continue
            seen[issue_index] = True
            if owner[issue_index] == -1 or assign(owner[issue_index], seen):
                owner[issue_index] = finding_index
                return True
        return False

    size = 0
    for finding_index in range(finding_count):
        if finding_index in blocked_findings:
            continue
        if assign(finding_index, [False] * issue_count):
            size += 1
    return size


def match(
    truth_issues: list[dict[str, Any]],
    findings: list[dict[str, Any]],
    tolerance_minor: int = 1,
    *,
    strict: bool = False,
    available_evidence: set[str] | None = None,
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
                if finding_matches(
                    finding,
                    issue,
                    tolerance_minor,
                    strict=strict,
                    available_evidence=available_evidence,
                )
            ]
        )

    max_size = _maximum_matching_size(
        adjacency, issue_count, finding_count, set(), set()
    )

    # Among all maximum matchings choose the lexicographically smallest sorted
    # sequence of (issue_id, finding_index) pairs, as the official brief
    # requires for equal-size matchings.
    edges = sorted(
        (
            (str(truth_issues[issue_index]["issue_id"]), finding_index, issue_index)
            for finding_index, issue_indices in enumerate(adjacency)
            for issue_index in issue_indices
        ),
        key=lambda item: (item[0], item[1]),
    )
    used_issues: set[int] = set()
    used_findings: set[int] = set()
    chosen: list[tuple[int, int]] = []
    for _issue_id, finding_index, issue_index in edges:
        if len(chosen) >= max_size:
            break
        if finding_index in used_findings or issue_index in used_issues:
            continue
        remaining_needed = max_size - len(chosen) - 1
        residual = _maximum_matching_size(
            adjacency,
            issue_count,
            finding_count,
            used_issues | {issue_index},
            used_findings | {finding_index},
        )
        if residual >= remaining_needed:
            chosen.append((finding_index, issue_index))
            used_findings.add(finding_index)
            used_issues.add(issue_index)

    finding_owner = [-1] * finding_count
    issue_owner = [-1] * issue_count
    for finding_index, issue_index in chosen:
        finding_owner[finding_index] = issue_index
        issue_owner[issue_index] = finding_index

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
    *,
    strict: bool = False,
    available_evidence: set[str] | None = None,
) -> MatchResult:
    return match(
        list(truth.get("issues", [])),
        list(payload.get("findings", [])),
        tolerance_minor=tolerance_minor,
        strict=strict,
        available_evidence=available_evidence,
    )
