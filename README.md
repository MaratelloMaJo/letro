# LETRO

**Ledger Evidence & Traceable Reward Oracle** — a reproducible reinforcement-learning
environment for training and evaluating a financial-audit agent.

One episode is one fictional company and one reporting period. The agent receives
read-only ledger, invoice, payment and FX records, investigates them with a narrow
tool interface, and submits findings. A closed evaluator matches those findings
against a hidden answer that was derived from the same open records, so every
reported discrepancy is provable and no unavailable fact is required.

The project is built for the REC Genesis Hackathon (FinTech track). It is a software
artefact, not a professional audit opinion. All companies, people, accounts and
amounts are synthetic.

## Quick start

Requirements: Python 3.11 or newer, no third-party packages.

```console
python --version
python -m letro.verify
```

`python -m letro.verify` is the single verification command. It runs the contract,
data, reward and reproducibility suites, checks the engineering artefacts, prints a
per-criterion table and exits non-zero on any failure. The expected final line is
`RESULT: PASS` with `TOTAL 100.00`.

Run the unit tests separately:

```console
python -m unittest discover -s tests -v
```

## Python API

The environment has two construction styles. The lazy style is the one a jury
harness usually expects:

```python
from letro.env import AuditEnv, LetroEnv
from letro.presets import preset

env = AuditEnv()                       # or LetroEnv(mode="eval")
observation, info = env.reset(seed=4242, config=preset("clean"))
observation, reward, terminated, truncated, info = env.step(
    {"type": "list_records", "table": "ledger", "limit": 10}
)
```

`reset` returns `(observation, info)`; `step` returns
`(observation, reward, terminated, truncated, info)`. A step before `reset` starts
the episode. `LetroEnv(mode="eval")` hides the terminal reward and diagnostics from
the policy while the evaluator keeps them. The environment never receives truth or
the seed: it holds only open data and a `finalize` closure owned by the runner.

## Jury harness, fuzz and workbench

```console
python -m letro.jury
python -m letro.fuzz --quick
python -m letro.fuzz --seeds 100
python -m letro.ui
```

`letro.jury` runs 20 unseen seeds with the four required adapters, 20 ID/order
permutations and 5 exact replays, checks observation isolation and exits non-zero on
failure. `letro.fuzz` checks 5 presets (default, hard, hard_composite, clean, wide)
for balance, truth reproduction, evidence resolution and permutation stability;
`--seeds 100` covers 500 episodes. `letro.ui` serves a read-only workbench at
http://127.0.0.1:8000 for the labelled train/dev episodes. The workbench is a demo
surface, not part of the scored environment; it never serves `truth.json`.

## Proof pack

The proof pack independently shows that truth is derived from open data, that reward
cannot be gamed, and that truth cannot leak through the observable surface:

```console
python -m letro.redteam
python -m letro.proof
python -m letro.isolation
python -m letro.bench
python -m letro.difficulty
python -m letro.challenge --episode ep-... --findings submission.json
```

`letro.redteam` runs 12 adversarial submissions (mark-all, duplicate spam,
evidence-less, wrong currency, wrong amount, guessed IDs, empty on clean, empty on
error, timeout, oversized payload, resubmit, duplicate correct) and asserts each stays
below its published bound; every attack must fail to earn reward. `letro.proof`
generates a clean episode and a single-error episode for each of the four error types
and both composites, and asserts the audit difference is exactly one issue (two for a
composite) with inclusion-minimal, independently recomputed evidence. `letro.isolation`
plants a canary string in a copied truth/provenance object, runs every action through
an eval-mode environment, and asserts the canary never appears in observations, info,
errors or trajectory records; a static AST check forbids `env.py` and `tools.py` from
importing the evaluator, the audit or the factory. `letro.bench` measures generation,
reset and 100 steps against the 60-second budget, peak memory against 4 GB, and the
`git archive` artefact against 1 GB, and checks hash-seed digest stability. `letro.difficulty`
measures per-error-type precision/recall for random, naive reconciliation, thorough,
limited-budget and mark-all policies, and counts clean-episode distractors (split
payments, refunds, recurring identical amounts, legitimately open invoices) that still
audit to zero. `letro.challenge` scores a submission file and prints only aggregates
— TP/FP/FN, precision/recall/F1 and reward — with no truth ids, amounts or evidence
sets.

![LETRO audit workbench](docs/ui.png)

## Container

```console
docker build -t letro:1.0.0 .
docker run --rm letro:1.0.0
docker run --rm -p 8000:8000 letro:1.0.0 python -m letro.ui --host 0.0.0.0
```

The image uses `python:3.11-slim`, installs no packages, runs as an unprivileged
user and executes `python -m letro.verify` by default. The repository contains no
runtime dependencies and the verifier makes no network calls; `requirements.txt`
documents that explicitly.

## Reproduce the shipped artefacts

```console
python scripts/build_episodes.py
python scripts/record_trajectories.py
python scripts/evaluate_policies.py
python scripts/demo.py
```

`build_episodes.py` is deterministic and rewrites `episodes/train`, `episodes/dev`
and `episodes/index.json`. The index records every seed, resolved config, issue
type, row/document count and the SHA-256 of the open files. `record_trajectories.py`
writes `trajectories/trajectories.jsonl` and `summary.json`; `evaluate_policies.py`
writes `docs/evidence/policy-metrics.json`; `demo.py` prints a scripted
thorough run on a composite episode and an empty submission on clean books.

## Episode data contract

Each directory contains six open files and two closed files:

| File | Visibility | Content |
| --- | --- | --- |
| `manifest.json` | open | schema version, episode id, base currency, period bounds, timezone, row/document counts, rounding and FX policy |
| `ledger.csv` | open | `row_id, timestamp, account, debit_minor, credit_minor, currency, entity_id, invoice_id, payment_id` |
| `invoices.jsonl` | open | `doc_id, invoice_id, entity_id, customer, issued_at, due_at, currency, total_minor, line_items` |
| `payments.jsonl` | open | `doc_id, payment_id, timestamp, currency, amount_minor, invoice_refs` |
| `fx.csv` | open | `date, source_currency, target_currency, rate` |
| `policy.json` | open | period bounds, rounding, rate-date choices, tolerance, evidence rule |
| `truth.json` | closed | issue id, type, canonical affected ids, expected amount in base minor units, currency, allowed evidence sets, explanation |
| `provenance.json` | closed | generation steps and seed fingerprint |

Rules: timestamps are ISO-8601 with an explicit offset; money is integer minor
units; FX rates are decimal strings; missing links are explicit `null` in JSON and
an empty field in CSV. Ledger rows are double-entry in the base currency and every
journal entry balances. Invoice and payment documents keep their original currency.
Limits: 200–2000 ledger rows, 20–200 documents, 0–12 truth issues, 30 findings,
10 evidence ids, 1000 explanation characters.

The generator first builds clean books and then injects errors. Truth is not written
by hand: after injection an independent reference audit reads only the open files
and reconstructs every discrepancy. Generation fails if the audit count differs from
the configured count, which makes contradictory or unsolvable episodes impossible
to ship silently.

## Actions

| Action | Arguments | Result |
| --- | --- | --- |
| `list_records` | `table`, `cursor`, `limit` | one page of `ledger`, `invoices`, `payments` or `fx`; `limit` 1–50, stable `next_cursor` |
| `get_record` | `table`, `id` | one ledger row or one document by business id or `doc_id` |
| `get_document` | `doc_id` | one invoice or payment document |
| `calculator` | `expression` | safe decimal arithmetic with `+ - * /` and parentheses |
| `submit` | `findings` | terminates the episode and is scored |

An invalid action or unknown id returns a short error, consumes one step and does
not reveal hidden data. There is no shell, SQL, filesystem or network access. The
episode limit is 100 steps including `submit`; reaching the limit terminates with
`truncated=True` and an empty answer.

## Findings and matching

`submit` receives:

```json
{
  "episode_id": "ep-...",
  "findings": [
    {
      "type": "duplicate_invoice",
      "affected_ids": ["INV-0001", "LED-000273", "LED-000274"],
      "claimed_amount_minor": 1670000,
      "currency": "KZT",
      "evidence_ids": ["INV-0001", "LED-000273", "LED-000274"],
      "explanation": "The invoice is posted twice."
    }
  ]
}
```

The four types are `duplicate_invoice`, `payment_allocation_gap`, `fx_rate_error`
and `period_cutoff`. Matching is one-to-one and requires all of:

- the same type;
- the exact canonical `affected_ids` set;
- the same currency;
- the claimed amount within ±1 minor unit of the expected amount;
- at least one complete allowed evidence set (a superset is accepted). Every
  shipped evidence set can be re-derived from the open records alone; for a
  duplicate invoice it must include the invoice and every AR and revenue posting
  for it, so the extra posting is provable against the original.

Unmatched findings and repeated findings are false positives; missed issues are
false negatives. Explanations are never scored, so persuasive text cannot change
the result. Malformed structure terminates with reward `-1`.

`P = TP/(TP+FP)`, `R = TP/(TP+FN)`, `F1 = 2TP/(2TP+FP+FN)`. A zero denominator
gives 0. Empty truth with empty findings gives F1 = 1; empty truth with any finding
gives F1 = 0.

## Reward

The terminal reward is exactly:

```text
clip(2 * F1 - 1 - 0.002 * inspection_steps, -1, 1)
```

`inspection_steps` counts every action except `submit`, including invalid actions.
There is no shaping reward during investigation. In training mode the terminal
reward is returned to the policy. In evaluation mode the environment returns
`reward = 0.0` and no diagnostics; the evaluator keeps the real reward and metrics
until the run ends. The environment object never receives truth: it holds only open
data and a `finalize` callback owned by the runner.

## Baselines

All adapters were measured on the same ten dev episodes (five clean, five with
errors, including composites). Full data: `docs/evidence/policy-metrics.json`.

| Policy | Mean F1 | Clean F1 | Erroneous F1 | Mean reward | Mean steps | TP | FP | FN |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `random_explorer` | 0.400 | 0.800 | 0.000 | -0.211 | 15.0 | 0 | 12 | 24 |
| `reconciliation` | 0.146 | 0.000 | 0.293 | -0.717 | 11.8 | 15 | 143 | 9 |
| `thorough` (reference) | 1.000 | 1.000 | 1.000 | 0.978 | 11.8 | 24 | 0 | 0 |
| `mark_all` | 0.000 | 0.000 | 0.000 | -1.000 | 2.0 | 0 | 300 | 24 |
| `oracle` (evaluator side) | 1.000 | 1.000 | 1.000 | 1.000 | 1.0 | 24 | 0 | 0 |

The `reconciliation` adapter is an honest, simple heuristic: it finds duplicate
postings, FX mismatches and cut-offs, but it reports every invoice with an open
balance as an unallocated payment. Legitimately open invoices therefore become
false positives (clean F1 0.000) and a gap behind a part-paid invoice gets the
wrong amount. Its low score is the measured evidence that the task is not solved
by a naive rule.

The `thorough` adapter is the exact reference arithmetic used as an upper bound
and in the demo. It proves the environment is solvable and the matcher is
correct; it is not evidence that a language model can perform the same audit.
The oracle reads closed truth and exists only to test the evaluator.

## Trajectories

`trajectories/trajectories.jsonl` contains 500 records from 40 runs over all 20
episodes. Every record has exactly seven fields: `episode_id`, `step`, `action`,
`observation`, `reward`, `terminated`, `truncated`. Observations are scanned for
forbidden keys before writing; `truth.json`, `provenance.json`, issue ids, expected
amounts, affected-id sets and answer keys never appear. The oracle is not recorded
because its answers come from closed truth.

## Reproducibility and generalization

The same seed and config reproduce byte-identical open files and identical rewards.
The verifier replays episodes and also applies a harmless transformation: every
invoice, payment, ledger row and document id is renamed, all tables are shuffled,
and truth is rebuilt from the transformed open files. The oracle answer and reward
must be preserved, which they are for all 20 paired checks.

## Continuous integration and runbook

`.github/workflows/ci.yml` runs the tests, the verifier, the jury harness and the
quick fuzz on Python 3.11, then builds and runs the container. `docs/RUNBOOK.md`
covers start/stop, common failures, the container and the hidden-seed check.

## Layout

```text
letro/                 environment, tools, matcher, reward, evaluator, verifier
letro/generator/       clean company builder, error injection, reference audit
letro/policies/        four baseline adapters plus the thorough reference
letro/ui/              read-only local workbench (stdlib http.server)
letro/jury.py          hidden-style integration harness
letro/fuzz.py          500-episode invariant and permutation sweep
letro/presets.py       default, hard, hard_composite, clean, wide
letro/redteam.py       12 adversarial submissions with published reward bounds
letro/proof.py         causal truth and evidence minimality proof
letro/isolation.py     canary sentinel and static boundary check
letro/bench.py         compute envelope, memory and archive-size measurement
letro/difficulty.py    per-error-type precision/recall and distractor counts
letro/challenge.py     sanitized submission scorer (aggregates only, no truth)
scripts/               episode build, trajectory recording, policy metrics, demo
episodes/train|dev/    10 + 10 open episodes with closed labels
trajectories/          recorded runs and summary
tests/                 134 unit and integration tests
docs/                  design, failure analysis, readiness, runbook, evidence
```

## Limitations

- The data is synthetic and deliberately small. The four-type taxonomy and the
  ±1 minor-unit tolerance are competition conventions, not a model of materiality
  or of a real audit.
- The simple reconciliation baseline is intentionally imperfect: it finds the
  provable duplicate, FX and cut-off issues but over-reports open invoices, so it
  scores 0.146 on dev. The `thorough` reference reaches 1.000 and proves the
  environment is solvable; neither number says anything about an LLM.
- Hidden grading seeds come from the same generator family as the open episodes.
  Generalization is therefore measured within one distribution; out-of-family
  documents, currencies or accounting standards are not covered.
- No model is trained and no GPU is used. The reward measures the quality of a
  submitted answer and its evidence, not the quality of an audit opinion.
- The environment exposes a narrow read-only interface by design. It cannot test
  tool misuse that requires filesystem, shell or network access, because those
  capabilities do not exist here.
- The workbench is a demo surface. It is read-only, serves only labelled train/dev
  episodes, and earns no competition points; it is not a hosted product.
- The 500-episode fuzz covers one generator family and five presets. It is strong
  evidence against contract drift, not proof of real-world generality.

## License

MIT. See `LICENSE`.

