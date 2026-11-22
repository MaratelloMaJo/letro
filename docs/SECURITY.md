# LETRO security note

This note describes what must stay secret, where the trust boundaries are, the
threats the design considers, and how to report a problem.

## Assets

| Asset | What it is | Confidentiality |
|---|---|---|
| `truth.json` | The closed answer key: the definitive issue list with expected amounts and allowed evidence sets. | Secret. Never observable by an agent. |
| `provenance.json` | The generation record: which seed/config produced which injected error. | Secret. It is a generator artifact, not an agent input. |
| Seed and config | The inputs that deterministically rebuild an episode. | Secret for held-out evaluation. A seed leaks the whole episode. |
| Evaluator | The only component that reads `truth.json` and scores a submission out of band. | Trusted. It must never be reachable from an observation. |

The open files (`manifest.json`, `policy.json`, `ledger.csv`, `invoices.jsonl`,
`payments.jsonl`, `fx.csv`) are public by design: the task is to find the
discrepancy in them, not to guess a hidden record.

## Trust boundaries

- **Agent** — untrusted. Receives only observations; may send arbitrary actions.
- **Environment (`AuditEnv` / `LetroEnv`)** — read-only over the open store. It
  holds an opaque `finalize` callback, never the truth object, and builds
  episodes through `letro.lazy` so `env.py` imports no evaluator or audit
  arithmetic.
- **Evaluator** — trusted. Owns `truth.json`, runs the matcher and the reward
  formula, and is the only place a submission is scored.
- **UI / workbench** — read-only, local (`127.0.0.1` by default), serves open
  files and aggregate results only, and never serves `truth.json`.

## Threats and mitigations

| Threat | Mitigation |
|---|---|
| Truth leak through observations | `FORBIDDEN_OBSERVATION_KEYS` plus a canary sentinel (`letro.isolation`) that scans observations, info, errors, and trajectories for a unique injected string. |
| Path traversal | The UI resolves episodes only through the labelled index and rejects arbitrary path input; the environment exposes a fixed table surface, not filesystem access. |
| Action injection | Actions are validated against a closed schema (`validate_action`); unknown shapes and unknown tables/ids produce bounded errors. |
| Calculator escape | `letro.tools.calculate` is a whitelisting decimal evaluator: no attributes, names, imports, powers, or division by zero. |
| Denial of service | Pagination is capped (`MAX_PAGE`, `limit` bounds), explanations and expressions are length-capped, findings are capped at `MAX_FINDINGS`, and each episode is bounded to `MAX_STEPS`. |
| Reward gaming | The reward depends on F1 and inspection-step cost (`clip(2*F1 - 1 - 0.002*steps, -1, 1)`); duplication, evidence-less findings, and wrong ids/amounts score poorly, as proven by `letro.redteam`. |
| Seed leakage / regeneration | Seeds are hashed into per-stream RNGs; held-out seeds are not enumerated in the UI, and labelled episodes are never regenerated in place. |

## Residual risks

- **Memory introspection is out of scope.** The isolation proof shows no leak
  through the *observable* surface; a process with full memory access to the
  evaluator process could in principle read truth. The evaluator is assumed to
  run out of the agent's process.
- **Train mode exposes post-submit diagnostics.** Aggregate metrics and
  per-finding `matched` flags are visible after a terminal submit in train mode;
  they are excluded from the closed (eval) surface.
- **The UI is a local demo.** It binds to `127.0.0.1` and is not hardened for
  multi-user or internet deployment; do not expose it beyond a single machine.
- **No external review.** No accountant reviewed the generated data, and the CI
  workflow has not been observed from this machine.

## Reporting a problem

If you find a leak, an isolation break, or a way to game the reward, open an
issue on the project tracker and include:

1. The command or action sequence that triggers it.
2. A minimal seed and configuration, if relevant.
3. Which surface leaked (observation, info, error string, trajectory, UI route).
4. The observed result versus the expected result.

Do not include `truth.json` or `provenance.json` contents in a public report.
