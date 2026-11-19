# Production-readiness audit

Audit date: 2026-11-19. Scope: the LETRO repository at `D:\documents\Projects\letro`,
release target **REC Genesis Hackathon online selection** (deadline 2026-11-22), not a
hosted production service. The audit is evidence-first; a claim without a command,
file or measured output is not a PASS.

## 1. Verdict

**READY for hackathon submission — 100/100 on the supplied competition rubric.**
All 80 technical checks and all five engineering criteria pass from a clean copy. The
package is not a production SaaS and does not claim to be one: there is no deployed
service, authentication, database or on-call rotation, because the brief asks for an
offline, reproducible RL environment.

## 2. Scope card

| Item | Value |
| --- | --- |
| Product | LETRO: a reproducible financial-audit RL environment with a shared matcher and terminal reward |
| Primary archetype | data/ML CLI + library (not a web app or API service) |
| Release target | hackathon judging, offline, Python 3.11, 2 CPU, 4 GB RAM, no GPU |
| Core journey | clean copy → `python -m letro.verify` → 100.00 PASS; optional `python scripts/demo.py` |
| Release artifact | source tree, 20 episodes, trajectories, Dockerfile, verifier |
| Runtime dependencies | none (Python standard library only) |
| Data | synthetic companies, documents, ledger and FX; no real financial or personal data |
| Out of scope | hosted deployment, multi-user auth, live data feeds, model training |

## 3. Claim → evidence

| Claim | Evidence | Status |
| --- | --- | --- |
| One command verifies the submission | `python -m letro.verify` → `TOTAL 100.00`, `RESULT: PASS`, exit 0; 2.58 s | PASS |
| A clean copy works without local state | copied the tree to `%TEMP%\letro-clean-audit`, removed `.git`, ran the verifier → 100.00, exit 0 | PASS |
| Tests pass | `python -m unittest discover -s tests -v` → 76 tests, 0 failures, 3.3 s | PASS |
| Truth cannot leak into observations | `letro/env.py` holds only open data + a `finalize` callback; `letro/evaluator.py` owns truth; `letro/trajectory.py` scans observations for forbidden keys; `tests/test_leaks.py` | PASS |
| Every truth issue is provable from open files | `letro/generator/audit.py` reads only open records; generation raises on count mismatch; verifier data criterion 20/20; evidence ids resolve in `tests/test_generator.py` | PASS |
| Reward resists mark-all and persuasive text | one-to-one matching, canonical ids, evidence sets; mark_all F1 0.000, reward -1.000; `tests/test_attacks.py` | PASS |
| Determinism and id/order invariance | byte-identical replay; permutation renames and shuffles all ids; 20/20 paired checks; `tests/test_reproducibility.py` | PASS |
| Trajectories contain no closed truth | 382 records, 30 runs, exact seven fields; validator rejects leaks; `trajectories/summary.json` | PASS |
| Container is defined | `Dockerfile` uses `python:3.11-slim`, non-root, `CMD ["python", "-m", "letro.verify"]` | PASS (definition) |
| Container image actually builds and runs | `docker build -t letro:1.0.0 .` → daemon unavailable: `open //./pipe/dockerDesktopLinuxEngine` | UNKNOWN |
| Runs on Python 3.11 exactly | local runtime is 3.14.6; `py -3.11` not installed; Docker would prove it | UNKNOWN |
| No secrets in the tree | pattern scan for `sk-…`, `AKIA…`, private keys, passwords, API keys → no matches; zero commits at audit time | PASS |
| No network, shell, SQL or filesystem tool | `letro/tools.py` exposes four read-only actions and a restricted AST calculator; no `subprocess`, `socket`, `os.system`, `eval` | PASS |
| Episodes are within the data contract | 20 episodes, 272–442 ledger rows, 76–112 documents, 0–6 issues; `episodes/index.json`; verifier data 20/20 | PASS |

## 4. P0–P4 status

| Phase | Status | Reason |
| --- | --- | --- |
| P0 Intake | PASS | Product, audience, core journey, stack, artifact and risk map are written down above and in `DESIGN.md`. |
| P1 Workability | PASS | Clean copy starts with one command, no dependencies, no manual seeding; core journey completes in 2.58 s. |
| P2 Trust | PASS | 76 tests, 80 verifier checks, read-only tool surface, safe calculator, derived truth, no secrets, deterministic data, measured limits. Residual risk: no external accounting review. |
| P3 Product and UX | PASS for the brief / WARN for a general product | The CLI output is clear, the demo is scripted and the README carries measured baselines. There is no GUI, which the brief does not require. |
| P4 Release | WARN | Reproducible and deterministic, but no CI workflow, no deployed service, no runbook or monitoring, and the Docker image is unverified because the daemon is down. These are not hackathon blockers. |

## 5. Score table (supplied competition rubric)

The score is produced by the verifier, not hand-computed.

| Criterion | Max | Fact | Awarded | Evidence |
| --- | ---: | --- | ---: | --- |
| Contract and isolation | 25 | 20/20 checks | 25.00 | `python -m letro.verify` |
| Data and truth | 25 | 20/20 checks | 25.00 | `python -m letro.verify` |
| Reward reliability | 25 | 20/20 checks | 25.00 | `python -m letro.verify` |
| Reproducibility and generalization | 15 | 20/20 checks | 15.00 | `python -m letro.verify` |
| Engineering and explanation | 10 | 5 criteria × 2 | 10.00 | README, Dockerfile, index, trajectories, failure analysis, limitations |
| **Total** | **100** | | **100.00** | `RESULT: PASS` |

## 6. Top blockers for a hosted production release

These do not block the hackathon submission; they block a claim of production service
readiness.

1. **Container image is unverified.** `docker build` could not reach the daemon.
   Impact: the advertised Python 3.11 runtime is untested. Fix: start Docker Desktop,
   run the build and the image, confirm `RESULT: PASS`.
2. **No CI.** `.github/workflows` is absent. Impact: a future change can break the
   verifier without a gate. Fix: a workflow that runs the unit tests and
   `python -m letro.verify` on every push.
3. **No independent accounting review.** The generator, reference audit and
   reconciliation policy share conventions. Impact: a wrong convention would be
   consistently wrong. Fix: a qualified accountant reviews 20 episodes and the four
   error definitions.
4. **The rule-following baseline is near-perfect.** Reconciliation reaches F1 1.000.
   Impact: the environment proves coherence, not LLM audit capability. Fix: a harder
   variant with noisy documents and judgment calls, plus a trained baseline.
5. **No deployment, runbook or monitoring.** There is no service to observe. Impact:
   none for an offline package; blocking for a hosted product. Fix: only if the
   release target changes.

## 7. Three killer questions

1. **Can truth leak through an observation, error or reward?**
   Why it kills: a single leak invalidates every closed episode.
   What must be in the answer: `AuditEnv` never receives an `Episode` or truth; the
   evaluator owns truth; eval mode returns reward 0 and no metrics; observations are
   scanned for forbidden keys; `tests/test_leaks.py` passes.
2. **Is every declared issue actually solvable from the open files?**
   Why it kills: an unsolvable issue turns difficulty into a broken answer key.
   What must be in the answer: `reference_audit` reads only open records, generation
   fails when the audit count differs, evidence ids resolve, and the verifier's data
   criterion is 20/20.
3. **Can a lazy or adversarial policy farm the reward?**
   Why it kills: a reward that pays for accusations teaches the wrong behaviour.
   What must be in the answer: one-to-one matching, canonical ids, complete evidence
   sets, explanations unscored; mark-all gets F1 0.000 and reward -1.000; clean books
   reward silence.

## 8. Critical vulnerabilities

No critical or high findings. Low-severity observations:

- `[LOW]` `Dockerfile:1` — base image tag is `python:3.11-slim`, not a digest. A
  moving tag can change the build. Fix: pin a digest at release time.
- `[LOW]` repository root — no CI workflow. A regression would be caught only by a
  manual verifier run.
- `[INFO]` `docs/FAILURE-ANALYSIS.md` — the shared-author accounting assumption is
  disclosed, not eliminated.

## 9. Remediation plan

**Now (before submission)**
- Run `docker build` and `docker run` once the daemon is available; acceptance:
  `RESULT: PASS` inside the image. Effort: minutes.
- Commit the tree and re-run `python -m letro.verify` from the commit. Acceptance:
  exit 0, 100.00.

**24 hours**
- Add a CI workflow for tests and the verifier. Acceptance: a red test blocks the
  workflow.
- Re-run the clean-copy check on a second machine. Acceptance: same 100.00 and the
  same episode hashes.

**7 days**
- Independent accounting review of the four error definitions and 20 episodes.
  Acceptance: signed review with no unresolved correctness issue.
- Add a harder episode family with noisy documents and a trained baseline.
  Acceptance: reconciliation no longer reaches F1 1.000 on the new family.

## 10. What I need from you

- A running Docker daemon (or permission to start Docker Desktop) to close the
  container check.
- A second machine or clean Python 3.11 environment for an independent rerun.
- A qualified accountant if the claim is extended beyond a synthetic competition
  artefact.

## 11. Not verified

- Docker image build and run: daemon unavailable at audit time.
- Execution on Python 3.11 exactly: only 3.14.6 is installed locally; the code avoids
  3.12+ syntax, but this is a static argument, not a run.
- Real audit suitability: the data is synthetic and no accountant reviewed it.
- Out-of-family generalization: hidden seeds share the generator family.
- A trained model: none is shipped; the demo uses a scripted policy.
