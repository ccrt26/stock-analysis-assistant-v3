# V3 Conclusion-First Research Dossier Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build immutable V03 stock dossiers that lead with plain-language conclusions, explain what each fact means and why it matters to selection, isolate data gaps, and optionally consume frozen official-source supplements published before the formation cutoff.

**Architecture:** Add a pure conclusion engine between the existing strict fact builder and Markdown renderer. Add an optional immutable official-supplement bundle whose facts are source-attributed and cutoff-validated. Preserve V01/V02 and write V03 under a new schema identity.

**Tech Stack:** Python 3.12, pandas, PyArrow, pytest, existing V3 forward ledger and strict-as-of inputs.

## Global Constraints

- Real outputs only under `/Volumes/ZHUTONG/股票分析助手-V3回测/2026-07-19-v3-forward-observation/`.
- Preserve formation, decision-card, dossier V01, and dossier V02 bundles byte-for-byte.
- Official internet facts require a primary-source URL and `published_at <= formation cutoff`.
- Internet supplements cannot change routes, action confirmations, prices, financial snapshots, or selected stocks.
- No target prices, positions, stops, lifecycle, selling, publishing, schedulers, Supabase, or trading.
- Use TDD: every production behavior starts with a failing test.
- Do not use subagents.

---

### Task 1: Pure Conclusion Engine

**Files:**
- Create: `src/stock_analyzer/evaluation/v3_forward/dossier_analysis.py`
- Create: `tests/test_v3_forward_dossier_analysis.py`

**Interfaces:**
- Produces: `analyze_dossier_facts(card, theme_info, history, metrics, announcements, supplements) -> dict[str, Any]`
- Produces sections: `top_conclusion`, `company_analysis`, `industry_theme_analysis`, `selection_analysis`, `financial_analysis`, `trading_valuation_analysis`, `announcement_analysis`, `data_gaps`

- [x] Write a failing test asserting the Purui price route becomes a numeric plain-language conclusion and contains no `召回条件`.
- [x] Run the focused test and verify the failure is caused by the missing module.
- [x] Implement route translation and top conclusion using `return_5d`, `relative_return_20d`, `current_amount_ratio_20d`, route and hotspot state.
- [x] Write a failing test asserting `return_1d < 0` plus `amount_ratio >= 1` becomes a “形成日放量下跌” contradiction.
- [x] Implement selection conflict analysis and evidence references.
- [x] Write failing tests for financial repair vs cash-flow support, valuation percentile strength, volatility/ATR path stability, and announcement driver categories.
- [x] Implement one pure analyzer per section; each returns `headline`, `meaning`, `selection_link`, `counterpoint`, `boundary`, and `evidence`.
- [x] Run `PYTHONPATH=src .venv/bin/python -m pytest tests/test_v3_forward_dossier_analysis.py -q` and require all tests pass.
- [x] Commit with `git commit -m "feat: analyze V3 dossier facts into conclusions"`.

### Task 2: Frozen Official Supplements

**Files:**
- Create: `src/stock_analyzer/evaluation/v3_forward/dossier_supplements.py`
- Modify: `src/stock_analyzer/evaluation/v3_forward/ledger.py`
- Create: `tests/test_v3_forward_dossier_supplements.py`

**Interfaces:**
- Produces: `validate_official_supplements(frame, cutoff) -> pd.DataFrame`
- Produces: `ForwardLedger.write_official_supplement_bundle(...) -> BundleWriteResult`
- Produces: `load_official_supplements(output_root, formation_date) -> tuple[pd.DataFrame, str | None]`

- [x] Write a failing test with official CNINFO facts, a nonofficial-domain fact, and a post-cutoff fact.
- [x] Verify the test fails because validation is missing.
- [x] Implement required fields, official-domain allowlist, URL validation and published-at cutoff.
- [x] Write a failing immutable-bundle test for same-content idempotence and changed-content conflict.
- [x] Implement the schema-versioned supplement writer and loader.
- [x] Run the supplement suite and existing ledger tests.
- [x] Commit with `git commit -m "feat: freeze official V3 dossier supplements"`.

### Task 3: V03 Fact Rows and Rendering

**Files:**
- Modify: `src/stock_analyzer/evaluation/v3_forward/dossiers.py`
- Modify: `tests/test_v3_forward_dossiers.py`

**Interfaces:**
- Updates: `DOSSIER_SCHEMA_VERSION = "v3-forward-research-dossier-03"`
- Updates: `build_research_dossiers(..., supplements=pd.DataFrame())`
- Stores: `analysis_json`, `supplement_facts_json`, `supplement_status`, `supplement_bundle_hash`

- [x] Write a failing test asserting V03 top contains core judgment, plain why-now, main conflict, next validation and boundary, with no data-gap text.
- [x] Verify RED against V02 rendering.
- [x] Integrate `analyze_dossier_facts` into row construction and render the top conclusion.
- [x] Write failing tests requiring sections two through six to contain `本节结论`, `为什么`, `与本次入选的关系`, `主要矛盾`, and `不能推出`.
- [x] Render each structured analysis block before its raw evidence table/list.
- [x] Write a failing test asserting missing local and official facts appear only in the final data-availability section.
- [x] Implement isolated `data_gaps` rendering.
- [x] Run dossier and analysis suites.
- [x] Commit with `git commit -m "feat: render conclusion-first V3 dossiers"`.

### Task 4: Service and Manual Supplement Input

**Files:**
- Modify: `src/stock_analyzer/evaluation/v3_forward/dossier_service.py`
- Modify: `src/stock_analyzer/evaluation/v3_forward/__main__.py`
- Modify: `tests/test_v3_forward_dossiers.py`
- Modify: `tests/test_v3_forward_service.py`

**Interfaces:**
- Adds manual command: `supplement-dossier --formation-date --facts-json --output-root`
- Existing `dossier` command automatically reads the immutable supplement bundle when present.

- [x] Write a failing parser and service test for `supplement-dossier`.
- [x] Verify the parser rejects the new command.
- [x] Implement JSON argument parsing, supplement validation and immutable write.
- [x] Write a failing V03 service test proving supplement hash enters the dossier payload and V02 remains unchanged.
- [x] Implement supplement loading and V03 service identity.
- [x] Run CLI, service, dossier, supplement and ledger tests.
- [x] Commit with `git commit -m "feat: wire official supplements into V3 dossiers"`.

### Task 5: Real Official Facts and V03 Generation

**Runtime only:** all artifacts under the frozen USB root.

- [x] Read the official 2025 annual reports published 2026-04-28/29 from CNINFO for 002603.SZ and 301257.SZ.
- [x] Record only company/business/segment facts that are directly stated, with official URL and publication time.
- [x] Run `supplement-dossier` with a single JSON payload containing both stocks; require two official sources and cutoff pass.
- [x] Record all source formation, decision-card and V02 dossier hashes.
- [x] Run the V03 `dossier` command for 2026-07-17.
- [x] Read both full reports and check every top and section conclusion against its evidence.
- [x] Rerun and require `idempotent`.
- [x] Recompute original hashes and require exact equality.

### Task 6: Final Verification

- [x] Run `PYTHONPATH=src .venv/bin/python -m pytest tests/test_v3_*.py -q`.
- [x] Verify V03 manifest hashes with `ForwardLedger.load_bundle_result`.
- [x] Scan code and real reports for prohibited capabilities and directives.
- [x] Run `git diff --check` and require a clean `git status --short` after commits.
- [x] Confirm no real artifact exists outside the frozen USB root and no remote operation occurred.

