# LETRO - jury hardening and difficulty ladder

Date: 2026-11-19
Status: approved (A + B + risk remediation + local UI)
Competition: REC Genesis Hackathon, FinTech, online selection
Deadline: 2026-11-22 23:59 Asia/Almaty

## Why this increment

The shipped tree passes our own verifier at 100.00, but the jury runs its own
harness. Two integration risks remain:

1. `AuditEnv.__init__` requires `open_data`. A harness that does
   `env = AuditEnv()` and then `env.reset(seed, config)` crashes on the first
   contract check. That is up to 25 points.
2. The README has no Python API section. A judge cannot see how to create the
   environment, what an observation contains, or what an action looks like.

Separately, the hidden episodes use seeds and configuration combinations we have
not exercised. A broad generator fuzz is the cheapest protection for the data and
truth criterion.

The brief is explicit that training weights is optional, earns no points by
itself, and cannot be claimed without a held-out comparison. The 10 engineering
points are five binary criteria, all already at 2/2. Training therefore adds no
rubric points; this increment does not include it.

## Chosen approach

A. Jury-proof integration layer.
B. Hard preset and generator fuzz.

Rejected:

- C. Remediation loop. It changes the fixed reward and the action contract, adds
  two days of risk, and the brief scores only the declared environment.
- D. Training harness. Zero rubric points, tiny data, and it would contradict the
  measured story that a naive rule fails while a reference succeeds.

## A. Integration layer

### Zero-argument environment

- `AuditEnv.__init__(open_data: dict | None = None, finalize=None, provider=None,
  expose_reward=True, seed=0)`.
- When `open_data` is `None`, `_store` is `None` and `_episode_id` is empty.
- `reset(seed=None, config=None)` regenerates when `_store` is `None`, even if
  both arguments are `None`; the default seed is `0`.
- `step(action)` before any reset calls `reset()` first.
- `LetroEnv(AuditEnv)` adds a lazy provider that calls
  `factory._build(seed, config, mode)` and returns `(open_data, finalize)`.
  The environment still never holds truth; the evaluator lives in the closure.
- Existing `make_env` and `env_from_episode` keep their behaviour.

### README API section

A copy-paste example that creates the environment, resets it, pages the ledger,
reads one invoice, uses the calculator and submits. It also documents the
observation keys, the five action shapes, the reward formula, and the difference
between train and eval mode.

### Jury runner

`python -m letro.jury` emulates the published protocol:

- 20 hidden-style episodes: 5 clean, 5 with two composites, 10 mixed.
- Four policies: `random_explorer`, `reconciliation`, `mark_all`, `oracle`.
- 20 paired permutations: oracle F1 and reward preserved; reconciliation metrics
  equal.
- 5 exact replays: same record digest, same steps, same reward.
- A leak scan over a sample of observations.
- Prints a table with mean F1, clean F1, erroneous F1, reward, steps, elapsed
  time and peak memory, writes `docs/evidence/jury-report.json` and `.md`, and
  exits non-zero on any failure.

### Optional Gymnasium

`letro/gym.py` exposes `register()` which soft-imports `gymnasium` and registers
`Letro-v0`. No dependency is added; if the package is absent the function
returns `False`. This path is optional and is not part of the required checks.

## B. Difficulty ladder and fuzz

### Presets

`letro/presets.py`:

- `default_config()`
- `clean_config()`
- `composite_config()`
- `hard_config()`: USD, 45 days, 90 invoices, 80 payments, 900 ledger rows,
  12 issues (2 of each simple type plus 2 composites).
- `hard_composite_config()`: 3 composites plus 6 simple issues, 12 total.
- `jury_configs()`: the 20 configurations used by the jury runner.

Every preset must pass `validate_config` and generate at least one episode.

### Fuzz

`python -m letro.fuzz --seeds 100`:

- Runs five presets over the seed range.
- Checks: generation does not raise; truth count equals the configured count;
  total debits equal credits; every journal group balances; the reference audit
  reproduces truth; every evidence set resolves to real records; manifest counts
  match the files; clean episodes have zero issues.
- Writes `docs/evidence/fuzz-report.json` with the seed matrix and any failure.
- `--quick` runs 20 seeds; the verifier runs a 5-seed smoke check.

### Difficulty evidence

The failure analysis gains a table comparing random, naive, thorough and oracle
on the default and hard presets, plus the fuzz coverage number.

## Interfaces

- `letro.env.LetroEnv`, `letro.env.AuditEnv`
- `letro.presets.*`
- `letro.jury.main`
- `letro.fuzz.main`
- CLI exit code 0 on success, non-zero on any failed check.

## Acceptance

1. `python -m unittest discover -s tests -q` passes with at least 90 tests.
2. `python -m letro.verify` prints 100.00 and `RESULT: PASS`.
3. `python -m letro.jury` exits 0, prints the table and covers 20 episodes and
   20 permutations.
4. `python -m letro.fuzz --seeds 100` exits 0 over at least 500 episodes with
   zero failures.
5. `LetroEnv().reset(seed=..., config=...)` works, and `step` before reset
   works.
6. Docker and a clean archive still pass 100.00.
7. README documents the API, the jury runner and the fuzz command.

## Risks

- Zero-argument changes can break existing paths. Mitigation: default arguments,
  unchanged `make_env`, and new tests for both construction styles.
- The jury runner can be slow. Mitigation: measure it; target under 120 seconds
  on 2 CPU.
- Fuzz may expose real generator failures. That is the point; fix the generator
  or narrow the preset, never weaken the check.
- Optional Gymnasium code cannot be verified here. Mitigation: keep it out of the
  required path and mark it optional in the README.

## Out of scope

- Training weights or a learned reranker.
- A UI or a hosted service.
- New error types, new reward terms, or a changed action contract.
- Third-party runtime dependencies.
