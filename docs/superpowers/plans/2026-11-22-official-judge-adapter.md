# Official Judge Adapter and Checklist Compliance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make LETRO callable through the mandatory `judge_adapter.py` contract and close the highest-value gaps against the official Genesis FinTech checklist.

**Architecture:** Add a thin root-level adapter that translates the jury's canonical observation/action names into LETRO's internal environment. Add a strict scoring path to the existing matcher/evaluator without changing default behavior. Add deterministic generator switches for the two missing Block 2 scenarios. Keep truth and provenance inside the evaluator process.

**Tech Stack:** Python 3.11+ standard library, existing `letro` package, `unittest`, no new runtime dependencies.

**Spec:** `D:\downloads\fintech-checks.txt` (official checklist, published 2026-11-20) and the audit findings in `docs/OFFICIAL-CHECKLIST-AUDIT.md` (to be created in Task 7).

## Global Constraints

- `judge_adapter.py` must be importable from the repository root and expose exactly:
  - `generate_episode(seed: int, config: dict, output_dir: str) -> None`
  - `make_env()` returning an object with `reset(seed, config)` and `step(action)`
  - `score_episode(episode_dir: str, findings: dict, inspection_steps: int) -> dict`
- Closed reset config is `{"mode": "closed", "episode_dir": "<dir>", "team_config": {...}}`; it must load exactly that directory and never regenerate or renumber records.
- Canonical action envelope is `{"name": "<action>", "args": {...}}`; names are `list_records`, `get_record`, `get_document`, `calculator`, `submit`.
- First observation keys: `task`, `manifest`, `policy`, `remaining_steps`. Later observation keys: `result`, `error`, `remaining_steps`.
- `list_records` returns `{"records": [...], "next_cursor": null | string}`.
- `calculator` returns a decimal string. `submit` returns `{"accepted": true}` or a bounded structure error, never correctness.
- Closed-mode reward returned to the policy is `0`, including termination. True reward is computed only by `score_episode` / evaluator side.
- `score_episode` valid result: `{"tp", "fp", "fn", "precision", "recall", "f1", "return"}`. Invalid: `return == -1` and the other six values are `null`.
- Official strict matching: exact IDs, exact currency, evidence IDs must exist in open data, unknown string type is an unmatched finding (FP), max-cardinality bipartite matching, default amount tolerance `0` unless policy says otherwise.
- Official numeric tolerance is `1e-9` absolute; do not round metrics or reward to six decimals on the official path.
- All 134 existing tests must keep passing. Default LETRO behavior stays unchanged unless the official adapter explicitly requests strict mode.
- No secrets, no new external services, no network in tests.

## Review Focus

- A 60-second wall-clock limit starts at `reset` and includes policy thinking time; a slow policy must end with `truncated=True` and empty findings, not a crash or a late submit.
- `list_records` cursors cross the adapter boundary as strings and must not skip, duplicate, or reorder records.
- Strict currency comparison must not uppercase or trim; strict evidence must reject IDs that are not present in open data even if the finding also contains the minimal allowed set.
- A structurally valid finding with an unknown string `type` is an FP, not a whole-submit structural error.
- Closed `reset` must be repeatable on the same `episode_dir` and must not keep state from the previous episode.
- Generator scenario switches must change only the declared scenario; the default seed/config output must remain reproducible.

---

## Milestone M0: Branch, plan, continuation prompt

**Files:**
- Create: `docs/superpowers/plans/2026-11-22-official-judge-adapter.md`
- Create: `docs/CONTINUATION_PROMPT.md`

- [x] **Step 1: Create branch `fix/official-judge-adapter` from `master`**
- [x] **Step 2: Write this plan**
- [ ] **Step 3: Write `docs/CONTINUATION_PROMPT.md`** with repository path, branch, plan path, checklist path, milestone list, current status, commands, and the official scoring table.
- [ ] **Step 4: Commit M0**

```bash
git add docs/superpowers/plans/2026-11-22-official-judge-adapter.md docs/CONTINUATION_PROMPT.md
git commit -m "docs: add official judge adapter plan and continuation prompt"
```

---

## Milestone M1: Adapter, closed mode, canonical interface

**Files:**
- Create: `judge_adapter.py`
- Create: `tests/test_judge_adapter.py`
- Modify: `letro/evaluator.py` (strict constructor flag; see Task 3 for strict internals)
- Modify: `letro/factory.py` (pass strict mode through `env_from_episode`)

**Interfaces:**
- Consumes: `letro.generator.generate_episode(seed, config)`, `letro.generator.write_episode(episode, directory, include_closed=True)`, `letro.generator.load_episode(directory, load_closed=True)`, `letro.factory.env_from_episode(episode, mode)`, `letro.env.AuditEnv`, `letro.env.TASK`.
- Produces:
  - `judge_adapter.generate_episode(seed: int, config: dict, output_dir: str) -> None`
  - `judge_adapter.make_env() -> JudgeEnv`
  - `judge_adapter.score_episode(episode_dir: str, findings: dict, inspection_steps: int) -> dict`
  - `JudgeEnv.reset(seed: int | None = None, config: dict | None = None) -> tuple[dict, dict]`
  - `JudgeEnv.step(action: dict) -> tuple[dict, float, bool, bool, dict]`
  - `judge_adapter.available_evidence_ids(open_data: dict) -> set[str]`

### Task 1: `generate_episode` wrapper and file layout

- [ ] **Step 1: Write the failing test**

```python
def test_generate_episode_writes_open_and_closed_files(tmp_path):
    judge_adapter.generate_episode(123, {"errors": {"duplicate_invoice": 1}}, str(tmp_path))
    for name in ("manifest.json", "policy.json", "ledger.csv",
                 "invoices.jsonl", "payments.jsonl", "fx.csv",
                 "truth.json", "provenance.json"):
        assert (tmp_path / name).exists(), name
```

- [ ] **Step 2: Run it and verify it fails**

Run: `python -m unittest tests.test_judge_adapter -v`
Expected: `ImportError` / `AttributeError` for `judge_adapter`.

- [ ] **Step 3: Implement `generate_episode`**

Call `letro.generator.generate_episode(seed, team_config)` where `team_config` is `config.get("team_config", config)` if it is a dict, then `write_episode(episode, output_dir, include_closed=True)`. Return `None`.

- [ ] **Step 4: Run the test and verify it passes**

Run: `python -m unittest tests.test_judge_adapter -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add judge_adapter.py tests/test_judge_adapter.py
git commit -m "feat: add judge adapter episode generator"
```

### Task 2: Closed/train reset and canonical observation

- [ ] **Step 1: Write the failing test**

```python
def test_closed_reset_loads_exact_episode_and_returns_first_observation(tmp_path):
    judge_adapter.generate_episode(7, {"errors": {"duplicate_invoice": 1}}, str(tmp_path))
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    env = judge_adapter.make_env()
    observation, info = env.reset(7, {"mode": "closed", "episode_dir": str(tmp_path), "team_config": {}})
    assert set(observation) == {"task", "manifest", "policy", "remaining_steps"}
    assert observation["manifest"]["episode_id"] == manifest["episode_id"]
    assert observation["remaining_steps"] == 100
    assert "truth" not in json.dumps(observation).lower()
```

- [ ] **Step 2: Run it and verify it fails**

Expected: `judge_adapter.make_env` missing or returns wrong shape.

- [ ] **Step 3: Implement `JudgeEnv.reset`**

- `mode = (config or {}).get("mode", "train")`.
- Closed: `episode = load_episode(config["episode_dir"], load_closed=True)`; `self._env, self._evaluator = env_from_episode(episode, mode="eval")`; `self._env.reset()`.
- Train: `team_config = config.get("team_config", config)`; `episode = generate_episode(seed or 0, team_config)`; `self._env, self._evaluator = env_from_episode(episode, mode="train")`; `self._env.reset()`.
- Store `self._episode`, `self._closed`, `self._deadline = time.monotonic() + 60.0`, `self._first = True`.
- Return canonical first observation from `self._env._store.manifest`, `self._env._store.policy`, `TASK`, and `MAX_STEPS - self._env._steps`.

- [ ] **Step 4: Run the test and verify it passes**

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add judge_adapter.py tests/test_judge_adapter.py letro/factory.py
git commit -m "feat: support closed episode reset in judge adapter"
```

### Task 3: Canonical action translation and step result

- [ ] **Step 1: Write the failing tests**

```python
def test_list_records_returns_canonical_page(tmp_path):
    judge_adapter.generate_episode(11, {}, str(tmp_path))
    env = judge_adapter.make_env()
    env.reset(11, {"mode": "closed", "episode_dir": str(tmp_path)})
    observation, reward, terminated, truncated, info = env.step(
        {"name": "list_records", "args": {"table": "ledger", "limit": 5}}
    )
    result = observation["result"]
    assert len(result["records"]) <= 5
    assert result["next_cursor"] is None or isinstance(result["next_cursor"], str)
    assert reward == 0.0 and terminated is False and truncated is False

def test_calculator_returns_decimal_string(tmp_path):
    judge_adapter.generate_episode(12, {}, str(tmp_path))
    env = judge_adapter.make_env()
    env.reset(12, {"mode": "closed", "episode_dir": str(tmp_path)})
    observation, *_ = env.step({"name": "calculator", "args": {"expression": "0.1+0.2"}})
    assert observation["result"] == "0.3"
```

- [ ] **Step 2: Run and verify failure**

Expected: `KeyError: 'type'` or wrong observation shape.

- [ ] **Step 3: Implement translation**

- `list_records`: internal `{"type": "list_records", "table": args["table"], "cursor": int(args.get("cursor") or 0), "limit": int(args.get("limit", 50))}`; map internal `rows` to `records`, `next_cursor` int to `str`, `None` stays `None`.
- `get_record`: `{"type": "get_record", "table": args["table"], "id": args["id"]}`.
- `get_document`: `{"type": "get_document", "doc_id": args["doc_id"]}`.
- `calculator`: `{"type": "calculator", "expression": args["expression"]}`; unwrap `{"result": "..."}` to the string.
- `submit`: `{"type": "submit", "findings": args["findings"]}`; inject `episode_id` from `self._episode.manifest` only if absent; on valid result return `{"accepted": true}`, on invalid return `None` plus `{"code": "invalid_findings", "message": "invalid findings structure"}`.
- Later observation: `{"result": <mapped result or None>, "error": <bounded error or None>, "remaining_steps": ...}`.
- Error text must be short, no paths, seed, truth, or provenance.

- [ ] **Step 4: Run and verify pass**

Run: `python -m unittest tests.test_judge_adapter -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add judge_adapter.py tests/test_judge_adapter.py
git commit -m "feat: translate canonical judge actions and observations"
```

### Task 4: Submit and `score_episode`

- [ ] **Step 1: Write the failing tests**

```python
def test_score_episode_test_1(tmp_path):
    judge_adapter.generate_episode(21, {"errors": {"duplicate_invoice": 1}}, str(tmp_path))
    episode = load_episode(tmp_path)
    truth = episode.truth["issues"][0]
    finding = {
        "type": truth["type"],
        "affected_ids": truth["affected_ids"],
        "claimed_amount_minor": truth["expected_amount_minor"],
        "currency": truth["currency"],
        "evidence_ids": truth["allowed_evidence_sets"][0],
        "explanation": "duplicate invoice posted twice",
    }
    result = judge_adapter.score_episode(
        str(tmp_path),
        {"episode_id": episode.manifest["episode_id"], "findings": [finding]},
        10,
    )
    assert result["tp"] == 1 and result["fp"] == 0 and result["fn"] == 0
    assert abs(result["return"] - 0.98) <= 1e-9

def test_score_episode_invalid_limit(tmp_path):
    judge_adapter.generate_episode(22, {}, str(tmp_path))
    result = judge_adapter.score_episode(
        str(tmp_path),
        {"episode_id": "x", "findings": [{}] * 31},
        10,
    )
    assert result == {"tp": None, "fp": None, "fn": None, "precision": None,
                      "recall": None, "f1": None, "return": -1}
```

- [ ] **Step 2: Run and verify failure**

Expected: `score_episode` missing.

- [ ] **Step 3: Implement**

`score_episode` loads the episode, injects `episode_id` only if absent, validates with `validate_findings_payload_strict`, calls `score(episode.truth, normalized, tolerance_minor=int(episode.policy.get("amount_tolerance_minor", 0)), strict=True, available_evidence=available_evidence_ids(episode.open_data()))`, and returns raw `tp/fp/fn/precision/recall/f1` plus `return=terminal_reward(f1, inspection_steps, exact=True)`.

`available_evidence_ids` adds ledger `row_id`, invoice `doc_id`/`invoice_id`, payment `doc_id`/`payment_id`.

- [ ] **Step 4: Run and verify pass**

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add judge_adapter.py tests/test_judge_adapter.py
git commit -m "feat: add official score_episode entry point"
```

---

## Milestone M2: Strict matcher, validator, reward

**Files:**
- Modify: `letro/matcher.py`
- Modify: `letro/schema.py`
- Modify: `letro/evaluator.py`
- Modify: `letro/reward.py`
- Create: `tests/test_official_matcher.py`

**Interfaces:**
- Produces: `finding_matches(finding, issue, tolerance_minor=1, *, strict=False, available_evidence=None)`, `match(..., strict=False, available_evidence=None)`, `score(..., strict=False, available_evidence=None)`, `validate_findings_payload_strict(payload)`, `terminal_reward(f1, inspection_steps, *, exact=False)`.

### Task 5: Strict finding validation

- [ ] **Step 1: Write failing tests**

```python
def test_strict_validator_accepts_unknown_string_type():
    payload = {"episode_id": "e", "findings": [{
        "type": "not_a_declared_type", "affected_ids": ["R1"],
        "claimed_amount_minor": 10000, "currency": "KZT",
        "evidence_ids": ["D1"], "explanation": "x",
    }]}
    normalized = validate_findings_payload_strict(payload)
    assert normalized["findings"][0]["type"] == "not_a_declared_type"

def test_strict_validator_does_not_strip_ids_or_uppercase_currency():
    payload = {"episode_id": "e", "findings": [{
        "type": "duplicate_invoice", "affected_ids": [" R1 "],
        "claimed_amount_minor": 10000, "currency": "kzt",
        "evidence_ids": [" D1 "], "explanation": "x",
    }]}
    normalized = validate_findings_payload_strict(payload)
    assert normalized["findings"][0]["affected_ids"] == [" R1 "]
    assert normalized["findings"][0]["currency"] == "kzt"
```

- [ ] **Step 2: Run and verify failure** (`ImportError`).

- [ ] **Step 3: Implement `validate_findings_payload_strict`**

Same limits as the existing validator (`MAX_FINDINGS=30`, `MAX_EVIDENCE_IDS=10`, `MAX_EXPLANATION_CHARS=1000`, `affected_ids <= 20`), but: unknown string types are accepted; IDs are not stripped; currency is not uppercased or checked against `CURRENCY_DECIMALS`; amount must be an `int` and not `bool`; missing required field or wrong type raises `FindingError`.

- [ ] **Step 4: Run and verify pass.**

### Task 6: Strict matching semantics

- [ ] **Step 1: Write the official Block 3 tests**

Implement at least the 20 numbered tests and M01-M12 from the checklist in `tests/test_official_matcher.py`, with helper fixtures:
`A` type `duplicate_invoice`, affected `["R1","R2"]`, amount `10000`, currency `KZT`, evidence `["D1","D2"]`, tolerance `0`; `D3` existing extra; `U` absent.

Key assertions:
- Test 1: TP=1, FP=0, FN=0, P=R=F1=1, reward 0.98.
- Test 5: two identical findings -> TP=1, FP=1, F1=2/3, reward 47/150 within 1e-9.
- Test 12: 20 findings, 5 records x 4 types -> TP=1, FP=19, F1=2/21, reward -871/1050 within 1e-9.
- Test 13: two errors, one correct -> F1=2/3, reward 47/150.
- Test 18/19/20: 31 findings, 11 evidence IDs, 1001-char explanation -> structural error, return -1.
- M04: evidence `["D1","D2","U"]` -> FP, no match.
- M06: currency `"kzt"` vs `"KZT"` -> FP, no match.
- M08: fixture tolerance 1, amount 10001 -> match; 10002 -> no match.
- M10/M11: max-cardinality matching; M10 requires F1->A, F0->B; M11 deterministic order.

- [ ] **Step 2: Run and verify failures** for strict currency/evidence and exact precision.

- [ ] **Step 3: Implement strict options**

In `finding_matches`:
- `strict=True`: compare `finding["currency"] == issue["currency"]`; require every evidence ID in `available_evidence`; do not uppercase/strip IDs.
- `strict=False`: preserve current behavior exactly.
In `match`: pass `strict` and `available_evidence` through; preserve augmenting-path max matching and special empty/empty F1=1.
In `reward.py`: add keyword-only `exact=False`; when true return clipped raw formula without `round(..., 6)`.
In `evaluator.py`: add `strict: bool = False` constructor/rebind; `score` uses `validate_findings_payload_strict` and passes `strict=True, available_evidence=...` when enabled; default path unchanged.

- [ ] **Step 4: Run the official matcher tests and the existing 134 tests.**

Run: `python -m unittest tests.test_official_matcher -v`
Run: `python -m unittest discover -s tests -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add letro/matcher.py letro/schema.py letro/evaluator.py letro/reward.py tests/test_official_matcher.py
git commit -m "feat: add strict official matcher and exact reward path"
```

---

## Milestone M3: 60-second limit and cursor edge cases

**Files:**
- Modify: `letro/env.py`
- Modify: `judge_adapter.py`
- Modify: `tests/test_judge_adapter.py`

### Task 7: Wall-clock truncation

- [ ] **Step 1: Write the failing test**

```python
def test_wall_clock_timeout_truncates_with_empty_findings(tmp_path):
    judge_adapter.generate_episode(31, {}, str(tmp_path))
    env = judge_adapter.make_env()
    env.reset(31, {"mode": "closed", "episode_dir": str(tmp_path)})
    env._deadline = 0.0
    observation, reward, terminated, truncated, info = env.step(
        {"name": "list_records", "args": {"table": "ledger", "limit": 1}}
    )
    assert terminated is True and truncated is True
    assert observation["remaining_steps"] >= 0
```

- [ ] **Step 2: Run and verify failure.**

- [ ] **Step 3: Implement `AuditEnv.truncate()` and deadline check**

`truncate()` sets `_done=True`, `_truncated=True`, `_last_result={"action":"timeout","ok":False,"error":"time limit exceeded"}`, returns `(observation, 0.0, True, True, info(truncated=True))`. `JudgeEnv.step` checks `time.monotonic() > self._deadline` before translating and calls `self._env.truncate()`.

- [ ] **Step 4: Run and verify pass.**

### Task 8: Cursor pagination through the adapter

- [ ] **Step 1: Write the failing test**

```python
def test_adapter_pagination_reaches_all_rows(tmp_path):
    judge_adapter.generate_episode(32, {}, str(tmp_path))
    env = judge_adapter.make_env()
    env.reset(32, {"mode": "closed", "episode_dir": str(tmp_path)})
    seen, cursor = [], None
    while True:
        observation, *_ = env.step(
            {"name": "list_records", "args": {"table": "ledger", "limit": 50, "cursor": cursor}}
        )
        page = observation["result"]
        seen.extend(row["row_id"] for row in page["records"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert len(seen) == len(set(seen))
    assert len(seen) == json.loads((tmp_path / "manifest.json").read_text())["ledger_rows"]
```

- [ ] **Step 2: Run and verify failure/pass after Task 3; fix string cursor conversion if needed.**

- [ ] **Step 3: Commit M3**

```bash
git add letro/env.py judge_adapter.py tests/test_judge_adapter.py
git commit -m "feat: enforce 60-second limit and canonical cursors"
```

---

## Milestone M4: Deterministic generator scenarios

**Files:**
- Modify: `letro/constants.py`
- Modify: `letro/schema.py`
- Modify: `letro/generator/errors.py`
- Modify: `letro/generator/company.py`
- Create: `tests/test_generator_scenarios.py`

**Interfaces:**
- Config additions:
  - `gap_mode`: `"partial"` (default), `"missing"`, `"mixed"`.
  - `composite_scenario`: `"alternate"` (default), `"first"`, `"second"`, `"both"`.
  - `split_payment`, `refund`, `recurring` booleans (default `true`).

### Task 9: Full missing allocation

- [ ] **Step 1: Write failing test**

```python
def test_gap_mode_missing_creates_full_unallocated_payment():
    episode = generate_episode(41, {"errors": {"payment_allocation_gap": 1}, "gap_mode": "missing"})
    issue = episode.truth["issues"][0]
    assert issue["type"] == "payment_allocation_gap"
    assert issue["expected_amount_minor"] > 0
    # The AR credit for the affected payment is zero; suspense carries the full amount.
```

- [ ] **Step 2: Run and verify failure** (`unknown config key: gap_mode`).

- [ ] **Step 3: Implement**

- Add `gap_mode` and `composite_scenario` to `DEFAULT_CONFIG` and `validate_config` with allowed values.
- `_inject_gap(..., gap_mode)`: `partial` keeps `max(1, int(credit*0.4))`; `missing` sets the AR credit to `0` and posts the full original credit to suspense; `mixed` alternates by call count. The truth expected amount follows the actual gap.
- Ensure `reference_audit` derives the same expected amount.

### Task 10: Pure second composite scenario

- [ ] **Step 1: Write failing test**

```python
def test_composite_scenario_second_can_run_alone():
    episode = generate_episode(42, {"errors": {"composite": 1}, "composite_scenario": "second"})
    assert episode.provenance["steps"][0]["scope"] == "gap_cutoff_payment"
```

- [ ] **Step 2: Run and verify failure.**

- [ ] **Step 3: Implement composite selection**

In `inject_errors`, choose by `config.get("composite_scenario", "alternate")`:
`first` -> `_composite_boundary_fx`; `second` -> `_composite_gap_cutoff`; `both`/`alternate` -> current odd/even behavior. Keep fallbacks.

### Task 11: Feature flags for clean scenarios

- [ ] **Step 1: Write failing tests** that `split_payment=False`, `refund=False`, `recurring=False` produce no split payment, no refund rows, and one occurrence per recurring expense.
- [ ] **Step 2: Implement flags in `company.py`** at the existing random branches; default `True` preserves current output.
- [ ] **Step 3: Run `tests/test_generator_scenarios.py` and the full suite.**
- [ ] **Step 4: Commit M4**

```bash
git add letro/constants.py letro/schema.py letro/generator/errors.py letro/generator/company.py tests/test_generator_scenarios.py
git commit -m "feat: add deterministic scenario switches to generator"
```

---

## Milestone M5: README, audit report, verification

**Files:**
- Modify: `README.md`
- Create: `docs/OFFICIAL-CHECKLIST-AUDIT.md`
- Modify: `docs/CONTINUATION_PROMPT.md`

### Task 12: Adapter documentation

- [ ] **Step 1: Add README section "Official judge adapter"**

Must state:
- working directory: repository root;
- launch command: `python -c "import judge_adapter"` or the jury's import command;
- three entry points and exact signatures;
- closed reset config example;
- canonical action/observation mapping;
- the four error-type mapping table (`duplicate_invoice`, `payment_allocation_gap`, `fx_rate_error`, `period_cutoff`);
- `score_episode` result schema, invalid `return=-1` with null metrics;
- closed reward 0, train reward visible;
- 60-second limit.

- [ ] **Step 2: Add `docs/OFFICIAL-CHECKLIST-AUDIT.md`** with the block-by-block score table (B1 25, B2 25, B3 25, B4 15, engineering 10), current estimated score, fixed items, and remaining gaps.

- [ ] **Step 3: Run full verification**

```bash
python -m unittest discover -s tests -v
python -m letro.verify
python -c "import judge_adapter; print(judge_adapter.make_env())"
```

Expected: all existing tests plus new tests pass; `letro.verify` remains 100/100; adapter imports.

- [ ] **Step 4: Commit M5**

```bash
git add README.md docs/OFFICIAL-CHECKLIST-AUDIT.md docs/CONTINUATION_PROMPT.md
git commit -m "docs: document official adapter and checklist status"
```

---

## Self-Review

**Spec coverage:** M1 covers the mandatory adapter, closed mode, canonical action/observation, submit and score_episode. M2 covers Block 3 exactness (IDs, currency, evidence, limits, matching, numeric tolerance). M3 covers the 60-second rule and cursor. M4 covers Block 2 D09-D11 missing/partial allocation and D19-D20 second scenario. M5 covers the engineering documentation anchors. Block 4 pair checks are structurally supported by closed `episode_dir` loading plus `score_episode`; no extra transform code is required.

**Known residual gaps after this plan:**
- The jury may still independently disagree with LETRO's accounting interpretation on some Block 2 episodes; the generator and audit are the same code path, so independent reconciliation remains a risk.
- The official fixture may use evidence IDs outside the three LETRO ID spaces; the adapter accepts only IDs reachable through LETRO tools.
- The project's own `letro.verify` is not the official jury; it is a regression gate only.

**Commands:**
- Focused: `python -m unittest tests.test_judge_adapter tests.test_official_matcher tests.test_generator_scenarios -v`
- Full: `python -m unittest discover -s tests -v`
- Self-check: `python -m letro.verify`
