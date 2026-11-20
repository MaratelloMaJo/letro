# LETRO dataset datasheet

This datasheet documents the synthetic dataset produced and consumed by the
LETRO environment. It follows the common "datasheets for datasets" structure.

## Motivation

LETRO needs a reproducible financial-audit environment in which an agent reads
open accounting records and reports material discrepancies against a closed
answer key. Real audit data cannot be published (confidentiality), and a
static, hand-authored dataset could not cover every error type, permutation, and
holdout-style seed. The dataset therefore exists to make every claim in the
design spec *executable*: every labelled episode is generated from a fixed seed
and a validated configuration, so an auditor can rebuild the exact same books
and re-derive the same truth.

Purpose of this dataset: evaluation of decision-making agents, not production
bookkeeping. It is not a source of accounting advice.

## Composition

- **Episodes.** 20 labelled episodes (10 train, 10 dev) indexed by
  `episodes/index.json`, plus an unbounded number of hidden-style episodes
  generated on demand from a seed and a configuration.
- **Open files** (agent-observable). `manifest.json`, `policy.json`,
  `ledger.csv`, `invoices.jsonl`, `payments.jsonl`, and `fx.csv`.
- **Closed files** (evaluator-only). `truth.json` and `provenance.json`.
- **Records.** Each episode contains a general ledger (a few hundred balanced
  journal rows), between 20 and 200 documents (invoices and payments), and an
  FX rate table. Money is stored as integers in minor units.
- **Errors.** Four material error types — duplicate invoice posting,
  payment-allocation gap, FX-rate error, and reporting-period cutoff — plus two
  composite scenarios (boundary-FX payment and gap/cutoff payment). Clean
  episodes contain realistic distractors (split payments, refunds, recurring
  identical amounts, legitimately open invoices) but zero injected errors.

## Generation process

1. A seed is validated and expanded into independent per-subsystem streams
   using a stable hash (`letro.rng`), so generation does not depend on
   `PYTHONHASHSEED` or process ordering.
2. `letro.generator.company.build_company` constructs a fictional company:
   entities, invoices, payments, FX rates, and a balanced journal.
3. `letro.generator.errors.inject_errors` injects the configured errors and
   records each injection as a provenance step.
4. A separate rebuild of the ledger in the injected episode is used to keep
   books balanced while the reference audit can still detect the discrepancy.
5. `reference_audit` re-derives the issues from open records alone; that
   re-derivation is the truth. `truth.json` is the closed answer key a
   submission is scored against, and `provenance.json` records how it was
   produced.

All generation is deterministic for a fixed seed, is offline, and uses only the
Python standard library.

## Intended use

- Evaluating auditing agents against a reproducible, seeded environment.
- Verifying the environment contract, reward reliability, and reproducibility
  with `python -m letro.verify`.
- Demonstrating evidence sufficiency (`python -m letro.proof`), reward bounds
  (`python -m letro.redteam`), isolation (`python -m letro.isolation`), and the
  compute envelope (`python -m letro.bench`).
- Honest difficulty science (`python -m letro.difficulty`).

## Out-of-scope use

- **Not real financial data.** Every company, entity, invoice, payment, rate,
  and period is fictional. No real company, person, or transaction is
  represented.
- **Not audit advice.** No finding produced by this dataset or by any policy
  running under it is a professional audit opinion. The environment rewards
  matching a synthetic answer key, not protecting a real stakeholder.
- **Not a trained model.** Training or running an LLM on this dataset produces
  no improvement claim this project endorses.
- **Not production bookkeeping.** The ledger is generated to exhibit balanced,
  auditable structure; it is not a general-purpose accounting engine.

## Biases and limitations

- The error taxonomy is fixed to four types and two composite scenarios. Real
  audit work involves many more failure modes and judgement calls.
- Distractors (split payments, refunds, open invoices) are synthetic and may not
  match the frequency or difficulty of real-world cases.
- The reference audit is deterministic and complete by construction; agents are
  compared to a computable answer key, which is a simplification of real audit
  uncertainty.
- Aggregate difficulty metrics are measured on the dev split and are not a
  guarantee of performance on unseen seeds.
- No professional accountant has reviewed the generated books or the findings
  for realism; `docs/FAILURE-ANALYSIS.md` and `docs/READINESS.md` state this
  explicitly.

## Maintenance

- The 20 labelled episodes are frozen; they must not be regenerated in place.
  Hidden-style checks generate unseen seeds instead.
- `docs/evidence/difficulty.json` is regenerated by `python -m letro.difficulty`
  and committed; documented numbers must be re-measured if generation changes.
- The verifier (`python -m letro.verify`) remains the single contract gate; new
  evidence commands must not weaken it.
- If the error taxonomy, reward formula, or schema version changes, this
  datasheet, `docs/SECURITY.md`, and the evidence files must be updated in the
  same change.
