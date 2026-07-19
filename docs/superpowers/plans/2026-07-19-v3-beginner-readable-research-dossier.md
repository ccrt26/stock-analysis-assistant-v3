# V3 Beginner-Readable Research Dossier Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an immutable, strict-as-of research dossier for every V3 action-confirmed stock so a first-time reader understands the company, industry, evidence-backed themes, multi-period performance, valuation, trading indicators, reasons for confirmation, counterevidence, and unknowns.

**Architecture:** Preserve the existing formation and decision-card bundles. Expose already-manifested multi-period financial and cash-flow frames through `FormationInputs`, build a new dossier projection in focused modules, and persist it under a separately versioned immutable bundle. The new manual `dossier` command reads only the original formation identity and produces Markdown/JSON/Parquet artifacts on the frozen USB root.

**Tech Stack:** Python 3.12, pandas, PyArrow, pytest, existing V3 strict-as-of snapshot and immutable ledger infrastructure.

## Global Constraints

- All real runtime artifacts must be written under `/Volumes/ZHUTONG/股票分析助手-V3回测/2026-07-19-v3-forward-observation/`.
- Preserve the 2026-07-17 V01 formation bundle and existing decision-card bundle byte-for-byte.
- Generate dossiers only for `action_confirmed=true` stocks.
- Do not add lifecycle, sell, position, stop-loss, target-price, publishing, scheduling, Supabase, or automatic-trading behavior.
- Do not add external facts to the original formation input identity.
- Follow strict red-green-refactor TDD for every production behavior.
- Do not use subagents; the user requested nonessential subagents be avoided.

---

### Task 1: Expose Existing Strict Multi-Period Facts

**Files:**
- Modify: `src/stock_analyzer/evaluation/v3_forward/inputs.py`
- Modify: `tests/test_v3_forward_explanations.py`

**Interfaces:**
- Produces: `FormationInputs.financial_history: pd.DataFrame`
- Produces: `FormationInputs.cashflow_history: pd.DataFrame`
- Preserves: `load_formation_inputs(...).input_manifest` content and hash

- [ ] **Step 1: Write the failing test**

Extend `test_formation_inputs_exposes_strict_explanation_frames` to construct and assert the two history frames. Add a loader test that patches the existing snapshot and verifies the frames exposed by `FormationInputs` are the same `FINANCIAL_INDICATOR` and `CASH_FLOW` frames already included in `_FORMATION_DATASETS`; no dataset is added to `_FORMATION_DATASETS`.

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_v3_forward_explanations.py::test_formation_inputs_exposes_strict_explanation_frames -q
```

Expected: failure because `FormationInputs` has no `financial_history` or `cashflow_history` fields.

- [ ] **Step 3: Implement the minimal fields**

Add frozen dataclass fields using `field(default_factory=pd.DataFrame)` so existing keyword-based test fixtures remain compatible. In `load_formation_inputs`, assign:

```python
financial_history=fact_frames[ResearchDatasetId.FINANCIAL_INDICATOR],
cashflow_history=fact_frames[ResearchDatasetId.CASH_FLOW],
```

Do not change `_FORMATION_DATASETS` or `input_manifest` construction.

- [ ] **Step 4: Run focused and existing input tests**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_v3_forward_explanations.py tests/test_v3_forward_inputs.py -q
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/stock_analyzer/evaluation/v3_forward/inputs.py tests/test_v3_forward_explanations.py
git commit -m "feat: expose strict dossier history facts"
```

### Task 2: Build Dossier Facts and Evidence Boundaries

**Files:**
- Create: `src/stock_analyzer/evaluation/v3_forward/dossiers.py`
- Create: `tests/test_v3_forward_dossiers.py`

**Interfaces:**
- Consumes: `build_decision_cards(payload, candidates, inputs) -> pd.DataFrame`
- Produces: `build_research_dossiers(payload, candidates, inputs) -> pd.DataFrame`
- Produces: `render_research_dossiers(payload, dossiers) -> tuple[str, dict[str, str]]`
- Produces schema constant: `DOSSIER_SCHEMA_VERSION = "v3-forward-research-dossier-01"`

- [ ] **Step 1: Write a failing scope and onboarding test**

Create a synthetic fixture with two confirmed stocks and one unconfirmed stock. Assert the result contains only the confirmed codes and includes company name, main business, L1 industry, route, hotspot, a 30-second summary, and a clear statement that a price-route stock without hotspot support was not selected because of a hotspot.

- [ ] **Step 2: Verify RED**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_v3_forward_dossiers.py::test_dossiers_only_include_confirmed_stocks_and_onboard_new_reader -q
```

Expected: import failure because `dossiers.py` does not exist.

- [ ] **Step 3: Implement minimal dossier rows**

Implement helpers that reuse the existing decision-card facts, active industry membership, original routes, hotspot and company profile. Store nested values with `json.dumps(..., ensure_ascii=False, sort_keys=True)` for stable output. Include a `business_composition_status` value saying strict segment revenue and margin data are unavailable rather than estimating them.

- [ ] **Step 4: Add and fail a theme-boundary test**

Use active and expired theme memberships. Assert only formation-date-active memberships are considered; the selection hotspot is marked `selection_relevant`, while other formal memberships are marked `index_membership_only`. Assert the report says formal theme membership is not proof of business revenue. Verify the test fails before implementation.

- [ ] **Step 5: Implement theme boundary**

Build active memberships with `valid_from <= formation_date <= valid_to or valid_to is null`. Deduplicate by `(group_type, group_code, ts_code)`. Always place the actual `hotspot_group_name` first. Cap other displayed formal memberships deterministically and disclose the total active count.

- [ ] **Step 6: Add and fail a five-period financial-history test**

Provide duplicated revisions, a future-visible record, and six legal periods. Assert future-visible rows cause strict failure, duplicate revisions resolve to the latest legal `available_at`/`revision_no`, and only the latest five distinct periods are rendered. Assert fields include `tr_yoy`, `netprofit_yoy`, `dt_netprofit_yoy`, `ocf_yoy`, `eps`, `grossprofit_margin`, `netprofit_margin`, `roe`, `debt_to_assets`, `current_ratio`, and `ocfps` when available.

- [ ] **Step 7: Implement financial-history normalization**

Validate `available_at` against the formation cutoff, filter to the stock, sort by report period and legal revision, deduplicate per report period, and serialize the latest five periods in descending order. Merge matching `n_cashflow_act` by report period when available. Preserve nulls as explicit Chinese missing text in Markdown, not invented zeroes.

- [ ] **Step 8: Add and fail a trading-metrics and glossary test**

Assert the dossier reads the formation-date stock context for 1/5/10/20/60-day returns, relative returns, volatility, ATR, price location, average amount, amount ratio, limit-up count, PE/PB, valuation percentiles and observation counts. Assert the Markdown explains at least 成交比率、三项确认、ATR、PE-TTM、PB、ROE and 资产负债率.

- [ ] **Step 9: Implement trading metrics and fixed glossary**

Join `inputs.stocks` by `ts_code` and formation date. Format percentages without changing stored raw numeric values. Include limitations from `coverage_status`, `valuation_data_status`, `pe_percentile_status` and `limitation_notes`.

- [ ] **Step 10: Add and fail a prohibited-content test**

Assert rendered reports do not contain field headings or directives for `目标价`, `仓位建议`, `止损`, `止盈`, `自动买入`, or `自动交易`. Also assert reports contain explicit `已确认事实`, `谨慎解释`, and `当前未知` sections.

- [ ] **Step 11: Implement evidence matrix and rendering**

Render a combined Markdown report plus a `{ts_code: markdown}` map for per-stock files. Use fixed cautious language. Reuse announcement titles as existence facts only. Include counterevidence and next facts to verify, with no action or position instructions.

- [ ] **Step 12: Run the full dossier unit suite**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_v3_forward_dossiers.py -q
```

Expected: all pass.

- [ ] **Step 13: Commit**

```bash
git add src/stock_analyzer/evaluation/v3_forward/dossiers.py tests/test_v3_forward_dossiers.py
git commit -m "feat: build beginner readable V3 dossiers"
```

### Task 3: Persist a Separately Versioned Immutable Dossier Bundle

**Files:**
- Modify: `src/stock_analyzer/evaluation/v3_forward/ledger.py`
- Create: `src/stock_analyzer/evaluation/v3_forward/dossier_service.py`
- Modify: `tests/test_v3_forward_dossiers.py`

**Interfaces:**
- Produces: `ForwardLedger.write_research_dossier_bundle(...) -> BundleWriteResult`
- Produces: `DossierRunResult(bundle: BundleWriteResult, dossier_count: int)`
- Produces: `build_research_dossier(...) -> DossierRunResult`

- [ ] **Step 1: Write a failing immutable-bundle test**

Create an existing formation and decision-card bundle in a temporary ledger. Run the dossier service twice and assert the first write forms the bundle, the second is idempotent, both point to the schema-versioned research-dossier path, and all hashes in the original formation and decision-card directories remain unchanged.

- [ ] **Step 2: Verify RED**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_v3_forward_dossiers.py::test_dossier_service_is_immutable_and_preserves_existing_bundles -q
```

Expected: failure because the service and ledger writer do not exist.

- [ ] **Step 3: Implement the ledger writer**

Follow the existing staging, fsync, manifest, atomic rename, idempotence and conflict pattern. Write `dossiers.json`, `dossiers.parquet`, `report.md`, `stocks/<ts_code>.md`, and `manifest.json`; include every file in the content-hash calculation. Reject duplicate stock codes and unsafe per-stock filenames.

- [ ] **Step 4: Implement the service**

The service must:

1. load exactly one formation for the date;
2. verify exactly one existing decision-card bundle for the same date/rule version;
3. load strict formation inputs and compare `input_manifest_hash` with the source formation;
4. build and render dossiers;
5. write the immutable bundle and a combined report projection;
6. write an audit containing cutoff, source hashes, dossier count, future-fact status, prohibited-field status and original-bundle hash comparisons.

- [ ] **Step 5: Add and fail conflict/guard tests**

Assert changed content at the same identity raises `ImmutableEvidenceConflict`; missing decision-card input fails; a non-USB real output fails when enforcement is on; and a dossier row for an unconfirmed stock fails.

- [ ] **Step 6: Implement guards and rerun**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_v3_forward_dossiers.py -q
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add src/stock_analyzer/evaluation/v3_forward/ledger.py src/stock_analyzer/evaluation/v3_forward/dossier_service.py tests/test_v3_forward_dossiers.py
git commit -m "feat: persist immutable V3 research dossiers"
```

### Task 4: Add the Manual Dossier Command

**Files:**
- Modify: `src/stock_analyzer/evaluation/v3_forward/__main__.py`
- Modify: `tests/test_v3_forward_dossiers.py`

**Interfaces:**
- Produces CLI command: `dossier --formation-date --warehouse-root --archive-root --output-root`

- [ ] **Step 1: Write the failing parser test**

Assert `build_parser().parse_args(["dossier", "--formation-date", "2026-07-17"])` produces the expected command and defaults without registering anything in the production Typer CLI.

- [ ] **Step 2: Verify RED**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_v3_forward_dossiers.py::test_manual_dossier_command_is_available -q
```

Expected: parser rejects `dossier`.

- [ ] **Step 3: Implement command dispatch**

Add the argparse subcommand and call `build_research_dossier`. Print stable JSON containing `status`, `path`, `dossier_count`, `schema_version` and no trade directive.

- [ ] **Step 4: Run parser and existing CLI tests**

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_v3_forward_dossiers.py tests/test_v3_forward_explanations.py -q
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/stock_analyzer/evaluation/v3_forward/__main__.py tests/test_v3_forward_dossiers.py
git commit -m "feat: add manual V3 dossier command"
```

### Task 5: Generate and Audit the Real 2026-07-17 Dossiers

**Files:**
- Runtime only under the frozen USB root; no repository source file is written by this task.

**Interfaces:**
- Consumes the real 2026-07-17 formation and decision-card bundles.
- Produces two immutable dossiers and a strict audit.

- [ ] **Step 1: Record original hashes**

Compute SHA-256 for every file under the 2026-07-17 V01 formation bundle and existing decision-card bundle. Keep the results in memory for post-run comparison; do not write runtime artifacts in the repository.

- [ ] **Step 2: Run the real command**

```bash
PYTHONPATH=src .venv/bin/python -m stock_analyzer.evaluation.v3_forward dossier \
  --formation-date 2026-07-17 \
  --warehouse-root /Users/ccrt/Documents/股票分析助手/local_warehouse \
  --archive-root /Users/ccrt/Documents/股票分析助手/local_archive \
  --output-root /Volumes/ZHUTONG/股票分析助手-V3回测/2026-07-19-v3-forward-observation
```

Expected: `dossier_count` is 2 and the path is under `research-dossiers` on the USB.

- [ ] **Step 3: Read and manually inspect both stock files**

Confirm 普蕊斯 is described as a clinical-trial site-management service company rather than a drug maker. Confirm 以岭药业 is described as a drug R&D, manufacturing and sales company. Confirm both include sector, route/theme boundary, five-period financial table, indicator explanations, announcement boundary, counterevidence and unknowns.

- [ ] **Step 4: Rerun for idempotence**

Run the same command again. Expected status: `idempotent`, with unchanged bundle content hash.

- [ ] **Step 5: Compare original hashes**

Recompute all V01 formation and existing decision-card hashes and require exact equality with Step 1.

- [ ] **Step 6: Commit no runtime artifacts**

Verify `git status --short` contains no USB outputs or unexpected local generated files.

### Task 6: Final Verification

**Files:**
- No new files unless a test-driven correction is required.

**Interfaces:**
- Verifies the complete feature and project boundaries.

- [ ] **Step 1: Run all related tests**

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_v3_forward_dossiers.py \
  tests/test_v3_forward_explanations.py \
  tests/test_v3_forward_inputs.py \
  tests/test_v3_forward_ledger.py \
  tests/test_v3_forward_service.py \
  tests/test_v3_forward_v2_routes.py \
  tests/test_v3_forward_v2_selection.py \
  tests/test_v3_forward_v2_service.py -q
```

Expected: all pass.

- [ ] **Step 2: Verify code hygiene**

```bash
git diff --check
git status --short
```

Expected: no whitespace errors and clean worktree after intentional commits.

- [ ] **Step 3: Scan prohibited capabilities and language**

Search new modules and real dossiers for `supabase`, `cloudflare`, `launchctl`, `place_order`, `position_size`, `sell_order`, `目标价`, `仓位建议`, `止损`, `止盈`, and `自动交易`. Any code capability or user directive is a failure; design documents may mention the terms only as explicit prohibitions.

- [ ] **Step 4: Verify frozen outputs**

Require all real new artifacts to resolve under the frozen USB root, both real dossiers to pass manifest hash verification, both source bundles to remain byte-identical, and no production task or remote system state to have changed.

