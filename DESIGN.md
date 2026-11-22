# LETRO design note

## 1. Problem

The competition asks for a reproducible environment in which a policy can investigate
a company's books and report accounting discrepancies. The difficult part is not the
interface; it is making the hidden answer *true*, *provable* and *isolated* at the same
time. A generator that writes a suspicious row and then declares it an error can
produce an unsolvable episode. A matcher that rewards persuasive text can be gamed.
An environment that holds truth can leak it.

LETRO is built around one rule: **the closed answer is a function of the open files,
computed by code that never reads the closed answer.** Everything else follows.

## 2. Architecture

```text
seed + config
     |
     v
build_company()          clean double-entry history, documents, FX, policy
     |
     v
inject_errors()          four types + two composites; every entry stays balanced
     |
     v
reference_audit()        reads open records only -> truth issues
     |                   generation fails if the count is wrong
     +-----------------------------+
     |                             |
     v                             v
open files                     truth.json / provenance.json
     |                             |
     v                             v
AuditEnv(open_data, finalize)   Evaluator (runner-owned)
     |                             |
     v                             v
policy actions -> observations   matcher + terminal reward
```

`AuditEnv` receives open data and a `finalize` callback. It never receives an
`Episode`, a `truth` dict or a seed. The `Evaluator` receives the episode, owns truth
and tolerance, and is the only component that can score a submission. In evaluation
mode the callback returns `reward=0.0` and empty diagnostics, so the policy cannot
learn the answer from the environment's response.

The package is standard-library only: `csv`, `json`, `decimal`, `datetime`,
`hashlib`, `ast`, `random`, `unittest`. There is no network, GPU or paid API.

## 3. Generator

`build_company(seed, config)` creates three related entities, invoices in KZT/USD/EUR,
full, split and partial payments, refunds, recurring operating expenses and a daily
FX table. The ledger is double-entry in the base currency. Invoice postings debit
receivables and credit revenue at the invoice-date rate. A payment debits cash at the
payment-date rate, credits receivables proportionally at the invoice-date rate, and
books the difference to an FX gain/loss account. This makes every journal entry
balance even when the payment date and invoice date have different rates.

Distractors are deliberate: split payments, negative refund payments, recurring
expenses with identical amounts, invoices left open, and documents in foreign
currencies. They look suspicious but are correct.

`inject_errors(episode, seed, config)` mutates the clean history:

| Type | Mutation | What the auditor must prove |
| --- | --- | --- |
| `duplicate_invoice` | a second AR/revenue posting for one invoice | the extra posting is not a legitimate split or adjustment |
| `payment_allocation_gap` | part of a receipt is left in a suspense account instead of clearing AR | the payment covers the invoice but AR is still overstated |
| `fx_rate_error` | an invoice or payment is converted at a nearby day's rate | the posted base amount differs from the policy rate for the document date |
| `period_cutoff` | a document inside the period is posted outside it | the document belongs to the period but the posting does not |

Two composites combine errors on one object:

- `boundary_fx_payment`: a foreign-currency partial payment at the period boundary,
  posted outside the period and converted at the wrong rate;
- `gap_cutoff_payment`: a domestic partial payment at the boundary with an allocation
  gap and a posting outside the period.

A composite is modelled as two separate truth issues, because each discrepancy must be
reported and evidenced separately. This keeps the matcher simple and the answer
unambiguous.

After injection, `reference_audit(episode)` recomputes every issue from open records
only. It derives canonical `affected_ids`, the expected amount in base minor units,
the currency, and two allowed evidence sets. Generation raises `GenerationError` if
the audit count differs from the configured count. Clean episodes assert an empty
audit. This is the central safety property: a shipped episode cannot contain a truth
issue that the open files do not prove.

## 4. Environment and tools

`reset(seed, config)` returns a first observation with the task text, manifest, a
policy summary and the step budget. Later observations contain only the last tool
result and the budget. `step(action)` validates the action, dispatches it through a
read-only store and returns the five-tuple.

`OpenStore` deep-copies the open tables, sorts them deterministically and paginates
with a stable cursor. `list_records` is capped at 50 rows. `get_record` accepts a
business id (`INV-…`, `PAY-…`) or a document id. `get_document` accepts a document
id. The calculator parses a restricted AST: numbers, `+ - * /`, unary signs and
parentheses. Names, calls, powers, modulo and non-finite values are rejected. There is
no shell, SQL, filesystem or network path.

Invalid actions and unknown ids produce a bounded error string, consume one step and
do not terminate the episode. A non-submit action on the 100th step terminates with
`truncated=True` and an empty answer; `submit` as the 100th step is scored normally.
`submit` is the only action that terminates normally.

## 5. Matching and reward

Matching is a maximum bipartite matching between findings and truth issues. An edge
exists only when type, canonical affected-id set, currency, amount (±1 minor unit) and
at least one complete allowed evidence set all agree. Maximum matching is important:
a greedy matcher could assign a finding to the wrong issue and undercount true
positives when several issues share a type.

The metrics and reward are exactly the published ones. `inspection_steps` counts
every non-submit action, including invalid ones, so probing is not free. There is no
intermediate reward. A malformed submission is a structural failure with reward `-1`.
Empty truth plus empty findings is F1 = 1, which rewards silence on clean books.

The evidence rule accepts a superset of an allowed set. This is deliberate: an auditor
may cite additional relevant rows without being penalised, as long as one complete
proof is present. Amounts are compared in the base currency, so a foreign-currency
document cannot be matched by comparing its original amount.

## 6. Determinism

All randomness comes from SHA-256-derived streams keyed by `(seed, purpose)`. The
episode id is a hash, not the seed. Tables are sorted by stable ids before
pagination. No decision depends on dictionary insertion order, wall-clock time,
locale or process state. The same seed and config produce byte-identical open files
and identical rewards.

The verifier also applies a harmless transformation: all ids are renamed, all tables
are shuffled and truth is rebuilt from the transformed files. The oracle answer and
reward must be preserved. This catches accidental dependence on original ids or
record order, which is exactly the kind of overfitting the rubric tests.

## 7. Engineering trade-offs

- **Truth derived, not authored.** Slightly slower generation, much stronger
  solvability guarantee. The audit is not reused by the scored baseline: the
  `thorough` reference keeps it as an upper bound, while `reconciliation` is a
  deliberately naive heuristic so the measured gap means something.
- **Two allowed evidence sets per issue where a second complete proof exists.**
  Gives the auditor a reasonable choice (for example, with or without the suspense
  row) without accepting an incomplete proof. A duplicate invoice requires the
  invoice plus every AR and revenue posting for it, because the original posting
  is what makes the extra one provable; the verifier rejects an evidence set that
  cannot be re-derived from the open records.
- **Composites as two issues.** Simpler matching and clearer partial credit than a
  special composite type, at the cost of requiring two findings.
- **No third-party dependencies.** Makes the container and the offline check trivial;
  the cost is hand-written CSV/JSON handling and no property-based testing library.
- **Two honest baselines instead of one perfect one.** The naive `reconciliation`
  heuristic finds provable duplicates, FX errors and cut-offs but treats every open
  invoice balance as an unallocated payment; the `thorough` reference mirrors the
  audit and reaches F1 1.000. The gap between them is the measured difficulty, and
  the random, mark-all and oracle adapters bracket the reward from below and above.

## 7.1 Hardening, fuzz and workbench

The environment supports both `AuditEnv(open_data)` and the lazy `AuditEnv()` /
`LetroEnv()`. The lazy form builds an episode on `reset` through the factory, so a
harness can call `env = AuditEnv(); env.reset(seed, config)` without constructing a
generator first. A `step` before `reset` starts the episode, which makes the object
safe for generic runners.

`letro.presets` adds `hard`, `hard_composite`, `clean` and `wide` configurations.
`letro.fuzz` checks balance, manifest counts, truth reproduction, evidence
resolution and permutation stability; the full run covers 500 episodes. `letro.jury`
runs 20 hidden-style seeds with the four required adapters, 20 ID/order permutations
and 5 exact replays. `letro.invariants` is an independent reader of the same
contract, so the fuzz does not inherit the verifier's assumptions.

`letro.ui` is a read-only workbench served by `http.server` on `127.0.0.1:8000`. It
shows the open records, runs a policy, and displays the evaluator's terminal
metrics. It never serves `truth.json`, never accepts a filesystem path from a client,
and is not part of the scored environment.

## 8. Proof pack

The proof pack is three independent guarantees:

**Truth is derived, not authored.** `letro/proof.py` regenerates a clean episode and a
single-error episode for each error type and both composites. For every case it
asserts the audit difference is exactly one issue (two for a composite) with the
right type, that each allowed evidence set is inclusion-minimal and sufficient, and
that every expected amount is recomputed by a separate calculator that reads only
invoices, payments, FX and policy — not `letro.generator.audit` arithmetic.

**Reward cannot be gamed.** `letro/redteam.py` runs 12 adversarial submissions and
asserts each stays at or below its published bound: mark-all ≤ 0.2, duplicate spam ≤
0.2, evidence-less / wrong currency / wrong amount / guessed IDs / empty-on-error ≤
0.0, timeout ≤ terminal reward at zero F1, oversized payload = −1, empty-on-clean =
1.0, resubmit does not improve, and a duplicated correct finding scores strictly less
than a single correct finding.

**Truth cannot leak.** `letro/isolation.py` plants a unique canary string in a copied
truth/provenance object, runs every action (list every table, get_record,
get_document, calculator, invalid action, submit) through an eval-mode environment,
and scans every observation, info, error string and trajectory record for the canary.
A static AST check forbids `letro/env.py` and `letro/tools.py` from importing the
evaluator, the audit module or the factory. `LetroEnv` lives in `letro/lazy.py`; the
lazy boundary is exercised by `AuditEnv()` building an episode on `reset`.

## 9. Measured evidence

`python -m letro.verify` runs 85 technical checks and five engineering criteria. On
the shipped artefacts all technical checks pass; the engineering score depends on the
presence of this note, the README, the container, the trajectory log, the failure
analysis and the limitations section.

On ten dev episodes the scripted baselines behave as intended: random exploration
gets mean F1 0.400 and reward -0.211, mark-all gets F1 0.000 and reward -1.000, the
naive reconciliation heuristic gets F1 0.146 and reward -0.717, the `thorough`
reference gets F1 1.000 and reward 0.978, and the evaluator-side oracle gets
F1 1.000 and reward 1.000. The naive baseline fails on clean books (F1 0.000)
because it accuses every open invoice, which is exactly the behaviour the reward
must punish; the reference proves the same episodes are solvable.

The hardening evidence is in `docs/evidence/hardening.json`: 134 unit and integration
tests, 85 technical verifier checks, 500 fuzz episodes with zero failures across five presets,
and a 20-episode jury run with 20/20 oracle and permutation checks and 5/5 exact
replays. The workbench is a demo surface and is not counted in the score.

## 9. Limitations

The data is synthetic and the taxonomy has four types. The tolerance is a competition
convention, not a materiality policy. Hidden seeds come from the same generator
family, so the generalization check is within-distribution. No model is trained and
no GPU is used; the reward measures answer quality and evidence, not the quality of a
professional audit. The environment deliberately has no shell, filesystem or network,
so it cannot test misuse of those capabilities. See `README.md` and
`docs/FAILURE-ANALYSIS.md` for the full honest list.

