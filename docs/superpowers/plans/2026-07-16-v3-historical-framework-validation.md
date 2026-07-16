# V3 Historical Framework Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Execute a reproducible first historical validation batch for the repaired V3 discovery framework and report what is supported, rejected, or still untestable.

**Architecture:** Recompute market, hotspot, and stock context observations in a temporary read-only research workspace for ten formation dates spaced by 20 trading sessions. Historical market facts were backfilled with July 2026 `available_at`, so immutable business-dated prices, calendars, and valid memberships must be reconstructed by `trade_date`/validity interval while company disclosures remain filtered by their public `available_at`; the result is explicitly pseudo-out-of-sample, not strict historical time travel. Separate formation evidence from future outcomes: first freeze date selection, route scan manifests, transparent probe policies, and any human-assisted framework candidates; only then evaluate adjusted forward high, close, and adverse paths. Probe policies compare search architectures but never become production stock-selection rules.

**Tech Stack:** Python 3.12, pandas, DuckDB, existing `ResearchWarehouse`, existing governed feature formulas, pytest, Markdown/YAML research artifacts.

## Global Constraints

- Use the current local `main`; do not create a branch or worktree because the user explicitly required direct work on current main.
- Do not change `local_warehouse`, add a data source, rebuild the data foundation, or deploy/activate anything.
- Company disclosures and financial revisions must be filtered by `available_at`; deterministic market facts use business date only because the current backfill stamped their historical rows in July 2026. This deviation must be reported and prohibits calling the batch a strict point-in-time backtest.
- Preserve the distinction between API facts, locally recomputed observations, model judgement, and user language.
- Do not introduce a production score, fixed weight, buy/sell rule, portfolio return, Sharpe ratio, or trader-identity inference.
- Transparent probe policies are validation controls only and must be named `probe`, documented, sensitivity-tested, and prohibited from runtime use.
- The complete framework coverage starts only after controlled theme history can support a 20-session window; five-year prices do not imply five-year full-framework coverage.

---

### Task 1: Freeze the validation batch and read-only feature inputs

**Files:**
- Create: `docs/superpowers/specs/2026-07-16-v3-historical-validation-batch-freeze.md`
- Use without modification: `src/stock_analyzer/ops/research_features.py`
- Temporary output only: `/tmp/v3-historical-validation-*/derived/**`

**Interfaces:**
- Consumes: local research warehouse and the framework rules in section 18.20.
- Produces: ten formation dates, source hashes, route coverage manifest, and exact temporary derived snapshots.

- [ ] **Step 1: Freeze formation dates**

Record these dates before reading any future result: `2025-08-15`, `2025-09-12`, `2025-10-20`, `2025-11-17`, `2025-12-15`, `2026-01-14`, `2026-02-11`, `2026-03-19`, `2026-04-17`, `2026-05-20`.

- [ ] **Step 2: Create a temporary research root**

Copy `local_warehouse/research.duckdb` into a new `/tmp/v3-historical-validation-*` directory and symlink its `facts` directory to the workspace facts. Do not write under `local_warehouse`.

- [ ] **Step 3: Attempt governed feature replay and freeze the availability limitation**

Call `run_research_features()` against the temporary root. If historical market facts are invisible because their backfill `available_at` is later than the formation date, record the failure and do not alter the formal warehouse. Reconstruct the same formula inputs read-only by business date for market facts and validity interval for classifications; continue filtering disclosures by public `available_at`.

- [ ] **Step 4: Commit the batch freeze before future evaluation**

Run `git diff --check`, stage the batch-freeze document, and commit it with message `docs: freeze V3 historical validation batch`.

### Task 2: Build tested formation-only probe and outcome utilities

**Files:**
- Create: `src/stock_analyzer/validation/historical_framework_validation.py`
- Create: `tests/test_historical_framework_validation.py`

**Interfaces:**
- Produces: `select_spaced_origins()`, `validate_formation_cutoff()`, `round_robin_union()`, `compute_forward_outcomes()`, and `summarize_outcomes()`.
- `round_robin_union(route_lists: Mapping[str, Sequence[str]], limit: int) -> tuple[str, ...]` interleaves route-native lists without adding weights.
- `compute_forward_outcomes(prices: DataFrame, selections: DataFrame, horizons: tuple[int, ...], target_return: float) -> DataFrame` uses formation adjusted close, future adjusted high/low/close, and never reads dates before validating frozen formation rows.

- [ ] **Step 1: Write failing tests for origin spacing and cutoff rejection**

Test that every 20th open session is selected and that evidence with `available_at` after the formation cutoff raises `ValueError`.

- [ ] **Step 2: Run RED tests**

Run `pytest tests/test_historical_framework_validation.py -v`; verify failure occurs because the module or functions do not exist.

- [ ] **Step 3: Implement the minimal origin and cutoff functions**

Implement deterministic date normalization and fail-closed cutoff validation without warehouse writes.

- [ ] **Step 4: Run GREEN tests**

Run the same pytest command and verify the origin/cutoff tests pass.

- [ ] **Step 5: Write failing tests for round-robin de-duplication**

Test that overlapping route lists produce unique candidates, preserve within-route order, and stop at the declared limit.

- [ ] **Step 6: Implement and verify round-robin union**

Run RED, implement the minimal iterator, then run GREEN.

- [ ] **Step 7: Write failing tests for 10/20/30-session path outcomes**

Use a synthetic adjusted-price panel to test target touch, terminal close, maximum adverse path, target-first versus drawdown-first, and missing-horizon handling.

- [ ] **Step 8: Implement and verify outcome calculation**

Run RED, implement adjusted path evaluation, and run GREEN. The function must not infer executable return or trading cost.

- [ ] **Step 9: Write and verify aggregate metric tests**

Test precision, base rate, median lead session, terminal return, adverse path, and coverage counts. Keep each metric separate; do not add a composite score.

### Task 3: Freeze formation-only candidate probes and framework audit

**Files:**
- Create: `docs/superpowers/specs/2026-07-16-v3-historical-validation-formation-freeze.yaml`
- Create: `docs/superpowers/specs/2026-07-16-v3-historical-validation-formation-audit.md`

**Interfaces:**
- Consumes: Task 1 temporary feature snapshots and only facts visible at each formation cutoff.
- Produces: for every date, universe count, hotspot panorama, route-native candidate lists, ten-candidate probe lists, exclusions, and coverage gaps.

- [ ] **Step 1: Build route-native formation lists without future data**

Create separate hotspot, earnings, event, cycle/distress, and price investigation lists. Each list records its own native ordering and source facts. Do not translate list position into confidence.

- [ ] **Step 2: Build four transparent controls**

Freeze `hotspot_probe`, `earnings_probe`, `price_probe`, and `parallel_round_robin_probe`, each with at most ten names. The parallel probe interleaves route-native lists and uses the same downstream hard boundaries.

- [ ] **Step 3: Record the human-framework boundary**

For each formation date record whether the full company evidence card was manually executable. If announcement正文 or economic materiality cannot be checked, the row is excluded from `human_framework` and the limitation is counted; no model guess may fill it.

- [ ] **Step 4: Validate and commit the formation freeze**

Run a no-future audit: every evidence timestamp must be at or before its formation cutoff and the freeze file must contain no outcome fields. Commit before any future price query with message `docs: freeze V3 historical formation candidates`.

### Task 4: Reveal outcomes and produce the report

**Files:**
- Create: `docs/superpowers/specs/2026-07-16-v3-historical-framework-validation-results.md`
- Modify: `docs/superpowers/specs/2026-07-15-v3-analysis-framework-working-draft.md`

**Interfaces:**
- Consumes: committed formation freeze and adjusted price facts.
- Produces: 10/20/30-session outcomes, baseline comparisons, route coverage, uncertainty cautions, failure analysis, and a go/no-go conclusion for implementation.

- [ ] **Step 1: Evaluate frozen candidates and same-day universe base rates**

Use exact adjusted formation close and future adjusted high/low/close. Report incomplete horizons separately.

- [ ] **Step 2: Compare controls without selecting the winner after seeing results**

Report every frozen probe and any human-framework sample, including poor results. Compare multiple dates and directions; do not optimize probe definitions on this batch.

- [ ] **Step 3: Audit representative misses and false occupancy**

For future target stocks omitted by all probes, inspect only their already-frozen formation evidence and classify the missing route, missing evidence, hard boundary, or probe-capacity cause.

- [ ] **Step 4: Write the decision**

State separately whether discovery architecture, ten-name compression, focus/candidate layering, and lifecycle replacement are supported, rejected, or still untestable. Historical evidence can authorize continued prospective validation, not deployment.

- [ ] **Step 5: Verify**

Run `pytest tests/test_historical_framework_validation.py -v`, the relevant existing research feature tests, `git diff --check`, and recompute all reported table totals from the committed freeze.

- [ ] **Step 6: Commit**

Commit the tested utility, result report, and framework record with message `test: report V3 historical framework validation`.
