# V3 Governed Derived Research Features Implementation Plan

> **For Codex:** REQUIRED SUB-SKILLS: use `superpowers:test-driven-development` for every behavior change, then `superpowers:verification-before-completion`; use `superpowers:requesting-code-review` before final acceptance. Do not create a branch or worktree. Work on the current local `main` as explicitly requested by the user.

**Goal:** Complete the missing derived layer of the unified research warehouse so market context, sector hotspot evidence, and stock trading context are reproducible, versioned, persisted, health-checked, and automatically recomputed by the existing data-only schedule.

**Architecture:** Add one governed derived store beside the existing fact store, in the same DuckDB and `local_warehouse` root. Formula modules remain deterministic and decision-free. A feature job reads only strict `as_of` fact queries, commits three atomic Parquet partitions with input manifests, and is called after the evening fact refresh and after next-morning repairs when inputs changed.

**Tech Stack:** Python 3.12, pandas, NumPy, DuckDB, PyArrow/Parquet, Pydantic, Typer, pytest, launchd.

**Design:** `docs/superpowers/specs/2026-07-14-v3-governed-derived-research-features-design.md`

**Scope guard:** Do not implement recommendation weights, a five-day 10% prediction model, LLM narrative, formal reports, activation, deployment, publication, or third-party black-box fund-flow ingestion. Do not reuse the old Phase 3 scoring output as a derived fact.

---

## Task 1: Add the governed derived storage contract

**Files:**

- Modify: `src/stock_analyzer/storage/research_schema.py`
- Create: `src/stock_analyzer/storage/research_derived.py`
- Modify: `tests/test_research_schema.py`
- Create: `tests/test_research_derived_store.py`

### Step 1: Write failing schema and store tests

Add tests proving:

- the research schema contains `research_derived_runs` and `research_derived_partitions`;
- `(feature_set, analysis_date, formula_version)` is unique;
- a valid DataFrame is staged, hashed, atomically promoted, and readable;
- a same-input/same-output retry is idempotent and does not rewrite the file;
- a changed input manifest replaces only that formula/date partition;
- a duplicate output entity key is rejected before writing;
- a simulated file-promotion or metadata failure leaves the previous partition readable;
- row count and SHA-256 are persisted.

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_research_schema.py \
  tests/test_research_derived_store.py -q
```

Expected: FAIL because the tables and store do not exist.

### Step 2: Implement the minimum storage layer

In `research_schema.py`:

- increment the schema version;
- add the two new tables and indexes without altering existing fact tables.

In `research_derived.py` implement:

- `DerivedCommitResult`;
- `DerivedFeatureStore.commit(...)`;
- `DerivedFeatureStore.read(...)`;
- `DerivedFeatureStore.partition_manifest(...)`;
- stable DataFrame content hashing;
- stable JSON input-manifest hashing;
- atomic staging/promotion using the existing Parquet helpers;
- feature-set-specific entity-key validation supplied by the caller.

The final path must be:

```text
derived/<feature_set>/analysis_date=<date>/formula_version=<version>/data.parquet
```

Do not register derived output in `research_fact_partitions`; facts and derived results have different contracts.

### Step 3: Run tests and commit

Run the Task 1 test command, then:

```bash
git add src/stock_analyzer/storage/research_schema.py \
  src/stock_analyzer/storage/research_derived.py \
  tests/test_research_schema.py tests/test_research_derived_store.py
git commit -m "feat: add governed derived feature storage"
```

---

## Task 2: Add efficient strict-as-of window queries and exact input manifests

**Files:**

- Modify: `src/stock_analyzer/storage/research_query.py`
- Modify: `src/stock_analyzer/storage/research_warehouse.py`
- Create: `tests/test_research_partition_query.py`

### Step 1: Write failing time-point tests

Tests must prove:

- only requested date partitions are physically read;
- rows with `available_at` after the cutoff are excluded;
- if a later current revision was not known at the cutoff, the correct earlier revision is returned;
- no future partition can enter a historical analysis;
- duplicate business keys across selected inputs fail closed;
- the generated manifest includes dataset, partition, row count, content hash, file hash, and quality status;
- manifest order and hash are deterministic.

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_research_partition_query.py -q
```

Expected: FAIL because the window query and manifest builder do not exist.

### Step 2: Implement the query boundary

Add:

- `ResearchQuery.dataset_partitions_as_of(dataset_id, partition_values, as_of)`;
- `ResearchQuery.input_manifest(dataset_partitions)`;
- a warehouse helper to read a selected list of current Parquet partitions in one DuckDB query.

Reuse the existing revision semantics; do not create a second interpretation of `available_at`.

### Step 3: Run tests and commit

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_research_partition_query.py tests/test_research_as_of.py -q
git add src/stock_analyzer/storage/research_query.py \
  src/stock_analyzer/storage/research_warehouse.py \
  tests/test_research_partition_query.py
git commit -m "feat: query research facts by strict time window"
```

---

## Task 3: Implement market-context observations

**Files:**

- Create: `src/stock_analyzer/analysis/market_context_features.py`
- Create: `tests/test_market_context_features.py`

### Step 1: Write failing formula tests

Use small hand-calculated fixtures to verify:

- 1/3/5/20-day equal-weight return, median return, and breadth;
- index returns for all available broad indexes;
- market turnover and 5/20-day ratios;
- 20/60-day moving-average breadth and new-high/new-low shares;
- limit-up, near-limit-up, limit-down, and near-limit-down counts based on actual daily limit prices;
- cross-sectional dispersion and 20-day annualized realized volatility;
- fewer than 95% expected current rows returns `limited` rather than silently computing a full-market result;
- no output field claims trader identity or recommends an action.

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_market_context_features.py -q
```

Expected: FAIL because the module does not exist.

### Step 2: Implement `market-context-v1`

Implement a deterministic function that accepts already time-bounded frames and returns exactly one market row. Use `NaN` for an unavailable horizon, never zero-fill missing history. Store the formula version in output.

### Step 3: Run tests and commit

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_market_context_features.py -q
git add src/stock_analyzer/analysis/market_context_features.py \
  tests/test_market_context_features.py
git commit -m "feat: compute market context observations"
```

---

## Task 4: Implement stock trading-context observations

**Files:**

- Create: `src/stock_analyzer/analysis/stock_context_features.py`
- Create: `tests/test_stock_context_features.py`

### Step 1: Write failing formula and boundary tests

Verify with hand-calculated stocks:

- 1/5/10/20/60-day returns and relative broad-index returns;
- 60-day beta, downside-day beta, and correlation;
- annualized 20-day volatility and ATR ratio;
- 60/82-day price location;
- current amount ratio and up-day/down-day amount ratio;
- high-volume up/down counts, median efficiency, minimum efficiency, and minimum date;
- a single extreme low-efficiency day is visible even when the median is normal;
- countertrend-up count and recency-weighted count do not include future dates;
- recent limit hit and post-limit behavior use actual `stock_limit` values;
- PE/PB 250-session and available-five-year percentiles, while non-positive PE is left unavailable;
- short-history stocks retain available short-window values and declare coverage;
- output always contains `trader_identity_status=unavailable` and contains no institutional intent claim.

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_stock_context_features.py -q
```

Expected: FAIL because the module does not exist.

### Step 2: Implement `stock-trading-context-v1`

Use vectorized pandas group operations where practical. Formula definitions must be named helpers and documented in docstrings. Do not add ranking weights or a candidate filter.

Daily efficiency is descriptive only:

- close location: `(close - low) / (high - low)`;
- body efficiency: `abs(close - open) / (high - low)`;
- zero-range days return `NaN`.

### Step 3: Run tests and commit

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_stock_context_features.py -q
git add src/stock_analyzer/analysis/stock_context_features.py \
  tests/test_stock_context_features.py
git commit -m "feat: compute stock trading context observations"
```

---

## Task 5: Replace the incomplete hotspot calculation with full sector evidence

**Files:**

- Rewrite: `src/stock_analyzer/analysis/hotspot_features.py`
- Rewrite/extend: `tests/test_hotspot_features.py`

### Step 1: Expand failing tests to match the approved design

Tests must cover:

- 1/3/5/20-day equal-weight, median, breadth, and relative returns;
- 1/3/5/20-day turnover-share averages plus 3/5-day change;
- current-day member coverage and the 80% usability boundary;
- effective-dated membership for every historical date, including a membership change inside the window;
- limit-up and near-limit-up concentration;
- 20/60-day new-high concentration;
- dispersion and top-three positive contribution;
- high-volume/low-progress, upper-wick reversal, narrow participation, and turnover/return divergence flags;
- official index return and bottom-up discrepancy where an index exists;
- L1/L2/L3 industry and theme identity fields;
- all catalog themes are returned, while no-member themes are `limited_no_membership` with null metrics;
- minute path metrics when minute data exists;
- daily results remain usable and minute fields remain null with `intraday_status=limited` when minute data is absent;
- duplicate fact input fails before any calculation;
- no output claims institution, main force, accumulation, distribution, or manipulation.

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_hotspot_features.py -q
```

Expected: FAIL for every currently missing behavior.

### Step 2: Implement `sector-hotspot-v2`

Keep the module decision-free. Expose observable fields and evidence flags, not a composite “hot score.” Replace `hotspot-v1` only for current production; keep the old version reproducible through its already committed code history, not by emitting both formulas in one current partition.

### Step 3: Run tests and commit

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_hotspot_features.py -q
git add src/stock_analyzer/analysis/hotspot_features.py tests/test_hotspot_features.py
git commit -m "feat: compute complete sector hotspot evidence"
```

---

## Task 6: Build one feature job that reads facts and commits all three outputs

**Files:**

- Create: `src/stock_analyzer/ops/research_features.py`
- Create: `tests/test_research_feature_job.py`

### Step 1: Write failing orchestration tests

Test that the job:

- obtains open-session windows from the fact calendar;
- reads all inputs through strict-as-of query methods;
- reads 82 sessions for price observations, 250 for market/valuation context, and longer history only for the explicit five-year valuation percentile;
- reads industry/theme catalogs and effective memberships;
- treats missing minute facts as a declared limitation, not a failure;
- commits market, sector, and stock outputs with exact formula versions and entity keys;
- writes exact input manifests and a run summary;
- is idempotent when inputs are unchanged;
- recomputes only changed partitions after an upstream revision;
- does not call any API client;
- leaves already committed outputs intact if a later feature set fails.

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_research_feature_job.py -q
```

Expected: FAIL because the feature job does not exist.

### Step 2: Implement the feature job

Create:

- `DerivedFeatureSummary` with plain-language counts and limitations;
- `run_research_features(warehouse, analysis_date, as_of=None)`;
- exact input builders for the three feature sets;
- independent commit boundaries so one failed set cannot corrupt another completed set;
- stable run/idempotency keys.

The default cutoff is 23:59:59 Asia/Shanghai on the analysis date. It may include only facts whose own `available_at` was no later than that cutoff.

### Step 3: Run tests and commit

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_research_feature_job.py \
  tests/test_research_partition_query.py -q
git add src/stock_analyzer/ops/research_features.py tests/test_research_feature_job.py
git commit -m "feat: orchestrate daily derived research features"
```

---

## Task 7: Add the manual derive command and integrate existing daily stages

**Files:**

- Modify: `src/stock_analyzer/cli.py`
- Modify: `src/stock_analyzer/ops/research_data_job.py`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_research_data_job.py`
- Modify: `tests/test_research_data_launchd.py`

### Step 1: Write failing command and schedule-flow tests

Test that:

- `data derive --data-date YYYY-MM-DD` runs without constructing API clients;
- evening derives only after event/classification/fundamental fact commits finish;
- next-morning derives after gap repair, late events, margin/minute attempts, and gap reconciliation;
- close does not create a partial sector partition;
- a feature failure makes the data stage visibly fail instead of printing success;
- launchd still invokes only the three fixed data-only stage commands;
- no report, render, activate, deploy, publish, Supabase, or Cloudflare command enters the data schedule.

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_cli.py tests/test_research_data_job.py \
  tests/test_research_data_launchd.py -q
```

Expected: FAIL before the command and integration exist.

### Step 2: Implement integration

- Add the no-network `data derive` command.
- Call `run_research_features` at the end of evening and next-morning stages.
- Keep the three existing launchd files and times unchanged.
- Print a short business-readable derived summary after each relevant stage.

### Step 3: Run tests and commit

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_cli.py tests/test_research_data_job.py \
  tests/test_research_data_launchd.py -q
git add src/stock_analyzer/cli.py src/stock_analyzer/ops/research_data_job.py \
  tests/test_cli.py tests/test_research_data_job.py \
  tests/test_research_data_launchd.py
git commit -m "feat: automate derived research feature refresh"
```

---

## Task 8: Extend health checks and operations documentation

**Files:**

- Modify: `src/stock_analyzer/ops/research_health.py`
- Modify: `tests/test_research_health.py`
- Modify: `docs/operations/runbook.md`
- Modify: `docs/operations/production-capability-matrix.md`

### Step 1: Write failing health tests

Tests must verify:

- latest expected trading date has all three derived feature sets;
- missing file, row-count mismatch, file-hash mismatch, stale formula, failed run, and stale input manifest are reported;
- `complete_with_declared_gaps` is not misreported as fully complete;
- the human-readable Markdown explains no-membership themes and minute limitation in plain language;
- core fact completeness remains a separate field and keeps its current semantics.

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_research_health.py -q
```

Expected: FAIL because health currently audits facts only.

### Step 2: Implement and document

Add derived health models and file audits. Update the runbook to state that 21:30 creates the daily research observations and 08:00 recomputes only when repaired facts change. Update the capability matrix with separate evidence for “program exists,” “real data landed,” and “automatic execution installed.”

### Step 3: Run tests and commit

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_research_health.py tests/test_config_health.py -q
git add src/stock_analyzer/ops/research_health.py tests/test_research_health.py \
  docs/operations/runbook.md docs/operations/production-capability-matrix.md
git commit -m "feat: audit derived research data health"
```

---

## Task 9: Produce and verify the real 2026-07-13 derived snapshot

**Files/data written:**

- `local_warehouse/derived/market_context/analysis_date=2026-07-13/...`
- `local_warehouse/derived/sector_hotspot/analysis_date=2026-07-13/...`
- `local_warehouse/derived/stock_trading_context/analysis_date=2026-07-13/...`
- `local_archive/data_health/2026-07-13.json`
- `local_archive/data_health/2026-07-13.md`

These runtime artifacts are local data and may be gitignored; do not add large Parquet files to Git.

### Step 1: Run the no-network real calculation

```bash
PYTHONPATH=src .venv/bin/python -m stock_analyzer data derive \
  --data-date 2026-07-13
```

### Step 2: Verify real row counts and limitations

Use read-only DuckDB/PyArrow checks to prove:

- one market row exists;
- sector rows cover all published industry catalog rows plus all 272 themes;
- exactly 43 current themes are visibly limited for absent public membership, unless the fact source has changed and the new count is explained;
- stock rows match the actual eligible current equity coverage, with short-history coverage explicit;
- there are zero duplicate entity keys;
- stored row counts and SHA-256 values match files;
- minute fields are null and `intraday_status=limited` while minute facts are absent;
- all three input manifests reference only facts available by the 2026-07-13 cutoff.

### Step 3: Re-run to prove idempotency

Run the same derive command again. Verify that all three content hashes and file modification times remain unchanged and the run summary reports skips.

### Step 4: Generate a fresh health report

Use the existing health command or direct health builder to rewrite the 2026-07-13 JSON and Markdown, then inspect the Markdown for business-readable wording.

Do not commit local data artifacts.

---

## Task 10: Full verification, operational confirmation, and review

**Files:** all files changed by Tasks 1-8.

### Step 1: Run targeted tests

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_research_schema.py \
  tests/test_research_derived_store.py \
  tests/test_research_partition_query.py \
  tests/test_market_context_features.py \
  tests/test_stock_context_features.py \
  tests/test_hotspot_features.py \
  tests/test_research_feature_job.py \
  tests/test_research_data_job.py \
  tests/test_research_data_launchd.py \
  tests/test_research_health.py -q
```

### Step 2: Run the complete suite

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q
```

Expected: all tests pass; only the existing explicitly documented skip may remain.

### Step 3: Run static repository checks

```bash
git diff --check
rg -n "institution|main force|accumulation|distribution|manipulation|\u673a\u6784\u6b63\u5728|\u4e3b\u529b\u6b63\u5728|\u5438\u7b79|\u51fa\u8d27" \
  src/stock_analyzer/analysis/market_context_features.py \
  src/stock_analyzer/analysis/hotspot_features.py \
  src/stock_analyzer/analysis/stock_context_features.py
rg -n "render|report|activate|deploy|publish|Supabase|Cloudflare" \
  src/stock_analyzer/ops/research_data_job.py \
  src/stock_analyzer/ops/research_features.py \
  ops/launchd/com.ccrt.stock-analysis-assistant.research-data-*.plist.example
```

The first search may find only explicit prohibition text. The second must not find an executable report/publication path.

### Step 4: Confirm installed automatic jobs

Read each installed service:

```bash
launchctl print gui/501/com.ccrt.stock-analysis-assistant.research-data-close
launchctl print gui/501/com.ccrt.stock-analysis-assistant.research-data-evening
launchctl print gui/501/com.ccrt.stock-analysis-assistant.research-data-next-morning
```

Verify working directory, command, fixed stage, and schedule. Do not trigger external data acquisition merely to prove installation.

### Step 5: Request code review and address findings

Use the `superpowers:requesting-code-review` checklist against the design and this plan. Fix any correctness, time-point, atomicity, automation, or expression-boundary issue, rerun the relevant tests, then rerun the full suite.

### Step 6: Final commit if review fixes exist

```bash
git add <only reviewed source/test/docs files>
git commit -m "fix: complete derived research feature acceptance"
```

### Step 7: Final handoff content

Report in plain Chinese:

- what the old Superpowers design already covered;
- what the previous implementation missed;
- which three computed data products now exist;
- actual 2026-07-13 row counts and declared limitations;
- whether all three daily jobs will calculate and land them automatically;
- exact tests and health evidence;
- what remains unavailable because the source/permission truly does not exist.

Do not describe the task as complete until real files, metadata, health checks, complete tests, and installed-job inspection all pass.

---

## Plan self-check

- Every design acceptance criterion maps to at least one test or real-data check.
- Storage, strict-as-of input, formulas, orchestration, automation, health, and real landing are separate steps; no single oversized “implement features” step can silently omit governance.
- Tests precede implementation in every behavior-changing task.
- The plan does not depend on AKShare, BaoStock, Level 2, or unavailable minute permission.
- The plan keeps the 43 no-membership themes visible without inventing constituents.
- The plan uses the five-year compact base only for valuation percentiles, not for daily full recomputation.
- The plan does not revive old Phase 3 reports or choose five stocks.
- Automatic execution is verified at both code-flow and installed-service levels.
