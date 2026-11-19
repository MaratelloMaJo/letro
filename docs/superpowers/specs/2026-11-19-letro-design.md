# LETRO — design

Date: 2026-11-19
Status: approved (approach A, full build)
Competition: REC Genesis Hackathon, FinTech, online selection
Deadline: 2026-11-22 23:59 Asia/Almaty

## Intent

Build a reproducible RL environment for training and evaluating a financial-audit
agent. The environment hands out synthetic company records, exposes read-only
investigation tools, hides a small number of accounting errors, and scores
submitted findings against a closed truth with evidence requirements.

The jury does not rank teams by their agent's reward. It checks that the
environment, the truth and the reward are correct, isolated, and reproducible.
Therefore the product is the environment and its verifier, not a chatbot or a
report generator.

## Goals

- Pass the 20 fixed contract/isolation checks (25 pts).
- Produce 20 closed-ready episodes whose books balance before injection, whose
  truth describes a real measurable discrepancy, and whose evidence is
  independently sufficient (25 pts).
- Make the matcher and reward survive clean cases, duplicates, false positives
  and adversarial submissions (25 pts).
- Reproduce transitions exactly and preserve oracle results under ID/order
  permutation (15 pts).
- Ship one-command verification, versioned configs, trajectories, measured
  failure analysis and honest limitations (10 pts).

Target: 90+/100 with evidence per criterion.

## Non-goals

- Training model weights; no GPU, no network, no paid API.
- A web UI or a polished dashboard. A tiny terminal demo is enough.
- Real companies, people, bank records or money.
- Claiming real audit suitability.

## Stack

Python 3.11, standard library only for runtime and tests. CSV/JSON/JSONL as
specified. `unittest` so the official run needs no package installation.
Docker image `python:3.11-slim` for the reproducible check.

## Approaches considered

- **A. Contract-first vertical slices (chosen).** Contract and two error types
  first, then the full taxonomy, then matcher/reward and attacks, then episodes,
  policies, trajectories, docs. Every layer is verified before the next.
- B. Evaluator-first. Fast, but risks the 25 data points and hides generator
  defects until late.
- C. Data-first. Rich companies, thin environment, high risk of contract and
  leak failures, which block evaluation.

## Architecture

```
letro/
  schema.py       constants, enums, validation of manifest/action/finding
  money.py        minor units, Decimal parsing, FX conversion, rounding
  rng.py          seed -> independent deterministic streams
  generator/      company history -> clean books -> injected errors -> episode
  env.py          AuditEnv.reset/step, budget, truncation, mode handling
  tools.py        list_records, get_record, get_document, calculator
  matcher.py      normalization, bipartite TP assignment, P/R/F1
  reward.py       terminal reward
  evaluator.py    out-of-band scoring; owns truth; env never does
  policies/       random, reconciliation, mark-all, oracle adapters
  trajectory.py   JSONL recorder
  verify.py       one-command check across all five criteria
```

### Episode

One company, one reporting period. Open files: `manifest.json`, `ledger.csv`,
`invoices.jsonl`, `payments.jsonl`, `fx.csv`, `policy.json`. Closed files:
`truth.json`, `provenance.json`. Open episodes (train/dev) ship the closed files
for local development; hidden grading uses unseen seeds. Closed files never
appear in an observation or a trajectory.

### Data model

- Entities: parent plus 2 subsidiaries; accounts: cash, AR, revenue, FX
  gain/loss, deferred revenue, suspense.
- Each journal entry is double-entry: per currency, sum(debit) == sum(credit).
- Invoices have line items whose sum equals the total; payments allocate to
  invoices through ledger rows carrying both `payment_id` and `invoice_id`.
- Values: ISO-8601 timestamps with offset, integer minor units, FX rates as
  decimal strings, explicit `null` for missing links.

### Error taxonomy

1. `duplicate_invoice` — the same invoice is posted twice; AR and revenue are
   overstated by the invoice total.
2. `payment_allocation_gap` — payment received but not (fully) allocated; AR
   overstated by the unallocated amount.
3. `fx_rate_error` — a foreign-currency entry uses the wrong rate or the wrong
   date's rate; the base-currency amount differs by a measurable delta.
4. `period_cutoff` — an entry is recognised in the wrong reporting period;
   period revenue/expense differs by the misattributed amount.

Two composite scenarios: partial foreign-currency payment on the period
boundary (2+4+3), and duplicate invoice with a wrong FX rate (1+3). Each
component is a separate truth issue so one-to-one matching stays well defined;
their evidence overlaps, which forces joint analysis.

Clean episodes have zero issues and include legitimate distractors: split
payments, refunds/credit notes, and recurring identical amounts.

### Truth and evidence

`truth.json` holds a list of issues: `issue_id`, `type`, `affected_ids`
(canonical set), `expected_amount_minor`, `currency`, `allowed_evidence_sets`.
Each allowed set is a minimal list of open-record IDs sufficient to prove the
issue. The generator asserts, using only open files, that at least one set is
sufficient.

### Matcher

- Normalize type (enum), IDs (trimmed strings, set), currency (upper), amount
  (int).
- TP requires: equal type, affected_ids exactly equal to the canonical set,
  `abs(claimed - expected) <= 1` minor unit, equal currency, and `evidence_ids`
  containing at least one full allowed set (superset allowed).
- One-to-one maximum bipartite assignment; unmatched or repeated findings are
  FP; unmatched truth issues are FN.
- `P = TP/(TP+FP)`, `R = TP/(TP+FN)`; zero denominator gives 0; empty truth and
  empty findings give F1=1; empty truth with findings gives F1=0.

### Reward

`reward = clip(2*F1 - 1 - 0.002*inspection_steps, -1, 1)`, where
`inspection_steps` counts every accepted action except `submit`. No shaping
reward during investigation. Malformed `findings` terminates with -1. Step or
time limit sets `truncated=true` and an empty final answer.

### Isolation and modes

`AuditEnv` receives only open data plus an optional `finalize` callback. Truth
lives in the runner's `Evaluator`, never in the environment. In `train` mode the
callback returns the terminal reward; in `eval` mode it records the submission
and the environment returns `reward=0.0` with empty diagnostics. Observations
contain only requested rows/documents, the tool result or a bounded error, and
the remaining step budget. No shell, SQL, filesystem or network tools exist.

### Reproducibility

Seed -> SHA-256-derived independent streams for company, errors, distractors and
ID assignment. No dependence on dict order, wall clock or environment. Same
seed/config/version/actions reproduce records, transitions and rewards.
`permute_episode` renames IDs and reorders rows while preserving links, used to
prove that the oracle and matcher are ID-agnostic.

## Verification

`python -m letro.verify` runs the five criteria as ~70 checks and prints a score
table with evidence counts. It also regenerates episodes, runs the four
baselines, scans trajectories and observations for truth leaks, and exits
non-zero on any failure.

## Risks

- Evidence sufficiency is the hardest part; it is enforced by an independent
  reference audit over open files.
- Composite errors can make matching ambiguous; they are modelled as separate
  truth issues with distinct canonical IDs.
- Python 3.11 is targeted; code avoids 3.12+ syntax.
