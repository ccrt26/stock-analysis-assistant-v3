# V3 Local Knowledge Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` task-by-task. The user selected inline execution and does not authorize subagents unless they later say otherwise. Every behavior change requires `superpowers:test-driven-development`; completion requires `superpowers:verification-before-completion`.

**Goal:** Complete reproducible point-in-time A-share validation for the nine existing empirical method families and attach final results to all thirteen legacy `revalidate` records without changing the data foundation or production analysis.

**Architecture:** Add an isolated `stock_analyzer.knowledge_validation` package. It reads existing facts only through `ResearchQuery`, loads immutable YAML study specifications, constructs historical point-in-time samples, evaluates three independent result layers, and writes only ignored local panels plus version-controlled summaries. Production analysis, reports, jobs and deployment never import this package.

**Tech Stack:** Python 3.11+, Pydantic 2.7+, PyYAML 6+, NumPy 1.26+, pandas 2.2+, existing DuckDB/Parquet warehouse, pytest 8+; no new dependency.

**Approved Design:** [`docs/superpowers/specs/2026-07-15-v3-local-validation-and-knowledge-expansion-design.md`](../specs/2026-07-15-v3-local-validation-and-knowledge-expansion-design.md)

**Approved Baseline:** local `main` commit `774b14e`.

## Global Constraints

- Work directly on local `main`; do not create a branch or worktree.
- Do not reuse abandoned first/second designs, old Phase 3 scoring, discarded report worktrees or old recommendation conclusions.
- Do not modify `src/stock_analyzer/data/`, `src/stock_analyzer/storage/`, `src/stock_analyzer/analysis/`, `src/stock_analyzer/ops/`, `src/stock_analyzer/reports/`, `ops/`, `supabase/`, `functions/` or `local_warehouse/`.
- Do not add dependencies, data sources, tables, fact partitions, derived formulas, crawlers, schedules, scores, rankings, recommendations, positions, reports, activation, deployment or trades.
- Read warehouse facts through `ResearchQuery.materialize_snapshot(...)` with Shanghai close converted by existing code; never use an unbounded current record.
- Evaluation horizons are exactly 10, 20 and 30 sessions; 20 is the center checkpoint.
- The intraday 20% target is Layer 3 only and cannot determine theory validity.
- Future comparable price is `future_raw_price * future_adj_factor / analysis_day_adj_factor`.
- Stock-day rows are not independent. Aggregate price studies by date, event studies by company/event date, and financial studies by company/report period.
- Nine primary hypotheses use Benjamini-Hochberg FDR at `q=0.05`.
- Moving-block bootstrap uses seed `20260715`, `2_000` repetitions and 30-session blocks.
- Large panels belong only under ignored `local_archive/knowledge_validation/`; summary YAML and acceptance evidence are versioned.
- A negative or insufficient result is valid. Never relax a rule to obtain a positive result.

## File Responsibility Map

| File | Responsibility |
|---|---|
| `src/stock_analyzer/knowledge_validation/models.py` | Frozen specs, statuses, metrics, results and hashes |
| `src/stock_analyzer/knowledge_validation/spec_registry.py` | Strict YAML loader and exact nine-study floor |
| `src/stock_analyzer/knowledge_validation/studies.yaml` | Nine frozen hypotheses and sufficiency rules |
| `src/stock_analyzer/knowledge_validation/samples.py` | As-of universe, sessions, adjusted paths, event and financial samples |
| `src/stock_analyzer/knowledge_validation/signals.py` | Exact signals for nine studies; no scoring |
| `src/stock_analyzer/knowledge_validation/statistics.py` | Date aggregation, bootstrap, BH and three-layer statuses |
| `src/stock_analyzer/knowledge_validation/runner.py` | Run studies and persist deterministic summaries |
| `src/stock_analyzer/knowledge_validation/__init__.py` | Validation-only exports |
| `src/stock_analyzer/knowledge_validation/__main__.py` | Module CLI |
| `src/stock_analyzer/knowledge/validation_results.yaml` | Immutable nine-study summaries |
| `src/stock_analyzer/knowledge/strategy_v2_migration.yaml` | Thirteen result references; actions unchanged |
| `src/stock_analyzer/knowledge/research_registry.yaml` | Validation references; effects not auto-upgraded |
| `tests/test_knowledge_validation_models.py` | Contracts and spec registry |
| `tests/test_knowledge_validation_samples.py` | As-of, adjustment, sessions and leakage |
| `tests/test_knowledge_validation_signals.py` | Nine formulas and wording boundaries |
| `tests/test_knowledge_validation_statistics.py` | Bootstrap, BH and layer independence |
| `tests/test_knowledge_validation_runner.py` | Determinism and output boundary |
| `tests/test_knowledge_validation_acceptance.py` | Results, migration, warehouse and isolation |
| `docs/operations/v3-local-knowledge-validation-acceptance.md` | Reproduction evidence and scientific review |

## Frozen Interfaces

```python
load_validation_registry(path: Path) -> ValidationRegistry
build_study_sample(spec: ValidationSpec, query: ResearchQuery) -> StudySample
compute_study_signal(spec: ValidationSpec, sample: StudySample) -> pd.DataFrame
evaluate_study(spec: ValidationSpec, panel: pd.DataFrame) -> ValidationResult
run_validation_studies(study_ids: tuple[str, ...], warehouse_root: Path, output_root: Path) -> ValidationRun
write_validation_results(path: Path, run: ValidationRun) -> None
```

```python
STUDY_IDS = (
    "a_share_size_value",
    "a_share_momentum_reversal",
    "price_limit_t_plus_one",
    "a_share_factor_industry_momentum",
    "overseas_industry_momentum_method",
    "daily_event_study",
    "a_share_earnings_announcement_drift",
    "formal_announcement_price_reaction",
    "financial_quality_turnaround",
)
```

## Frozen Scientific Rules

- Sort eligible dates; first 70% is development, last 30% confirmation. Persist the split before outcomes are evaluated.
- Price studies require 720 sessions overall, 180 confirmation sessions and 24 non-overlapping 30-session blocks.
- Industry studies require 480 overall, 120 confirmation and 16 blocks. Current coverage may be insufficient; do not lower the rule.
- General event studies require 120 non-overlapping company events, 60 companies, four quarters and 40 confirmation events.
- Earnings-event studies require 80 events, 40 companies, four quarters and 30 confirmation events.
- Financial studies require eight report periods, two year-over-year comparisons, 200 companies overall and 60 confirmation companies.
- “No event” means no matching local formal announcement; never write “no public news.”

| Study | Fixed signal | Primary Layer-1 statistic |
|---|---|---|
| `a_share_size_value` | Positive E/P ranked within date and cap tercile; smallest 30% separate | Date-level top-minus-bottom E/P quintile 20-session market-excess close return |
| `a_share_momentum_reversal` | Prior adjusted 20-session return quintile | Bottom-minus-top 5-session market-excess close return; 10/20/30 secondary |
| `price_limit_t_plus_one` | Actual `high >= up_limit` and close-at-limit flags | Next-session return versus same-date non-touch stocks matched by cap tercile and prior-20-session return quintile |
| `a_share_factor_industry_momentum` | Industry 20-session relative-return quintile with breadth/concentration conditions | Top-minus-bottom industry quintile 20-session relative return |
| `overseas_industry_momentum_method` | Individual and industry prior-20-session returns | Reduction of individual spread after industry subtraction |
| `daily_event_study` | Official timestamp, `[0,+1]` market-adjusted CAR and pseudo-events | TOST equivalence of pseudo-event mean CAR inside ±0.25%, plus empirical 95% interval coverage between 92% and 98%; calibration only |
| `a_share_earnings_announcement_drift` | Forecast/express/report event CAR quintile | Top-minus-bottom CAR quintile 20-session post-event excess return |
| `formal_announcement_price_reaction` | Extreme market-adjusted day matched by date/size/move, announcement flag | 20-session difference between announced and locally unmatched shocks |
| `financial_quality_turnaround` | Count: ROE up, OCF up, leverage down, current ratio up, margin up, turnover up | Report-period Spearman correlation with subsequent 20-session excess return |

Layer 2 always reports 10/20/30 close, market-relative and available industry-relative return, favorable/adverse excursion, positive rate, rank gradient and first-hit order. Layer 3 always reports 10/20/30 20%-touch rate, same-date baseline lift, first touch, pre-touch drawdown and no-touch distribution. Layers never overwrite each other. The event-calibration study contributes its TOST p-value to the same nine-hypothesis BH correction; failure to reject a zero-effect null is never treated as proof of calibration.

---

### Task 1: Baseline and contracts

**Files:** Create `models.py`, `__init__.py`, model tests.

- [ ] Capture baseline:

```bash
git status --short
git rev-parse HEAD
shasum -a 256 local_warehouse/research.duckdb > /private/tmp/v3-local-validation.before.sha256
PYTHONPATH=src .venv/bin/python -m pytest tests/test_research_as_of.py tests/test_knowledge_registry.py tests/test_knowledge_migration.py -q
```

- [ ] Write failing tests for exact horizons, frozen/extra-forbid models, blank IDs, separate layers, and confirmation required for positive method status:

```python
def test_positive_method_status_requires_confirmation():
    payload = valid_result(method_status="validated_general", confirmation=None)
    with pytest.raises(ValidationError, match="confirmation"):
        ValidationResult.model_validate(payload)
```

- [ ] Implement `MethodStatus` (`validated_general`, `validated_conditional`, `not_validated`, `insufficient_sample`, `execution_failed`), `RelevanceStatus` (`strong_support`, `weak_support`, `neutral`, `adverse`, `insufficient_sample`) and frozen spec/result models. Runtime and manual review are excluded from computed result hash.
- [ ] Run `PYTHONPATH=src .venv/bin/python -m pytest tests/test_knowledge_validation_models.py -q`; expected PASS.
- [ ] Commit:

```bash
git add src/stock_analyzer/knowledge_validation/models.py src/stock_analyzer/knowledge_validation/__init__.py tests/test_knowledge_validation_models.py
git commit -m "feat: add local knowledge validation contracts"
```

### Task 2: Freeze nine YAML studies

**Files:** Create `spec_registry.py`, `studies.yaml`; modify model tests.

- [ ] Write failing tests asserting exact ordered `STUDY_IDS`, exactly thirteen unique migration IDs, unique knowledge IDs, valid `ResearchDatasetId` values and no score/weight/buy field.
- [ ] Implement strict loader, canonical registry hash and complete YAML with every number and primary definition above.
- [ ] Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_knowledge_validation_models.py -q
rg -n "score|weight|buy|recommend" src/stock_analyzer/knowledge_validation/studies.yaml
```

Expected: tests PASS; `rg` has no prohibited field.
- [ ] Commit with only registry, YAML and tests:

```bash
git add src/stock_analyzer/knowledge_validation/spec_registry.py src/stock_analyzer/knowledge_validation/studies.yaml tests/test_knowledge_validation_models.py
git commit -m "data: freeze nine local validation studies"
```

### Task 3: Leakage-safe samples and labels

**Files:** Create `samples.py`, sample tests.

- [ ] Write failing tests:

```python
def test_adjusted_future_price_uses_both_factors():
    assert adjusted_future_price(55, future_factor=2, base_factor=1) == 110

def test_high_can_touch_without_close_earning_target():
    labels = label_path(base_close=100, future_high=[121], future_close=[109])
    assert labels["touch_20pct_10d"] is True
    assert labels["close_return_10d"] == pytest.approx(0.09)
```

Also cover revision after as-of, listing/delisting, suspension, missing close, exact next-session counts, missing future horizon and future labels excluded from signal inputs.
- [ ] Implement `adjusted_future_price`; reject nonpositive factors. Every study date calls `materialize_snapshot` only for requested partitions at close-time `as_of`; persist input-manifest hash. Future paths are stored separately from signal inputs.
- [ ] Run sample tests plus `tests/test_research_as_of.py`; check baseline SHA-256; expected PASS/OK.
- [ ] Commit `feat: build point-in-time validation samples`.

### Task 4: Exact nine signals

**Files:** Create `signals.py`, signal tests.

- [ ] Write one failing formula test per study, including:

```python
def test_ep_only_for_positive_pe():
    out = size_value_signal(pd.DataFrame({"pe_ttm": [10.0, -5.0, np.nan]}))
    assert out.loc[0, "signal_value"] == pytest.approx(0.1)
    assert out.loc[1:, "signal_value"].isna().all()

def test_limit_touch_uses_high_and_up_limit():
    out = limit_signal(pd.DataFrame({"high": [10.0], "close": [9.8], "up_limit": [10.0]}))
    assert out.loc[0, "limit_touched"] and not out.loc[0, "closed_at_limit"]
```

- [ ] Event tests map after-close announcements to next session, de-duplicate same-company events within 30 sessions by earliest event and emit only `no_local_formal_announcement_match`.
- [ ] Implement closed dispatch for nine IDs. Quintiles use per-date ranks and `ts_code` tie-break; size-value first uses cap terciles. Breadth/concentration are conditions, not weights. Financial count uses exactly six directions above and never creates `f_score`.
- [ ] Reject input columns starting `future_` or containing `touch_20pct`; emit no trader identity/intent wording.
- [ ] Run signal tests; expected PASS; commit `feat: implement nine frozen validation signals`.

### Task 5: Statistics and layer independence

**Files:** Create `statistics.py`, statistics tests.

- [ ] Write failing tests for deterministic block bootstrap, hand-calculated BH on nine p-values, insufficient sample, confirmation reversal, conditional stability, duplicated stock rows not changing date aggregate, and:

```python
def test_target_success_cannot_upgrade_failed_method():
    result = classify_layers(method_supported=False, trend_supported=False, target_supported=True)
    assert result.method.status == "not_validated"
    assert result.target.status == "strong_support"
```

- [ ] Implement NumPy/pandas moving-block bootstrap and BH. Exact method rules:

```python
general = sufficient and direction_ok and confirmation_direction_ok and q_value <= 0.05 and stable_blocks_ratio >= 0.75
conditional = sufficient and not general and predeclared_condition_only and conditional_q <= 0.05 and conditional_stable_blocks_ratio >= 0.75
```

Insufficient data gives `insufficient_sample`; otherwise failure of both gives `not_validated`. A q-value alone never passes.
- [ ] Run statistics tests; expected PASS; commit `feat: add robust local validation statistics`.

### Task 6: Deterministic runner

**Files:** Create `runner.py`, `__main__.py`, runner tests; modify `.gitignore`.

- [ ] Write failing tests that identical inputs/spec/code yield identical hash, exceptions stay `execution_failed`, and output under `local_warehouse` is rejected.
- [ ] Implement fixed CLI:

```bash
PYTHONPATH=src .venv/bin/python -m stock_analyzer.knowledge_validation \
  --warehouse-root local_warehouse \
  --spec src/stock_analyzer/knowledge_validation/studies.yaml \
  --results src/stock_analyzer/knowledge/validation_results.yaml \
  --panel-root local_archive/knowledge_validation
```

- [ ] Persist commit, spec/input hashes, exclusions, three layers, `manual_review: pending_review` and canonical result hash. Sort all content; exclude runtime from canonical output. Add exactly `/local_archive/knowledge_validation/` to `.gitignore`.
- [ ] Run runner tests; expected PASS; commit `feat: add deterministic knowledge validation runner`.

### Task 7: Execute and scientifically review

**Files:** Create results YAML and acceptance document.

- [ ] Require clean diff and all new unit tests passing before first real run.
- [ ] Run fixed CLI twice; compare first copy in `/private/tmp` using `cmp`. Expected byte-identical output.
- [ ] For every study document overall/confirmation counts; independent dates/events/periods; estimate, interval, raw p, BH q and stable-block ratio; Layer 2/3 metrics; opposite evidence; limitations; three statuses.
- [ ] Do not change a spec, formula, exclusion or threshold after viewing results. Edit only separate `manual_review` text and manual-review hash.
- [ ] Commit results and acceptance document as `data: record local knowledge validation results`.

### Task 8: Reconcile migrations and active methods

**Files:** Modify governance model, migration YAML, registry and existing tests; create acceptance test.

- [ ] Write failing tests:

```python
def test_thirteen_revalidate_records_have_final_references():
    rows = [r for r in load_legacy_migration(PATH).entries if r.action.value == "revalidate"]
    assert len(rows) == 13
    assert all(r.validation_reference in RESULT_REFERENCES for r in rows)
```

- [ ] Add `validation_reference: str | None = None` to `LegacyMigrationRecord`; require a final reference for all real `revalidate` rows. Link thirteen rows to nine results.
- [ ] Set active entries’ `local_validation.validation_reference`. Change status to `validated` only for `validated_general`/`validated_conditional`; never change `effect` in this plan.
- [ ] Acceptance asserts nine results, no `execution_failed`, warehouse hash unchanged and no production import. `insufficient_sample` is acceptable.
- [ ] Run migration/registry/acceptance tests; commit `data: reconcile validated knowledge migrations`.

### Task 9: Final verification

- [ ] Run targeted suite:

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_knowledge_validation_models.py tests/test_knowledge_validation_samples.py \
  tests/test_knowledge_validation_signals.py tests/test_knowledge_validation_statistics.py \
  tests/test_knowledge_validation_runner.py tests/test_knowledge_validation_acceptance.py \
  tests/test_knowledge_governance_acceptance.py tests/test_knowledge_migration.py \
  tests/test_knowledge_registry.py -q
```

- [ ] Run full suite, warehouse checksum, changed-path audit and production-import search:

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q
shasum -a 256 -c /private/tmp/v3-local-validation.before.sha256
git diff --name-only 774b14e..HEAD
rg -n "knowledge_validation" src/stock_analyzer/analysis src/stock_analyzer/ops src/stock_analyzer/reports ops || true
```

- [ ] Acceptance evidence records pass counts, commit, before/after hashes, nine statuses, thirteen mappings, limitations and: “本阶段仅完成本地研究验证，未接入评分、推荐、报告、自动任务或生产。”
- [ ] Commit `docs: verify local knowledge validation`.

## Stop Conditions

Stop if warehouse hash changes; as-of cannot prevent leakage; adjustment conflicts with corporate actions; historical listing status materially fails; a spec changes after results; deterministic rerun differs; a study remains `execution_failed`; a new dataset/formula is required; or production import is needed.

The second plan may begin only after Task 9 passes and the user accepts the validation evidence.
