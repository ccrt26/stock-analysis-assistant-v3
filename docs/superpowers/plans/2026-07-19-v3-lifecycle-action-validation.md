# V3 Lifecycle and Action Confirmation Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an isolated, non-production validator that freezes a simple project lifecycle and one action-confirmation rule, replays the untouched 2025-12-11 to 2026-01-23 formation period, and reports whether the method is technically and economically usable.

**Architecture:** Reuse the existing layered formation runner and the already-approved single-list compression function without modifying either policy. A new focused evaluator creates holdout evidence on the USB drive, simulates at most ten persistent projects in chronological order, computes next-session-open action paths, and evaluates lifecycle stability and action discrimination separately. Development A/B/C results are written only as hypothesis provenance; all pass/fail decisions use the frozen holdout.

**Tech Stack:** Python 3.12, pandas, NumPy, PyArrow parquet, PyYAML, pytest; existing `v3_layered_validation`, `v3_compression_revalidation`, and `v3_next_day_entry_validation` helpers.

**Execution status (2026-07-19):** Completed through final holdout evaluation and documentation. The action-confirmation method passed its frozen holdout criteria. The lifecycle passed the pre-registered stability thresholds but was vetoed by a post-run safety audit because 22 of 26 hard exits reached the target only after exit; it is therefore recorded as rejected, not as a successful framework change.

## Global Constraints

- Work directly on the current local `main`; do not create a branch or worktree.
- Do not stage, commit, push, activate, deploy, or generate a formal recommendation.
- Do not use subagents.
- Do not modify the data foundation, feature builders, approved compression behavior, or old A/B/C source results.
- All runtime artifacts, logs, temporary tables, manifests, and reports must be written under `/Volumes/ZHUTONG/股票分析助手-V3回测/2026-07-19-v3-lifecycle-action-validation/`.
- The only holdout formation interval is 2025-12-11 through 2026-01-23, exactly 30 consecutive market sessions.
- The action rule is exactly `return_5d > 0`, `relative_return_20d > 0`, and `current_amount_ratio_20d >= 1`, with no score or tuned fallback.
- User output remains one attention list of at most ten; internal state names are audit-only.

---

### Task 1: Freeze configuration and action-condition contracts

**Files:**
- Create: `docs/superpowers/specs/2026-07-19-v3-lifecycle-action-validation-config.yaml`
- Create: `src/stock_analyzer/evaluation/v3_lifecycle_action_validation.py`
- Create: `tests/test_v3_lifecycle_action_validation.py`

**Interfaces:**
- Produces: `LifecycleActionConfig`, `load_config(path) -> LifecycleActionConfig`, `action_condition(row: pd.Series) -> bool`, `prepare_output_root(config) -> Path`.
- Consumes: frozen warehouse and USB paths from the YAML configuration.

- [ ] **Step 1: Write failing configuration and action-condition tests**

```python
def test_action_condition_requires_all_three_observable_confirmations():
    row = pd.Series({
        "return_5d": 0.01,
        "relative_return_20d": 0.02,
        "current_amount_ratio_20d": 1.0,
        "hard_invalid": False,
        "user_layer": "关注",
    })
    assert action_condition(row)
    for field in ("return_5d", "relative_return_20d", "current_amount_ratio_20d"):
        failed = row.copy()
        failed[field] = 0.0 if field != "current_amount_ratio_20d" else 0.99
        assert not action_condition(failed)

def test_config_freezes_holdout_and_usb_root(tmp_path):
    config = load_config(CONFIG_PATH)
    assert config.holdout_start.isoformat() == "2025-12-11"
    assert config.holdout_end.isoformat() == "2026-01-23"
    assert config.formation_sessions == 30
    assert str(config.output_root).startswith("/Volumes/ZHUTONG/")
```

- [ ] **Step 2: Run tests and verify RED**

Run: `.venv/bin/pytest tests/test_v3_lifecycle_action_validation.py -q`
Expected: FAIL because the module and interfaces do not exist.

- [ ] **Step 3: Implement the minimal dataclass, config validation, USB guard, and action predicate**

The YAML must freeze `experiment_id`, warehouse and development roots, output root, holdout block `D`, 20/30 horizons, 20% target, 1/3/5 retention windows, candidate cap 10, day-10/day-20/day-30 checkpoints, next-session-open entry, minimum 20 executable action projects, and a runtime stop boundary.

- [ ] **Step 4: Run the focused tests and verify GREEN**

Run: `.venv/bin/pytest tests/test_v3_lifecycle_action_validation.py -q`
Expected: configuration and predicate tests PASS.

### Task 2: Implement the chronological project state machine

**Files:**
- Modify: `src/stock_analyzer/evaluation/v3_lifecycle_action_validation.py`
- Modify: `tests/test_v3_lifecycle_action_validation.py`

**Interfaces:**
- Produces: `simulate_lifecycle(daily_attention, daily_market, daily_prices, config) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]` returning daily project snapshots, first executable actions, and capacity exclusions.
- Consumes: daily single-list compression rows; same-day market/stock facts; no future result columns.

- [ ] **Step 1: Write one failing test for each state invariant**

Tests must prove:

```python
assert snapshots.groupby("formation_date").active.sum().max() <= 10
assert one_day_absence_project.status != "ended"
assert never_confirmed_day_10.exit_reason == "not_confirmed_by_day_10"
assert confirmed_without_second_wave_day_20.exit_reason == "no_second_wave_confirmation"
assert surviving_project_day_30.exit_reason == "day_30_expiry"
assert actions.groupby("project_id").size().max() == 1
assert hard_invalid_project.exit_reason == "hard_invalidation"
```

Include an unexecutable next-open fixture showing that the project remains trackable and can form one later executable action.

- [ ] **Step 2: Run the state tests and verify RED**

Run: `.venv/bin/pytest tests/test_v3_lifecycle_action_validation.py -q`
Expected: FAIL on the missing state engine.

- [ ] **Step 3: Implement the minimal ordered state engine**

Process sessions in ascending order. Existing active projects retain slots before new daily candidates. Soft absence carries the project without creating an action. The day-10, day-20, and day-30 checks use project age from first admission. Only a current daily attention row may create an action plan. Never read target outcomes while choosing candidates or forming plans.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `.venv/bin/pytest tests/test_v3_lifecycle_action_validation.py -q`
Expected: all lifecycle unit tests PASS.

### Task 3: Build the untouched holdout formation and action paths

**Files:**
- Modify: `src/stock_analyzer/evaluation/v3_lifecycle_action_validation.py`
- Modify: `tests/test_v3_lifecycle_action_validation.py`

**Interfaces:**
- Produces: `build_holdout_formations(config)`, `build_daily_attention(config)`, `build_action_paths(config, actions)`, and source-tree signatures.
- Consumes: existing `run_blocks`, `reveal_outcomes`, `compress_decision_list`, `_read_action_price_frame`, and `compute_action_path` behavior without changing those functions.

- [ ] **Step 1: Write failing integration-contract tests using temporary synthetic formation partitions**

Tests must assert that evidence is recompressed with `user_layer == "关注"`, daily rows never exceed ten, action paths start at the next market-session open, 20-day touch is a subset of 30-day touch, close is a subset of touch, and source signatures are unchanged.

- [ ] **Step 2: Run tests and verify RED**

Run: `.venv/bin/pytest tests/test_v3_lifecycle_action_validation.py -q`
Expected: FAIL on missing formation/action orchestration.

- [ ] **Step 3: Implement holdout orchestration**

Construct an in-memory `ValidationConfig` for block `D` and call the existing historical formation/reveal functions. Read the 30 frozen `evidence.parquet` files, apply `compress_decision_list(candidate_cap=10)`, and write only compact holdout tables under the dedicated USB experiment root. Build next-open 20/30-day paths only after the formation set and action plans are frozen.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `.venv/bin/pytest tests/test_v3_lifecycle_action_validation.py -q`
Expected: orchestration contracts PASS without network or production writes.

### Task 4: Implement metrics, acceptance, cases, and the Chinese report

**Files:**
- Modify: `src/stock_analyzer/evaluation/v3_lifecycle_action_validation.py`
- Modify: `tests/test_v3_lifecycle_action_validation.py`

**Interfaces:**
- Produces: `summarize_action_value`, `summarize_lifecycle`, `evaluate_acceptance`, `generate_report`, and `run_validation`.
- Writes: compact parquet tables plus JSON manifests and `reports/v3-lifecycle-action-validation-results.md` on the USB drive.

- [ ] **Step 1: Write failing acceptance and report tests**

Tests must demonstrate three independent outcomes: `technical_passed`, `lifecycle_feasibility`, and `action_feasibility`. They must cover `supported`, `insufficient_evidence`, `stable_but_unusable`, and `rejected`. The report test must verify plain Chinese explanations, exact denominators, all failed checks, early-exit winners, capacity-missed winners, and the statement that no formal buy/sell capability has been proven.

- [ ] **Step 2: Run tests and verify RED**

Run: `.venv/bin/pytest tests/test_v3_lifecycle_action_validation.py -q`
Expected: FAIL on missing summaries and report.

- [ ] **Step 3: Implement minimal metrics and report generation**

Write `daily_attention.parquet`, `project_snapshots.parquet`, `project_actions.parquet`, `action_paths.parquet`, `action_summary.parquet`, `lifecycle_summary.parquet`, `capacity_exclusions.parquet`, `case_studies.parquet`, `quality_checks.json`, `acceptance_checks.json`, `input_manifest.json`, and the final Markdown report. No table may contain a future result in a formation-decision column.

- [ ] **Step 4: Run focused and neighboring tests**

Run: `.venv/bin/pytest tests/test_v3_lifecycle_action_validation.py tests/test_v3_compression_revalidation.py tests/test_v3_layered_validation.py tests/test_v3_next_day_entry_validation.py -q`
Expected: all tests PASS.

### Task 5: Execute the frozen holdout, independently verify, and update the framework

**Files:**
- Modify after results: `docs/superpowers/specs/2026-07-15-v3-analysis-framework-working-draft.md`
- Runtime output only: `/Volumes/ZHUTONG/股票分析助手-V3回测/2026-07-19-v3-lifecycle-action-validation/`

**Interfaces:**
- Consumes: the frozen config and validator CLI.
- Produces: final evidence-backed feasibility conclusion and framework record.

- [ ] **Step 1: Run preflight and freeze source signatures**

Run: `.venv/bin/python -m stock_analyzer.evaluation.v3_lifecycle_action_validation preflight --config docs/superpowers/specs/2026-07-19-v3-lifecycle-action-validation-config.yaml`
Expected: exactly 30 holdout sessions, complete 30-day future window, writable USB root, unchanged source signatures.

- [ ] **Step 2: Run formation before reveal**

Run: `.venv/bin/python -m stock_analyzer.evaluation.v3_lifecycle_action_validation form --config docs/superpowers/specs/2026-07-19-v3-lifecycle-action-validation-config.yaml`
Expected: 30 frozen formation partitions and no action outcome table yet.

- [ ] **Step 3: Reveal paths and generate the report without changing rules**

Run: `.venv/bin/python -m stock_analyzer.evaluation.v3_lifecycle_action_validation evaluate --config docs/superpowers/specs/2026-07-19-v3-lifecycle-action-validation-config.yaml`
Expected: quality, acceptance, compact tables, cases, and Chinese report under the USB output root.

- [ ] **Step 4: Independently recompute headline numerators and denominators**

Read `action_paths.parquet` and `project_snapshots.parquet` directly and recompute 20/30 touch, close, retain-3, median adverse return, project duration, day-5 survival, churn, early exits, and capacity misses. Compare each value with the generated report and JSON checks.

- [ ] **Step 5: Update the working framework with the actual result**

Add one dated section that states the exact holdout interval, rule, all metrics, pass/fail result, what is retained, what is deleted, and why. Do not rewrite an unsuccessful result as a successful framework change.

- [ ] **Step 6: Run final verification**

Run: `.venv/bin/pytest tests/test_v3_lifecycle_action_validation.py tests/test_v3_compression_revalidation.py tests/test_v3_layered_validation.py tests/test_v3_next_day_entry_validation.py -q`
Run: `git diff --check`
Expected: zero test failures and no whitespace errors. Re-read `quality_checks.json`, `acceptance_checks.json`, and source signatures before any completion claim.
