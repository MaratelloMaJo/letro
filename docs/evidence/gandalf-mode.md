# Production readiness score — rec-genesis-letro-100

**Verdict:** `Finalist` — **100.0/100.0** (raw 100.0, penalties 0.0, reward 1.0000)

| ID | Phase | Weight | Met | Awarded | Criterion | Evidence | Reasoning |
|---|---|---:|---|---:|---|---|---|
| `c1.contract` | P1 | 25 | yes | 25 | Contract and isolation: reset/step shapes, schemas, limits, completion, invalid input, no truth leaks (20 fixed checks) | python -m letro.verify | All checks pass. |
| `c2.data` | P1 | 25 | yes | 25 | Data and truth: books balanced before injection, declared discrepancy after, independently sufficient evidence (20 closed episodes) | python -m letro.verify | All checks pass. |
| `c3.reward` | P2 | 25 | yes | 25 | Reward reliability: matching, clean cases, false positives, duplicates, cost, adversarial answers (20 checks) | python -m letro.verify | All checks pass. |
| `c4.repro` | P2 | 15 | yes | 15 | Reproducibility and generalization: exact replay, id and order permutation preserve oracle answer and reward (20 paired checks) | python -m letro.verify | All checks pass. |
| `c5.engineering` | P4 | 10 | yes | 10 | Engineering and explanation: one-command launch, config versions, trajectory logs, measured failure analysis, honest limitations (5 x 0/1/2) | python -m letro.verify | All checks pass. |
