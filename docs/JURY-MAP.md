# LETRO jury map

The jury should be able to check every claim in this submission with one
command. This map is the index: one row per rubric check family, the command
that proves it, and the expected result. `python -m letro.verify` remains the
single pass/fail gate; the other commands are focused evidence and run
independently.

| Rubric area | Claim | Command | Expected |
|---|---|---|---|
| Contract and isolation | reset/step, schemas, limits, invalid input, no leaks | `python -m letro.verify` | Contract 24/24, 25.00 |
| Data and truth | balanced books, declared discrepancy, sufficient evidence | `python -m letro.verify` and `python -m letro.proof` | Data 21/21; proof PASS |
| Reward reliability | matching, clean cases, false positives, duplicates, cost, attacks | `python -m letro.verify` and `python -m letro.redteam` | Reward 20/20; all attacks bounded |
| Reproducibility and generalization | exact replay, permutation and ID change | `python -m letro.verify` and `python -m letro.jury` | Repro 20/20; jury PASS |
| Engineering and explanation | one command, versions, trajectories, failure analysis, limitations | `python -m letro.verify`; `docs/FAILURE-ANALYSIS.md`; `docs/READINESS.md` | Engineering 10/10 |
| Compute envelope | 60 s/episode, 4 GB, offline | `python -m letro.bench` | all budgets PASS |

## Observed locally

The table above is the acceptance target for each row. The numbers below are
the observed output at the commit that added this file, on Python 3.14.6 with
the standard library only; the project targets Python 3.11+.

- `python -m letro.verify` — Contract 24/24, Data 21/21, Reward 20/20,
  Reproducibility 20/20, Engineering 10/10, `TOTAL 100.00`,
  `RESULT: PASS`.
- `python -m letro.redteam` — 12 attacks, 12 PASS, 0 FAIL,
  `RESULT: PASS`. The per-attack rewards and bounds are printed by the
  command and repeated in the task report.
- `python -m letro.jury` — 20 hidden-style episodes, oracle 20/20,
  permutations 20/20, exact replays 5/5, `RESULT: PASS`.

`letro.proof`, `letro.isolation`, `letro.bench`, `letro.difficulty` and
`letro.challenge` are the remaining commands of this proof pack. Rows that
name them are acceptance targets until those modules land; after that, this
section records their observed output as well.

## What is not locally observable

Three parts of the jury's run happen outside this repository. Each has a local
substitute that measures the same property without pretending to reproduce the
hidden data.

| Hidden item | Why it is not observable here | Local substitute |
|---|---|---|
| The official hidden seeds | The organizer draws the seed, config and episode ids after submission; none of them is published | `python -m letro.jury` runs 20 hidden-style seeds (7001-7020) over clean, composite and mixed configurations, and `python -m letro.proof` reconstructs each injected cause from open records |
| The organizer's four policies | Their exact adapters and scores are not published, so their leaderboard numbers cannot be replayed | `python -m letro.jury` runs local equivalents of all four (`random_explorer`, `reconciliation`, `mark_all`, `oracle`), and `python -m letro.redteam` bounds what any policy can gain from the twelve reward attacks |
| The final jury score | The score is computed by the jury after the submission closes | `python -m letro.verify` is the local gate, and the published `docs/evidence/*.json` files carry the measured numbers: `policy-metrics.json`, `hardening.json`, `gandalf-verdicts.json`, `competition-rubric.json` |

None of these substitutes reads `truth.json` from a labelled episode: the jury
and red-team suites generate their own episodes, the proof re-derives amounts
from open records, and the evidence files are produced by the commands that
are named beside them.
