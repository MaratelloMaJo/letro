# Failure analysis

This note records what broke while building LETRO, how it was detected, what was
fixed, and which risks remain. Numbers come from the shipped artefacts and from
`python -m letro.verify`.

## 1. Measured baseline behaviour

Ten dev episodes: five clean, five with errors (including composites). The same five
adapters ran on all ten.

| Policy | Mean F1 | Clean F1 | Erroneous F1 | Mean reward | Mean steps | TP | FP | FN |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| random_explorer | 0.400 | 0.800 | 0.000 | -0.211 | 15.0 | 0 | 12 | 24 |
| reconciliation | 0.146 | 0.000 | 0.293 | -0.717 | 11.8 | 15 | 143 | 9 |
| thorough (reference) | 1.000 | 1.000 | 1.000 | 0.978 | 11.8 | 24 | 0 | 0 |
| mark_all | 0.000 | 0.000 | 0.000 | -1.000 | 2.0 | 0 | 300 | 24 |
| oracle | 1.000 | 1.000 | 1.000 | 1.000 | 1.0 | 24 | 0 | 0 |

The naive `reconciliation` heuristic is the scored baseline. It detects duplicate
postings, FX mismatches and cut-offs, but it treats every invoice with an open
balance as an unallocated payment. On clean books it therefore accuses 12-23
invoices per episode and scores F1 0.000; on erroneous books it finds 15 of 24
issues but pays 143 false positives. This is the measured difficulty the
environment is supposed to expose: a simple rule is not enough.

The `thorough` reference mirrors the audit arithmetic and reaches F1 1.000 on the
same episodes. It proves solvability and matcher correctness, not model capability.
The oracle is evaluator-side only and sets the ceiling.

The random explorer's clean mean F1 of 0.800 is not a bug: on four clean episodes it
stays silent and gets F1 = 1.0; on one it submits a guessed row and gets F1 = 0.0.
Averaged over five clean episodes that is 0.800.

## 2. Bugs found during development

### 2.1 FX-payment injection broke double-entry

The payment FX row was adjusted with the wrong sign:

```text
new_signed = signed_fx - delta   # wrong
```

The cash row moved by `delta`, so the journal entry was off by `2 * delta`. The
balance check caught it on the first injected payment. Fixed to `+ delta` in
`_inject_fx_payment` and `_composite_boundary_fx`. All 20 shipped episodes and all
hidden verification seeds now have equal total debits and credits, and every
`(timestamp, entity, invoice, payment)` group balances.

### 2.2 Duplicate-invoice truth depended on record order

The reference audit originally took the first AR debit as the legitimate posting and
treated the rest as duplicates. After the permutation check renamed and shuffled
records, the "first" row changed, so the canonical affected-id set changed and the
oracle stopped matching. Fixed by sorting AR debits by `(timestamp, row_id)` before
choosing the legitimate row and the extras. The same rule is applied in the
reconciliation policy. The 20 paired permutation checks now preserve the oracle
answer and reward.

### 2.3 Mark-all submitted an empty list

The mark-all adapter's state machine marked the ledger request as asked but skipped
collecting the rows, then submitted zero findings. That produced F1 = 0 for the wrong
reason. Fixed the state machine; the adapter now submits 30 accusations, gets 300
false positives across the ten dev episodes and reward -1.000. The test
`test_mark_all_on_clean_is_punished` guards the clean case.

### 2.4 Trajectory validator allowed only one run per episode

The recorder intentionally runs the same episode with more than one policy. The first
validator treated a second `step = 1` as an out-of-order step and rejected the file.
Fixed to track runs: `step = 1` starts a new run only after the previous run is
finished, a run cannot restart before it ends, and a run cannot continue after
termination or truncation. The shipped log validates as 500 records, 20 episodes and
40 runs.

### 2.5 A partial single payment was allocated as a full payment

The clean company builder used the "last part gets the remainder" rule even when the
payment plan was a single partial payment. That cleared the whole invoice in AR and
made a legitimate partial payment look fully paid. Fixed by applying the remainder
only when the parts sum to the invoice total; otherwise the allocation is
proportional. This removed a class of false negatives from clean books.

## 3. Tests that guard the failure modes

- Clean seeds: 30 generated clean episodes, zero audit issues.
- Error counts: each of the four types alone; two composites; mixed configurations
  up to 60 invoices and 600 ledger rows; audit count equals truth count on every
  seed tested.
- Matcher: perfect answer, duplicate finding, missing evidence, evidence superset,
  amount ±1 and ±2, wrong currency, wrong type, non-canonical affected set.
- Attacks: mark-all on dirty and clean books, silence on dirty books, false
  accusation on clean books, fabricated evidence, persuasive text, repeated finding.
- Contract: pagination covers every row exactly once, invalid action costs one step,
  submit terminates, second submit does not rescore, timeout truncates with an empty
  answer, eval mode hides reward and metrics, reset clears state.
- Reproducibility: byte-identical replay, id renaming and table shuffling, oracle and
  reconciliation answers preserved.
- Leaks: forbidden-key scan over observations and info, recorder rejection, exact
  seven-field trajectory schema.

The suite has 78 tests and passes in about 3 seconds on the development machine. The
verifier's 80 technical checks all pass.

## 4. Residual risks

- **Shared assumptions.** The generator, reference audit and `thorough` reference
  policy were written by the same author and share accounting conventions. The audit
  reads only open files and is a separate code path from injection, but a wrong
  convention would be wrong consistently. External review of the accounting rules is
  the best mitigation.
- **Within-family generalization.** Hidden seeds use the same generator. The
  permutation check covers id and order changes, not new document formats, new
  currencies or new error types. The environment does not claim out-of-family
  generalization.
- **The naive baseline fails, by design.** `reconciliation` scores F1 0.146 because it
  accuses every open invoice; `thorough` reaches 1.000 because it mirrors the published
  rules. The gap proves the matcher and reward are coherent and that a simple rule is
  not enough, but it is still not evidence that an LLM can audit. A harder variant
  would add noisy documents or require judgment calls that neither policy can read off
  a formula.
- **Finite seed coverage.** The tests use a fixed set of seeds. They do not prove
  that every seed in the allowed range generates a solvable episode, although the
  generator raises rather than shipping a mismatch.
- **Tolerance and evidence choices.** The ±1 minor-unit tolerance and the
  superset-evidence rule are explicit policy choices. A different tolerance would
  change the FP/FN boundary; the policy file and README document the choice.
- **No trained model.** The project measures the environment and the matcher. It does
  not claim a trained agent or a real audit capability.
