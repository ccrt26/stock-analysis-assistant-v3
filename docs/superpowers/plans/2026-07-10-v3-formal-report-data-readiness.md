# V3 Formal Report Data Readiness Implementation Plan

> **Lifecycle:** Historical execution record for commits `f22d63b` through `8e252ad`. It completed the offline safety framework but did not complete the concrete production routes or default production dependency factory required by the approved design. Current status is authoritative only in [`docs/operations/production-capability-matrix.md`](../../operations/production-capability-matrix.md). Do not resume this plan or use its self-review as production-readiness evidence.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. This plan must be executed inline by the current primary agent; do not use subagent-driven-development.

**Goal:** Make Strategy V2 formal reports possible only from complete, current, traceable acquisition groups, with atomic primary/backup switching, immutable history, frozen candidates, contiguous focus history, committed run receipts, and fail-closed activation.

**Architecture:** Add a typed formal-readiness layer beside the existing Phase 3 analysis code. Acquisition routes return whole immutable group payloads that pass one shared validator; a local evidence store versions payloads, receipts, candidate sets, canonical pointers, and reconciliation tasks. A formal coordinator owns the `READY_TO_SCREEN` and `READY_TO_ANALYZE` gates, while a two-phase activation coordinator keeps staged files and narrow-ledger rows invisible until both markers agree. Existing Strategy V2 scoring, actions, position ranges, evidence content, and report layout remain unchanged and are called only after readiness.

**Tech Stack:** Python 3.11+, Pydantic 2, pathlib/json/hashlib, existing pandas/pyarrow/DuckDB stack, pytest 8, existing repository/report/ops modules.

## Global Constraints

- The approved design is `docs/superpowers/specs/2026-07-10-v3-formal-report-data-readiness-design.md`; commits `d868fce` and `6ce0dec` are the design authority and `451a81f` is the Phase 3 behavior baseline.
- Required-data failure stops before Strategy V2 builders, LLM expression, report rendering, publication, recommendation/focus/evidence/evaluation ledger writes, and pointer changes.
- Blocked output is local internal JSON under `logs/run-daily/`; it is never written below `reports/`, `dist/`, local report archives, or Supabase decision tables.
- Primary and backup are availability routes. Never compare their values, alert on differences, or combine their records/fields in one group version.
- A rejected primary payload is discarded in full. Backup fetch starts from an empty request and must pass the identical `AcquisitionGroupContract`.
- Historical cache may supply prior sessions, replay, audit, and same-run resume only. It cannot supply target-day price, volume, amount, valuation, board state, suspension, announcement, or hard-risk facts.
- The initial rehearsal window is exactly the 82 official sessions from `2026-03-12` through `2026-07-10` inclusive.
- Screening freezes an ordered candidate set. Missing target evidence blocks; it never promotes the next-ranked code.
- Formal manual rendering requires a committed `REPORT_GENERATED` receipt with matching `input_set_id` and evidence/artifact hashes.
- Strategy rules, action decisions, position ranges, LLM expression rules, and existing report content structure are out of scope.
- Tests and rehearsals use synthetic/recorded adapters, in-memory ledgers, and temporary directories. They perform no live network call, Supabase mutation, Cloudflare deployment, broker connection, or order action.
- Never read, print, copy, persist, or log `.env.local`, tokens, passwords, API keys, authorization headers, or service-role values.

## File Structure

- Create `src/stock_analyzer/data/readiness.py`: formal group IDs, route kinds, contracts, payload/version/capability models, shared validation, and July 10 official-session constant.
- Create `src/stock_analyzer/data/acquisition.py`: route protocol, transient/permanent failure types, atomic primary/backup acquisition, and capability gate.
- Create `src/stock_analyzer/data/formal_routes.py`: executable normalized endpoint-route adapters and primary/backup route registry for every required acquisition group.
- Modify `src/stock_analyzer/data/source_registry.py`: replace declaration-only or invalid endpoint names with exact executable route factories and explicit approved single-source policy.
- Create `src/stock_analyzer/storage/evidence_store.py`: immutable group versions, canonical pointers, run receipts, candidate sets, checkpoints, reconciliation tasks, point-in-time history reads, and redacted blocked status.
- Create `src/stock_analyzer/ops/formal_run.py`: state transitions, two-stage acquisition, deterministic screen gate, candidate freeze, analysis gate, blocked outcome, and formal run orchestration.
- Create `src/stock_analyzer/ops/activation.py`: staging verification, pending narrow-ledger protocol, dual activation markers, atomic pointers, idempotent retry, and injected-failure boundaries.
- Modify `src/stock_analyzer/analysis/focus.py`: require the five immediately preceding eligible trading days for formal focus entry and break the window on blocked/incomplete dates.
- Modify `src/stock_analyzer/pipeline.py`: expose a formal Strategy V2 entry point and require a committed receipt for stored-row manual rendering; remove production `data_insufficient` report escape.
- Modify `src/stock_analyzer/cli.py`: pass the local receipt store to `render-report`; reject uncredentialed stored rows before rendering.
- Modify `src/stock_analyzer/ops/job.py`: turn production provider/readiness failures into internal `BLOCKED_NEEDS_HUMAN` status without creating deploy artifacts or publishing.
- Modify `src/stock_analyzer/ops/status.py`: represent `blocked_needs_human` and stable `run_id` without changing secret redaction.
- Modify `src/stock_analyzer/storage/repositories.py`: add a narrow formal-ledger protocol plus in-memory and Supabase RPC-backed pending/activation operations.
- Create `supabase/migrations/202607100004_formal_run_readiness.sql`: receipt, pending-batch, activation-marker, reconciliation-task schema and one transactional activation RPC; no wide market tables.
- Add focused tests listed below and extend existing pipeline, focus, job, CLI, repository, and schema tests only at the exact affected contracts.
- Modify `docs/operations/runbook.md` and `docs/operations/mandatory-next-phases.md`: document blocked operation, reconciliation, receipt-gated rendering, and the explicit prohibition on treating offline rehearsal as production approval.

---

### Task 1: Formal Acquisition Contracts and Shared Validator

**Files:**
- Create: `src/stock_analyzer/data/readiness.py`
- Test: `tests/test_formal_readiness_contracts.py`

**Interfaces:**
- Produces `AcquisitionGroupId`, `RouteKind`, `FormalRunState`, `FailureClassification` string enums.
- Produces immutable `RouteCapabilityEvidence(route_id, group_id, contract_version, full_contract_tested, field_semantics_verified, full_universe_verified, post_close_verified, tested_at)`.
- Produces immutable `AcquisitionGroupContract(group_id, contract_version, required_fields, legitimate_null_fields, unique_key_fields, current_fact_fields, minimum_history_sessions, require_target_date, expected_codes)`.
- Produces immutable `AcquisitionRequest(run_id, trade_date, report_cutoff, target_codes, contract_version)`.
- Produces immutable `AcquisitionPayload(group_id, route_id, route_kind, trade_date, fetched_at, source_names, records, covered_dates, field_coverage, unit_metadata, adjustment_basis, publication_times)`; `content_hash` is computed from canonical JSON and cannot be supplied by callers.
- Produces `GroupValidation(complete, reasons, covered_codes, covered_dates)` and `validate_group_payload(contract, request, payload) -> GroupValidation`.
- Produces `JULY_10_OFFICIAL_SESSIONS: tuple[date, ...]` with 82 unique ascending dates, first `2026-03-12`, last `2026-07-10`.

- [ ] **Step 1: Write failing contract tests**

Add tests named:

```python
def test_july_10_window_is_exactly_82_official_sessions(): ...
def test_group_validator_accepts_complete_current_payload(): ...
def test_group_validator_rejects_missing_required_column_even_when_null_is_legitimate(): ...
def test_group_validator_accepts_classified_legitimate_null(): ...
def test_group_validator_rejects_duplicate_keys_nonfinite_ohlc_and_negative_amount(): ...
def test_group_validator_requires_target_date_and_expected_code_coverage(): ...
def test_payload_hash_is_order_stable_and_route_bound(): ...
def test_point_in_time_payload_rejects_publication_after_report_cutoff(): ...
```

Use a market contract with required fields `trade_date, ts_code, open, high, low, close, vol, amount, pe_ttm, pe_ttm_null_reason`; classify `pe_ttm` as legitimate-null only when `pe_ttm_null_reason` is a non-empty string. Assert failures contain exact machine-readable reason prefixes `missing_field:`, `duplicate_key:`, `invalid_ohlc:`, `negative_value:`, `missing_target_date:`, `missing_code:`, and `look_ahead:`.

- [ ] **Step 2: Run RED**

Run: `.venv/bin/python -m pytest tests/test_formal_readiness_contracts.py -q`

Expected: collection fails with `ModuleNotFoundError: No module named 'stock_analyzer.data.readiness'`.

- [ ] **Step 3: Implement the models, constant, canonical hash, and validator**

Implementation rules:

```python
def validate_group_payload(
    contract: AcquisitionGroupContract,
    request: AcquisitionRequest,
    payload: AcquisitionPayload,
) -> GroupValidation:
    # Require matching group/date/contract route evidence.
    # Inspect required-column presence separately from value validity.
    # Enforce unique_key_fields, finite numerics, OHLC order, nonnegative vol/amount.
    # Require target-day current_fact_fields for every expected code.
    # Require minimum_history_sessions distinct covered dates.
    # Reject publication_times later than request.report_cutoff.
    # Return every reason; do not silently repair or drop records.
```

Build `JULY_10_OFFICIAL_SESSIONS` from weekdays in the inclusive range excluding exactly `2026-04-06`, `2026-05-01`, `2026-05-04`, `2026-05-05`, and `2026-06-19`, then assert its invariants at import time.

- [ ] **Step 4: Run GREEN and regression slice**

Run: `.venv/bin/python -m pytest tests/test_formal_readiness_contracts.py tests/test_ingestion_contracts.py tests/test_strategy_v2_contracts.py -q`

Expected: all selected tests pass with zero warnings or network access.

- [ ] **Step 5: Commit**

```bash
git add src/stock_analyzer/data/readiness.py tests/test_formal_readiness_contracts.py
git commit -m "feat: define formal data readiness contracts"
```

### Task 2: Atomic Acquisition, Immutable Evidence, Cache, and Primary Reconciliation

**Files:**
- Create: `src/stock_analyzer/data/acquisition.py`
- Create: `src/stock_analyzer/data/formal_routes.py`
- Modify: `src/stock_analyzer/data/source_registry.py`
- Create: `src/stock_analyzer/storage/evidence_store.py`
- Test: `tests/test_atomic_acquisition.py`
- Test: `tests/test_formal_routes.py`
- Modify: `tests/test_strategy_v2_source_registry.py`
- Test: `tests/test_evidence_store.py`

**Interfaces:**
- `AcquisitionRoute` protocol: attributes `route_id`, `kind`, `capability`; method `fetch(request: AcquisitionRequest) -> AcquisitionPayload`.
- `TransientRouteFailure` and `PermanentRouteFailure` preserve only redacted messages and `FailureClassification`.
- `AtomicGroupAcquirer(primary_retry_limit=2).acquire(contract, request, primary, backup) -> AcquisitionResult` where `AcquisitionResult` contains exactly one accepted payload, both attempt records, validation, and `used_backup`.
- `AcquisitionBlocked(group_id, attempts, reasons)` is raised only after both complete routes are exhausted.
- `FormalEndpointClient` protocol exposes exact normalized methods `fetch_calendar_universe`, `fetch_market_decision`, `fetch_board_industry`, `fetch_candidate_fundamentals`, `fetch_official_events_risk`, and `fetch_concepts`; each receives only `AcquisitionRequest` and returns records plus publication/unit metadata.
- `NormalizedEndpointRoute(route_id, kind, group_id, client_method, capability)` calls one exact protocol method and returns a whole `AcquisitionPayload`; it never reads another route's payload or cache.
- `FormalRoutePair(primary, backup, approved_single_source)` and `build_formal_route_registry(primary_client, backup_client, official_client, holdings_path, capabilities) -> dict[AcquisitionGroupId, FormalRoutePair]` provide executable routes for calendar/universe, market decision, board/industry, candidate company/fundamental, official events/risk, conditional concept/theme, and manual holdings. `capabilities` must contain recorded `RouteCapabilityEvidence` for every network route; registry construction fails if evidence is missing or bound to the wrong group.
- `source_registry.strategy_v2_source_registry()` points to those route factory names; it removes `tushare.announcements`, requires official exchange/regulator event adapters, and represents manual holdings as an approved local single-source dependency whose missing/malformed file blocks personalized output while an explicit valid empty list means no holdings.
- `LocalEvidenceStore(root)` methods:
  - `save_group_version(payload, validation) -> GroupVersionManifest`
  - `read_group_version(version_id) -> AcquisitionPayload`
  - `set_canonical(group_id, trade_date, version_id) -> None`
  - `canonical_manifest(group_id, trade_date) -> GroupVersionManifest | None`
  - `load_prior_sessions(group_id, before_date, limit) -> list[AcquisitionPayload]`
  - `save_checkpoint(run_id, trade_date, contract_version, stage, object_id) -> None`
  - `load_checkpoint(run_id, trade_date, contract_version, stage) -> str | None`
  - `create_reconciliation_task(backup_manifest) -> ReconciliationTask`
  - `reconcile_primary(task_id, primary_payload, validation) -> GroupVersionManifest`
- Immutable writes use exclusive creation; canonical/checkpoint pointers use temp-file + `os.replace`; no method deletes raw versions.

- [ ] **Step 1: Write atomic-failover RED tests**

```python
def test_complete_primary_succeeds_without_calling_backup(): ...
def test_transient_primary_failure_retries_before_backup(): ...
def test_partial_primary_is_discarded_and_backup_starts_empty(): ...
def test_backup_result_contains_no_primary_record_or_source_name(): ...
def test_no_provider_value_comparison_or_difference_alert_is_emitted(): ...
def test_incomplete_backup_raises_acquisition_blocked(): ...
def test_unproven_route_capability_blocks_before_fetch(): ...
```

The fake backup asserts its own call receives only `AcquisitionRequest`; it must never receive the primary payload. The no-comparison test uses deliberately different valid values and asserts success plus no warning/alert callback API exists.

- [ ] **Step 2: Run atomic RED**

Run: `.venv/bin/python -m pytest tests/test_atomic_acquisition.py -q`

Expected: collection fails on missing `stock_analyzer.data.acquisition`.

- [ ] **Step 3: Implement minimal atomic acquirer and run GREEN**

Run: `.venv/bin/python -m pytest tests/test_atomic_acquisition.py -q`

Expected: all atomic acquisition tests pass; attempts show two primary calls only for transient failure and one backup call after rejection.

- [ ] **Step 4: Write executable-route RED tests**

```python
def test_every_required_group_has_executable_primary_and_backup_or_approved_single_source(): ...
def test_each_route_calls_its_exact_endpoint_method_and_normalizes_a_complete_payload(): ...
def test_market_route_preserves_declared_units_adjustment_basis_and_82_covered_sessions(): ...
def test_official_event_route_accepts_proven_empty_coverage_but_rejects_endpoint_failure(): ...
def test_calendar_route_excuses_only_officially_suspended_or_hard_excluded_codes(): ...
def test_unknown_missing_market_code_is_not_inferred_suspended(): ...
def test_manual_holdings_route_distinguishes_explicit_empty_missing_and_malformed_files(): ...
def test_registry_contains_no_unverified_tushare_announcements_name(): ...
```

Run before implementation: `.venv/bin/python -m pytest tests/test_formal_routes.py tests/test_strategy_v2_source_registry.py -q`

Expected RED: the executable route registry is missing and the old invalid declaration remains.

Implement `formal_routes.py` and update `source_registry.py`, then run the same command.

Expected GREEN: every required group resolves to callable route objects with passing recorded-response capability evidence; no live endpoint is contacted.

- [ ] **Step 5: Write evidence-store RED tests**

```python
def test_versions_are_immutable_and_canonical_pointer_is_atomic(): ...
def test_prior_session_cache_excludes_target_date_current_facts(): ...
def test_checkpoint_resume_requires_same_run_date_and_contract_version(): ...
def test_backup_version_creates_pending_reconciliation_task(): ...
def test_recovered_primary_becomes_canonical_without_deleting_backup(): ...
def test_reconciliation_preserves_frozen_receipt_input_set_and_artifact_hashes(): ...
def test_look_ahead_financial_or_event_version_is_not_read(): ...
```

- [ ] **Step 6: Run store RED, implement store, then run GREEN**

Run before implementation: `.venv/bin/python -m pytest tests/test_evidence_store.py -q`

Expected RED: missing `stock_analyzer.storage.evidence_store`.

Run after implementation: `.venv/bin/python -m pytest tests/test_atomic_acquisition.py tests/test_formal_routes.py tests/test_strategy_v2_source_registry.py tests/test_evidence_store.py -q`

Expected GREEN: all tests pass; target-date cache reads return no payload; reconciliation keeps both raw version files.

- [ ] **Step 7: Commit**

```bash
git add src/stock_analyzer/data/acquisition.py src/stock_analyzer/data/formal_routes.py src/stock_analyzer/data/source_registry.py src/stock_analyzer/storage/evidence_store.py tests/test_atomic_acquisition.py tests/test_formal_routes.py tests/test_strategy_v2_source_registry.py tests/test_evidence_store.py
git commit -m "feat: acquire and version formal evidence atomically"
```

### Task 3: Run Receipt State Machine, Candidate Freeze, and Internal Blocked Status

**Files:**
- Create: `src/stock_analyzer/ops/formal_run.py`
- Modify: `src/stock_analyzer/storage/evidence_store.py`
- Modify: `src/stock_analyzer/ops/status.py`
- Test: `tests/test_formal_run_state.py`
- Test: `tests/test_ops_status.py`

**Interfaces:**
- `RunReceipt(run_id, target_date, report_cutoff, acquisition_contract_version, screening_version, state, group_version_ids, input_set_id, candidate_set_id, evidence_hashes, artifact_hashes, local_activation_id, ledger_activation_id)` is immutable per revision; `LocalEvidenceStore.advance_receipt(receipt, next_state, **updates)` writes an append-only revision.
- `CandidateSet(candidate_set_id, run_id, ordered_codes, active_focus_codes, screening_version, upstream_input_set_id, content_hash)` is content addressed and immutable.
- `FormalRunController.start(...)`, `record_group(...)`, `enter_ready_to_screen()`, `freeze_candidates(...)`, `enter_ready_to_analyze()`, and `block(...)` enforce the exact design transition graph.
- `write_blocked_status(log_root, receipt, group_id, attempts, reasons, operator_action) -> Path` writes both `{run_id}.json` and `latest-status.json` using redacted text and never accepts a reports path.
- Add `RunStatus.BLOCKED_NEEDS_HUMAN = "blocked_needs_human"`; existing `FAILED_NEEDS_HUMAN` remains readable for older job statuses.

- [ ] **Step 1: Write state-machine and blocked-status RED tests**

```python
def test_only_ready_to_screen_can_freeze_candidates(): ...
def test_candidate_set_is_ordered_frozen_and_resume_uses_same_id(): ...
def test_target_failure_does_not_replace_candidate_with_next_ranked_code(): ...
def test_only_ready_to_analyze_can_begin_analysis(): ...
def test_blocked_receipt_has_no_candidate_analysis_or_artifact_hashes(): ...
def test_blocked_status_is_redacted_local_only_and_contains_operator_fields(): ...
def test_blocked_retry_preserves_existing_report_and_current_pointer_bytes(): ...
```

- [ ] **Step 2: Run RED**

Run: `.venv/bin/python -m pytest tests/test_formal_run_state.py tests/test_ops_status.py -q`

Expected: missing formal-run symbols and missing `RunStatus.BLOCKED_NEEDS_HUMAN` assertions fail.

- [ ] **Step 3: Implement append-only receipts, candidate freeze, transition map, and blocked writer**

The transition map must be literal and exhaustive:

```python
ALLOWED_TRANSITIONS = {
    PENDING: {ACQUIRING_SCREENING_PRIMARY, BLOCKED_NEEDS_HUMAN},
    ACQUIRING_SCREENING_PRIMARY: {ACQUIRING_SCREENING_BACKUP, VALIDATING_SCREENING, BLOCKED_NEEDS_HUMAN},
    ACQUIRING_SCREENING_BACKUP: {VALIDATING_SCREENING, BLOCKED_NEEDS_HUMAN},
    VALIDATING_SCREENING: {READY_TO_SCREEN, BLOCKED_NEEDS_HUMAN},
    READY_TO_SCREEN: {SCREENING, BLOCKED_NEEDS_HUMAN},
    SCREENING: {TARGET_SET_FROZEN, BLOCKED_NEEDS_HUMAN},
    TARGET_SET_FROZEN: {ACQUIRING_TARGET_PRIMARY, BLOCKED_NEEDS_HUMAN},
    ACQUIRING_TARGET_PRIMARY: {ACQUIRING_TARGET_BACKUP, VALIDATING_TARGET, BLOCKED_NEEDS_HUMAN},
    ACQUIRING_TARGET_BACKUP: {VALIDATING_TARGET, BLOCKED_NEEDS_HUMAN},
    VALIDATING_TARGET: {READY_TO_ANALYZE, BLOCKED_NEEDS_HUMAN},
    READY_TO_ANALYZE: {ANALYZING, BLOCKED_NEEDS_HUMAN},
    ANALYZING: {RENDERING, ANALYSIS_COMPLETE_NO_RECOMMENDATIONS, BLOCKED_NEEDS_HUMAN},
    RENDERING: {VERIFYING, FAILED_RETRYABLE, FAILED_NEEDS_HUMAN},
    VERIFYING: {COMMITTING, FAILED_RETRYABLE, FAILED_NEEDS_HUMAN},
    COMMITTING: {REPORT_GENERATED, FAILED_RETRYABLE, FAILED_NEEDS_HUMAN},
}
```

- [ ] **Step 4: Run GREEN**

Run: `.venv/bin/python -m pytest tests/test_formal_run_state.py tests/test_ops_status.py -q`

Expected: all selected tests pass; secret-shaped strings appear only as `[redacted]`.

- [ ] **Step 5: Commit**

```bash
git add src/stock_analyzer/ops/formal_run.py src/stock_analyzer/storage/evidence_store.py src/stock_analyzer/ops/status.py tests/test_formal_run_state.py tests/test_ops_status.py
git commit -m "feat: gate formal runs with immutable receipts"
```

### Task 4: Consecutive Eligible-Day Focus History

**Files:**
- Modify: `src/stock_analyzer/analysis/focus.py`
- Modify: `src/stock_analyzer/pipeline.py`
- Modify: `src/stock_analyzer/storage/repositories.py`
- Test: `tests/test_focus_strategy_v2.py`
- Test: `tests/test_pipeline_smoke.py`

**Interfaces:**
- Add `FormalFocusDay(trade_date, formally_committed, blocked, fixture, backfill_only)`.
- Add `contiguous_focus_window(snapshots, eligible_dates, current_date) -> list[StrategyEvidenceSnapshot]`; it examines exactly the five immediately preceding eligible dates and returns an empty window if any date lacks one formally committed snapshot or is blocked/fixture/backfill-only.
- Extend `update_focus_watchlist_v2(..., eligible_focus_days: list[FormalFocusDay] | None = None)`; formal coordinator always passes the list, while fixture-only legacy tests may omit it.
- Add repository method `load_formally_committed_strategy_snapshots(before_date, eligible_dates)` to protocol, in-memory implementation, and Supabase read implementation; it reads only receipts whose dual activation markers agree.

- [ ] **Step 1: Add RED tests**

```python
def test_focus_uses_five_immediately_preceding_eligible_dates(): ...
def test_blocked_middle_day_breaks_window_instead_of_using_older_snapshot(): ...
def test_fixture_incomplete_and_backfill_only_days_do_not_count(): ...
def test_formally_committed_zero_recommendation_focus_day_counts(): ...
def test_reconciled_primary_does_not_retroactively_create_focus_observation(): ...
def test_pipeline_loads_prior_formally_committed_focus_snapshots_before_update(): ...
```

- [ ] **Step 2: Run RED**

Run: `.venv/bin/python -m pytest tests/test_focus_strategy_v2.py tests/test_pipeline_smoke.py -q`

Expected: new tests fail because current `_system_focus_candidates` uses the last five available snapshots and can skip missing dates.

- [ ] **Step 3: Implement exact-date window and repository read**

Do not change `_is_supportive`, `MIN_SUPPORTIVE_OBSERVATIONS = 3`, `SUPPORTIVE_OBSERVATION_WINDOW = 5`, ranking, action, or position behavior. Replace only the snapshot selection boundary for formal runs.

- [ ] **Step 4: Run GREEN**

Run: `.venv/bin/python -m pytest tests/test_focus_strategy_v2.py tests/test_pipeline_smoke.py tests/test_repositories.py -q`

Expected: all selected tests pass and existing Phase 3 focus assertions remain unchanged.

- [ ] **Step 5: Commit**

```bash
git add src/stock_analyzer/analysis/focus.py src/stock_analyzer/pipeline.py src/stock_analyzer/storage/repositories.py tests/test_focus_strategy_v2.py tests/test_pipeline_smoke.py tests/test_repositories.py
git commit -m "fix: require contiguous committed focus history"
```

### Task 5: Two-Phase Formal Activation and Narrow-Ledger Transaction

**Files:**
- Create: `src/stock_analyzer/ops/activation.py`
- Modify: `src/stock_analyzer/storage/repositories.py`
- Create: `supabase/migrations/202607100004_formal_run_readiness.sql`
- Test: `tests/test_formal_activation.py`
- Modify: `tests/test_repositories.py`
- Modify: `tests/test_supabase_schema.py`

**Interfaces:**
- `FormalLedger` protocol methods `prepare_formal_run(run_id, receipt_hash, rows) -> pending_id`, `pending_hash(pending_id) -> str`, `activate_formal_run(run_id, pending_id, activation_id) -> None`, `is_formal_run_active(run_id, activation_id) -> bool`, and `discard_pending(pending_id) -> None`.
- `InMemoryFormalLedger` keeps pending rows invisible from all existing load methods until activation.
- `SupabaseAnalysisRepository` implements prepare/activate with RPC `activate_formal_run_v1`; the RPC locks the receipt row, verifies pending/receipt hashes, inserts narrow decision rows, writes the ledger marker, and marks the receipt committed in one transaction.
- `FormalActivationCoordinator.activate(receipt, render, verify, ledger_rows, pointer_paths) -> RunReceipt` stages under `{report_root}/.staging/{run_id}`, records hashes, verifies linkage, prepares pending ledger rows, writes a local marker, activates the ledger, requires marker agreement, then atomically advances local/current and publish-candidate pointers.
- `ActivationFailurePoint` allows deterministic test injection at `render`, `verify`, `ledger_prepare`, `local_marker`, `ledger_activate`, and `pointer`.
- Formal readers call `activation_markers_agree(receipt, ledger)`, otherwise they ignore both staged artifacts and pending rows.

- [ ] **Step 1: Write activation RED tests**

```python
def test_pending_ledger_rows_are_invisible_until_both_markers_agree(): ...
@pytest.mark.parametrize("failure_point", ["render", "verify", "ledger_prepare", "local_marker", "ledger_activate", "pointer"])
def test_each_activation_failure_preserves_prior_report_ledger_and_pointers(failure_point): ...
def test_retry_is_idempotent_and_does_not_duplicate_rows_or_artifacts(): ...
def test_artifact_or_pending_hash_mismatch_fails_closed(): ...
def test_zero_recommendations_commits_focus_rows_without_advancing_report_pointer(): ...
```

- [ ] **Step 2: Run RED**

Run: `.venv/bin/python -m pytest tests/test_formal_activation.py -q`

Expected: missing activation module.

- [ ] **Step 3: Implement local coordinator and in-memory ledger; run GREEN**

Run: `.venv/bin/python -m pytest tests/test_formal_activation.py tests/test_repositories.py -q`

Expected: all failure injections leave the sentinel prior report and pointer bytes unchanged; retry produces one activated batch.

- [ ] **Step 4: Add SQL migration and schema/RPC tests**

Migration must create only narrow metadata/decision activation structures, use RLS/service-role policy consistent with existing migrations, and contain one `security definer` transaction function with a fixed `search_path`. Tests named:

```python
def test_formal_readiness_migration_adds_receipts_pending_batches_markers_and_reconciliation(): ...
def test_activation_rpc_verifies_hashes_and_activates_in_one_transaction(): ...
def test_formal_readiness_schema_does_not_add_wide_market_payload_columns(): ...
```

Run: `.venv/bin/python -m pytest tests/test_supabase_schema.py tests/test_repositories.py tests/test_formal_activation.py -q`

Expected: all pass without opening a Supabase connection.

- [ ] **Step 5: Commit**

```bash
git add src/stock_analyzer/ops/activation.py src/stock_analyzer/storage/repositories.py supabase/migrations/202607100004_formal_run_readiness.sql tests/test_formal_activation.py tests/test_repositories.py tests/test_supabase_schema.py
git commit -m "feat: activate formal reports and ledger atomically"
```

### Task 6: Formal Pipeline, Manual Render Receipt Gate, and Production Fail-Closed Wiring

**Files:**
- Modify: `src/stock_analyzer/ops/formal_run.py`
- Modify: `src/stock_analyzer/pipeline.py`
- Modify: `src/stock_analyzer/cli.py`
- Modify: `src/stock_analyzer/ops/job.py`
- Modify: `src/stock_analyzer/ops/verify.py`
- Modify: `src/stock_analyzer/ops/artifacts.py`
- Test: `tests/test_formal_pipeline.py`
- Modify: `tests/test_pipeline_smoke.py`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_ops_job.py`
- Modify: `tests/test_ops_artifacts.py`

**Interfaces:**
- `FormalPipelineDependencies(screening_routes, target_routes, screen, analyze, llm_express, render, verify, ledger, evidence_store, log_root)` is fully injectable for offline tests.
- `run_formal_strategy_v2(trade_date, report_cutoff, dependencies, run_id=None) -> FormalRunResult`:
  1. acquires/validates all screening groups;
  2. enters `READY_TO_SCREEN`;
  3. calls only deterministic `screen`;
  4. freezes candidate set;
  5. acquires/validates all target groups for exact frozen candidates plus active/manual focus codes;
  6. enters `READY_TO_ANALYZE`;
  7. calls existing Strategy V2 structured analysis then optional LLM expression;
  8. returns `ANALYSIS_COMPLETE_NO_RECOMMENDATIONS` or performs two-phase activation to `REPORT_GENERATED`.
- `render_report_for_date(..., receipt_store: LocalEvidenceStore | None = None, expected_input_set_id: str | None = None)` rejects missing, blocked, uncommitted, hash-incomplete, or input-mismatched receipts before reading repository analysis rows.
- `ops.artifacts.prepare_pages_artifact` and `ops.verify.verify_production_result` accept only an activated `REPORT_GENERATED` receipt; `.staging`, blocked logs, and pending markers are excluded from deploy artifacts.
- `_default_run_daily` uses the formal entry and never sets `allow_data_insufficient_output=True`. A readiness block returns `RunStatus.BLOCKED_NEEDS_HUMAN`, skips verify/deploy/publish, and writes only internal status/notification.

- [ ] **Step 1: Write gate and call-order RED tests**

```python
def test_screening_gate_cannot_call_analysis_llm_render_or_ledger(): ...
def test_target_failure_for_frozen_candidate_blocks_without_promotion(): ...
def test_required_group_failure_calls_no_strategy_llm_report_publish_or_decision_write(): ...
def test_complete_run_calls_analysis_only_after_ready_to_analyze(): ...
def test_manual_render_rejects_missing_blocked_uncommitted_and_mismatched_receipts(): ...
def test_manual_render_accepts_only_matching_committed_report_generated_receipt(): ...
def test_blocked_job_skips_verify_prepare_deploy_and_publish(): ...
def test_deploy_artifact_excludes_blocked_status_staging_and_pending_content(): ...
```

- [ ] **Step 2: Run RED slices**

Run: `.venv/bin/python -m pytest tests/test_formal_pipeline.py tests/test_pipeline_smoke.py tests/test_cli.py tests/test_ops_job.py tests/test_ops_artifacts.py -q`

Expected: new formal symbols/receipt requirements fail; existing production-insufficient tests expose the old public `data_insufficient` behavior.

- [ ] **Step 3: Implement coordinator call order and formal pipeline wrapper**

Every callback records the receipt state it observes. Tests assert `screen == READY_TO_SCREEN`, `analyze == READY_TO_ANALYZE/ANALYZING`, `llm_express == ANALYZING`, `render == RENDERING`, and no downstream callback occurs after `AcquisitionBlocked`.

- [ ] **Step 4: Implement receipt-gated render and job/artifact/verification fail-closed changes**

Keep fixture reports available only through explicit fixture mode. Remove `allow_data_insufficient_output` from production scheduler use; keep the old function parameter temporarily for fixture/backward-compatible unit tests but raise `ProductionDataSourceUnavailable` whenever `fixture_mode=False`.

- [ ] **Step 5: Run GREEN slices**

Run: `.venv/bin/python -m pytest tests/test_formal_pipeline.py tests/test_pipeline_smoke.py tests/test_cli.py tests/test_ops_job.py tests/test_ops_artifacts.py -q`

Expected: all selected tests pass; no test creates production credentials, network calls, Supabase writes, or deploys.

- [ ] **Step 6: Commit**

```bash
git add src/stock_analyzer/ops/formal_run.py src/stock_analyzer/pipeline.py src/stock_analyzer/cli.py src/stock_analyzer/ops/job.py src/stock_analyzer/ops/verify.py src/stock_analyzer/ops/artifacts.py tests/test_formal_pipeline.py tests/test_pipeline_smoke.py tests/test_cli.py tests/test_ops_job.py tests/test_ops_artifacts.py
git commit -m "fix: close formal report readiness escape paths"
```

### Task 7: July 10 Offline Acceptance, Operations Documentation, and Final Review Fixes

**Files:**
- Create: `tests/test_july10_formal_readiness_acceptance.py`
- Modify: `docs/operations/runbook.md`
- Modify: `docs/operations/mandatory-next-phases.md`
- Modify only files required by Critical/Important final-review findings.

**Interfaces:**
- Recorded/synthetic `July10FixtureRoutes` return 82-session screening data and complete target evidence without network access.
- `AcceptanceCallRecorder` records route, screen, analysis, LLM, render, verify, ledger, pointer, and publish calls so absence is assertable.

- [ ] **Step 1: Write the seven acceptance tests**

```python
def test_july10_complete_82_session_path_generates_formal_strategy_v2_report(): ...
def test_july10_partial_primary_is_discarded_and_complete_backup_alone_supports_report(): ...
def test_july10_incomplete_primary_and_backup_block_without_analysis_or_report(): ...
def test_july10_recovered_primary_becomes_canonical_without_rewriting_frozen_report(): ...
def test_july10_focus_history_breaks_on_blocked_eligible_day(): ...
def test_july10_direct_render_rejects_rows_without_committed_receipt(): ...
@pytest.mark.parametrize("failure_point", ["render", "verify", "ledger_prepare", "pointer"])
def test_july10_atomic_failures_preserve_all_formal_consumers(failure_point): ...
```

The complete-path report assertions must also prove: every required manifest is complete; evidence resolves to exact versions; no fixture/sample marker; no user-facing numeric total score; and every focus action contains decision, position range, reasons, confirmation, invalidation, and risk-if-wrong.

- [ ] **Step 2: Run acceptance RED then GREEN**

Run before final fixture/coordinator adjustments: `.venv/bin/python -m pytest tests/test_july10_formal_readiness_acceptance.py -q`

Expected RED: at least the first not-yet-covered end-to-end assertion fails for the exact missing integration.

Make the minimal integration change, then run the same command.

Expected GREEN: all seven scenarios (including parametrized atomic failures) pass offline.

- [ ] **Step 3: Document exact operator behavior**

Add commands for reading `logs/run-daily/latest-status.json`, locating a run receipt/candidate set, checking both activation markers, listing pending reconciliation tasks, and invoking offline acceptance. State explicitly that blocked runs preserve the prior published report, backup use creates reconciliation work but no source-difference warning, and live acquisition/Supabase/Cloudflare remain separately approval-gated.

- [ ] **Step 4: Run focused regression set**

Run: `.venv/bin/python -m pytest tests/test_formal_readiness_contracts.py tests/test_atomic_acquisition.py tests/test_evidence_store.py tests/test_formal_run_state.py tests/test_formal_activation.py tests/test_formal_pipeline.py tests/test_july10_formal_readiness_acceptance.py tests/test_focus_strategy_v2.py tests/test_pipeline_smoke.py tests/test_ops_job.py tests/test_report_generation.py tests/test_repositories.py tests/test_supabase_schema.py -q`

Expected: all focused tests pass.

- [ ] **Step 5: Commit acceptance and docs**

```bash
git add tests/test_july10_formal_readiness_acceptance.py docs/operations/runbook.md docs/operations/mandatory-next-phases.md
git commit -m "test: accept july 10 formal report readiness"
```

- [ ] **Step 6: Perform read-only final review**

Review exact range `6ce0dec..HEAD` against this plan and the approved design using `git diff --check`, `git diff --stat 6ce0dec..HEAD`, `git diff 6ce0dec..HEAD -- src tests supabase docs/operations`, and targeted `rg` scans for `data_insufficient`, direct report writes, pointer writes, source merging, fixture markers, and secret-shaped literals. Categorize findings as Critical/Important/Minor. Fix every Critical and Important finding with a failing regression test first; record Minor findings in the final handoff only when they are genuinely out of scope.

- [ ] **Step 7: Commit review fixes if any**

```bash
git add -u
git commit -m "fix: address formal readiness final review"
```

- [ ] **Step 8: Fresh verification before completion**

Run exactly once as the final full suite: `.venv/bin/python -m pytest -q`

Expected: all tests pass, zero failures. Also run:

```bash
git diff --check
git status --short --branch
git log --oneline --decorate 6ce0dec..HEAD
```

Expected: no whitespace errors; branch is `codex/v3-mvp`; worktree is clean after the final verification commit.

- [ ] **Step 9: Push only after all gates pass**

Run: `git push origin codex/v3-mvp`

Expected: push succeeds without force and updates `origin/codex/v3-mvp` to local `HEAD`. Re-run `git status --short --branch` and expect no ahead/behind marker and no working-tree entries.

## Plan Self-Review Record

- Spec coverage: Tasks 1-2 cover contracts, exact executable adapters for every required group, recorded capability evidence, 82 sessions, atomic failover, edge-case coverage, cache, point-in-time rules, and reconciliation; Tasks 3 and 6 cover two readiness gates, frozen candidates, receipts, blocked operation, and manual render; Task 4 covers contiguous focus history; Task 5 covers two-phase activation/narrow ledger; Task 7 covers every July 10 scenario, documentation, final review, full suite, clean tree, and push.
- Placeholder scan: no placeholder marker, deferred implementation phrase, unnamed error-handling step, unspecified test step, or shell-path substitution remains.
- Type consistency: `AcquisitionRequest`, `AcquisitionPayload`, `GroupValidation`, `RunReceipt`, `CandidateSet`, `LocalEvidenceStore`, `FormalLedger`, `FormalActivationCoordinator`, `FormalPipelineDependencies`, and `FormalFocusDay` retain the same names and roles across all tasks.
- Scope control: no Strategy V2 scoring, recommendation logic, action/position rule, LLM content rule, report layout redesign, live provider call, production write, deployment, broker link, or order feature is introduced.
