# V3 Selection Accuracy Pareto Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reuse frozen A/B/C/D evidence to determine whether any known counter-evidence removes false stock selections without removing later winners.

**Architecture:** Add one isolated research evaluator and one focused test file. The evaluator reads only compact USB parquet artifacts, constructs one first executable action per stock and block under the frozen three-condition baseline, evaluates four pre-registered counter-evidence families separately, produces precision–recall/risk–coverage and Pareto tables, and writes a Chinese report to a dedicated USB analysis directory. It does not modify the production selector or implement lifecycle, holdings, exits, or deployment.

**Tech Stack:** Python 3.12, pandas, NumPy, PyArrow parquet, pytest; existing `v3_lifecycle_action_validation.action_condition` semantics.

## Global Constraints

- Work directly on the current local `main`; do not create a branch or worktree.
- Do not stage, commit, push, activate, deploy, or generate formal recommendations.
- Do not use subagents.
- Do not modify the production selector, data foundation, feature builders, current compression behavior, or frozen A/B/C/D results.
- Use A/B/C/D only as revealed development diagnostics, never as independent validation of a new rule.
- All runtime outputs go under `/Volumes/ZHUTONG/股票分析助手-V3回测/2026-07-19-v3-selection-accuracy-pareto-analysis/`.
- Do not use a fixed total score, tuned feature weights, an 80% target, or a 75% retention floor.
- Analyze only four known problems: continuous price overextension, high-location/volume interaction, profit–cash contradiction, and hotspot weakening with relative-strength loss.
- Stop after the development diagnostic report and framework update; do not select a new holdout or write a production implementation plan.

---

### Task 1: Build frozen diagnostic rows

**Files:**
- Create: `src/stock_analyzer/evaluation/v3_selection_accuracy_pareto.py`
- Create: `tests/test_v3_selection_accuracy_pareto.py`

**Interfaces:**
- Consumes: `recompressed_action_outcomes.parquet`, `daily_attention.parquet`, `project_actions.parquet`, and `action_paths.parquet`.
- Produces: `build_development_projects(abc_root: Path, d_root: Path) -> pd.DataFrame` with one row per `(block, ts_code)` first executable baseline action and paired 20/30-day outcomes.

- [x] **Step 1: Write failing data-contract tests**

Use temporary parquet fixtures to assert that `build_development_projects`:

```python
projects = build_development_projects(abc_root, d_root)
assert projects.groupby(["block", "ts_code"]).size().max() == 1
assert set(projects["block"]) == {"A", "B", "C", "D"}
assert projects["action_date"].gt(projects["formation_date"]).all()
assert not ({"first_touch_date", "close_confirmed_20"} & set(projects.filter(regex="feature").columns))
```

The fixtures must include repeated daily appearances of one stock and prove that only its first executable three-condition signal remains.

- [x] **Step 2: Run the focused test and verify RED**

Run: `.venv/bin/pytest tests/test_v3_selection_accuracy_pareto.py -q`

Expected: import failure because the evaluator does not exist.

- [x] **Step 3: Implement minimal loading and first-action construction**

Implement these public functions:

```python
def baseline_action_mask(frame: pd.DataFrame) -> pd.Series:
    return (
        frame["user_layer"].eq("关注")
        & ~frame["hard_invalid"].fillna(False).astype(bool)
        & frame["return_5d"].gt(0)
        & frame["relative_return_20d"].gt(0)
        & frame["current_amount_ratio_20d"].ge(1)
    )

def build_development_projects(abc_root: Path, d_root: Path) -> pd.DataFrame:
    """Return the first executable baseline action per stock and block."""
```

For A/B/C, filter `policy == "v3_recompressed"`, apply the frozen mask, require complete executable 20/30 paths, pivot paired outcomes, and retain the earliest formation date for each stock and block. For D, join each `project_actions.plan_date` to `daily_attention.formation_date`, then join the `policy == "project_action"` 20/30 paths. Preserve formation features and rename next-session entry date to `action_date`.

- [x] **Step 4: Run focused tests and verify GREEN**

Run: `.venv/bin/pytest tests/test_v3_selection_accuracy_pareto.py -q`

Expected: all data-contract tests pass.

### Task 2: Evaluate the four known counter-evidence families and Pareto dominance

**Files:**
- Modify: `src/stock_analyzer/evaluation/v3_selection_accuracy_pareto.py`
- Modify: `tests/test_v3_selection_accuracy_pareto.py`

**Interfaces:**
- Consumes: the project table from Task 1.
- Produces: `diagnostic_bins`, `rule_metrics`, `pareto_frontier`, `attempt_registry`, and `case_examples` data frames.

- [x] **Step 1: Write failing metric and dominance tests**

Synthetic rows must prove:

```python
metrics = summarize_rule(projects, keep_mask, rule_id="candidate")
assert metrics.loc[metrics.horizon.eq(30), "precision_close"].iat[0] == 2 / 3
assert metrics.loc[metrics.horizon.eq(30), "winner_count_close"].iat[0] == 2

assert pareto_status(candidate_better, baseline) == "pareto_improvement"
assert pareto_status(candidate_more_precise_but_misses_winner, baseline) == "tradeoff_only"
assert pareto_status(candidate_worse, baseline) == "dominated"
```

Add a test showing that a rule cannot pass merely by keeping one successful row.

- [x] **Step 2: Run focused tests and verify RED**

Run: `.venv/bin/pytest tests/test_v3_selection_accuracy_pareto.py -q`

Expected: failures on missing summaries and Pareto classification.

- [x] **Step 3: Implement fixed diagnostic families without outcome-tuned thresholds**

Implement the exact public signatures `add_unsupervised_bins(projects: pd.DataFrame) -> pd.DataFrame`, `candidate_keep_masks(projects: pd.DataFrame) -> dict[str, pd.Series]`, `summarize_rule(projects: pd.DataFrame, keep: pd.Series, rule_id: str) -> pd.DataFrame`, `pareto_status(candidate: pd.DataFrame, baseline: pd.DataFrame) -> str`, and `run_diagnostics(projects: pd.DataFrame) -> dict[str, pd.DataFrame]`.

Use only formation-feature quantiles for descriptive bins; never use outcomes to place cut points. Register every attempted rule. Evaluate each family alone before any two-family combination. The only candidate masks are:

- upper formation-only quantile bands of `return_5d` and `price_location_60d`, reported as a curve rather than a selected magic cutoff;
- joint formation-only quantile cells of `price_location_60d` and `current_amount_ratio_20d`;
- profit positive with `n_cashflow_act <= 0`, and profit positive with `ocf_yoy < 0`, restricted to earnings/company-driven rows;
- hotspot support weakening combined with non-positive or deteriorating relative-strength evidence when that evidence exists at formation time.

For every rule and block, report selected projects, action days, touch/close/retain-3 successes, precision, baseline-winner recall, median entry gap, and median window minimum return at 20/30 days. Classify a rule as `pareto_improvement` only under the exact design criteria; otherwise use `tradeoff_only` or `dominated`.

- [x] **Step 4: Run focused tests and verify GREEN**

Run: `.venv/bin/pytest tests/test_v3_selection_accuracy_pareto.py -q`

Expected: all diagnostic and Pareto tests pass.

### Task 3: Run the compact diagnostic, report honestly, and update the framework

**Files:**
- Modify: `src/stock_analyzer/evaluation/v3_selection_accuracy_pareto.py`
- Modify: `tests/test_v3_selection_accuracy_pareto.py`
- Modify after results: `docs/superpowers/specs/2026-07-15-v3-analysis-framework-working-draft.md`
- Runtime output only: `/Volumes/ZHUTONG/股票分析助手-V3回测/2026-07-19-v3-selection-accuracy-pareto-analysis/`

**Interfaces:**
- Produces CLI command `.venv/bin/python -m stock_analyzer.evaluation.v3_selection_accuracy_pareto --abc-root /Volumes/ZHUTONG/股票分析助手-V3回测/2026-07-19-v3-compression-revalidation --d-root /Volumes/ZHUTONG/股票分析助手-V3回测/2026-07-19-v3-lifecycle-action-validation --output-root /Volumes/ZHUTONG/股票分析助手-V3回测/2026-07-19-v3-selection-accuracy-pareto-analysis` and a Chinese report.

- [x] **Step 1: Write a failing report test**

The generated report must contain:

```python
text = report.read_text(encoding="utf-8")
assert "A/B/C/D都是已揭示开发样本" in text
assert "帕累托改进" in text
assert "错过的后来赢家" in text
assert "未找到帕累托改进" in text or "值得冻结的候选规则" in text
assert "不是独立验证" in text
```

- [x] **Step 2: Implement output manifests and the Chinese report**

Write:

- `tables/development_projects.parquet`
- `tables/diagnostic_bins.parquet`
- `tables/rule_metrics.parquet`
- `tables/pareto_frontier.parquet`
- `tables/attempt_registry.parquet`
- `tables/case_examples.parquet`
- `manifests/input_signatures.json`
- `reports/v3-selection-accuracy-pareto-results.md`

The report must identify what works, what fails, exact numerators/denominators, winner losses, cross-block direction, and whether any rule deserves freezing. If no rule Pareto-dominates the baseline, say so and retain the baseline.

- [x] **Step 3: Run focused and neighboring tests**

Run: `.venv/bin/pytest tests/test_v3_selection_accuracy_pareto.py tests/test_v3_lifecycle_action_validation.py tests/test_v3_compression_revalidation.py tests/test_v3_next_day_entry_validation.py -q`

Expected: all tests pass.

- [x] **Step 4: Execute the compact USB diagnostic**

Run the module with the frozen A/B/C and D roots. Expected runtime is minutes, not a new formation replay. Verify source signatures are unchanged.

- [x] **Step 5: Independently recompute headline counts**

Read `development_projects.parquet` and `rule_metrics.parquet` directly. Recompute each retained-row count, close-confirmed winner count, baseline-winner recall, retain-3 count, and median adverse path. Compare with the report.

- [x] **Step 6: Update only the result section of the working framework**

Record exact development-sample findings, all failed hypotheses, any Pareto candidate, and the explicit boundary that no new rule is active until an untouched-period validation. Do not reactivate lifecycle, holdings, exits, or system work.

- [x] **Step 7: Final verification**

Run: `git diff --check`

Re-read the USB report, attempt registry, source signatures, and framework result section before any completion claim.
