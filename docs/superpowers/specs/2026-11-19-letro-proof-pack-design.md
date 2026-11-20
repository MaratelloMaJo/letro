# LETRO proof pack, difficulty science and judge experience

Status: proposed for approval
Date: 2026-11-19
Owner: LETRO
Supersedes: nothing. Extends `2026-11-19-letro-design.md`.

## 1. Intent and why

LETRO already satisfies the published hackathon contract: a reproducible
financial-audit environment, 20 labelled episodes, four policy adapters, a
verifier that reports 100/100, a jury-style runner, a 500-episode fuzz run,
Docker, and a read-only workbench.

The remaining risk is not missing features. It is that a judge sees another
well-built environment and cannot quickly tell why this one is more trustworthy
than the others. Most teams will score the table-stakes checks. Differentiation
has to come from evidence density and a memorable, verifiable story:

> LETRO is the environment that cannot lie to itself. Truth is derived by an
> independent audit over open records, every evidence set is sufficient and
> minimal, reward is attacked and bounded, and truth cannot leak by
> architecture. One command proves it.

This design adds three layers, in priority order:

- **A. Proof pack** — public, executable evidence for the claims the rubric
  actually rewards: contract, data/truth, reward reliability, reproducibility.
- **B. Difficulty science** — measured evidence that the task is solvable but
  not trivial, and that the reward separates careful work from guessing.
- **C. Experience layer** — a 90-second demo and a judge-facing workbench that
  makes the proof visible. The brief says a pretty UI earns no points, so this
  layer is explicitly demo-only and never a scored claim.

## 2. Goals

1. A busy judge can map every rubric check to one command and one expected
   result without reading the source.
2. Every core claim has an executable proof, not a README assertion:
   - truth follows from open records;
   - evidence is sufficient and minimal;
   - reward resists obvious gaming;
   - closed truth cannot leak through the observation surface;
   - the environment fits the stated compute budget.
3. The difficulty story is measured per error type, not asserted from a single
   aggregate F1.
4. A judge can reproduce the demo locally in under two minutes and see the
   evidence chain behind a finding.
5. All additions stay standard-library-only, offline, Python 3.11 compatible,
   and preserve every existing contract and reward rule.

## 3. Non-goals

- No new error type, no new reward term, no change to the matcher semantics.
- No model training, fine-tuning, LLM API, GPU use, or claims of model
  improvement. The brief awards zero points for training and forbids
  uncontrolled improvement claims.
- No hosted service, accounts, authentication, or multi-user deployment.
- No real financial data, real companies, real people, or professional audit
  opinion.
- No claim that the UI earns competition points.
- No replacement of the four required policy adapters.

## 4. Anti-goals

The work fails if any of these become true:

- A proof command passes because it checks the same code path it is supposed to
  audit, rather than an independent reconstruction.
- The proof pack or UI exposes closed truth, provenance, issue ids, or hidden
  seeds.
- A new check is added to the verifier merely to increase the reported count
  without adding a distinct failure mode.
- The difficulty section claims the task is hard because one naive baseline
  scores badly, without showing where and why it fails.
- The UI becomes the centerpiece or implies production readiness.
- The project grows runtime dependencies, network calls, or non-determinism.

## 5. Constraints

- Python 3.11+, standard library only at runtime and in tests.
- Offline. No paid API, no GPU, no telemetry.
- Two CPU cores, 4 GB RAM, 1 GB solution, 60 seconds per episode.
- Truth never enters `AuditEnv`, observations, info, errors, or trajectories.
- Existing commands and contracts remain valid:
  `python -m letro.verify`, `python -m letro.jury`, `python -m letro.fuzz`,
  `python -m letro.ui`, `python -m unittest discover -s tests`.
- Existing episodes under `episodes/train` and `episodes/dev` remain the
  labelled set; hidden-style checks generate unseen seeds.
- Documentation stays honest: no independent accountant review exists, the
  GitHub Actions workflow has not been observed from this machine, and the
  UI is local-only.

## 6. Approaches considered

### A. Proof pack (chosen, first)

Build a set of independent, executable proofs and a rubric map. This directly
targets the highest-weight rubric dimensions and is the strongest defense
against a judge who only skims.

Trade-off: more code and more commands to maintain. Mitigated by keeping each
proof small, deterministic, and covered by tests.

### B. Difficulty science (chosen, second)

Measure per-error-type precision and recall for the existing policies, add a
limited-information baseline, and count legitimate distractors in clean
episodes. This turns "the naive baseline scores 0.146" into a defensible
statement about what is hard and why.

Trade-off: requires new evidence generation and doc updates. It does not
change the environment.

### C. Experience layer (chosen, third)

A scripted 90-second demo and three workbench additions: an evidence-chain
panel, a judge challenge tab, and a compact policy leaderboard. This is
demo-only.

Trade-off: front-end work with no rubric points. Kept deliberately small and
read-only.

### D. Add a fifth error type (rejected)

Rejected. The brief requires four types and two interacting scenarios; a fifth
type adds surface area, regeneration cost, and no scoring value. It would also
dilute the proof that the existing taxonomy is complete.

### E. Train a model or call an LLM (rejected)

Rejected. Zero points, no GPU, no budget, high variance, and the brief warns
against unproven improvement claims. A scripted policy is explicitly enough.

### F. Hosted judge portal (rejected)

Rejected. Introduces auth, deployment, uptime, and data-handling risk for a
local hackathon submission. The local workbench plus Docker covers the demo.

## 7. Detailed design

### A1. Rubric map: `docs/JURY-MAP.md`

A table with one row per rubric check family:

| Rubric area | Claim | Command | Expected |
|---|---|---|---|
| Contract and isolation | reset/step, schemas, limits, invalid input, no leaks | `python -m letro.verify` | Contract 24/24, 25.00 |
| Data and truth | balanced books, declared discrepancy, sufficient evidence | `python -m letro.verify` and `python -m letro.proof` | Data 21/21; proof PASS |
| Reward reliability | matching, clean cases, false positives, duplicates, cost, attacks | `python -m letro.verify` and `python -m letro.redteam` | Reward 20/20; all attacks bounded |
| Reproducibility and generalization | exact replay, permutation and ID change | `python -m letro.verify` and `python -m letro.jury` | Repro 20/20; jury PASS |
| Engineering and explanation | one command, versions, trajectories, failure analysis, limitations | `python -m letro.verify`; `docs/FAILURE-ANALYSIS.md`; `docs/READINESS.md` | Engineering 10/10 |
| Compute envelope | 60 s/episode, 4 GB, offline | `python -m letro.bench` | all budgets PASS |

The map also lists the hidden-style checks the team cannot run directly and
what local evidence substitutes for them. It is the first document after
README.

### A2. Red-team reward suite: `letro/redteam.py`

Command: `python -m letro.redteam`.

Runs a fixed set of attacks against generated episodes and reports, for each:

- attack name;
- episode seed and config;
- reward;
- expected upper bound;
- verdict PASS/FAIL;
- one-line reason.

Attacks:

1. `mark_all` — submit a finding for every ledger row, capped at 30.
2. `duplicate_spam` — repeat the same plausible finding many times.
3. `evidence_less` — correct type and amount, no evidence ids.
4. `wrong_currency` — correct finding with another currency.
5. `wrong_amount` — correct finding with amount outside tolerance.
6. `guessed_ids` — plausible but non-existent affected ids.
7. `empty_on_clean` — submit nothing on a clean episode (must score 1.0).
8. `empty_on_error` — submit nothing on an erroneous episode (must be < 1).
9. `timeout` — exhaust the step budget without submitting (must truncate).
10. `oversized_payload` — more than 30 findings or oversized explanation.
11. `resubmit` — submit twice; the second call must not improve the score.
12. `duplicate_correct` — submit a correct finding twice; the duplicate is FP.

Bounds are explicit and per attack:

| Attack | Bound |
|---|---|
| `mark_all` | reward <= 0.2 |
| `duplicate_spam` | reward <= 0.2 |
| `evidence_less` | reward <= 0.0 |
| `wrong_currency` | reward <= 0.0 |
| `wrong_amount` | reward <= 0.0 |
| `guessed_ids` | reward <= 0.0 |
| `empty_on_clean` | reward == 1.0 |
| `empty_on_error` | reward <= 0.0 |
| `timeout` | reward <= terminal_reward(0, steps) |
| `oversized_payload` | reward == -1.0 |
| `resubmit` | second reward <= first reward |
| `duplicate_correct` | reward <= 0.5, and strictly less than the same single finding submitted once |

The `duplicate_correct` case is not a full gaming attack: it contains one true
finding and one duplicate. Its bound proves the duplicate earns nothing without
pretending the reward should be near zero.

The suite uses the public env and evaluator, never truth inside observations.
It exits 1 if any attack violates its bound.

### A3. Causal and evidence proof: `letro/proof.py`

Command: `python -m letro.proof`.

For each simple error type:

1. Generate a clean episode.
2. Generate the same episode with exactly one injected error of that type.
3. Assert the audit difference is exactly one issue of the right type. With a
   clean baseline there are no other issues, so the "other issues unchanged"
   clause is intentionally vacuous for this case.
4. Assert the single issue is the injected one, using the generator's closed
   provenance step as the injection record, and that its amount recomputes
   from documents and policy independently of `generator/audit.py`.

For the two current composite scenarios, the same with exactly two issues:

- `boundary_fx_payment`: a foreign-currency partial payment at the period
  boundary produces one FX issue and one period-cutoff issue.
- `gap_cutoff_payment`: a domestic partial payment at the period boundary
  produces one allocation-gap issue and one period-cutoff issue.

The proof covers the scopes the injectors actually produce: invoice and payment
FX, and invoice and payment cutoff (payment cutoff appears in composites). It
does not add a duplicate-plus-FX scenario; the earlier design mention of one is
stale and the current generator is authoritative.

Independence bar: `proof.py` does not import `generator/audit.py` arithmetic
and does not trust `truth.json` as the cause. It may read `provenance.json` to
learn what was injected, because provenance is the generation record, not the
audit's conclusion. Amounts are recomputed by a separate calculator in the
proof module. A second full issue detector is explicitly out of scope.

Evidence checks for every issue in a sample of episodes:

- every issue has at least one inclusion-minimal allowed set;
- every inclusion-minimal allowed set passes the matcher as a complete set;
- removing any one id from an inclusion-minimal set makes that set fail;
- additional allowed sets may be supersets; they are valid alternatives, but
  the minimality proof tests only inclusion-minimal sets;
- every affected id and evidence id resolves to an open record or document;
- the expected amount is recomputed from invoice/payment/fx/policy data by a
  separate small calculator in the proof module;
- no issue depends on a closed file.

Clean-episode distractors are asserted in aggregate across the five clean dev
episodes, not per episode:

- at least one split payment, one refund, one pair of recurring identical
  amounts, and one legitimately open invoice exist in the sample;
- the reference audit still returns zero issues.

Exit 1 on any failure. The proof is intentionally independent: it re-derives
amounts instead of importing the reference audit's arithmetic.

### A4. Isolation sentinel: `letro/isolation.py`

Command: `python -m letro.isolation`.

Two independent checks:

1. **Canary in closed mode.** Generate an episode, insert a unique canary
   string into its truth and provenance, run a maximal policy through the
   public env in eval mode, and scan every observation, info dict, error
   string, and trajectory record for the canary. Any hit fails.
2. **Static boundary.** Parse `letro/env.py` and `letro/tools.py` with `ast`
   and assert they do not directly import `evaluator`, `generator.audit`, or
   read `truth.json`. Also assert `AuditEnv` and `OpenStore` expose no
   attribute whose value is the truth object.

Scope: the sentinel proves the claim for the closed/eval surface. Train mode is
explicitly open and may expose aggregate diagnostics after a terminal submit;
it must not expose truth before or during the episode. The existing train-mode
`matched` diagnostics are allowed only after termination and are excluded from
the closed-mode scan.

To keep the static boundary honest, `LetroEnv` moves to `letro/lazy.py`; the
lazy factory import lives there, not in `env.py`. The finalize callable still
closes over the evaluator, but it is an opaque callable, not a truth-bearing
attribute of the environment. The isolation proof therefore claims "no leak
through the observable surface", not "truth is unreachable by memory
introspection".

The sentinel is stronger than key-name scanning because it detects a leak even
if the key is renamed.

### A5. Compute benchmark: `letro/bench.py`

Command: `python -m letro.bench`.

Measures:

- episode generation p50/p95/max;
- reset p50/p95/max;
- 100-step episode p50/p95/max;
- full verifier wall time;
- peak traced memory for one episode and for 20 episodes run sequentially;
- repository size of the clean archive;
- deterministic digest under two different `PYTHONHASHSEED` values.

Memory semantics: the 4 GB limit applies to one episode at a time. The
20-episode figure is a sequential run (each episode released before the next),
reported for stability; it is not compared to the 4 GB single-episode limit.
The 1 GB solution limit is checked as the size of the clean `git archive`
artifact, not as resident memory.

Compares time and single-episode memory against 60 s/episode and 4 GB, checks
the archive against 1 GB, prints a table, and exits 1 on breach. The benchmark
is descriptive, not a performance optimization project.

### A6. Datasheet and security note

- `docs/DATASHEET.md`: motivation, composition, generation process, intended
  use, out-of-scope use, biases and limitations, maintenance.
- `docs/SECURITY.md`: assets, trust boundaries, threats (truth leak, path
  traversal, action injection, calculator escape, DoS, reward gaming),
  mitigations, residual risks, and how to report a problem.

### B1. Per-error-type difficulty: `letro/difficulty.py`

Command: `python -m letro.difficulty`.

Runs the five policy classes in the code on the 10 dev episodes:
`random_explorer`, `reconciliation`, `thorough`, `mark_all`, and `oracle`.
`oracle` is evaluator-side reference and is labelled as such; it is not a
public-env adapter. Reports, per error type and per policy:

- TP, FP, FN, precision, recall, F1;
- which policy finds the type and which misses it;
- concrete failure examples (episode id, issue type, reason).

Writes `docs/evidence/difficulty.json` and prints a compact table. The point
is not to rank policies but to show which error types require real evidence
work.

### B2. Information-budget curve

Add `letro/policies/limited.py`: `LimitedPolicy` is a `ThoroughPolicy` with a
page budget. It uses the same analysis code and the same exact rules; only the
number of pages read per table varies. The default probe reads one page per
table; a second run reads two pages per table. This isolates information from
heuristic quality, so the measured gap is not confounded by the naive
reconciliation rule.

It is not one of the four required adapters; it is a difficulty probe.

Report F1 and steps for limited (1 page and 2 pages), thorough, and oracle.
The expected result is that partial reading loses findings, while the step cost
alone is too small to explain the gap. This avoids overclaiming a reward-shaping
effect.

### B3. Negative controls

In `letro/difficulty.py`, count in the five clean dev episodes in aggregate:

- split payments;
- refunds;
- recurring identical amounts;
- legitimately open invoices.

Assert each aggregate count is above zero and the reference audit returns zero
issues across the sample. This proves the dataset contains realistic
distractors, not empty books. Per-episode assertions are explicitly not
required: a single clean episode may legitimately contain no refund.

### B4. Human review status

No accountant review is performed. `docs/FAILURE-ANALYSIS.md` and
`docs/READINESS.md` state this explicitly and describe what a review would
require. No fake external validation.

### C1. Ninety-second demo

`scripts/demo.py` becomes a scripted story with timing comments:

1. Open a clean episode; show zero issues.
2. Run the naive reconciliation policy; show false accusations and low F1.
3. Run the thorough policy; show the exact issues and one evidence chain.
4. Permute ids and order; show the same answer and reward.
5. Run the red-team table; show every attack bounded.

The demo is deterministic, offline, and needs no narration beyond the printed
steps.

### C2. Workbench additions

Keep the existing read-only server and add:

- **Evidence chain panel.** For a selected finding, show the referenced
  invoice/payment/ledger rows, the arithmetic, and the policy rule that makes
  the set sufficient. Data comes from open files only.
- **Challenge tab.** A judge can paste or load a findings JSON for a labelled
  episode. `POST /api/challenge` scores it evaluator-side and returns aggregate
  TP/FP/FN, P/R/F1, reward, and per-finding match status. It never returns
  truth ids or hidden amounts.
- **Leaderboard.** A compact table on the selected episode or the dev set with
  F1, reward, and steps for `random_explorer`, `reconciliation`, `thorough`,
  and `mark_all`. `oracle` is shown as an evaluator-side reference row using
  the published evidence file, not instantiated with truth inside the UI. The
  UI never receives `truth.json`.

New endpoint rules: same body cap, same headers, episode ids only from the
index, no truth.json, no arbitrary file paths.

### C3. Challenge CLI

`python -m letro.challenge --episode <id> --findings <path>` scores a JSON
submission against a labelled episode and prints aggregate metrics plus
per-finding status. It is evaluator-side and refuses hidden seeds. Useful when
a judge wants to test the matcher without the UI.

## 8. Interfaces and data shapes

### Red-team result

```json
{
  "attack": "mark_all",
  "seed": 1001,
  "episode_id": "ep-...",
  "reward": -1.0,
  "bound": 0.2,
  "verdict": "PASS",
  "reason": "30 false positives; F1 0.0"
}
```

### Proof result

```json
{
  "case": "duplicate_invoice",
  "seed": 1001,
  "clean_issues": 0,
  "injected_issues": 1,
  "added_types": ["duplicate_invoice"],
  "evidence_minimal": true,
  "amount_recomputed": true,
  "verdict": "PASS"
}
```

### Benchmark result

```json
{
  "operation": "100_steps",
  "p50_ms": 12.4,
  "p95_ms": 18.1,
  "max_ms": 25.0,
  "budget_ms": 60000,
  "verdict": "PASS"
}
```

### Difficulty result

```json
{
  "policy": "reconciliation",
  "error_type": "payment_allocation_gap",
  "tp": 0,
  "fp": 12,
  "fn": 6,
  "precision": 0.0,
  "recall": 0.0,
  "f1": 0.0,
  "example": "false accusation on a legitimately open invoice"
}
```

## 9. Acceptance criteria

The increment is accepted only when all of these are true and evidenced:

1. `python -m unittest discover -s tests -q` passes with at least 110 tests.
2. `python -m letro.verify` reports 100.00 and `RESULT: PASS`.
3. `python -m letro.jury` reports PASS with oracle 20/20, permutations 20/20,
   exact replays 5/5, and zero failures.
4. `python -m letro.fuzz --seeds 100` reports 500/500 and zero failures.
5. `python -m letro.redteam` reports every attack within its bound and exits 0.
6. `python -m letro.proof` reports every causal, evidence, and distractor case
   PASS and exits 0.
7. `python -m letro.isolation` finds no canary and no forbidden import and
   exits 0.
8. `python -m letro.bench` stays within 60 s/episode and 4 GB, checks the
   clean archive against 1 GB, and prints the same digest under two hash seeds.
9. `python -m letro.difficulty` writes `docs/evidence/difficulty.json` and
   shows per-type results and aggregate non-zero distractor counts across the
   five clean dev episodes.
10. `docs/JURY-MAP.md`, `docs/DATASHEET.md`, `docs/SECURITY.md`,
    `docs/FAILURE-ANALYSIS.md`, `docs/READINESS.md`, `README.md`, and
    `DESIGN.md` are consistent with the measured numbers.
11. The workbench shows the evidence chain, challenge scoring, and
    leaderboard; it remains read-only and does not serve truth.
12. `docker build` and `docker run --rm letro:1.0.0` pass on Python 3.11.
13. A clean `git archive` extraction passes the verifier.
14. The working tree is committed and clean.

## 10. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Proof duplicates the audit logic and proves nothing | High | Recompute amounts independently in `proof.py`; do not import `generator/audit.py` arithmetic |
| Red-team suite is too easy | High | Include guessed ids, evidence-less, wrong currency, duplicates, timeout, resubmit, and clean/error silence |
| Canary check gives false confidence | Medium | Pair it with a static import boundary check and trajectory scan |
| Difficulty metrics overclaim | Medium | Report per-type results and failure examples; state the step cost is small |
| UI leaks truth | Critical | Serve only open files; no truth.json; challenge endpoint returns aggregates only; tests for every route |
| More commands break one-command story | Medium | Keep `python -m letro.verify` as the single gate; document the rest as focused proofs |
| Time budget | Medium | A first, B second, C last; C can be reduced to the existing workbench plus one evidence panel |
| Docker or CI drift | Medium | Re-run Docker and clean archive before commit; CI remains a configured, unobserved check |

## 11. Out of scope

- New error types, new reward terms, matcher changes.
- Model training, fine-tuning, LLM calls, GPU work.
- Hosted deployment, authentication, multi-user state.
- Real financial data or professional audit conclusions.
- A fifth policy adapter for the official four.
- Changing the 20 labelled episodes or the published reward formula.

## 12. Builder calls already made

These are decisions the builder should follow unless evidence forces a change:

- The proof pack uses generated hidden-style seeds, not the labelled episodes,
  except where the labelled set is needed for the judge-facing demo.
- `redteam`, `proof`, `isolation`, `bench`, `difficulty`, and `challenge` are
  separate modules with `python -m` entry points, not subcommands of the
  verifier.
- The verifier remains the single pass/fail gate for the competition contract;
  the new commands are focused evidence and may be run independently.
- The UI stays standard-library `http.server`, binds `127.0.0.1` by default,
  and serves no closed file.
- `LimitedPolicy` is a difficulty probe, not a required adapter.
- The demo uses `ThoroughPolicy` for the correct solve and
  `ReconciliationPolicy` for the naive contrast.
- Evidence minimality means "at least one inclusion-minimal allowed set"; a
  truth issue may also carry a valid superset. The proof tests minimal sets and
  does not require regenerating the 20 labelled episodes.
- Isolation is proved for the closed/eval surface. Train mode may expose
  aggregate diagnostics after terminal submit; it never exposes truth before
  or during the episode. `LetroEnv` moves to `letro/lazy.py` so `env.py` has no
  direct evaluator or audit import.
- Proof independence means: provenance is the injection record, amounts are
  recomputed by a separate calculator, and no second full audit detector is
  built. The proof does not import `generator/audit.py` arithmetic.
- Proof covers the two composites the generator actually produces:
  `boundary_fx_payment` and `gap_cutoff_payment`.
- `LimitedPolicy` is a page-budgeted `ThoroughPolicy`; only information varies,
  not the heuristic.
- Red-team bounds are the per-attack table in A2, not a single global bound.
- Benchmark memory is measured one episode at a time; the 20-episode figure is
  sequential, and the 1 GB limit applies to the clean archive.
- Distractor assertions are aggregate across the five clean dev episodes.
- The leaderboard shows the four public policies plus `thorough`; `oracle` is
  an evaluator-side reference row from evidence, never instantiated with truth
  in the UI.

## 13. What is left to the builder

- Exact module layout and helper names inside each new module.
- Test organization and fixture reuse.
- Whether `difficulty` and `bench` share a small reporting helper.
- Whether the workbench challenge tab is a separate route or a panel in the
  existing page, as long as the security rules hold.
- The precise wording of the rubric map and datasheet, provided every claim is
  backed by a command and an observed result.
