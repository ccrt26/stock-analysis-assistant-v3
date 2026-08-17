# Selection Lab and Opportunity Types Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a point-in-time-safe, track-aware selection laboratory that truthfully reports the currently unavailable candidate-chain experiment while providing reusable labeling, ranking, auditing, and review-bundle tooling.

**Architecture:** Keep formation-date inputs physically separate from future labels and gate every label phase with deterministic manifests. Treat `frozen_candidate_chain` as the only business-answer track, keep `deterministic_research_surface` explicitly exploratory, and fail closed when historical identity or candidate records are unavailable.

**Tech Stack:** Python 3.11+, pandas, NumPy, DuckDB/PyArrow, Pydantic, Typer, optional scikit-learn 1.5–1.x, pytest.

## Global Constraints

- Base commit: `ad7d1385dbeb1c91771af66a3294da74b857c2b0`.
- Work only on `feat/selection-lab-opportunity-types`; never merge to `main`.
- Do not touch or stage `bingo/` or `who-is-it/`.
- Only facts with `available_at <= formation_as_of` may enter formation features or opportunity types.
- Main track is `frozen_candidate_chain`; no machine candidate chain means main conclusion `实验阻塞`.
- Never reconstruct candidate chains from reports or backfill historical identity from current values.
- Future labels, action-day executability, AI fate, stock code, input order, research-text size, and evidence counts are forbidden model inputs.
- Final-test labels stay closed until split, feature dictionary, model variant, C, and threshold manifests are frozen.
- No fixed investment score, Gate, quota, position sizing, trading, cloud publication, Supabase, Cloudflare, or legacy V3 restoration.
- Local full datasets, predictions, and models remain under ignored `local_*\/selection_lab/` paths.

---

### Task 1: Freeze preregistration artifacts and core schemas

**Files:**
- Create: `docs/selection_lab/review/previously_used_formation_dates.json`
- Create: `docs/selection_lab/review/feature_dictionary.json`
- Create: `docs/selection_lab/review/split_manifest.json`
- Create: `src/stock_analyzer/selection_lab/__init__.py`
- Create: `src/stock_analyzer/selection_lab/schemas.py`
- Create: `src/stock_analyzer/selection_lab/temporal_split.py`
- Create: `tests/selection_lab/test_schemas.py`
- Create: `tests/selection_lab/test_temporal_split.py`

**Interfaces:**
- Produces `ResearchTrack`, `EligibilityStatus`, `CandidateStatus`, `OpportunityType`, `CapabilityStatus`, `LabelRevealState` enums.
- Produces `SplitDefinition`, `CapabilityResult`, `FormationSample`, `FutureLabels` Pydantic models.
- Produces `build_split_manifest(calendar, definitions) -> dict[str, object]` and `assert_non_overlapping_label_windows(manifest) -> None`.

- [ ] **Step 1: Write failing enum and schema tests**

```python
def test_surface_sample_cannot_claim_eligible():
    with pytest.raises(ValueError, match="unknown_identity_history"):
        FormationSample(
            research_track="deterministic_research_surface",
            eligibility_status="eligible",
            formation_date=date(2026, 1, 5),
            formation_as_of="2026-01-05T23:59:59+08:00",
            action_date=date(2026, 1, 6),
            ts_code="000001.SZ",
            candidate_status="non_candidate",
        )
```

- [ ] **Step 2: Run schema tests and confirm RED**

Run: `.venv/bin/python -m pytest tests/selection_lab/test_schemas.py -q`
Expected: collection fails because `stock_analyzer.selection_lab.schemas` does not exist.

- [ ] **Step 3: Implement minimal models and enum validation**

```python
class ResearchTrack(StrEnum):
    FROZEN_CANDIDATE_CHAIN = "frozen_candidate_chain"
    DETERMINISTIC_RESEARCH_SURFACE = "deterministic_research_surface"
    FULL_UNIVERSE = "full_universe"

class FormationSample(BaseModel):
    research_track: ResearchTrack
    eligibility_status: EligibilityStatus
    formation_date: date
    formation_as_of: AwareDatetime
    action_date: date
    ts_code: str
    candidate_status: CandidateStatus

    @model_validator(mode="after")
    def validate_track_identity(self):
        if self.research_track is ResearchTrack.DETERMINISTIC_RESEARCH_SURFACE:
            if self.eligibility_status is not EligibilityStatus.UNKNOWN_IDENTITY_HISTORY:
                raise ValueError("surface track requires unknown_identity_history")
        return self
```

- [ ] **Step 4: Write failing split-window and exact-date tests**

```python
def test_registered_splits_have_non_overlapping_label_windows(trading_days):
    manifest = build_registered_split_manifest(trading_days)
    assert manifest["development"]["last_label_date"] == "2026-04-01"
    assert manifest["validation"]["first_formation_date"] == "2026-04-02"
    assert manifest["validation"]["last_label_date"] == "2026-05-21"
    assert manifest["final_test"]["first_formation_date"] == "2026-05-26"
    assert manifest["embargo_open_days"] == {
        "development_to_validation": 20,
        "validation_to_final_test": 22,
    }
```

- [ ] **Step 5: Implement trading-day action/label calculations and immutable split constants**

Store the exact 30/10/10 formation dates from the execution prompt. Compute `action_date` as the next open day and `label_end` as the twentieth open day starting with action day. Reject missing calendar days and any overlap.

- [ ] **Step 6: Run focused tests and confirm GREEN**

Run: `.venv/bin/python -m pytest tests/selection_lab/test_schemas.py tests/selection_lab/test_temporal_split.py -q`
Expected: all pass.

- [ ] **Step 7: Generate and validate the three preregistration JSON files**

Use deterministic UTF-8 JSON (`sort_keys=True`, two-space indent, trailing newline). `previously_used_formation_dates.json` records base-commit evidence only; `feature_dictionary.json` expands every wildcard to an exact column; `split_manifest.json` records action/label dates and label-reveal flags all false.

- [ ] **Step 8: Commit preregistration and design**

```bash
git add docs/selection_lab/2026-08-17-selection-lab-and-opportunity-type-execution-prompt.md \
  docs/selection_lab/2026-08-17-selection-lab-design.md \
  docs/selection_lab/review/previously_used_formation_dates.json \
  docs/selection_lab/review/feature_dictionary.json \
  docs/selection_lab/review/split_manifest.json \
  docs/superpowers/plans/2026-08-17-selection-lab-opportunity-types.md \
  src/stock_analyzer/selection_lab/__init__.py \
  src/stock_analyzer/selection_lab/schemas.py \
  src/stock_analyzer/selection_lab/temporal_split.py \
  tests/selection_lab/test_schemas.py \
  tests/selection_lab/test_temporal_split.py
git commit -m "docs: preregister selection lab experiment"
```

### Task 2: Implement labels and opportunity-type contracts

**Files:**
- Create: `src/stock_analyzer/selection_lab/labels.py`
- Create: `src/stock_analyzer/selection_lab/opportunity_types.py`
- Create: `tests/selection_lab/test_labels.py`
- Create: `tests/selection_lab/test_opportunity_types.py`

**Interfaces:**
- Produces `build_future_labels(prices, trading_days, formation_date, benchmark=None) -> FutureLabels`.
- Produces `OpportunityEvidence`, `OpportunityAssignment`, `assign_opportunity_type(evidence) -> OpportunityAssignment`.
- Produces `audit_sole_company_gate(assignment, rejection_reason, blockers) -> bool | None`.

- [ ] **Step 1: Write RED tests for day 3/day 21/close-only/adjustment/executability**

Use small DataFrames with `trade_date`, `open`, `high`, `low`, `close`, `adj_factor`, `suspended`, `limit_up`, and `reliable_quote`. Assert day 3 hit, day 21 false, high-only false, consistent adjusted returns, one-price limit-up non-executable, and incomplete window null.

- [ ] **Step 2: Run label tests and confirm expected failures**

Run: `.venv/bin/python -m pytest tests/selection_lab/test_labels.py -q`
Expected: import failure for missing label module.

- [ ] **Step 3: Implement labels without action-day substitution**

Compute adjusted price as raw price times the row factor relative to the entrance factor. Preserve the original formation ranking; labels never produce replacement candidates.

- [ ] **Step 4: Write RED opportunity-type tests**

```python
def test_company_catalyst_requires_direct_company_fact():
    with pytest.raises(ValueError, match="direct company fact"):
        assign_opportunity_type(OpportunityEvidence(
            proposed_type="company_catalyst",
            direct_company_fact=False,
        ))

def test_price_anomaly_without_catalyst_remains_assignable():
    result = assign_opportunity_type(price_anomaly_evidence(company_catalyst=False))
    assert result.primary_type == "independent_price_anomaly"
```

Also test sector eligibility without a new announcement, future-label key rejection, null assignment without a causal thesis, secondary types, no quotas, and sole-gate null when track is unavailable.

- [ ] **Step 5: Implement strict type assignment and sole-gate audit**

The assignment API accepts only formation-date evidence fields. Explicitly reject `future_labels`, `hit_20pct_close_within_20d`, and action-day fields.

- [ ] **Step 6: Run focused tests and confirm GREEN**

Run: `.venv/bin/python -m pytest tests/selection_lab/test_labels.py tests/selection_lab/test_opportunity_types.py -q`
Expected: all pass.

### Task 3: Build track-aware datasets and feature matrices

**Files:**
- Create: `src/stock_analyzer/selection_lab/feature_builder.py`
- Create: `src/stock_analyzer/selection_lab/dataset_builder.py`
- Create: `src/stock_analyzer/selection_lab/audit.py`
- Create: `tests/selection_lab/test_feature_builder.py`
- Create: `tests/selection_lab/test_dataset_builder.py`
- Create: `tests/selection_lab/test_audit.py`
- Modify: `.gitignore`

**Interfaces:**
- Produces `FeatureSpec`, `load_feature_dictionary(path)`, `build_model_frame(samples, include_opportunity_type)`.
- Produces `SelectionDatasetBuilder(warehouse, output_root, preregistration).preflight() -> DatasetCapabilities`.
- Produces `build_formation_inputs(track, split) -> BuildResult` and `open_labels(split, freeze_manifest) -> BuildResult`.
- Produces `scan_base_commit_formation_dates(repo, base_commit) -> list[DateUse]` and `scan_public_payload(payload) -> list[AuditFinding]`.

- [ ] **Step 1: Write RED tests for forbidden features and exact columns**

Assert rejection of `ts_code`, `current_ai_fate`, `executable_on_action_date`, future labels, unknown feature columns, and any dictionary/model mismatch. Assert the typed model adds opportunity type as the only extra column.

- [ ] **Step 2: Implement dictionary-driven feature matrix construction**

Do not infer columns from DataFrame contents. Preserve the dictionary order and return numeric/categorical names with the frame.

- [ ] **Step 3: Write RED preflight and reveal-gate tests**

Assert current local capability results:

```python
assert capabilities.frozen_candidate_chain.reason_code == "no_frozen_candidate_chain"
assert capabilities.full_universe.reason_code == "point_in_time_security_master_unavailable"
assert capabilities.main_conclusion == "实验阻塞"
```

Assert final labels cannot open without matching frozen hashes.

- [ ] **Step 4: Implement preflight and local artifact layout**

Use existing `ResearchWarehouse`/`ResearchQuery`. Write full artifacts only under ignored paths. Formation input and label output paths must be different and content-addressed.

- [ ] **Step 5: Write RED base-commit date and sensitive-data audit tests**

Test self-generated prompt exclusion, ordinary business-date non-pollution, true formation-date classification, absolute path detection, `.env`/token key detection, and oversized per-stock payload rejection.

- [ ] **Step 6: Implement audits and add ignore rules**

Add `local_models/` plus explicit selection-lab paths without removing existing ignore coverage.

- [ ] **Step 7: Run focused tests and confirm GREEN**

Run: `.venv/bin/python -m pytest tests/selection_lab/test_feature_builder.py tests/selection_lab/test_dataset_builder.py tests/selection_lab/test_audit.py -q`
Expected: all pass.

### Task 4: Implement baselines, ranker, and date-equal evaluation

**Files:**
- Create: `src/stock_analyzer/selection_lab/baselines.py`
- Create: `src/stock_analyzer/selection_lab/ranker.py`
- Create: `src/stock_analyzer/selection_lab/evaluation.py`
- Create: `tests/selection_lab/test_baselines.py`
- Create: `tests/selection_lab/test_ranker.py`
- Create: `tests/selection_lab/test_evaluation.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Produces `rank_random`, `rank_relative_return`, `rank_volume_progress`, `rank_event_freshness`.
- Produces `train_candidate_models(train, validation, feature_specs) -> FrozenRankerDecision`.
- Produces `select_probability_threshold(validation_predictions) -> ThresholdDecision`.
- Produces `evaluate_rankings(predictions, labels, ks=(1,3,5)) -> EvaluationBundle`.

- [ ] **Step 1: Write RED deterministic-baseline tests**

Assert 1,000 random draws are deterministic, ties use the registered SHA key, and stock-code lexical order cannot determine rank.

- [ ] **Step 2: Implement baselines minimally**

Simple rankings consume only the single preregistered field relevant to each baseline and return probability-like scores only when meaningful.

- [ ] **Step 3: Write RED date-equal evaluation tests**

Use one date with 2 rows and one with 20 rows to prove the result is the mean of date metrics, not a pooled row metric. Test `effective_k`, empty date null, policy/executable differences, Top 5 remainder, lift, Brier, and deterministic date bootstrap.

- [ ] **Step 4: Implement evaluation**

Bootstrap dates 10,000 times with seed `20260817`. Return null plus reason when input is unavailable.

- [ ] **Step 5: Write RED ranker and threshold tests**

Assert preprocessing fits only training rows, one-class training is `not_trainable`, Cs use the registered tie rules, typed model differs by one column, typed model needs +2 percentage points and no worse Brier, and threshold coverage/0–5 constraints are exact.

- [ ] **Step 6: Add optional dependency and implement ranker**

Add `selection-lab = ["scikit-learn>=1.5,<2"]`. Import sklearn lazily so data/audit CLI remains usable without the extra.

- [ ] **Step 7: Run focused tests and confirm GREEN**

Run: `.venv/bin/python -m pytest tests/selection_lab/test_baselines.py tests/selection_lab/test_ranker.py tests/selection_lab/test_evaluation.py -q`
Expected: all pass (or ranker tests skip with an explicit optional-dependency reason only if sklearn is genuinely absent).

- [ ] **Step 8: Commit program and tests**

Stage only `src/stock_analyzer/selection_lab/`, `tests/selection_lab/`, `.gitignore`, and `pyproject.toml`, then commit `feat: add isolated selection lab`.

### Task 5: Add CLI and deterministic review-bundle reporting

**Files:**
- Create: `src/stock_analyzer/selection_lab/reporting.py`
- Create: `tests/selection_lab/test_reporting.py`
- Create: `tests/selection_lab/test_cli.py`
- Modify: `src/stock_analyzer/cli.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Produces `build_review_bundle(state, output_dir) -> tuple[Path, ...]`.
- Adds Typer group `selection-lab` and six commands from the execution prompt.

- [ ] **Step 1: Write RED CLI help tests**

Assert the root exposes `data` and `selection-lab`, each of the six subcommands loads, and help never executes a data job.

- [ ] **Step 2: Implement lazy CLI wrappers**

Each command loads implementation modules inside the function, emits one concise status line plus a JSON path, and exits 2 for structured capability/dependency blockers.

- [ ] **Step 3: Write RED review-bundle tests**

Assert all eleven files exist, unavailable metrics are null with reason codes, rank examples are empty when main track is unavailable, output is byte-identical across runs, and the public-payload audit passes.

- [ ] **Step 4: Implement deterministic reporting**

Use one JSON writer with sorted keys, UTF-8, indent 2, and newline. Never serialize `Path.resolve()` or raw local input records.

- [ ] **Step 5: Run CLI/report tests and confirm GREEN**

Run: `.venv/bin/python -m pytest tests/selection_lab/test_reporting.py tests/selection_lab/test_cli.py tests/test_cli.py -q`
Expected: all pass.

### Task 6: Amend the four Skill contracts and architecture

**Files:**
- Modify: `.agents/skills/orchestrating-stock-research/SKILL.md`
- Modify: `.agents/skills/researching-sectors-industries/SKILL.md`
- Modify: `.agents/skills/researching-company-events/SKILL.md`
- Modify: `.agents/skills/analyzing-price-trading/SKILL.md`
- Modify: `docs/architecture/current-v3-architecture.md`
- Modify: `README.md`
- Create: `tests/selection_lab/test_skill_contracts.py`

**Interfaces:**
- Adds opportunity-type fields to orchestrator candidate ledger and selected output.
- Adds type-specific evidence responsibilities without scores, quotas, or Gates.

- [ ] **Step 1: Write RED contract tests against current Skill text/YAML frontmatter**

Assert all four required files mention the exact three enum values, the orchestrator output fields, no-company-event allowance for the latter two types, and the “not a score/quota/Gate” boundary.

- [ ] **Step 2: Run contract tests and confirm RED**

Run: `.venv/bin/python -m pytest tests/selection_lab/test_skill_contracts.py -q`
Expected: failures identifying missing opportunity-type contract text.

- [ ] **Step 3: Apply minimal semantic edits**

Do not change the market Skill. Do not add selection thresholds or claim performance improvement. Update architecture/README to describe the isolated lab and current main-track blocker, while retaining “no automated selector” status.

- [ ] **Step 4: Run Skill and documentation tests**

Run: `.venv/bin/python -m pytest tests/selection_lab/test_skill_contracts.py tests/test_cli.py tests/test_knowledge_governance_acceptance.py -q`
Expected: all pass.

- [ ] **Step 5: Commit semantic contract changes**

Stage only the four Skill files, architecture, README, and contract test; commit `docs: define opportunity-type research contracts`.

### Task 7: Generate the blocked experiment report and public review bundle

**Files:**
- Create: `docs/selection_lab/2026-08-17-selection-lab-and-opportunity-type-report.md`
- Create: `docs/selection_lab/review/README.md`
- Create/update: the eleven review JSON files required by the execution prompt

**Interfaces:**
- Consumes the preregistration manifests, capability audit, test outputs, Git metadata, and any explicitly available aggregate evaluation.
- Produces a main conclusion `实验阻塞`, Gate `not_evaluable`, and opportunity-type result `not_evaluable` unless a genuine frozen machine candidate chain is found.

- [ ] **Step 1: Run the six CLI workflows in allowed order**

Run help first, then build formation inputs, audit opportunity types, evaluate available baselines, train only if a trainable track exists, walk-forward only if legal, and build the review bundle. Record exact exit codes; capability exit 2 is an expected experiment result, not a test failure.

- [ ] **Step 2: Write the report with null metrics and precise blockers**

Answer all fifteen report questions. Separate implemented tooling, verified contracts, unavailable main-track evidence, and exploratory secondary output.

- [ ] **Step 3: Run public-payload and sensitive-data audits**

Assert no absolute home path, `.env`, token-shaped key, local facts, full predictions, or model binary is staged.

- [ ] **Step 4: Commit report and review bundle**

Stage only the report and review directory; commit `docs: publish selection lab review bundle`.

### Task 8: Fresh verification, scope review, and draft PR

**Files:**
- Update: `docs/selection_lab/review/verification.json`

- [ ] **Step 1: Run all focused and full checks fresh**

```bash
.venv/bin/python -m pytest tests/selection_lab -q
.venv/bin/python -m pytest -q
.venv/bin/python -m stock_analyzer selection-lab --help
.venv/bin/python -m stock_analyzer selection-lab build-dataset --help
.venv/bin/python -m stock_analyzer selection-lab audit-opportunity-types --help
.venv/bin/python -m stock_analyzer selection-lab evaluate-baselines --help
.venv/bin/python -m stock_analyzer selection-lab train-ranker --help
.venv/bin/python -m stock_analyzer selection-lab walk-forward --help
.venv/bin/python -m stock_analyzer selection-lab build-review-bundle --help
git diff --check
```

- [ ] **Step 2: Verify repeatability and Git boundary**

Build the review bundle twice and compare hashes. Inspect `git status --short`, `git diff --cached --stat`, staged paths, and staged blob sizes. Confirm `bingo/`, `who-is-it/`, local warehouses, models, tokens, logs, and absolute paths are absent.

- [ ] **Step 3: Update verification JSON and commit it**

Record commands, exit codes, pass counts, expected capability blockers, current branch, exact commit(s), and status. Commit `test: record selection lab verification` if this changes the already committed bundle.

- [ ] **Step 4: Push and create draft PR**

Push `feat/selection-lab-opportunity-types`; create a draft PR titled `feat: add selection lab and opportunity-type research contract`. If authentication remains invalid, do not push elsewhere; report the exact blocker with all local commit SHAs.

## Plan self-review

- Every execution-Prompt component maps to a task: preregistration (1), labels/types (2), data/audit (3), models/evaluation (4), CLI/reporting (5), Skill semantics (6), public results (7), verification/GitHub (8).
- No task reconstructs candidate chains or historical identity.
- No final-test label can open before model and threshold freezing.
- The current expected scientific result is explicit and cannot be replaced by a secondary-track metric.
- Every production module begins with a targeted failing test.
