# V3 Production Capability Correction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to execute this plan inline in the current primary-agent context. Do not default to `subagent-driven-development`. A subagent is optional only for an independent, read-only, high-value investigation or final review; if used it must be GPT-5.6 sol, reasoning high, speed standard, must not modify files/commit/push, and its conclusions must be re-verified by the primary agent.

**Goal:** Replace the formal-production shell with concrete primary/backup clients, production contracts, durable capability evidence, default screening/analysis/render bindings, and a recorded-response default-entry acceptance so the program is fully implemented and offline verified without performing unauthorized production actions.

**Architecture:** Keep the existing fail-closed state machine, immutable evidence store, Strategy V2 decision rules, two-phase activation, report structure, narrow Supabase ledger, and publication gates. Add provider-specific raw-response clients behind transport boundaries, heterogeneous record contracts, one materializer, and one production dependency factory; tests replace only Tushare/AkShare/Supabase external boundaries and always construct the real internal production path.

**Tech Stack:** Python 3.11+, Pydantic 2, pandas 2, httpx 0.27, optional Tushare 1.4.19+, optional AKShare 1.14+, Supabase Python 2.6+, pytest 8, pathlib/JSON/hashlib, existing Jinja2 report generator.

## Global Constraints

- Authority: `docs/operations/production-capability-matrix.md` and `docs/superpowers/specs/2026-07-10-v3-formal-report-data-readiness-design.md`.
- Worktree: `/Users/ccrt/股票分析助手/.worktrees/codex/v3-mvp`; branch `codex/v3-mvp`.
- Current primary agent performs all implementation, test decisions, commits, and push.
- Do not use `superpowers:subagent-driven-development`.
- Optional subagents must use GPT-5.6 sol, reasoning high, speed standard; if that exact configuration cannot be guaranteed, do not dispatch them.
- Never read, print, copy, persist, or log `.env.local`, token values, passwords, service-role keys, authorization headers, or cookies.
- This plan authorizes production-code implementation and offline recorded-response tests only.
- This plan does not authorize real provider acquisition, Supabase migration/application/write, Cloudflare deployment, launchd loading, broker connection, or order action.
- Primary and backup are whole-group availability routes. Never merge partial records or fields, compare provider values, or emit difference warnings.
- Historical cache cannot replace target-date current facts.
- The initial history window is exactly the 82 official sessions from 2026-03-12 through 2026-07-10 inclusive.
- Formal contract version becomes `formal-v2`; existing `formal-v1` evidence and reports remain immutable historical records.
- Strategy V2 decisions, position ranges, focus rules, score hiding, report structure, and broker/order boundary remain unchanged.
- A test may inject raw provider modules/objects, clocks, and a fake external ledger transport. It may not replace `build_production_formal_dependencies`, production clients, contracts, materializer, screen/analyze/render/verify callbacks, or the formal coordinator.
- Every implementation task follows TDD: named RED test, exact failure, minimal implementation, focused GREEN, regression command, commit.
- Supabase migration must explicitly grant only required service-role table/view privileges, enable RLS, keep views `security_invoker`, revoke function execution from `public`, `anon`, and `authenticated`, and grant RPC execution only to `service_role`.
- Do not mark a matrix row above the evidence actually produced.

## File Structure

- Create `src/stock_analyzer/data/formal_contracts.py`: `formal-v2` heterogeneous record schemas and screening/target contract factories.
- Modify `src/stock_analyzer/data/readiness.py`: record-type-aware contract validation and recorded/live capability evidence distinction.
- Create `src/stock_analyzer/data/capability_store.py`: immutable JSON capability bundle load/save and recorded/live mode enforcement.
- Create `src/stock_analyzer/data/tushare_formal_client.py`: concrete Tushare normalized primary routes.
- Create `src/stock_analyzer/data/akshare_formal_client.py`: concrete AKShare/Eastmoney and exchange-backed backup routes.
- Modify `src/stock_analyzer/data/formal_routes.py`: bind concrete clients, reject wrong capability kind, and keep route atomicity.
- Create `src/stock_analyzer/data/formal_materializer.py`: convert accepted group payloads into domain rows, market bundle, contexts, and manual holdings.
- Modify `src/stock_analyzer/analysis/strategy_v2.py`: consume structured fundamentals/valuation facts already required by the approved design without changing decision thresholds.
- Create `src/stock_analyzer/ops/formal_strategy_runtime.py`: production screen/analyze/render/verify callbacks and exact ledger-row serialization.
- Create `src/stock_analyzer/ops/production_dependencies.py`: external runtime boundary plus the real default dependency factory.
- Modify `src/stock_analyzer/ops/job.py`: delegate to the real factory; retain stable run ID and fail-closed job handling.
- Modify `src/stock_analyzer/storage/repositories.py`: formal focus-day reads and any narrow formal row conversion required by the runtime.
- Modify `supabase/migrations/202607100004_formal_run_readiness.sql`: explicit Data API grants/revokes and service-role-only access.
- Add focused tests in `tests/test_formal_contract_registry.py`, `tests/test_capability_store.py`, `tests/test_tushare_formal_client.py`, `tests/test_akshare_formal_client.py`, `tests/test_formal_materializer.py`, `tests/test_formal_strategy_runtime.py`, `tests/test_default_formal_production_entry.py`.
- Modify existing formal, repository, schema, job, report, and documentation tests only where their public contract changes.
- Update `docs/operations/production-capability-matrix.md`, `README.md`, and active runbooks after evidence exists.
- Delete deprecated `docs/operations/mandatory-next-phases.md` only in the same task that removes all active references and updates documentation tests.

---

### Task 1: Close Documentation Authority Gaps (`GOV-001`–`GOV-003`)

**Files:**
- Modify: `tests/test_config_health.py`
- Modify: `README.md`
- Delete: `docs/operations/mandatory-next-phases.md`
- Modify: `docs/operations/production-capability-matrix.md`

**Interfaces:**
- Produces one active status source: `docs/operations/production-capability-matrix.md`.
- Historical specs/plans remain immutable audit records and keep their lifecycle banners.

- [ ] **Step 1: Replace deprecated-roadmap tests with canonical-authority RED tests**

Add exact tests:

```python
def test_readme_links_only_canonical_current_status_and_active_runbooks():
    readme = read_project_file("README.md")
    assert "docs/operations/production-capability-matrix.md" in readme
    assert "mandatory-next-phases.md" not in readme


def test_historical_specs_and_plans_disclaim_current_status_authority():
    for directory in ("docs/superpowers/specs", "docs/superpowers/plans"):
        for path in (PROJECT_ROOT / directory).glob("*.md"):
            assert "production-capability-matrix.md" in path.read_text(encoding="utf-8")


def test_deprecated_mandatory_next_phases_file_is_removed():
    assert not (PROJECT_ROOT / "docs/operations/mandatory-next-phases.md").exists()
```

- [ ] **Step 2: Run RED**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_config_health.py -q`

Expected: FAIL because README still links the deprecated file and the file still exists.

- [ ] **Step 3: Remove the deprecated file and active references**

Delete the file with `apply_patch`, remove its README link, and replace any active runbook reference with the capability matrix. Do not edit historical plan bodies that mention the old path; their lifecycle banners already make them audit-only.

- [ ] **Step 4: Run GREEN and documentation checks**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_config_health.py -q`

Expected: all tests pass.

Run: `git diff --check`

Expected: no output.

- [ ] **Step 5: Commit**

```bash
git add README.md docs/operations/production-capability-matrix.md tests/test_config_health.py
git add -u docs/operations/mandatory-next-phases.md
git commit -m "docs: enforce canonical production capability status"
```

---

### Task 2: Add Formal V2 Heterogeneous Record Contracts (`PIPE-001`, `PIPE-002`)

**Files:**
- Modify: `src/stock_analyzer/data/readiness.py`
- Create: `src/stock_analyzer/data/formal_contracts.py`
- Create: `tests/test_formal_contract_registry.py`
- Modify: `tests/test_formal_readiness_contracts.py`

**Interfaces:**
- Produces immutable `RecordTypeContract(record_type, required_fields, legitimate_null_fields, unique_key_fields, current_fact_fields)`.
- Extends `AcquisitionGroupContract` with `record_type_field: str = "record_type"` and `record_types: tuple[RecordTypeContract, ...] = ()`; legacy flat contracts continue to validate unchanged.
- Produces `FORMAL_CONTRACT_VERSION = "formal-v2"`.
- Produces `build_screening_contracts(trade_date, expected_codes) -> dict[AcquisitionGroupId, AcquisitionGroupContract]`.
- Produces `build_target_contracts(trade_date, target_codes, include_concepts=False) -> dict[AcquisitionGroupId, AcquisitionGroupContract]`.

- [ ] **Step 1: Write record-dispatch RED tests**

```python
def test_market_contract_validates_equity_bars_daily_basic_and_index_bars_by_record_type():
    contract = build_screening_contracts(TARGET, ("600000.SH",))[AcquisitionGroupId.MARKET_DECISION]
    result = validate_group_payload(contract, request(), complete_market_payload())
    assert result.complete is True


def test_unknown_record_type_and_missing_type_specific_field_fail_closed():
    payload = complete_market_payload().model_copy(
        update={"records": ({"record_type": "unknown", "trade_date": TARGET},)}
    )
    result = validate_group_payload(market_contract(), request(), payload)
    assert "unknown_record_type:unknown:row=0" in result.reasons


def test_formal_v2_registry_contains_all_required_groups_and_exact_history():
    screening = build_screening_contracts(TARGET, CODES)
    target = build_target_contracts(TARGET, CODES)
    assert set(screening) == {AcquisitionGroupId.CALENDAR_UNIVERSE, AcquisitionGroupId.MARKET_DECISION}
    assert set(target) == {
        AcquisitionGroupId.BOARD_INDUSTRY,
        AcquisitionGroupId.CANDIDATE_FUNDAMENTAL,
        AcquisitionGroupId.OFFICIAL_EVENTS_RISK,
        AcquisitionGroupId.MANUAL_HOLDINGS,
    }
    assert screening[AcquisitionGroupId.MARKET_DECISION].minimum_history_sessions == 82
```

- [ ] **Step 2: Run RED**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_formal_contract_registry.py tests/test_formal_readiness_contracts.py -q`

Expected: collection fails because `RecordTypeContract` and `formal_contracts` do not exist.

- [ ] **Step 3: Implement record-type dispatch**

Use this exact selection rule inside `validate_group_payload`:

```python
record_contracts = {item.record_type: item for item in contract.record_types}
for index, record in enumerate(payload.records):
    selected = None
    if record_contracts:
        value = record.get(contract.record_type_field)
        selected = record_contracts.get(str(value))
        if selected is None:
            reasons.append(f"unknown_record_type:{value}:row={index}")
            continue
    required_fields = selected.required_fields if selected else contract.required_fields
    legitimate_null_fields = (
        selected.legitimate_null_fields if selected else contract.legitimate_null_fields
    )
    unique_key_fields = selected.unique_key_fields if selected else contract.unique_key_fields
```

The production registry uses these exact record types:

- calendar/universe: `calendar`, `security`;
- market decision: `equity_bar`, `daily_basic`, `index_bar`;
- board/industry: `industry_mapping`, `board_bar`;
- candidate/fundamental: `company_profile`, `financial_summary`, `main_business`, `forecast`, `express`;
- official events/risk: `official_event` with proven-empty coverage allowed;
- concept/theme: `concept_mapping`;
- manual holdings: `manual_holding`, with zero records accepted only when the file exists and contains `[]`.

- [ ] **Step 4: Run GREEN and legacy regression**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_formal_contract_registry.py tests/test_formal_readiness_contracts.py tests/test_atomic_acquisition.py tests/test_formal_routes.py -q`

Expected: all tests pass, including legacy flat-contract tests.

- [ ] **Step 5: Commit**

```bash
git add src/stock_analyzer/data/readiness.py src/stock_analyzer/data/formal_contracts.py tests/test_formal_contract_registry.py tests/test_formal_readiness_contracts.py
git commit -m "feat: define formal v2 production contracts"
```

---

### Task 3: Separate Recorded and Live Capability Evidence (`DATA-010`)

**Files:**
- Modify: `src/stock_analyzer/data/readiness.py`
- Create: `src/stock_analyzer/data/capability_store.py`
- Modify: `src/stock_analyzer/data/formal_routes.py`
- Create: `tests/test_capability_store.py`
- Modify: `tests/test_atomic_acquisition.py`

**Interfaces:**
- Adds `CapabilityEvidenceKind(str, Enum): RECORDED = "recorded"; LIVE = "live"`.
- Extends `RouteCapabilityEvidence` with `evidence_kind`, `response_hash`, and `tested_library_versions`.
- Produces `CapabilityBundle(contract_version, generated_at, routes)` and `LocalCapabilityStore(path)`.
- Produces `LocalCapabilityStore.load(*, require_live: bool) -> dict[str, RouteCapabilityEvidence]`.
- Existing `.approved` means contract flags pass; new `.approved_for_live` additionally requires `evidence_kind == LIVE`.

- [ ] **Step 1: Write RED tests**

```python
def test_recorded_capability_supports_offline_factory_but_not_live_factory(tmp_path):
    store = LocalCapabilityStore(tmp_path / "capabilities.json")
    store.save(bundle(kind=CapabilityEvidenceKind.RECORDED))
    assert store.load(require_live=False)
    with pytest.raises(CapabilityEvidenceError, match="live capability evidence required"):
        store.load(require_live=True)


def test_capability_bundle_rejects_wrong_contract_route_group_and_tampering(tmp_path):
    path = tmp_path / "capabilities.json"
    LocalCapabilityStore(path).save(bundle())
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["routes"][0]["response_hash"] = "tampered"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(CapabilityEvidenceError, match="bundle hash mismatch"):
        LocalCapabilityStore(path).load(require_live=False)
```

- [ ] **Step 2: Run RED**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_capability_store.py tests/test_atomic_acquisition.py -q`

Expected: collection fails because the store and evidence kind do not exist.

- [ ] **Step 3: Implement immutable canonical JSON storage**

Write with exclusive creation for versioned files and atomic replacement only for `latest.json`. Store `bundle_hash = sha256(canonical_json(bundle_without_hash))`. Never store credentials, headers, request tokens, or raw response bodies; store only response hashes and library versions.

- [ ] **Step 4: Bind runtime mode to route approval**

Add `require_live_capability: bool` to `build_formal_route_registry`. Reject recorded evidence when true before constructing routes. Keep atomic acquirer behavior unchanged.

- [ ] **Step 5: Run GREEN**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_capability_store.py tests/test_atomic_acquisition.py tests/test_formal_routes.py -q`

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/stock_analyzer/data/readiness.py src/stock_analyzer/data/capability_store.py src/stock_analyzer/data/formal_routes.py tests/test_capability_store.py tests/test_atomic_acquisition.py tests/test_formal_routes.py
git commit -m "feat: persist formal route capability evidence"
```

---

### Task 4: Implement Concrete Tushare Primary Client (`DATA-001`, `DATA-003`, `DATA-005`–`DATA-008`)

**Files:**
- Create: `src/stock_analyzer/data/tushare_formal_client.py`
- Modify: `src/stock_analyzer/data/tushare_source.py`
- Create: `tests/test_tushare_formal_client.py`

**Interfaces:**
- Produces `TushareFormalEndpointClient(pro, *, required_index_codes=("000001.SH", "399001.SZ", "899050.BJ"))` implementing every `FormalEndpointClient` method.
- All provider calls receive a frozen `AcquisitionRequest`; all dates are `YYYYMMDD`; all publication rows are filtered at or before `request.report_cutoff`.
- Tushare methods used exactly: `trade_cal`, `stock_basic`, `suspend_d`, `stock_st`, `daily`, `daily_basic`, `index_daily`, `index_classify`, `index_member_all`, `stock_company`, `fina_indicator`, `forecast`, `express`, `fina_mainbz`, `concept`, `concept_detail`.

- [ ] **Step 1: Write raw-provider RED tests**

Create `RecordedTusharePro` whose methods return provider-shaped pandas DataFrames and record method/kwargs. Add:

Add tests named `test_tushare_calendar_universe_calls_exact_endpoints_and_normalizes_verified_status`, `test_tushare_market_fetches_each_of_82_sessions_daily_basic_and_indexes_with_declared_units`, `test_tushare_board_industry_maps_members_and_history_without_text_inference`, `test_tushare_candidate_fundamentals_filters_announcements_after_cutoff`, `test_tushare_official_events_proves_empty_target_coverage_and_keeps_risks`, `test_tushare_concepts_returns_only_requested_codes`, and `test_tushare_schema_or_permission_error_is_classified_and_redacted`.

The tests must assert exact recorded method names/kwargs, exact normalized `record_type` sets, exact coverage codes/dates, publication cutoff filtering, and the expected `FailureClassification`; they must also assert that a credential-shaped sentinel never appears in exception text or `repr`.

The market assertion requires exactly 82 `daily(trade_date=...)` calls, one `daily_basic(trade_date=TARGET)`, and three `index_daily(start_date=..., end_date=...)` calls. Normalize Tushare `vol` to shares and `amount` from thousand CNY to CNY; set `adjustment_basis="unadjusted"`.

- [ ] **Step 2: Run RED**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_tushare_formal_client.py -q`

Expected: collection fails because `TushareFormalEndpointClient` does not exist.

- [ ] **Step 3: Implement exact normalization helpers**

Implement private helpers `_require_columns`, `_yyyymmdd`, `_safe_float`, `_publication_time`, `_classify_provider_error`, and `_ts_code`. Every output record has `record_type`, group-specific keys, `source_name`, and publication metadata where applicable. Missing columns raise `PermanentRouteFailure(FailureClassification.SCHEMA)`; transport/rate-limit errors raise `TransientRouteFailure` with redacted messages.

- [ ] **Step 4: Run GREEN and source regression**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_tushare_formal_client.py tests/test_tushare_source.py tests/test_formal_contract_registry.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/stock_analyzer/data/tushare_formal_client.py src/stock_analyzer/data/tushare_source.py tests/test_tushare_formal_client.py
git commit -m "feat: implement formal tushare primary routes"
```

---

### Task 5: Implement Concrete AKShare and Exchange Backup Client (`DATA-002`, `DATA-004`–`DATA-008`)

**Files:**
- Create: `src/stock_analyzer/data/akshare_formal_client.py`
- Create: `tests/test_akshare_formal_client.py`

**Interfaces:**
- Produces `AkshareFormalEndpointClient(ak, *, required_index_symbols=("sh000001", "sz399001", "bj899050"))`.
- Uses exact AKShare functions: `tool_trade_date_hist_sina`, `stock_info_sh_name_code`, `stock_info_sz_name_code`, `stock_info_bj_name_code`, `stock_info_sh_delist`, `stock_info_sz_delist`, `stock_zh_a_spot_em`, `stock_zh_a_hist`, `stock_zh_index_daily_em`, `stock_board_industry_name_em`, `stock_board_industry_cons_em`, `stock_board_industry_hist_em`, `stock_individual_info_em`, `stock_financial_abstract_ths`, `stock_notice_report`, `stock_board_concept_name_em`, `stock_board_concept_cons_em`.
- Missing current snapshot rows are never inferred suspended. The route emits `status_verified=False`, causing contract rejection, unless an exchange delist/status response proves exclusion.

- [ ] **Step 1: Write provider-shaped RED tests**

Add tests named `test_akshare_calendar_universe_uses_exchange_lists_and_refuses_unproven_missing_spot_row`, `test_akshare_market_builds_whole_82_session_group_without_primary_records`, `test_akshare_market_preserves_spot_valuation_units_and_unadjusted_history`, `test_akshare_board_industry_calls_name_constituent_and_history_endpoints`, `test_akshare_candidate_fundamentals_normalizes_profile_and_financial_abstract`, `test_akshare_notice_report_filters_codes_categories_and_cutoff`, `test_akshare_concept_mapping_is_structured_not_inferred_from_text`, and `test_akshare_changed_column_name_fails_schema_instead_of_guessing`.

The whole-group test must put a sentinel primary record in a separate object and assert that no accepted backup record or `source_names` entry contains the sentinel. The schema test removes exactly one required Chinese column and asserts `FailureClassification.SCHEMA` names that column.

- [ ] **Step 2: Run RED**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_akshare_formal_client.py -q`

Expected: collection fails because `AkshareFormalEndpointClient` does not exist.

- [ ] **Step 3: Implement strict Chinese-column maps**

Use explicit per-endpoint maps such as:

```python
SPOT_COLUMNS = {
    "代码": "symbol", "名称": "name", "最新价": "close", "今开": "open",
    "最高": "high", "最低": "low", "昨收": "pre_close", "成交量": "volume",
    "成交额": "amount", "换手率": "turnover_rate", "市盈率-动态": "pe_ttm",
    "市净率": "pb", "总市值": "total_mv", "流通市值": "circ_mv",
}
```

Do not accept synonyms silently. A version-specific schema change must fail capability verification and block the route. Convert codes to `.SH`, `.SZ`, or `.BJ` deterministically; keep raw provider names only in source metadata.

- [ ] **Step 4: Run GREEN and route regression**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_akshare_formal_client.py tests/test_formal_routes.py tests/test_atomic_acquisition.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/stock_analyzer/data/akshare_formal_client.py tests/test_akshare_formal_client.py
git commit -m "feat: implement formal akshare backup routes"
```

---

### Task 6: Materialize Formal Payloads and Freeze Screening (`PIPE-007`, `STORE-001`)

**Files:**
- Create: `src/stock_analyzer/data/formal_materializer.py`
- Create: `tests/test_formal_materializer.py`
- Modify: `src/stock_analyzer/data/feature_builder.py`

**Interfaces:**
- Produces `FormalMarketInputs(bundle: MarketDataBundle, included_codes: tuple[str, ...], feature_profiles: dict[str, FeatureSnapshot])`.
- Produces `materialize_market_inputs(trade_date, payloads) -> FormalMarketInputs`.
- Produces `materialize_target_context(trade_date, target_codes, payloads) -> FormalTargetContext` containing structured company, fundamental, board, event, concept, and holding maps.
- Produces `screen_formal_market(receipt, payloads, repository) -> FormalScreeningOutput`.

- [ ] **Step 1: Write RED tests**

Add tests named `test_materializer_builds_features_only_for_verified_universe_with_61_bars_and_current_basic`, `test_materializer_rejects_payload_code_or_date_outside_frozen_contract`, `test_target_context_requires_every_frozen_candidate_and_active_focus_code`, `test_screening_uses_score_feature_only_and_never_calls_final_strategy_builder`, and `test_screening_freezes_top_ten_plus_active_focus_without_replacement`.

Use 11 eligible recorded stocks with deterministic features; assert the first 10 codes follow `(-score_feature, ts_code)` and an active focus code outside the ten appears only in `active_focus_codes`, never as a replacement recommendation candidate.

Patch `generate_strategy_v2_recommendations` in the screening test to raise if called. Patching the final builder here is a negative assertion, not a replacement of the production path.

- [ ] **Step 2: Run RED**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_formal_materializer.py -q`

Expected: collection fails because the materializer does not exist.

- [ ] **Step 3: Implement strict conversion**

Reuse `build_market_bundle`, `clean_stock_pool`, and `score_feature`. Screening order is:

```python
ranked = sorted(
    included_features,
    key=lambda item: (-score_feature(item), item.ts_code),
)
ordered_codes = tuple(item.ts_code for item in ranked[:10])
active_focus_codes = tuple(sorted(active_code_set))
```

No final Strategy V2 builder, LLM, report, or ledger method is called.

- [ ] **Step 4: Run GREEN**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_formal_materializer.py tests/test_feature_builder.py tests/test_pool_filtering.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/stock_analyzer/data/formal_materializer.py src/stock_analyzer/data/feature_builder.py tests/test_formal_materializer.py
git commit -m "feat: materialize formal screening inputs"
```

---

### Task 7: Bind Structured Fundamentals and Build Formal Analysis (`PIPE-008`, `STRAT-001`–`STRAT-003`)

**Files:**
- Modify: `src/stock_analyzer/analysis/strategy_v2.py`
- Create: `src/stock_analyzer/ops/formal_strategy_runtime.py`
- Modify: `src/stock_analyzer/storage/repositories.py`
- Create: `tests/test_formal_strategy_runtime.py`
- Modify: `tests/test_strategy_v2_recommendation.py`
- Modify: `tests/test_repositories.py`

**Interfaces:**
- Extends `generate_strategy_v2_recommendations(..., fundamental_summaries: dict[str, FundamentalSummaryRow] | None = None)`.
- Produces `FormalReportPayload` with recommendations, focus states, evidence packages, evaluation tasks, cards, snapshots, theses, updates, operational status, source versions, and input set ID.
- Produces `analyze_formal_inputs(receipt, candidate_set, payloads, repository) -> FormalAnalysisOutput`.
- Adds repository method `load_formal_focus_days(before_date: date, eligible_dates: list[date]) -> list[FormalFocusDay]`.

- [ ] **Step 1: Write RED tests for structured evidence**

Add tests named `test_fundamental_module_uses_structured_summary_and_never_claims_missing_values`, `test_formal_analysis_uses_only_frozen_candidates_and_active_focus_codes`, `test_formal_analysis_loads_exact_five_formal_days_and_breaks_on_blocked_day`, `test_formal_analysis_builds_complete_evidence_hashes_and_narrow_ledger_rows`, and `test_zero_recommendations_with_focus_output_commits_rows_without_publishable_pointer`.

The structured-fundamental test supplies only `revenue_yoy` and asserts no claim mentions profit, margin, or cashflow. The ledger test asserts the exact kind set listed in Step 4 and recomputes every evidence hash from canonical JSON.

- [ ] **Step 2: Run RED**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_formal_strategy_runtime.py tests/test_strategy_v2_recommendation.py tests/test_repositories.py -q`

Expected: failures for missing argument, runtime module, and repository method.

- [ ] **Step 3: Extend only the approved fundamentals module**

When a structured summary exists, emit evidence only for non-null fields and identify the exact reporting period/source. When absent, retain the existing counter-evidence behavior. Do not change action thresholds, expected-upside logic, score formula, position ranges, or rank limit.

- [ ] **Step 4: Implement formal analysis serialization**

Ledger row kinds are exact and stable:

```python
("recommendation", Recommendation),
("focus_state", FocusState),
("evidence_package", EvidencePackage),
("evaluation_task", EvaluationTask),
("strategy_snapshot", StrategyEvidenceSnapshot),
("focus_entry_thesis", FocusEntryThesis),
("focus_daily_update", FocusDailyUpdate),
("action_recommendation", ActionRecommendationSummary),
("manual_holding_summary", ManualHoldingSummary),
("operational_status", OperationalDailyStatus),
```

Each row is `{"kind": kind, **model.model_dump(mode="json")}`. Evidence hashes use canonical JSON of the exact evidence model. `has_publishable_output` is true only when recommendations are non-empty; complete focus-only output remains a committed non-publication run.

- [ ] **Step 5: Run GREEN and strategy regression**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_formal_strategy_runtime.py tests/test_strategy_v2_recommendation.py tests/test_focus_strategy_v2.py tests/test_repositories.py -q`

Expected: all tests pass and prior Strategy V2 decisions remain unchanged for inputs without new fundamentals.

- [ ] **Step 6: Commit**

```bash
git add src/stock_analyzer/analysis/strategy_v2.py src/stock_analyzer/ops/formal_strategy_runtime.py src/stock_analyzer/storage/repositories.py tests/test_formal_strategy_runtime.py tests/test_strategy_v2_recommendation.py tests/test_repositories.py
git commit -m "feat: bind formal strategy analysis runtime"
```

---

### Task 8: Bind Formal Rendering, Staged Verification, and Optional LLM Boundary (`PIPE-009`, `REPORT-001`, `REPORT-002`)

**Files:**
- Modify: `src/stock_analyzer/ops/formal_strategy_runtime.py`
- Modify: `src/stock_analyzer/reports/generator.py`
- Create: `tests/test_formal_runtime_render.py`
- Modify: `tests/test_report_generation.py`

**Interfaces:**
- Produces `StructuredExpressionClient` protocol: `express(payload: FormalReportPayload) -> dict[str, str]`.
- Produces `express_formal_analysis(receipt, payload, client=None) -> dict[str, str] | None`; `client=None` is a valid deterministic no-LLM production configuration.
- Produces `render_formal_report(staging, receipt, payload, narrative) -> None`.
- Produces `verify_staged_formal_report(staging, artifact_hashes, receipt) -> bool`.
- Renderer writes `data/formal-run.json` containing run ID, input set ID, candidate set ID, evidence hashes, and report cutoff; it contains no credentials or raw provider data.

- [ ] **Step 1: Write RED tests**

Add tests named `test_formal_renderer_writes_production_report_and_receipt_manifest`, `test_staged_verifier_rejects_fixture_text_hash_mismatch_or_wrong_input_set`, `test_expression_client_receives_structured_payload_only_and_cannot_add_ledger_facts`, and `test_no_llm_configuration_renders_deterministic_formal_report`.

The expression test returns extra unknown keys and asserts they are rejected before rendering; accepted output is limited to narrative text keyed by existing evidence IDs and is never serialized as a ledger fact.

- [ ] **Step 2: Run RED**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_formal_runtime_render.py tests/test_report_generation.py -q`

Expected: failures for missing runtime functions and formal manifest.

- [ ] **Step 3: Implement render and verify**

Call existing `render_reports(..., fixture_mode=False)` with values from `FormalReportPayload`, then atomically write the formal manifest. Verification recomputes `hash_artifact_tree`, parses `data/latest.json` and `data/formal-run.json`, requires `report_mode == "production"`, `is_fixture is False`, exact run/input/evidence IDs, and scans all text artifacts for fixture/sample and secret-shaped markers.

- [ ] **Step 4: Run GREEN**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_formal_runtime_render.py tests/test_report_generation.py tests/test_formal_activation.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/stock_analyzer/ops/formal_strategy_runtime.py src/stock_analyzer/reports/generator.py tests/test_formal_runtime_render.py tests/test_report_generation.py
git commit -m "feat: render and verify formal strategy reports"
```

---

### Task 9: Assemble the Real Default Production Dependency Factory (`PIPE-006`, `OPS-001`)

**Files:**
- Create: `src/stock_analyzer/ops/production_dependencies.py`
- Modify: `src/stock_analyzer/ops/job.py`
- Modify: `src/stock_analyzer/data/formal_routes.py`
- Create: `tests/test_production_dependencies.py`
- Modify: `tests/test_ops_job.py`

**Interfaces:**
- Produces `ProductionExternalRuntime(config, tushare_pro, akshare_module, capability_store, capability_mode)` where `capability_mode` is `recorded` or `live`.
- Produces `build_production_formal_dependencies(project_root, repository, trade_date, *, runtime=None) -> FormalPipelineDependencies`.
- `runtime=None` lazily loads `AppConfig`, optional packages, token-backed Tushare `pro`, and `local_warehouse/formal_evidence/capabilities/formal-v2/latest.json`; it requires live capability evidence.
- Recorded tests provide only raw provider objects and recorded capability storage. The factory still constructs every contract, client, route, materializer, callback, evidence store, and ledger binding.

- [ ] **Step 1: Write factory RED tests**

```python
def test_recorded_runtime_builds_complete_real_dependencies_without_high_level_monkeypatch(tmp_path):
    deps = build_production_formal_dependencies(
        tmp_path, repository(), TARGET, runtime=recorded_external_runtime(tmp_path)
    )
    assert {g.contract.group_id for g in deps.screening_routes} == {
        AcquisitionGroupId.CALENDAR_UNIVERSE, AcquisitionGroupId.MARKET_DECISION
    }
    assert callable(deps.screen) and callable(deps.analyze)
    assert callable(deps.render) and callable(deps.verify)


def test_live_runtime_rejects_recorded_capability_before_provider_call(tmp_path):
    runtime = recorded_external_runtime(tmp_path, mode="live")
    with pytest.raises(CapabilityEvidenceError, match="live capability evidence required"):
        build_production_formal_dependencies(tmp_path, repository(), TARGET, runtime=runtime)
    assert runtime.tushare_pro.calls == []


def test_default_factory_reports_missing_optional_packages_without_secret_values(tmp_path):
    with pytest.raises(ProductionDependencyError, match="optional data dependencies") as raised:
        load_default_external_runtime(config_without_packages(tmp_path))
    assert "secret-sentinel" not in str(raised.value)


def test_job_default_run_uses_factory_and_stable_formal_date_run_id(monkeypatch, tmp_path):
    captured = []
    monkeypatch.setattr("stock_analyzer.ops.job.run_formal_strategy_v2", recording_runner(captured))
    result = _default_run_daily(tmp_path, repository(), TARGET, runtime=recorded_external_runtime(tmp_path))
    assert result.receipt.run_id == "formal-2026-07-10"
```

- [ ] **Step 2: Run RED**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_production_dependencies.py tests/test_ops_job.py -q`

Expected: collection fails because `production_dependencies` does not exist and the old factory raises unconditionally.

- [ ] **Step 3: Implement lazy external loading and exact assembly**

The factory must not catch route construction errors and substitute legacy `run_daily_pipeline`. Manual holdings path is `local_warehouse/manual/holdings.json`; an explicit `[]` is valid. Concepts are constructed but excluded from target routes unless `STOCK_ANALYZER_ENABLE_CONCEPTS=1`; if enabled, the complete concept contract becomes required.

- [ ] **Step 4: Remove unconditional blocker from `job.py`**

Keep `build_production_formal_dependencies` import-compatible by re-exporting the new function. `_default_run_daily` remains the only scheduled analysis entry and keeps `run_id=f"formal-{trade_date.isoformat()}"`.

- [ ] **Step 5: Run GREEN**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_production_dependencies.py tests/test_ops_job.py tests/test_formal_pipeline.py -q`

Expected: all tests pass; no test monkeypatches the factory for the recorded construction assertion.

- [ ] **Step 6: Commit**

```bash
git add src/stock_analyzer/ops/production_dependencies.py src/stock_analyzer/ops/job.py src/stock_analyzer/data/formal_routes.py tests/test_production_dependencies.py tests/test_ops_job.py
git commit -m "feat: assemble formal production dependencies"
```

---

### Task 10: Harden Supabase Formal Access and Focus-Day Reads (`STORE-002`, `STORE-003`, `STRAT-003`)

**Files:**
- Modify: `supabase/migrations/202607100004_formal_run_readiness.sql`
- Modify: `src/stock_analyzer/storage/repositories.py`
- Modify: `tests/test_supabase_schema.py`
- Modify: `tests/test_repositories.py`

**Interfaces:**
- `SupabaseAnalysisRepository.load_formal_focus_days(before_date, eligible_dates) -> list[FormalFocusDay]` reads `active_formal_run_receipt` only.
- Formal tables/views are accessible through the Data API only to `service_role`; `anon`, `authenticated`, and `public` receive no table/view/RPC privilege.

- [ ] **Step 1: Write security and focus-day RED tests**

Add tests named `test_formal_migration_explicitly_grants_service_role_and_revokes_public_api_roles`, `test_formal_views_are_security_invoker_and_service_role_select_only`, `test_activation_rpc_revokes_public_anon_authenticated_and_grants_service_role`, `test_supabase_repository_builds_focus_days_only_from_active_receipts`, and `test_blocked_fixture_or_backfill_receipt_cannot_become_formal_focus_day`.

The SQL tests normalize whitespace and assert every table name separately. The repository tests populate active-receipt rows for exactly five eligible dates plus blocked/backfill rows and assert only the five active formal dates are returned.

- [ ] **Step 2: Run RED**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_supabase_schema.py tests/test_repositories.py -q`

Expected: grant assertions and focus-day repository tests fail.

- [ ] **Step 3: Add explicit SQL access control**

For each of `formal_run_receipt`, `formal_run_pending_batch`, `formal_run_activation_marker`, `formal_decision_activation_row`, and `formal_reconciliation_task`, add `revoke all on table public.<name> from public, anon, authenticated` and `grant select, insert, update, delete on table public.<name> to service_role`. For `active_formal_run_receipt` and `active_formal_decision_row`, revoke all from public/anon/authenticated and grant select to service_role. Retain RLS and service-role policies. Retain fixed `search_path`; revoke RPC execute from public/anon/authenticated and grant only service_role.

- [ ] **Step 4: Run GREEN**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_supabase_schema.py tests/test_repositories.py tests/test_formal_activation.py -q`

Expected: all tests pass without opening a Supabase connection.

- [ ] **Step 5: Commit**

```bash
git add supabase/migrations/202607100004_formal_run_readiness.sql src/stock_analyzer/storage/repositories.py tests/test_supabase_schema.py tests/test_repositories.py
git commit -m "fix: harden formal supabase access"
```

---

### Task 11: Prove the Default July 10 Recorded-Response Path (`DATA-011`, all offline gates)

**Files:**
- Create: `tests/test_default_formal_production_entry.py`
- Modify: `tests/test_july10_formal_readiness_acceptance.py`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_ops_job.py`

**Interfaces:**
- Uses the real `build_production_formal_dependencies`, `run_formal_strategy_v2`, clients, contracts, materializer, runtime callbacks, renderer, verifier, and activation coordinator.
- Replaces only Tushare/AkShare raw provider objects and the external ledger implementation.

- [ ] **Step 1: Write end-to-end RED tests**

Add tests named `test_default_recorded_july10_complete_path_generates_and_activates_formal_report`, `test_default_recorded_july10_partial_primary_discards_it_and_uses_complete_backup_only`, `test_default_recorded_july10_incomplete_primary_and_backup_blocks_before_strategy`, `test_default_recorded_reconciliation_keeps_frozen_report_and_promotes_primary_history`, `test_default_recorded_focus_window_breaks_on_blocked_day`, and `test_default_recorded_direct_render_requires_activated_receipt`. Add `test_default_recorded_atomic_failure_preserves_prior_consumers` parametrized with `render`, `verify`, `ledger_prepare`, `local_marker`, `ledger_activate`, and `pointer`.

The complete case supplies exactly 82 provider-shaped session responses and target data for two candidates. Assert `REPORT_GENERATED`, exact input/candidate/evidence hashes, production report mode, no fixture marker, no visible numeric total score, complete focus action fields, and matching activation IDs.

- [ ] **Step 2: Run RED**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_default_formal_production_entry.py -q`

Expected: at least one assertion fails until all default bindings are complete; collection must not be bypassed by monkeypatching the dependency factory.

- [ ] **Step 3: Stop on any integration failure and trace it to the originating task**

Expected after Tasks 2-10: the acceptance passes. If it fails, invoke `superpowers:systematic-debugging`, add the narrowest failing assertion to the focused test file owned by the originating task, fix that layer, rerun that task's focused command, then rerun this acceptance. Do not weaken contracts, delete required target codes, fall back to sample data, or bypass activation.

- [ ] **Step 4: Add production-shell scans**

```python
def test_required_production_methods_have_no_empty_stub_or_unconditional_not_configured_raise():
    forbidden = ("return []", "Production formal route clients and recorded capability evidence are not configured")
    paths = required_production_source_paths()
    rendered = "\n".join(path.read_text(encoding="utf-8") for path in paths)
    assert all(value not in rendered for value in forbidden)


def test_default_acceptance_does_not_use_sample_market_or_patch_dependency_factory():
    source = Path(__file__).read_text(encoding="utf-8")
    assert "_sample_market" not in source
    assert "monkeypatch.setattr" not in source or "build_production_formal_dependencies" not in source
```

- [ ] **Step 5: Run the expanded offline gate**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_default_formal_production_entry.py tests/test_july10_formal_readiness_acceptance.py tests/test_formal_pipeline.py tests/test_formal_activation.py tests/test_ops_job.py tests/test_cli.py -q`

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add tests/test_default_formal_production_entry.py tests/test_july10_formal_readiness_acceptance.py tests/test_cli.py tests/test_ops_job.py src/stock_analyzer
git commit -m "test: prove default formal production path offline"
```

---

### Task 12: Update Capability Gates and Active Documentation

**Files:**
- Modify: `docs/operations/production-capability-matrix.md`
- Modify: `README.md`
- Modify: `docs/operations/runbook.md`
- Modify: `docs/operations/cloudflare-pages.md`
- Modify: `docs/superpowers/specs/2026-07-10-v3-formal-report-data-readiness-design.md`
- Modify: `tests/test_config_health.py`

**Interfaces:**
- Advances only rows proven by Tasks 1-11 to `OFFLINE_VERIFIED`.
- Keeps `DATA-011` real acquisition at `NOT_IMPLEMENTED` or `BLOCKED` until an approved live read occurs; do not call synthetic 82-session evidence real data.
- Keeps Supabase production write, launchd, Cloudflare, broker/order rows unchanged unless separately authorized and verified.

- [ ] **Step 1: Write documentation RED assertions**

Add tests named `test_active_docs_say_program_offline_ready_but_live_actions_not_executed`, `test_matrix_default_factory_and_route_rows_match_verified_evidence`, and `test_matrix_does_not_claim_live_read_supabase_write_launchd_or_publish`.

Assert exact matrix levels: implemented route/factory/runtime rows become `OFFLINE_VERIFIED`; `DATA-011` remains below `LIVE_READ_VERIFIED`; `STORE-002`/`STORE-003` remain below `PRODUCTION_WRITE_VERIFIED`; `OPS-002` and `PUB-003` remain `BLOCKED`; `SAFE-001` remains `NOT_APPLICABLE`.

- [ ] **Step 2: Run RED**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_config_health.py -q`

Expected: fail because active docs still describe the formal program as not implemented.

- [ ] **Step 3: Update exact rows and commands**

Document the recorded default acceptance command, capability-record location, and separate next approvals. Do not duplicate endpoint tables from the plan into the runbook; link the matrix and keep the runbook operational.

- [ ] **Step 4: Run GREEN and link scans**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_config_health.py -q`

Expected: all pass.

Run: `git diff --check`

Expected: no output.

- [ ] **Step 5: Commit**

```bash
git add docs/operations/production-capability-matrix.md README.md docs/operations/runbook.md docs/operations/cloudflare-pages.md docs/superpowers/specs/2026-07-10-v3-formal-report-data-readiness-design.md tests/test_config_health.py
git commit -m "docs: record corrected formal production gates"
```

---

### Task 13: Eliminate Operational Hardcoding and Add the Live-Read Bootstrap

**Reason for amendment:** The primary-agent adversarial review found that July 10-specific session lists were still used by both production clients and focus history, and that live capability evidence had a loader but no executable bootstrap. The user explicitly expanded the final scope to a repository-wide operational-hardcoding audit followed by approved real data acquisition, Supabase persistence, formal analysis, and local report generation.

**Files:**
- Modify: `src/stock_analyzer/data/tushare_formal_client.py`
- Modify: `src/stock_analyzer/data/akshare_formal_client.py`
- Modify: `src/stock_analyzer/data/formal_contracts.py`
- Modify: `src/stock_analyzer/data/formal_routes.py`
- Modify: `src/stock_analyzer/data/readiness.py`
- Modify: `src/stock_analyzer/ops/formal_run.py`
- Modify: `src/stock_analyzer/ops/formal_strategy_runtime.py`
- Modify: `src/stock_analyzer/ops/job.py`
- Create: `src/stock_analyzer/ops/formal_live.py`
- Modify: `src/stock_analyzer/cli.py`
- Modify: `tests/test_tushare_formal_client.py`
- Modify: `tests/test_akshare_formal_client.py`
- Modify: `tests/test_formal_contract_registry.py`
- Modify: `tests/test_formal_pipeline.py`
- Modify: `tests/test_formal_strategy_runtime.py`
- Modify: `tests/test_production_dependencies.py`
- Modify: `tests/test_default_formal_production_entry.py`
- Create: `tests/test_formal_live.py`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_config_health.py`
- Modify: `docs/operations/production-capability-matrix.md`
- Modify: `docs/operations/runbook.md`
- Modify: `README.md`

**Hardcoding classification:**
- Approved invariant constants may remain only when they express a named product contract: state enum values, `formal-v2`, schema/table names, route IDs, required benchmark index identifiers, approved Strategy V2 thresholds, the three declared schedule slots, and the July 10 acceptance fixture.
- Run-varying values may not be embedded in production flow: target dates, history start/end dates, prior focus dates, report cutoff, candidate/security codes, absolute user paths, provider/library versions, capability hashes, credentials, Supabase project identity, Cloudflare project/domain, or activation IDs.
- A named policy default is configurable or centralized and tested. A duplicated literal that can change independently is rejected even if its present value is correct.

**Interfaces:**
- Each formal provider client derives the latest 82 official sessions ending at `request.trade_date` from its own validated calendar response. July 10 must still resolve exactly to 2026-03-12 through 2026-07-10.
- Formal focus dates are the five immediately preceding sessions in the accepted market payload, never a module-level July fixture.
- Market acquisition derives eligible codes from validated security status and listing dates; suspended, hard-excluded, unverified, or fewer-than-61-session new listings cannot create unexplained history failures.
- Primary and backup clients reject an older eligible code missing any of the latest 61 required bars; they validate all required benchmark-index dates and at least 21 board sessions before claiming coverage.
- Legitimate valuation/fundamental nulls require an explicit normalized reason; a missing column or unexplained null remains incomplete.
- `_default_run_daily()` applies the centralized 18:30 Asia/Shanghai first-attempt cutoff policy and reuses that same cutoff on retries.
- `verify_and_record_live_capabilities(runtime, trade_date, report_cutoff) -> CapabilityBundle` directly validates both production clients without a pre-existing capability file, writes hashed live evidence, and stores the complete primary calendar/market versions as the initial local backfill. It writes no Supabase rows and invokes no strategy, LLM, renderer, deployment, or publication code.
- CLI command `stock_analyzer ops verify-formal-capabilities --trade-date YYYY-MM-DD --confirm-live-read` is fail-closed unless the explicit confirmation flag is present.
- A subsequent default formal run may reuse only a same-date canonical group that passes the current contract and cutoff again; prior-date cache cannot satisfy current facts.

- [ ] **Step 1: Write RED tests for every discovered run-specific literal**

Add tests named:

- `test_tushare_market_uses_provider_calendar_for_next_trading_day_window`
- `test_akshare_market_uses_provider_calendar_for_next_trading_day_window`
- `test_market_request_excludes_suspended_hard_excluded_and_too_new_codes`
- `test_eligible_code_missing_one_of_latest_61_sessions_rejects_whole_route`
- `test_index_and_board_history_must_cover_declared_windows`
- `test_formal_focus_sessions_come_from_current_market_payload`
- `test_default_cutoff_uses_centralized_first_schedule_policy`
- `test_legitimate_null_requires_explicit_provider_reason`
- `test_live_capability_bootstrap_uses_real_clients_and_writes_no_ledger_or_report`
- `test_live_capability_cli_requires_explicit_confirmation`
- `test_production_source_has_no_july10_or_absolute_user_path_runtime_literal`

The source audit parses Python AST under `src/stock_analyzer` and rejects date/string literals representing `2026-07-10`, `2026-03-12`, `/Users/`, `.worktrees/`, or a candidate stock code outside the named July acceptance constant module and fixture-only CLI examples. It separately scans SQL, shell, plist, and active operations docs for absolute user paths or embedded project identities; examples must use `${PROJECT_ROOT}` or documented placeholders.

- [ ] **Step 2: Run the hardcoding RED gate**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_tushare_formal_client.py \
  tests/test_akshare_formal_client.py \
  tests/test_formal_contract_registry.py \
  tests/test_formal_pipeline.py \
  tests/test_formal_strategy_runtime.py \
  tests/test_production_dependencies.py \
  tests/test_formal_live.py \
  tests/test_cli.py \
  tests/test_config_health.py -q
```

Expected: fail for July-only client/focus windows, ineligible-code propagation, unexplained legitimate nulls, fixed cutoff, missing bootstrap command, and disallowed runtime literals.

- [ ] **Step 3: Implement dynamic sessions, eligibility, and point-in-time semantics**

Use provider calendars for 82-session windows. Keep the July constant only as a test oracle. Validate last-61 equity coverage per eligible code, full declared index coverage, 21-session board coverage, current daily-basic facts, and point-in-time financial/event timestamps. Use `cashflow.n_cashflow_act` for operating cash flow; never map `fina_indicator.ocf_to_or` into a cash amount. Include `anns_d` disclosures in the Tushare event route and never claim complete empty-event coverage from ST/suspension calls alone.

- [ ] **Step 4: Implement and offline-test the live bootstrap**

The bootstrap validates primary and backup routes independently against the same contracts, hashes normalized responses, records library versions without credentials, saves an immutable version plus `latest.json`, and stores the validated primary screening payloads in `LocalEvidenceStore`. Recorded tests inject provider-shaped clients only at the transport boundary. They assert no repository, ledger, report, publish, launchd, broker, or order method is reachable.

- [ ] **Step 5: Run GREEN and the repository hardcoding scan**

Run the Step 2 command again.

Expected: all pass.

Run:

```bash
rg -n "2026[-, ]+0?[37][-, ]+|20260710|20260312|/Users/|\.worktrees/|600000\.SH" \
  src supabase ops functions README.md docs/operations
```

Expected: every match is either a named initial-backfill acceptance constant, an approved benchmark/route invariant, a parameterized test/example placeholder, or a historical document. No production runtime path depends on a July date, personal absolute path, or candidate code.

- [ ] **Step 6: Commit the review correction**

```bash
git add src/stock_analyzer tests README.md docs/operations docs/superpowers/plans/2026-07-10-v3-production-capability-correction.md
git commit -m "fix: eliminate formal runtime hardcoding"
```

---

### Task 14: Final Review, Approved Live Run, Full Verification, Clean Tree, and Push

**Files:**
- Modify only when a concrete Critical/Important finding has a failing regression test.

**Interfaces:**
- Produces a clean `codex/v3-mvp` branch pushed to `origin/codex/v3-mvp`.
- After offline verification, performs the now explicitly approved real read-only capability verification, exact July 10 82-session local acquisition, required Supabase migration/write, formal analysis, and local report generation.
- Still performs no `.env.local` read/print, Cloudflare deployment, launchd activation, broker access, or order action.

- [ ] **Step 1: Review the exact correction range**

Run: `git diff --check`

Expected: no output.

Run: `git diff --stat 7d43196..HEAD`

Expected: only planned source, tests, migration, matrix, and active-doc changes.

Run production-shell scans:

```bash
rg -n "return \[\]|NotImplementedError|not configured|_sample_market|allow_data_insufficient_output" src/stock_analyzer/data src/stock_analyzer/ops src/stock_analyzer/pipeline.py tests/test_default_formal_production_entry.py
```

Expected: no required production stub, default-entry sample reuse, or formal escape; legitimate legacy/fixture references must be individually explained.

- [ ] **Step 2: Perform primary-agent adversarial review**

Review every capability ID changed by the plan against its production symbol and test. Categorize findings Critical/Important/Minor. For every Critical/Important finding, invoke `superpowers:receiving-code-review` and `superpowers:test-driven-development`, add a failing regression, fix, and rerun the affected gate. Do not dispatch a subagent unless GPT-5.6 sol/high/standard is guaranteed and the review is read-only and non-duplicative.

- [ ] **Step 3: Run focused correction suite once**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_formal_contract_registry.py \
  tests/test_capability_store.py \
  tests/test_tushare_formal_client.py \
  tests/test_akshare_formal_client.py \
  tests/test_formal_materializer.py \
  tests/test_formal_strategy_runtime.py \
  tests/test_formal_runtime_render.py \
  tests/test_production_dependencies.py \
  tests/test_default_formal_production_entry.py \
  tests/test_supabase_schema.py \
  tests/test_repositories.py -q
```

Expected: all pass.

- [ ] **Step 4: Run complete suite once**

Run: `PYTHONPATH=src .venv/bin/python -m pytest -q`

Expected: all tests pass.

- [ ] **Step 5: Execute the approved live-read bootstrap**

Run without printing environment or credential values:

```bash
PYTHONPATH=src .venv/bin/python -m stock_analyzer ops verify-formal-capabilities \
  --trade-date 2026-07-10 --confirm-live-read
```

Expected: both route families pass their complete contracts, live capability evidence is written under `local_warehouse/formal_evidence/capabilities/formal-v2/`, and immutable primary calendar/market versions cover exactly 82 sessions. If any route, field, unit, permission, rate limit, timestamp, or coverage check fails, stop before Supabase mutation and add a redacted regression before fixing.

- [ ] **Step 6: Apply and verify the approved Supabase migration**

Run `supabase migration list` first. If the linked project and migration history are consistent, run `supabase db push`; otherwise stop without repair commands that rewrite remote history. Run the service-role-only schema/read-back checks without printing project URL or keys.

Expected: `202607100004_formal_run_readiness.sql` is applied once, formal tables/views/RPC exist with the declared grants/RLS, and no decision row is visible without an active dual-marker receipt.

- [ ] **Step 7: Run the approved formal analysis and local report generation**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m stock_analyzer run-daily --trade-date 2026-07-10
PYTHONPATH=src .venv/bin/python -m stock_analyzer ops verify-production --trade-date 2026-07-10
```

Expected: the run either completes with a committed formal receipt and verified local report, or fails closed with local redacted status and no new public report/active ledger rows. A live contract failure is not bypassed with cache, a sample, a lower-ranked replacement, or a manual render.

- [ ] **Step 8: Verify remaining unauthorized actions were not performed**

Confirm from command history and changed files:

- no `.env.local` or credential file read;
- no Wrangler/Cloudflare command;
- no launchctl load/bootstrap/change;
- no broker or order action.

- [ ] **Step 9: Commit live-discovered fixes if any**

```bash
git diff --name-only -z | xargs -0 git add --
git commit -m "fix: address production correction review"
```

Skip this commit only if no file changed after Task 12.

- [ ] **Step 10: Re-run affected offline gates and verify branch state**

Run: `git status --short --branch`

Expected: clean worktree; branch ahead of origin only by the new correction commits.

- [ ] **Step 11: Push without force**

Run: `git push origin codex/v3-mvp`

Expected: push succeeds and updates the remote to local `HEAD`.

- [ ] **Step 12: Verify synchronization**

Run: `git status --short --branch`

Expected: `## codex/v3-mvp...origin/codex/v3-mvp` with no ahead/behind marker and no worktree entries.

## Plan Self-Review Record

- **Matrix coverage:** `GOV-001`–`GOV-003` map to Tasks 1 and 12; `DATA-001`–`DATA-010` map to Tasks 2-5 and 9; `DATA-011` code path maps to Task 11 but remains not live-verified; `PIPE-001`–`PIPE-009` map to Tasks 2-9; strategy rows map to Task 7; storage/activation/report rows map to Tasks 7-10; operations/publication status maps to Tasks 9, 11, and 12.
- **Authorization boundary amended:** after all offline gates pass, the user explicitly authorized real data acquisition, required Supabase migration/write, formal analysis, persistence, and local report generation. Cloudflare deployment, launchd activation, broker access, and orders remain excluded.
- **No proxy acceptance:** the final acceptance constructs the real default production dependencies and replaces external provider objects only; it never patches the dependency factory or uses `_sample_market`.
- **Type consistency:** `formal-v2`, `RecordTypeContract`, `CapabilityEvidenceKind`, `CapabilityBundle`, `LocalCapabilityStore`, `TushareFormalEndpointClient`, `AkshareFormalEndpointClient`, `FormalMarketInputs`, `FormalTargetContext`, `FormalReportPayload`, and `ProductionExternalRuntime` are introduced before use.
- **Supabase currency:** the plan includes explicit Data API grants, RLS, `security_invoker` views, and service-role-only RPC access in response to current Supabase platform defaults.
- **Placeholder scan:** no TBD, TODO, “implement later”, unnamed error handling, unspecified test, or source-name-only route remains.
- **Execution mode:** inline current-primary-agent execution with optional exact-model read-only subagents only; no subagent-driven-development.
