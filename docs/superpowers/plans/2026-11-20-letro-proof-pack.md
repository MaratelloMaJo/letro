# LETRO Proof Pack Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add executable proof, difficulty evidence, and a judge-facing demo layer to LETRO without changing the environment contract, truth semantics, or reward formula.

**Architecture:** Six small, independently runnable modules (`redteam`, `proof`, `isolation`, `bench`, `difficulty`, `challenge`) plus one policy probe, one scripted demo, and three workbench additions. Each proof reconstructs its claim from open records or from the public environment, never from a second copy of the audit logic. The verifier remains the single contract gate.

**Tech Stack:** Python 3.11+, standard library only, `unittest`, `http.server`, JSON/JSONL/CSV, Docker `python:3.11-slim`.

**Spec:** `docs/superpowers/specs/2026-11-19-letro-proof-pack-design.md`

## Global Constraints

- Python 3.11+ and standard library only at runtime and in tests. No new dependencies.
- Offline. No network calls, paid APIs, GPU, telemetry, or external services.
- Truth never enters `AuditEnv`, observations, info, errors, or trajectories.
- Preserve the four error types, the two composite scenarios, the matcher, and
  `clip(2*F1 - 1 - 0.002*inspection_steps, -1, 1)`.
- Preserve `python -m letro.verify` as the single 100-check contract gate.
- Do not regenerate the 20 labelled episodes or change `episodes/index.json`.
- The workbench stays local, read-only, bound to `127.0.0.1` by default, and
  never serves `truth.json`.
- Every new command is deterministic for a fixed seed and exits non-zero on
  failure.
- All new tests use `unittest`; the suite must remain runnable with
  `python -m unittest discover -s tests -q`.

## Review Focus

These are the failure modes most likely to make a proof look good while proving
nothing. Each line is pinned by a test in the task that owns the code.

1. **Proof imports the audit arithmetic it is supposed to audit.** A test
   blocks `letro/proof.py` from importing the amount helpers in
   `letro.generator.audit` (`_base`, `_payment_base`, `_expected_allocation`)
   and checks that amounts are recomputed by the proof calculator. Importing
   `reference_audit` as a detector is allowed; trusting its arithmetic is not.
2. **Canary leaks through an error or a trajectory record.** A test scans every
   eval-mode observation, info, error, and trajectory record for the canary.
3. **Challenge endpoint leaks truth ids or hidden amounts.** A test asserts the
   response contains only aggregate metrics and per-finding booleans.
4. **Benchmark compares 20-episode sequential memory to the 4 GB single-episode
   limit.** A test asserts only the one-episode figure is compared to 4 GB and
   the archive is compared to 1 GB.
5. **LimitedPolicy reads all pages despite a page budget.** A test asserts the
   policy stops after the configured pages and loses findings relative to
   thorough.

---

### Task 1: Red-team reward suite and rubric map

**Files:**
- Create: `letro/redteam.py`
- Create: `tests/test_redteam.py`
- Create: `docs/JURY-MAP.md`

**Interfaces:**
- Consumes: `letro.factory.env_from_episode(episode, mode="train")`,
  `letro.generator.generate_episode(seed, config)`,
  `letro.policies.make_policy(name, episode=None, seed=0, **kwargs)`,
  `letro.reward.terminal_reward(f1, inspection_steps)`.
- Produces:
  - `ATTACKS: tuple[str, ...]` with exactly the 12 names below.
  - `BOUNDS: dict[str, float]`.
  - `@dataclass class AttackResult` with fields
    `attack: str`, `seed: int`, `episode_id: str`, `reward: float`,
    `bound: float`, `verdict: str`, `reason: str`.
  - `run_attack(name: str, seed: int = 1001, config: dict[str, Any] | None = None) -> AttackResult`.
  - `run_all(seeds: Sequence[int] | None = None) -> list[AttackResult]`.
  - `main(argv: Sequence[str] | None = None) -> int`.

Attack names and bounds:

| Name | Bound |
|---|---|
| `mark_all` | `reward <= 0.2` |
| `duplicate_spam` | `reward <= 0.2` |
| `evidence_less` | `reward <= 0.0` |
| `wrong_currency` | `reward <= 0.0` |
| `wrong_amount` | `reward <= 0.0` |
| `guessed_ids` | `reward <= 0.0` |
| `empty_on_clean` | `reward == 1.0` |
| `empty_on_error` | `reward <= 0.0` |
| `timeout` | `reward <= terminal_reward(0, steps)` |
| `oversized_payload` | `reward == -1.0` |
| `resubmit` | second reward `<=` first reward |
| `duplicate_correct` | `reward <= 0.5` and strictly less than the same single finding |

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_redteam.py
import unittest

from letro.redteam import ATTACKS, BOUNDS, run_attack, run_all


class RedteamTest(unittest.TestCase):
    def test_bounds_cover_every_attack(self):
        self.assertEqual(set(BOUNDS), set(ATTACKS))
        self.assertEqual(len(ATTACKS), 12)

    def test_mark_all_is_bounded(self):
        result = run_attack("mark_all", seed=1001)
        self.assertEqual(result.verdict, "PASS")
        self.assertTrue(result.reward <= 0.2)

    def test_empty_on_clean_scores_one(self):
        result = run_attack("empty_on_clean", seed=1001)
        self.assertEqual(result.verdict, "PASS")
        self.assertAlmostEqual(result.reward, 1.0)

    def test_evidence_less_is_bounded(self):
        result = run_attack("evidence_less", seed=1001)
        self.assertTrue(result.reward <= 0.0)

    def test_duplicate_correct_is_bounded(self):
        result = run_attack("duplicate_correct", seed=1001)
        self.assertTrue(result.reward <= 0.5)

    def test_run_all_returns_one_result_per_attack(self):
        results = run_all([1001])
        self.assertEqual(len(results), len(ATTACKS))
        self.assertTrue(all(item.verdict == "PASS" for item in results))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_redteam -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'letro.redteam'`.

- [ ] **Step 3: Implement `letro/redteam.py`**

Use a fresh episode per attack. Build payloads from the public episode and the
thorough policy, never from `truth.json`. For `mark_all`, submit one finding per
ledger row capped at 30. For `duplicate_spam`, submit the same correct finding
12 times. For `evidence_less`, remove `evidence_ids` from one correct finding.
For `wrong_currency`, replace the currency with a different valid code. For
`wrong_amount`, add 1_000_000 minor units. For `guessed_ids`, replace affected
ids with `["INV-9999"]`. For `empty_on_clean` use `{"clean": True}` and an empty
findings list. For `empty_on_error` use the default config and an empty list.
For `timeout`, call `step` with a cheap `list_records` action 100 times without
submitting. For `oversized_payload`, submit 31 findings. For `resubmit`, submit
the correct payload, then submit it again and compare the second reward. For
`duplicate_correct`, submit one correct finding twice and compare with the
same finding submitted once.

Use `env_from_episode(episode, mode="train")`, `make_policy("thorough", episode=episode)`,
and `run_episode` or direct `step` calls. The `reason` string must name the
metric that decided the verdict.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest tests.test_redteam -v`
Expected: PASS, 6 tests.

- [ ] **Step 5: Write `docs/JURY-MAP.md`**

Add the six-row table from the spec, plus a short section “What is not locally
observable” listing the official hidden seeds, the organizer’s four policies,
and the final jury score. For each, name the local substitute: `letro.jury`,
`letro.redteam`, `letro.proof`, and the published evidence files.

- [ ] **Step 6: Run the command**

Run: `python -m letro.redteam`
Expected: a table with 12 PASS rows and exit 0.

- [ ] **Step 7: Commit**

```bash
git add letro/redteam.py tests/test_redteam.py docs/JURY-MAP.md
git commit -m "feat: add adversarial reward suite and jury map"
```

---

### Task 2: Causal and evidence proof

**Files:**
- Create: `letro/proof.py`
- Create: `tests/test_proof.py`

**Interfaces:**
- Consumes: `generate_episode(seed, config)`, `reference_audit(episode)`,
  `Episode.truth`, `Episode.provenance`, `letro.money.convert_minor`,
  `letro.generator.model.rate_on`, `proportional_base`.
- Produces:
  - `CASES: tuple[str, ...] = ("duplicate_invoice", "payment_allocation_gap", "fx_rate_error", "period_cutoff", "boundary_fx_payment", "gap_cutoff_payment")`.
  - `@dataclass class ProofResult` with fields
    `case: str`, `seed: int`, `clean_issues: int`, `injected_issues: int`,
    `added_types: list[str]`, `evidence_minimal: bool`,
    `amount_recomputed: bool`, `verdict: str`.
  - `check_case(case: str, seed: int = 1001) -> ProofResult`.
  - `run_all(seeds: Sequence[int] | None = None) -> list[ProofResult]`.
  - `recompute_expected(episode: Episode, issue: dict[str, Any]) -> int`.
  - `main(argv: Sequence[str] | None = None) -> int`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_proof.py
import unittest

from letro.proof import CASES, check_case, run_all


class ProofTest(unittest.TestCase):
    def test_simple_cases_add_one_issue(self):
        for case in ("duplicate_invoice", "payment_allocation_gap",
                     "fx_rate_error", "period_cutoff"):
            result = check_case(case, seed=1001)
            self.assertEqual(result.verdict, "PASS", case)
            self.assertEqual(result.clean_issues, 0, case)
            self.assertEqual(result.injected_issues, 1, case)
            self.assertEqual(result.added_types, [case], case)
            self.assertTrue(result.evidence_minimal, case)
            self.assertTrue(result.amount_recomputed, case)

    def test_composites_add_two_issues(self):
        for case in ("boundary_fx_payment", "gap_cutoff_payment"):
            result = check_case(case, seed=1001)
            self.assertEqual(result.verdict, "PASS", case)
            self.assertEqual(result.injected_issues, 2, case)
            self.assertEqual(len(result.added_types), 2, case)

    def test_run_all_covers_every_case(self):
        results = run_all([1001])
        self.assertEqual({item.case for item in results}, set(CASES))
        self.assertTrue(all(item.verdict == "PASS" for item in results))

    def test_proof_does_not_import_audit_arithmetic(self):
        import pathlib
        source = pathlib.Path("letro/proof.py").read_text(encoding="utf-8")
        for helper in ("_base", "_payment_base", "_expected_allocation"):
            self.assertNotIn(f"import {helper}", source)
            self.assertNotIn(f"from letro.generator.audit import {helper}", source)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_proof -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'letro.proof'`.

- [ ] **Step 3: Implement `letro/proof.py`**

For each simple case, generate a clean episode and an injected episode with
`{"sizes": {"issues": 1}, "errors": {case: 1}}`, except `fx_rate_error` and
`period_cutoff` which use the same shape. Compare `reference_audit` signatures.
Use `provenance.json` steps to confirm the injected document id or row ids.
Recompute amounts with a local calculator that reads invoices, payments, fx,
and policy; do not import `letro.generator.audit` arithmetic.

For `boundary_fx_payment`, use
`{"errors": {"composite": 1}, "sizes": {"issues": 2}}` and assert one
`fx_rate_error` plus one `period_cutoff`. For `gap_cutoff_payment`, force the
second composite by generating with `{"errors": {"composite": 2}, "sizes":
{"issues": 4}}` and selecting the `gap_cutoff_payment` provenance step. If the
generator produces a different composite order for a seed, try seeds 1001–1010
until both composite scopes are observed; fail with a clear message if not.

Evidence minimality: for each issue, take each allowed set; assert it is
sufficient as a set, and removing any one id makes every allowed set fail. Only
inclusion-minimal allowed sets are tested; supersets are allowed to exist.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest tests.test_proof -v`
Expected: PASS, 4 tests.

- [ ] **Step 5: Run the command**

Run: `python -m letro.proof`
Expected: one PASS row per case, exit 0.

- [ ] **Step 6: Commit**

```bash
git add letro/proof.py tests/test_proof.py
git commit -m "feat: prove causal truth and evidence minimality"
```

---

### Task 3: Isolation sentinel and lazy environment boundary

**Files:**
- Create: `letro/lazy.py`
- Create: `letro/isolation.py`
- Create: `tests/test_isolation.py`
- Modify: `letro/env.py`
- Modify: `letro/__init__.py`
- Test: `tests/test_jury_hardening.py` (existing imports must keep passing)

**Interfaces:**
- Consumes: `AuditEnv`, `factory._build(seed, config, mode)`,
  `env_from_episode`, `run_episode`, `TrajectoryRecorder`.
- Produces:
  - `letro/lazy.py`: `class LetroEnv(AuditEnv)` with
    `__init__(self, mode: str = "train", seed: int = 0, config: dict[str, Any] | None = None)`.
  - `letro/env.py`: `__getattr__(name: str)` returns `LetroEnv` for the name
    `"LetroEnv"` by importing `letro.lazy`; `__all__` keeps `"LetroEnv"`.
  - `letro/isolation.py`: `CANARY: str`, `scan_for_canary(value: Any, canary: str = CANARY) -> bool`,
    `check_canary(seed: int = 1001) -> dict[str, Any]`,
    `check_static_boundary() -> list[str]`, `main(argv: Sequence[str] | None = None) -> int`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_isolation.py
import unittest

from letro.env import LetroEnv
from letro.isolation import CANARY, check_canary, check_static_boundary, scan_for_canary


class IsolationTest(unittest.TestCase):
    def test_canary_is_not_observable_in_eval_mode(self):
        report = check_canary(seed=1001)
        self.assertEqual(report["verdict"], "PASS")
        self.assertFalse(report["found"])

    def test_canary_scanner_detects_nested_value(self):
        self.assertTrue(scan_for_canary({"a": [{"b": CANARY}]}))
        self.assertFalse(scan_for_canary({"a": [{"b": "clean"}]}))

    def test_env_and_tools_do_not_import_truth_or_audit(self):
        violations = check_static_boundary()
        self.assertEqual(violations, [])

    def test_letro_env_is_still_importable_from_env(self):
        env = LetroEnv(mode="eval")
        observation, info = env.reset(seed=1001)
        self.assertIn("task", observation)
        self.assertNotIn("truth", observation)
        self.assertNotIn("truth", info)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_isolation -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'letro.isolation'`.

- [ ] **Step 3: Move `LetroEnv` to `letro/lazy.py`**

Copy the class from `letro/env.py`. Keep its behavior and `_build_episode`.
Remove the class from `env.py` and add:

```python
def __getattr__(name: str):
    if name == "LetroEnv":
        from .lazy import LetroEnv
        return LetroEnv
    raise AttributeError(name)
```

Keep `"LetroEnv"` in `__all__`. Update `letro/__init__.py` to import
`LetroEnv` from `letro.lazy`.

- [ ] **Step 4: Implement `letro/isolation.py`**

`check_canary` generates an episode, sets a canary in a copied truth and
provenance object, builds `env_from_episode(episode, mode="eval")`, runs a
maximal policy that pages every table and exercises `get_record`,
`get_document`, `calculator`, invalid action, and submit. Record every
observation, info, error string, and trajectory record. Scan all of them for
`CANARY`. Also assert the train-mode reward is visible only on the terminal
submit, never on an intermediate observation.

`check_static_boundary` parses `letro/env.py` and `letro/tools.py` with `ast`.
Fail if either imports `evaluator`, `generator.audit`, `truth`, or `factory`
(the lazy boundary must keep `env.py` free of factory imports).

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m unittest tests.test_isolation -v`
Expected: PASS, 4 tests.

- [ ] **Step 6: Run the command**

Run: `python -m letro.isolation`
Expected: `canary: PASS`, `static boundary: PASS`, exit 0.

- [ ] **Step 7: Commit**

```bash
git add letro/lazy.py letro/isolation.py tests/test_isolation.py letro/env.py letro/__init__.py
git commit -m "feat: isolate the lazy environment boundary and add a canary sentinel"
```

---

### Task 4: Compute benchmark, datasheet, and security note

**Files:**
- Create: `letro/bench.py`
- Create: `tests/test_bench.py`
- Create: `docs/DATASHEET.md`
- Create: `docs/SECURITY.md`

**Interfaces:**
- Consumes: `generate_episode`, `env_from_episode`, `run_episode`,
  `ThoroughPolicy`, `letro.verify.main`.
- Produces:
  - `@dataclass class BenchResult` with fields
    `operation: str`, `p50_ms: float`, `p95_ms: float`, `max_ms: float`,
    `budget_ms: float`, `verdict: str`.
  - `measure(operation: str, function: Callable[[], Any], repeats: int = 5, budget_ms: float = 60_000.0) -> BenchResult`.
  - `run_bench(seeds: int = 5) -> list[BenchResult]`.
  - `archive_size() -> int`.
  - `main(argv: Sequence[str] | None = None) -> int`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_bench.py
import unittest

from letro.bench import BenchResult, archive_size, measure, run_bench


class BenchTest(unittest.TestCase):
    def test_measure_returns_percentiles(self):
        result = measure("noop", lambda: None, repeats=3)
        self.assertIsInstance(result, BenchResult)
        self.assertEqual(result.verdict, "PASS")
        self.assertTrue(0.0 <= result.p50_ms <= result.p95_ms <= result.max_ms)

    def test_run_bench_covers_generation_reset_and_steps(self):
        operations = {item.operation for item in run_bench(seeds=1)}
        self.assertIn("generation", operations)
        self.assertIn("reset", operations)
        self.assertIn("100_steps", operations)

    def test_archive_size_is_positive_and_under_one_gb(self):
        size = archive_size()
        self.assertGreater(size, 0)
        self.assertLess(size, 1_000_000_000)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_bench -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'letro.bench'`.

- [ ] **Step 3: Implement `letro/bench.py`**

Measure generation, reset, and a 100-step thorough run with `time.perf_counter`.
Use `tracemalloc` for peak memory. Report one-episode peak memory against 4 GB;
report the 20-episode sequential figure separately and never compare it to 4 GB.
Measure the clean archive with `git archive --format=zip HEAD` written to a
temporary file and compare its size to 1 GB. Run generation twice under two
different `PYTHONHASHSEED` values via `subprocess` and compare the episode
digest. Print a table; exit 1 on a time, memory, or archive breach.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest tests.test_bench -v`
Expected: PASS, 3 tests.

- [ ] **Step 5: Write the datasheet and security note**

`docs/DATASHEET.md`: motivation, composition, generation process, intended use,
out-of-scope use, biases and limitations, maintenance. State that all companies
are fictional, no real financial data is used, and no professional audit
opinion is produced.

`docs/SECURITY.md`: assets (truth, provenance, seed, evaluator), trust
boundaries (agent, env, evaluator, UI), threats (truth leak, path traversal,
action injection, calculator escape, DoS, reward gaming), mitigations, residual
risks, and a reporting path.

- [ ] **Step 6: Run the command**

Run: `python -m letro.bench`
Expected: all rows PASS, archive under 1 GB, exit 0.

- [ ] **Step 7: Commit**

```bash
git add letro/bench.py tests/test_bench.py docs/DATASHEET.md docs/SECURITY.md
git commit -m "feat: measure the compute envelope and document data and security"
```

---

### Task 5: Difficulty science and limited-information probe

**Files:**
- Create: `letro/difficulty.py`
- Create: `letro/policies/limited.py`
- Create: `tests/test_difficulty.py`
- Modify: `letro/policies/thorough.py`
- Modify: `letro/policies/__init__.py`
- Create: `docs/evidence/difficulty.json` (generated, committed)

**Interfaces:**
- Consumes: `load_episode`, `env_from_episode`, `run_episode`,
  `make_policy`, `reference_audit`, `episodes/index.json`.
- Produces:
  - `@dataclass class TypeMetric` with fields
    `policy: str`, `error_type: str`, `tp: int`, `fp: int`, `fn: int`,
    `precision: float`, `recall: float`, `f1: float`, `example: str`.
  - `collect(episodes: list[Episode] | None = None) -> list[TypeMetric]`.
  - `write_evidence(metrics: list[TypeMetric], path: Path) -> Path`.
  - `main(argv: Sequence[str] | None = None) -> int`.
  - `class LimitedPolicy(ThoroughPolicy)` with `name = "limited"` and
    `__init__(self, max_pages: int = 1)`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_difficulty.py
import unittest

from letro.difficulty import collect
from letro.policies.limited import LimitedPolicy


class DifficultyTest(unittest.TestCase):
    def test_collect_reports_every_policy_and_type(self):
        metrics = collect()
        policies = {item.policy for item in metrics}
        types = {item.error_type for item in metrics}
        self.assertIn("reconciliation", policies)
        self.assertIn("thorough", policies)
        self.assertIn("payment_allocation_gap", types)
        self.assertTrue(all(0.0 <= item.f1 <= 1.0 for item in metrics))

    def test_limited_policy_stops_after_page_budget(self):
        policy = LimitedPolicy(max_pages=1)
        self.assertEqual(policy.name, "limited")
        self.assertEqual(policy.max_pages, 1)

    def test_thorough_policy_still_reads_all_pages(self):
        policy = __import__("letro.policies", fromlist=["ThoroughPolicy"]).ThoroughPolicy()
        self.assertIsNone(policy.max_pages)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_difficulty -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'letro.difficulty'`.

- [ ] **Step 3: Add the page budget to `ThoroughPolicy`**

Add `max_pages: int | None = None` to `ThoroughPolicy.__init__`, store it as
`self.max_pages`, and initialize `self._pages_in_table = 0` in `reset`. On a
successful list result, increment `_pages_in_table`. Advance the table when
`max_pages is not None and _pages_in_table >= max_pages`; otherwise advance only
when `next_cursor is None`. Reset `_pages_in_table = 0` in `_advance_table`.
`ThoroughPolicy()` must keep `max_pages is None`.

- [ ] **Step 4: Implement `LimitedPolicy` and `letro/difficulty.py`**

`LimitedPolicy` subclasses `ThoroughPolicy`, sets `name = "limited"`, and calls
`super().__init__(max_pages=max_pages)`. Add it to `letro/policies/__init__.py`
exports but not to `POLICY_NAMES`.

`difficulty.collect()` loads the 10 dev episodes. For each policy in
`("random_explorer", "reconciliation", "thorough", "mark_all")`, run it and
compare findings to truth per error type using the matcher. Add an `oracle` row
from the existing published evidence, labelled `evaluator-side`. For each
type/policy, record TP/FP/FN and a short failure example: the first missed
issue id or false-positive type. Run `LimitedPolicy(1)` and `LimitedPolicy(2)`
as extra rows labelled `limited_1` and `limited_2`. Count split payments,
refunds, recurring identical amounts, and legitimately open invoices across
the five clean dev episodes; assert each aggregate count is at least 1 and the
clean audit is zero.

`write_evidence` writes deterministic JSON sorted by policy and type to
`docs/evidence/difficulty.json`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m unittest tests.test_difficulty -v`
Expected: PASS, 3 tests.

- [ ] **Step 6: Generate evidence and run the command**

Run: `python -m letro.difficulty`
Expected: per-type table, distractor counts, `docs/evidence/difficulty.json`,
exit 0.

- [ ] **Step 7: Commit**

```bash
git add letro/difficulty.py letro/policies/limited.py tests/test_difficulty.py letro/policies/thorough.py letro/policies/__init__.py docs/evidence/difficulty.json
git commit -m "feat: measure per-type difficulty and information budget"
```

---

### Task 6: Ninety-second scripted demo

**Files:**
- Modify: `scripts/demo.py`
- Create: `tests/test_demo.py`

**Interfaces:**
- Consumes: `load_episode`, `env_from_episode`, `run_episode`,
  `ThoroughPolicy`, `ReconciliationPolicy`, `permute_episode`,
  `letro.redteam.run_all`.
- Produces: `story() -> list[str]` returning the printed section titles in
  order, and `main(argv: Sequence[str] | None = None) -> int`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_demo.py
import unittest

from scripts.demo import story


class DemoTest(unittest.TestCase):
    def test_story_has_five_sections_in_order(self):
        self.assertEqual(
            story(),
            [
                "clean books",
                "naive reconciliation",
                "thorough audit",
                "permutation",
                "red team",
            ],
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_demo -v`
Expected: FAIL with `ImportError` or `AttributeError`.

- [ ] **Step 3: Rewrite `scripts/demo.py`**

Load a clean dev episode and print that the reference audit returns zero
issues. Run `ReconciliationPolicy` and print F1, reward, steps, and the first
three false accusations. Run `ThoroughPolicy` and print F1, reward, steps, and
one finding with its evidence ids and the resolved records. Permute the episode
with `permute_episode(episode, "demo")`, run thorough, and print that F1 and
reward match the original. Print the red-team table from `run_all([1001])`.
Keep every section deterministic and under roughly 18 seconds of output.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_demo -v`
Expected: PASS.

- [ ] **Step 5: Run the demo**

Run: `python scripts/demo.py`
Expected: five sections, clean zero issues, naive F1 below thorough, matching
permutation metrics, all red-team rows PASS, exit 0.

- [ ] **Step 6: Commit**

```bash
git add scripts/demo.py tests/test_demo.py
git commit -m "feat: add a ninety-second scripted proof demo"
```

---

### Task 7: Challenge CLI and workbench proof surfaces

**Files:**
- Create: `letro/challenge.py`
- Create: `tests/test_challenge.py`
- Modify: `letro/ui/server.py`
- Modify: `letro/ui/static/index.html`
- Modify: `letro/ui/static/app.js`
- Modify: `letro/ui/static/style.css`
- Modify: `tests/test_ui.py`

**Interfaces:**
- Consumes: `load_episode`, `Evaluator`, `validate_findings_payload`,
  `episodes/index.json`, existing `Handler` routes.
- Produces:
  - `score_submission(episode: Episode, payload: dict[str, Any], inspection_steps: int = 0) -> dict[str, Any]`
    returning `tp`, `fp`, `fn`, `precision`, `recall`, `f1`, `reward`,
    `findings: list[{"index": int, "matched": bool}]`; no issue ids, no
    expected amounts, no truth.
  - `main(argv: Sequence[str] | None = None) -> int`.
  - `GET /api/episodes/<id>/evidence?ids=ID1,ID2` returning resolved open
    records only.
  - `POST /api/challenge` accepting
    `{"episode_id": str, "findings": {...}}` and returning the sanitized
    `score_submission` result.
  - `GET /api/leaderboard?episode_id=<id>` returning the four public policy
    rows plus an `oracle` row read from `docs/evidence/policy-metrics.json`,
    labelled `evaluator-side`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_challenge.py
import unittest

from letro.challenge import score_submission
from letro.generator import load_episode, reference_findings


class ChallengeTest(unittest.TestCase):
    def test_oracle_submission_scores_perfectly(self):
        episode = load_episode("episodes/dev/ep-0dc0a85bf7")
        result = score_submission(episode, reference_findings(episode))
        self.assertEqual(result["f1"], 1.0)
        self.assertEqual(result["tp"], len(episode.truth["issues"]))
        self.assertEqual(result["fp"], 0)
        self.assertEqual(result["fn"], 0)
        self.assertNotIn("issue_id", result)
        self.assertTrue(all(set(item) == {"index", "matched"} for item in result["findings"]))

    def test_empty_submission_is_valid_and_has_no_truth_ids(self):
        episode = load_episode("episodes/dev/ep-0dc0a85bf7")
        result = score_submission(episode, {"episode_id": episode.manifest["episode_id"], "findings": []})
        self.assertEqual(result["tp"], 0)
        self.assertNotIn("missed_issue_ids", result)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_challenge -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'letro.challenge'`.

- [ ] **Step 3: Implement `letro/challenge.py`**

Load the labelled episode by id from the dev index only. Validate the payload.
Call `Evaluator.score(payload, inspection_steps, expose=True)`. Build a
sanitized response: aggregate TP/FP/FN/P/R/F1/reward, and a per-finding
`matched` boolean derived from `last_result.matched`. Do not include
`issue_id`, `missed_issue_ids`, `allowed_evidence_sets`, or expected amounts.
`main` parses `--episode` and `--findings`, prints the sanitized result as JSON,
and exits 1 on invalid input.

- [ ] **Step 4: Add the workbench routes**

In `letro/ui/server.py`, add the three routes. Keep the existing body cap,
security headers, episode-id validation, and path rules. `/evidence` resolves
ids through `OpenStore.get_record` or `get_document`; unknown ids are omitted
with a `missing` list. `/challenge` calls `score_submission`. `/leaderboard`
runs the four public policies with `env_from_episode(..., mode="eval")` and
`run_episode`; the oracle row is read from the published evidence file and
labelled `evaluator-side`. Never read `truth.json` in the UI process.

- [ ] **Step 5: Add the UI panels**

Add an evidence-chain panel that renders the resolved records for the selected
finding, a challenge tab with a textarea and aggregate result, and a compact
leaderboard table. Keep the existing visual system; no new dependencies. The
challenge result must not render issue ids or hidden amounts.

- [ ] **Step 6: Write the UI tests**

Extend `tests/test_ui.py` with:
- `test_evidence_returns_open_records_only`
- `test_evidence_omits_missing_ids`
- `test_challenge_returns_aggregates_and_booleans`
- `test_challenge_never_returns_issue_ids`
- `test_leaderboard_has_four_public_rows_and_labelled_oracle`
- `test_challenge_rejects_unknown_episode`
- `test_evidence_rejects_path_traversal`

Run: `python -m unittest tests.test_ui -v`
Expected: PASS, existing 11 tests plus 7 new tests.

- [ ] **Step 7: Run the commands**

Run: `python -m letro.challenge --episode ep-0dc0a85bf7 --findings <oracle-json>`
Expected: F1 1.0 and no truth ids. Create the oracle JSON with a one-line
Python command using `reference_findings` in a temp file; do not commit it.

Run: `python -m letro.ui --no-browser` and open the workbench.
Expected: evidence chain, challenge tab, and leaderboard render; no truth.

- [ ] **Step 8: Commit**

```bash
git add letro/challenge.py tests/test_challenge.py letro/ui/server.py letro/ui/static/index.html letro/ui/static/app.js letro/ui/static/style.css tests/test_ui.py
git commit -m "feat: add challenge scoring and evidence-chain workbench panels"
```

---

### Task 8: Integration, documentation, and final acceptance

**Files:**
- Modify: `README.md`
- Modify: `DESIGN.md`
- Modify: `docs/FAILURE-ANALYSIS.md`
- Modify: `docs/READINESS.md`
- Modify: `docs/JURY-MAP.md`
- Modify: `pyproject.toml`
- Test: full suite and all commands

**Interfaces:**
- Consumes: all previous tasks.
- Produces: consistent docs, console scripts, and a clean commit.

- [ ] **Step 1: Add console scripts**

Add `letro-redteam`, `letro-proof`, `letro-isolation`, `letro-bench`,
`letro-difficulty`, and `letro-challenge` to `[project.scripts]` in
`pyproject.toml`, each pointing at the matching `main`.

- [ ] **Step 2: Update the documentation**

README: add a “Proof pack” section with the six commands and expected results,
link `docs/JURY-MAP.md`, and add the new test count. DESIGN: add the proof-pack
architecture and the isolation boundary. FAILURE-ANALYSIS: add measured
failure modes from `difficulty.json`, the red-team results, and the honest
limits (no accountant review, CI not observed, local UI). READINESS: update
the P1–P4 table and score evidence; keep the UI as demo-only and do not claim
production readiness. JURY-MAP: fill in the actual observed numbers.

- [ ] **Step 3: Run the full test suite**

Run: `python -m unittest discover -s tests -q`
Expected: PASS, at least 110 tests.

- [ ] **Step 4: Run the contract verifier**

Run: `python -m letro.verify`
Expected: Contract 24/24, Data 21/21, Reward 20/20, Reproducibility 20/20,
Engineering 10/10, TOTAL 100.00, `RESULT: PASS`.

- [ ] **Step 5: Run the proof commands**

Run each and expect exit 0:

```bash
python -m letro.jury
python -m letro.fuzz --seeds 100
python -m letro.redteam
python -m letro.proof
python -m letro.isolation
python -m letro.bench
python -m letro.difficulty
```

- [ ] **Step 6: Run the container and clean archive checks**

```bash
docker build -t letro:1.0.0 .
docker run --rm letro:1.0.0
```

Expected: verifier 100.00 PASS inside the container.

Create a clean archive in a temporary directory and run
`python -m letro.verify` there. Expected: 100.00 PASS.

- [ ] **Step 7: Commit**

```bash
git add README.md DESIGN.md docs/FAILURE-ANALYSIS.md docs/READINESS.md docs/JURY-MAP.md pyproject.toml
git commit -m "docs: publish the proof pack and final acceptance evidence"
```

---

## Self-review notes

- Spec coverage: A1 Task 1; A2 Task 1; A3 Task 2; A4 Task 3; A5 Task 4;
  A6 Task 4; B1 Task 5; B2 Task 5; B3 Task 5; C1 Task 6; C2 Task 7;
  C3 Task 7; acceptance Task 8.
- Type consistency: `AttackResult`, `ProofResult`, `BenchResult`, and
  `TypeMetric` are defined once and referenced by their exact field names.
- Review Focus tests: proof import boundary in Task 2; canary in Task 3;
  challenge leak in Task 7; benchmark memory semantics in Task 4; page budget
  in Task 5.
- Proportion: tasks specify signatures, bounds, and assertions; they do not
  transcribe full implementations.
