# V3 Formal Production Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task in the current main-agent context. Do not use `subagent-driven-development`. A subagent is optional only for an independent read-only final review when GPT-5.6 sol, high reasoning, standard speed can be guaranteed.

**Goal:** Admit a precise official-announcement backup route, complete the real 2026-07-10 formal run, atomically activate its Supabase decision rows and report, publish it, activate daily automation, and push a fully verified clean branch.

**Architecture:** Tushare remains the preferred event source but receives no live capability when `anns_d` is denied. A new direct CNINFO backup route independently refetches authorized Tushare status facts and raw CNINFO disclosures, preserves epoch-millisecond publication times, and is admitted only after separate populated and empty live probes. Existing readiness, candidate-freeze, Strategy V2, report, two-phase ledger, and publication components remain unchanged except for stronger capability and activation read-back evidence.

**Tech Stack:** Python 3.11-compatible application code, Pydantic v2, pandas, httpx, Tushare Pro, CNINFO public disclosure JSON, Supabase/Postgres, Typer, pytest, launchd, Cloudflare Pages/Wrangler.

## Global Constraints

- The active normative design is `docs/superpowers/specs/2026-07-10-v3-formal-report-data-readiness-design.md`, including its 2026-07-11 production-completion amendment.
- Never read, print, log, persist, or include `.env.local`, tokens, passwords, service-role keys, or credential values in tool output, evidence, reports, commits, or deployment artifacts.
- Provider reads, the formal 2026-07-10 run, Supabase narrow formal writes, first Cloudflare publication, and launchd activation are authorized only in the Gate order in this plan.
- Broker connectivity and order operations remain prohibited.
- A required-data failure stops before Strategy V2 analysis, LLM expression, report generation, ledger activation, or publication.
- Primary and backup are complete routes. The backup starts from the original request and never reuses a row from the rejected primary payload.
- Runtime dates, report cutoff, candidate codes, personal paths, provider credentials, deployment IDs, and scheduler identities must come from request/configuration/runtime discovery, not production literals.
- Approved named policy defaults may live only in `formal_policy.py`; provider URLs and rate/timeout controls must be configuration-backed.
- Tushare pacing remains endpoint-aware and honors the documented account frequency tier. CNINFO uses a conservative configurable default and bounded retry; HTTP 429 is retryable, schema/time ambiguity is permanent.
- The initial target remains the exact 82 official sessions from 2026-03-12 through 2026-07-10. Existing immutable versions are reused only when their contract and content hashes validate.
- No new strategy, position, LLM-content, report-layout, broker, or order behavior is in scope.
- Every code task follows red-green-refactor, runs its named tests, and ends at the stated commit boundary.

## File and Interface Map

- `src/stock_analyzer/data/readiness.py`: persist route-specific semantic probe hashes in `RouteCapabilityEvidence`.
- `src/stock_analyzer/data/capability_store.py`: reject event capability without populated and empty proof.
- `src/stock_analyzer/data/formal_policy.py`: named CNINFO request-rate and retry defaults.
- `src/stock_analyzer/config.py`: environment-backed CNINFO base URL, timeout, and call-rate configuration.
- `src/stock_analyzer/data/tushare_formal_client.py`: expose a complete status-only event component reused by both event recipes.
- `src/stock_analyzer/data/cninfo_disclosure_client.py`: direct raw CNINFO adapter, pagination, exact time conversion, category dedupe, coverage, semantic probes, and failure classification.
- `src/stock_analyzer/data/formal_routes.py`: bind `cninfo.direct.events_risk.v2` to a dedicated event-backup owner.
- `src/stock_analyzer/ops/production_dependencies.py`: build an injected `httpx.Client` and direct CNINFO event client.
- `src/stock_analyzer/ops/formal_live.py`: issue event capability only after two distinct semantic probes and the full contract pass.
- `src/stock_analyzer/storage/repositories.py`: verify active receipt and active decision-row hashes after RPC activation.
- `src/stock_analyzer/ops/activation.py`: require strong ledger read-back before pointer activation.
- `tests/test_cninfo_disclosure_client.py`: direct adapter contract tests.
- Existing focused tests: update capability, route, dependency, live, activation, repository, default-entry, configuration, and July 10 acceptance coverage.
- `docs/operations/production-capability-matrix.md`, `docs/operations/runbook.md`, and `docs/operations/cloudflare-pages.md`: record only evidence actually obtained.

---

### Task 1: Make event capability evidence impossible to infer from an empty response

**Files:**
- Modify: `src/stock_analyzer/data/readiness.py`
- Modify: `src/stock_analyzer/data/capability_store.py`
- Modify: `tests/test_capability_store.py`
- Modify: `tests/test_formal_routes.py`
- Modify: `tests/test_production_dependencies.py`
- Modify: `tests/test_formal_pipeline.py`
- Modify: `tests/test_july10_formal_readiness_acceptance.py`

**Interfaces:**
- Produces: `RouteCapabilityEvidence.semantic_probe_hashes: dict[str, str]`
- Required event keys: `populated_precise_time` and `empty_coverage`
- Each value: lowercase 64-character SHA-256 digest of redacted normalized probe content

- [ ] **Step 1: Write the failing capability tests**

Add these named tests:

```python
def test_event_capability_requires_distinct_populated_and_empty_probe_hashes(): ...
def test_non_event_capability_does_not_require_event_probe_hashes(): ...
def test_capability_store_rejects_malformed_semantic_probe_hash(): ...
```

The first test constructs an otherwise complete `OFFICIAL_EVENTS_RISK` capability with `{}` and with only one key and asserts `approved is False`; it then supplies two distinct nonzero SHA-256 values and asserts `approved is True`. The third persists a non-hex or all-zero probe digest and expects `CapabilityEvidenceError` containing `semantic probe hash`.

- [ ] **Step 2: Run the tests and prove red**

Run:

```bash
.venv/bin/python -m pytest tests/test_capability_store.py tests/test_formal_routes.py -q
```

Expected: FAIL because `semantic_probe_hashes` is absent and event evidence is still approved without two probes.

- [ ] **Step 3: Implement the evidence rule**

Add the frozen model field and conditional approval:

```python
semantic_probe_hashes: dict[str, str] = Field(default_factory=dict)

def _event_semantics_approved(self) -> bool:
    if self.group_id is not AcquisitionGroupId.OFFICIAL_EVENTS_RISK:
        return True
    required = {"populated_precise_time", "empty_coverage"}
    values = {self.semantic_probe_hashes.get(key) for key in required}
    return None not in values and len(values) == 2
```

Include `_event_semantics_approved()` in `approved`. In capability-store validation, require both keys, validate `_SHA256`, reject all-zero values, and reject identical populated/empty hashes.

Update every existing recorded event-capability fixture in the listed tests with two distinct deterministic nonzero hashes. Do not add hashes to production `_route_evidence()` in this task; live and recorded bootstrap evidence must come from the provider-specific probe implemented in Task 4.

- [ ] **Step 4: Run the focused tests and prove green**

Run the Step 2 command.

Expected: PASS.

- [ ] **Step 5: Commit the evidence boundary**

```bash
git add src/stock_analyzer/data/readiness.py src/stock_analyzer/data/capability_store.py tests/test_capability_store.py tests/test_formal_routes.py tests/test_production_dependencies.py tests/test_formal_pipeline.py tests/test_july10_formal_readiness_acceptance.py docs/superpowers/plans/2026-07-11-v3-formal-production-completion.md
git commit -m "fix: require event semantic probe evidence"
```

---

### Task 2: Implement the complete direct CNINFO event backup route

**Files:**
- Create: `src/stock_analyzer/data/cninfo_disclosure_client.py`
- Create: `tests/test_cninfo_disclosure_client.py`
- Modify: `src/stock_analyzer/data/tushare_formal_client.py`
- Modify: `tests/test_tushare_formal_client.py`
- Modify: `src/stock_analyzer/data/formal_policy.py`
- Modify: `src/stock_analyzer/config.py`
- Modify: `tests/test_config_health.py`

**Interfaces:**
- `TushareFormalEndpointClient.fetch_official_status_risk(request) -> EndpointResponse`
- `TushareFormalEndpointClient.verify_event_semantics(request) -> dict[str, str]`
- `CninfoDisclosureClient(status_client, http_client, *, base_url, calls_per_minute, timeout_seconds, max_retries)`
- `CninfoDisclosureClient.fetch_official_events_risk(request) -> EndpointResponse`
- `CninfoDisclosureClient.verify_event_semantics(request) -> dict[str, str]`
- CNINFO endpoints: `GET /new/data/szse_stock.json`; `POST /new/hisAnnouncement/query`
- Risk category codes: generic `""`, risk warning `category_fxts_szsh`, special treatment/delisting `category_tbclts_szsh`, delisting period `category_tszlq_szsh`

- [ ] **Step 1: Write failing status-component tests**

Add:

```python
def test_tushare_status_risk_component_never_calls_anns_d(): ...
def test_tushare_full_event_route_combines_fresh_status_with_anns_d(): ...
def test_tushare_event_semantic_probe_requires_populated_and_valid_empty_cases(): ...
```

The first asserts exact calls `trade_cal`, `suspend_d`, `stock_basic`, complete target coverage, and no `anns_d`. The second asserts the existing full primary route calls `fetch_official_status_risk` behavior and then `anns_d` without reusing caller-provided rows. The third uses one date-wide populated `anns_d` response and one valid-code empty response, then proves permission, date-only, or empty-only results cannot issue semantic hashes.

- [ ] **Step 2: Write failing direct-CNINFO tests**

Create deterministic fake HTTP responses and these tests:

```python
def test_cninfo_route_preserves_epoch_milliseconds_and_filters_after_cutoff(): ...
def test_cninfo_route_paginates_each_code_and_category_and_deduplicates_id(): ...
def test_cninfo_route_refetches_status_and_never_reuses_primary_payload(): ...
def test_cninfo_route_proves_valid_code_empty_coverage(): ...
def test_cninfo_route_rejects_missing_stock_map_code(): ...
def test_cninfo_route_rejects_date_string_missing_or_malformed_timestamp(): ...
def test_cninfo_route_rejects_wrong_code_date_duplicate_or_missing_pdf(): ...
def test_cninfo_route_classifies_429_as_transient_and_schema_as_permanent(): ...
def test_cninfo_semantic_probe_requires_non_midnight_populated_and_real_empty_case(): ...
def test_cninfo_pacer_waits_at_configured_limit_without_busy_loop(): ...
```

The precise sample uses raw `1783677605123` and asserts Asia/Shanghai conversion retains seconds and milliseconds. The after-cutoff row is excluded. Empty proof uses a valid code from `stockList`, `totalAnnouncement == 0`, and `announcements == []`; an unknown fabricated code is rejected before query.

- [ ] **Step 3: Run and prove red**

```bash
.venv/bin/python -m pytest tests/test_cninfo_disclosure_client.py tests/test_tushare_formal_client.py tests/test_config_health.py -q
```

Expected: FAIL because the direct client, status-only method, and CNINFO configuration do not exist.

- [ ] **Step 4: Add named policy and runtime configuration**

Add to `formal_policy.py`:

```python
CNINFO_DEFAULT_CALLS_PER_MINUTE = 20
CNINFO_RATE_LIMIT_WINDOW_SECONDS = 60.0
CNINFO_DEFAULT_TIMEOUT_SECONDS = 20.0
CNINFO_DEFAULT_MAX_RETRIES = 2
```

Add `AppConfig` fields loaded from `CNINFO_BASE_URL`, `CNINFO_CALLS_PER_MINUTE`, `CNINFO_TIMEOUT_SECONDS`, and `CNINFO_MAX_RETRIES`, with positive-value validation and default base URL `https://www.cninfo.com.cn`. Tests assert defaults, overrides, invalid zero/negative rejection, and serialized output contains no credential.

- [ ] **Step 5: Extract the complete Tushare status component**

Move the existing `suspend_d` and `stock_basic` record construction into `fetch_official_status_risk()`. `fetch_official_events_risk()` must call that method, fetch `anns_d`, and return a newly assembled `EndpointResponse`. Do not accept an existing payload parameter.

Implement `verify_event_semantics()` for the future authorized Tushare primary: use a date-wide `anns_d` query to prove at least one populated `rec_time` with sub-day precision, use valid codes returned by `stock_basic` to find a provider-confirmed empty window within 20 deterministic candidates, and return the same two named hashes as CNINFO. The currently denied account must fail with `PERMISSION` and receive no evidence.

- [ ] **Step 6: Implement direct CNINFO transport, normalization, and probes**

The production code must:

```python
raw_ms = int(row["announcementTime"])
published_at = datetime.fromtimestamp(raw_ms / 1000, tz=timezone.utc)
published_at = published_at.astimezone(request.report_cutoff.tzinfo)
```

It must validate `totalAnnouncement`, page count, list types, code equality, stable `announcementId`, `adjunctUrl`, and raw numeric timestamp; query every requested code and every declared category; deduplicate by announcement ID while retaining `hard_risk=True` when any risk-category query contains the ID; join freshly fetched status records; and return coverage only after every code/category page succeeds.

`verify_event_semantics()` must query a populated all-market page for the target date until it observes a valid non-midnight raw timestamp, then select valid stock-map codes deterministically and query the target date until one provider-confirmed empty result is found within 20 codes. It returns SHA-256 hashes of normalized redacted response facts and raises `PermanentRouteFailure(INVALID_SEMANTICS)` if either proof is unavailable.

- [ ] **Step 7: Run focused tests and prove green**

Run the Step 3 command.

Expected: PASS.

- [ ] **Step 8: Commit the complete provider adapter**

```bash
git add src/stock_analyzer/data/cninfo_disclosure_client.py src/stock_analyzer/data/tushare_formal_client.py src/stock_analyzer/data/formal_policy.py src/stock_analyzer/config.py tests/test_cninfo_disclosure_client.py tests/test_tushare_formal_client.py tests/test_config_health.py
git commit -m "feat: add precise direct cninfo event route"
```

---

### Task 3: Bind the dedicated event backup without changing other backup groups

**Files:**
- Modify: `src/stock_analyzer/data/formal_routes.py`
- Modify: `src/stock_analyzer/ops/production_dependencies.py`
- Modify: `tests/test_formal_routes.py`
- Modify: `tests/test_production_dependencies.py`

**Interfaces:**
- Route ID: `cninfo.direct.events_risk.v2`
- `build_formal_route_registry(..., *, events_backup_client: FormalEndpointClient | None = None, require_live_capability=False)`
- `ProductionExternalRuntime.cninfo_http_client: Any`

- [ ] **Step 1: Write failing ownership and factory tests**

Add:

```python
def test_registry_binds_only_event_backup_to_dedicated_owner(): ...
def test_default_runtime_builds_cninfo_http_client_without_secret_headers(): ...
def test_factory_uses_direct_cninfo_for_event_backup_and_akshare_elsewhere(): ...
```

The first invokes every route and proves only `OFFICIAL_EVENTS_RISK` reaches the dedicated owner. The runtime test inspects header names and configuration values but never credential values.

- [ ] **Step 2: Run and prove red**

```bash
.venv/bin/python -m pytest tests/test_formal_routes.py tests/test_production_dependencies.py -q
```

Expected: FAIL because the dedicated owner, runtime client, and v2 route ID are absent.

- [ ] **Step 3: Change route identity and dependency assembly**

Replace only the event backup route ID. Default `events_backup_client` to the general backup client for fixture compatibility; production passes `CninfoDisclosureClient`. Build `httpx.Client` with configured base URL, timeout, `User-Agent`, `Referer`, and JSON accept headers. Do not include Tushare, Supabase, Cloudflare, or report credentials in this client.

- [ ] **Step 4: Run and prove green**

Run the Step 2 command.

Expected: PASS.

- [ ] **Step 5: Commit production wiring**

```bash
git add src/stock_analyzer/data/formal_routes.py src/stock_analyzer/ops/production_dependencies.py tests/test_formal_routes.py tests/test_production_dependencies.py
git commit -m "feat: wire dedicated cninfo event backup"
```

---

### Task 4: Require dual live semantic probes before issuing event capability

**Files:**
- Modify: `src/stock_analyzer/ops/formal_live.py`
- Modify: `tests/test_formal_live.py`
- Modify: `tests/test_default_formal_production_entry.py`
- Modify: `src/stock_analyzer/data/source_registry.py`
- Modify: `tests/test_strategy_v2_source_registry.py`

**Interfaces:**
- `_route_evidence(..., semantic_probe_hashes: dict[str, str] | None = None) -> RouteCapabilityEvidence`
- Event evidence receives exactly the hashes returned by `verify_event_semantics()`.

- [ ] **Step 1: Write failing live-Gate tests**

Add:

```python
def test_live_event_capability_requires_populated_and_empty_semantic_probes(): ...
def test_denied_anns_d_issues_no_primary_event_capability_but_admits_cninfo_v2(): ...
def test_failed_event_probe_revokes_only_latest_event_route_and_preserves_history(): ...
def test_empty_contract_response_cannot_set_field_semantics_verified(): ...
```

The denied-primary test expects `official.events_risk.v1` absent, `cninfo.direct.events_risk.v2` present, and two distinct probe hashes. The failed-probe test expects `latest.json` to exclude every event route, the immutable prior version to remain, and no report/ledger calls.

- [ ] **Step 2: Run and prove red**

```bash
.venv/bin/python -m pytest tests/test_formal_live.py tests/test_default_formal_production_entry.py -q
```

Expected: FAIL because live verification does not call or persist route-specific semantic probes.

- [ ] **Step 3: Implement event-specific live verification**

Instantiate the direct CNINFO owner separately from AkShare. Before issuing evidence for either primary or backup event route, call that exact owner's `verify_event_semantics()` with the frozen capability request. Pass only its returned hashes into `_route_evidence`. Never synthesize hashes for an empty response, and never copy probe hashes between routes. Continue storing partial latest bundles on failure.

Replace the revoked event backup route ID in the Strategy V2 source registry with `cninfo.direct.events_risk.v2`; source-policy metadata and executable route definitions must identify the same route.

- [ ] **Step 4: Run and prove green**

Run the Step 2 command.

Expected: PASS.

- [ ] **Step 5: Commit live admission**

```bash
git add src/stock_analyzer/ops/formal_live.py src/stock_analyzer/data/source_registry.py tests/test_formal_live.py tests/test_default_formal_production_entry.py tests/test_strategy_v2_source_registry.py tests/test_production_dependencies.py tests/test_tushare_formal_client.py docs/superpowers/plans/2026-07-11-v3-formal-production-completion.md
git commit -m "fix: harden live event capability admission"
```

---

### Task 5: Prove atomic event failover through the unchanged formal pipeline

**Files:**
- Modify: `tests/test_july10_formal_readiness_acceptance.py`
- Modify: `tests/test_default_formal_production_entry.py`
- Modify: `tests/test_formal_pipeline.py`

**Interfaces:**
- No production interface change.
- Acceptance inspects route IDs, input-set versions, call order, artifact reachability, and ledger activation.

- [ ] **Step 1: Add the three exact acceptance scenarios**

```python
def test_july10_denied_anns_d_uses_complete_cninfo_group_without_primary_rows(): ...
def test_july10_invalid_cninfo_time_blocks_before_analysis_llm_report_and_ledger(): ...
def test_july10_cninfo_empty_coverage_still_allows_formal_analysis(): ...
```

Assert that the successful backup group contains only the declared backup recipe source names, the primary attempt is recorded as failed, candidate IDs are unchanged, and no primary payload row appears in the backup version. The invalid-time test asserts byte-for-byte unchanged active report pointers.

- [ ] **Step 2: Run and prove red if any path still depends on the revoked route**

```bash
.venv/bin/python -m pytest tests/test_july10_formal_readiness_acceptance.py tests/test_default_formal_production_entry.py tests/test_formal_pipeline.py -q
```

Expected before fixture updates: FAIL on old route ID or missing direct-client fixture. Expected after minimal fixture binding: PASS without production behavior beyond Tasks 1-4.

- [ ] **Step 3: Update only recorded transport fixtures and expected route IDs**

Recorded fixtures must expose raw CNINFO keys and milliseconds, not already-normalized datetimes. Do not monkeypatch `build_production_formal_dependencies`, the coordinator, Strategy V2, report renderer, ledger, or capability store.

- [ ] **Step 4: Run and prove green**

Run the Step 2 command.

Expected: PASS.

- [ ] **Step 5: Commit end-to-end failover proof**

```bash
git add tests/test_july10_formal_readiness_acceptance.py tests/test_default_formal_production_entry.py tests/test_formal_pipeline.py
git commit -m "test: prove precise event failover end to end"
```

---

### Task 6: Strengthen Supabase activation read-back before report pointers move

**Files:**
- Modify: `src/stock_analyzer/ops/activation.py`
- Modify: `src/stock_analyzer/storage/repositories.py`
- Modify: `src/stock_analyzer/ops/production_dependencies.py`
- Modify: `tests/test_formal_activation.py`
- Modify: `tests/test_repositories.py`

**Interfaces:**
- Add `FormalLedger.verify_formal_run_active(run_id, activation_id, receipt_hash, rows_hash) -> bool`.
- `SupabaseAnalysisRepository.verify_formal_run_active()` reads `active_formal_run_receipt`, `active_formal_decision_row`, and the active pending batch; it recomputes the active rows hash and compares all four identifiers/hashes.
- `hash_ledger_rows()` and `_formal_rows_sha256()` hash canonical rows in declared tuple/`row_ordinal` order; changing ordinals changes the hash.

- [ ] **Step 1: Write failing hash-read-back tests**

Add:

```python
def test_supabase_activation_readback_requires_matching_receipt_and_rows_hashes(): ...
def test_supabase_activation_readback_rejects_missing_extra_or_reordered_rows(): ...
def test_coordinator_does_not_move_local_pointer_when_strong_readback_fails(): ...
```

Each failure asserts the previous report pointer and formal consumer remain unchanged.

- [ ] **Step 2: Run and prove red**

```bash
.venv/bin/python -m pytest tests/test_repositories.py tests/test_formal_activation.py -q
```

Expected: FAIL because only run/activation identity is currently checked.

- [ ] **Step 3: Implement strong read-back**

Select the active receipt by both identifiers, compare its `receipt_hash`, fetch active rows ordered by `row_ordinal`, recompute `_formal_rows_sha256`, and compare the active pending batch `rows_hash`. The coordinator must call this method after RPC completion and before local/current/published pointer activation. Keep `is_formal_run_active()` as the read-only history predicate, not the activation commit proof.

Add `verify_formal_run_active` to `_require_formal_ledger()` so the default production factory fails before acquisition when a ledger cannot provide strong read-back.

- [ ] **Step 4: Run and prove green**

Run the Step 2 command.

Expected: PASS.

- [ ] **Step 5: Commit atomic read-back**

```bash
git add src/stock_analyzer/ops/activation.py src/stock_analyzer/storage/repositories.py src/stock_analyzer/ops/production_dependencies.py tests/test_formal_activation.py tests/test_repositories.py tests/test_production_dependencies.py docs/superpowers/plans/2026-07-11-v3-formal-production-completion.md
git commit -m "fix: verify formal activation hashes on readback"
```

---

### Task 7: Complete offline verification, hardcoding audit, and security Gate

**Files:**
- Modify only files required by failures in Tasks 1-6.

- [ ] **Step 0: Verify the declared Python runtime**

```bash
.venv/bin/python --version
```

Expected: Python 3.11 or newer, matching `pyproject.toml`.

- [ ] **Step 1: Run all targeted production-path tests**

```bash
.venv/bin/python -m pytest tests/test_cninfo_disclosure_client.py tests/test_tushare_formal_client.py tests/test_capability_store.py tests/test_formal_routes.py tests/test_production_dependencies.py tests/test_formal_live.py tests/test_formal_activation.py tests/test_repositories.py tests/test_default_formal_production_entry.py tests/test_july10_formal_readiness_acceptance.py -q
```

Expected: PASS.

- [ ] **Step 2: Run source hardcoding Gate**

```bash
rg -n "2026-07-10|20260710|2026-03-12|600000\.SH|301059\.SZ|/Users/ccrt|e16d5352" src ops --glob '*.py' --glob '*.sh' --glob '*.plist*'
```

Expected: no production runtime match. A named policy invariant may not contain target dates, candidate codes, personal paths, or authorization codes. Test and documentation fixtures are excluded intentionally.

- [ ] **Step 3: Run secret and unsafe-fallback Gate**

```bash
rg -n "\.env\.local|TUSHARE_TOKEN\s*=|SUPABASE_SERVICE_ROLE_KEY\s*=|CLOUDFLARE_API_TOKEN\s*=|announcementTime.*00:00|time\.min" src reports dist --glob '!*.pyc'
```

Expected: no credential value, no `.env.local` content, and no announcement-time fallback. Allowlisted strings are configuration variable names and redaction checks only; inspect every match.

- [ ] **Finding 7A: Remove synthetic midnight from current official status facts**

Files: `src/stock_analyzer/data/tushare_formal_client.py`, `tests/test_tushare_formal_client.py`.

Add `test_tushare_status_risk_uses_frozen_cutoff_as_asof_time_not_synthetic_midnight`. It must fail while suspension/ST status rows use `time.min`. Set current status records and their `publication_times` entry to the frozen `request.report_cutoff`, add `time_semantics="as_of_cutoff"`, and rerun the Tushare/CNINFO/formal failover tests. Prior-day date-only financial facts may retain midnight because they are categorically before the current-day cutoff and same-day date-only facts already fail closed.

Commit boundary:

```bash
git add docs/superpowers/plans/2026-07-11-v3-formal-production-completion.md src/stock_analyzer/data/tushare_formal_client.py tests/test_tushare_formal_client.py
git commit -m "fix: remove synthetic current-status timestamps"
```

- [ ] **Step 4: Run one complete test suite**

```bash
.venv/bin/python -m pytest -q
```

Expected: all tests pass, zero failures.

- [ ] **Step 5: Enforce the no-drift response to an unexpected failure**

Expected: no source change and no commit in this task. If a Gate fails, stop execution, identify the root cause with `superpowers:systematic-debugging`, add a finding-specific failing test and exact file/symbol amendment to this plan, then resume at the owning Task 1-6 commit boundary. Do not make an unplanned production edit from the verification task.

---

### Task 8: Admit the real event route and preserve the 82-session canonical data

**Files:**
- Runtime evidence under ignored `local_warehouse/formal_evidence/`
- Modify after success: `docs/operations/production-capability-matrix.md`
- Modify after success: `docs/operations/runbook.md`

- [ ] **Finding 8A: Accept the provider's proven-empty null shape without weakening schema checks**

Live diagnosis proved that CNINFO returns `totalAnnouncement: 0` with `announcements: null` for a valid-code empty window. Add `test_cninfo_route_accepts_null_announcements_only_when_total_zero` in `tests/test_cninfo_disclosure_client.py`; it must fail before the fix. In `src/stock_analyzer/data/cninfo_disclosure_client.py`, normalize `null` to an empty list only when the declared total is exactly zero, and keep `null` with a positive total as `SCHEMA` failure. Run the complete CNINFO/Tushare/live/default-entry target set and commit:

```bash
git add docs/superpowers/plans/2026-07-11-v3-formal-production-completion.md src/stock_analyzer/data/cninfo_disclosure_client.py tests/test_cninfo_disclosure_client.py
git commit -m "fix: accept proven-empty cninfo response shape"
```

- [ ] **Step 1: Run the redacted Tushare permission probe**

Use `AppConfig.resolve_tushare_token()` inside the process and print only `granted`, `denied`, or a redacted failure class. Call `anns_d` once for a dynamically selected valid code/date. Never print request headers, URLs containing credentials, client repr, or exception payloads.

Expected for the currently configured account: `denied`; no primary event capability is written.

- [ ] **Step 2: Run live capability verification**

```bash
PYTHONPATH=src .venv/bin/python -m stock_analyzer ops verify-formal-capabilities --trade-date 2026-07-10 --confirm-live-read
```

Expected: command exits 0; `cninfo.direct.events_risk.v2` is live-approved with two distinct semantic hashes; `official.events_risk.v1` is absent; all required groups retain at least one live route; no analysis, LLM, report, Supabase write, Cloudflare deploy, or scheduler action occurs.

- [ ] **Step 3: Verify immutable evidence without printing payload content**

Run a redacted Python check that prints only route IDs, evidence kinds, probe-key names, canonical group IDs, session count, first date, last date, and booleans for hash validity.

Expected: 82 sessions, first `2026-03-12`, last `2026-07-10`; event route is CNINFO v2; all hashes valid; prior immutable capability versions still exist.

- [ ] **Step 4: Update evidence status only after Steps 1-3 pass**

Advance `DATA-007` to `LIVE_READ_VERIFIED`; record the denied primary permission and live CNINFO v2 evidence without response content or identifiers. Keep unrelated blocked backup rows unchanged.

- [ ] **Step 5: Commit live-read evidence status**

```bash
git add docs/operations/production-capability-matrix.md docs/operations/runbook.md
git commit -m "docs: record precise event live capability"
```

---

### Task 9: Execute and verify the real formal run and Supabase activation

**Files:**
- Runtime local evidence, reports, deploy staging, and Supabase formal tables
- Modify after success: `docs/operations/production-capability-matrix.md`
- Modify after success: `docs/operations/runbook.md`

- [ ] **Finding 9A: Remove the incomplete CNINFO stock map as a false universe Gate**

The first real formal run froze candidate `603065.SH` and failed closed because the legacy `GET /new/data/szse_stock.json` response omitted that active security. Direct read-only provider probes proved that `POST /new/hisAnnouncement/query` with `stock=603065,` is incorrectly broadened to the all-market result, `stock=603065` returns zero, and `searchkey=603065` returns only rows whose `secCode` is exactly `603065`. The map is therefore a query optimization rather than authoritative coverage evidence.

In `tests/test_cninfo_disclosure_client.py`, replace `test_cninfo_route_rejects_missing_stock_map_code` with `test_cninfo_missing_stock_map_code_uses_exact_searchkey_and_preserves_frozen_candidate`; assert all four category calls use `stock=""`, `searchkey="603065"`, coverage remains exactly `("603065.SH",)`, and returned announcements are normalized normally. Add `test_cninfo_searchkey_fallback_rejects_wrong_code_or_incomplete_pagination`; it must prove that a wrong-code row is `SCHEMA` failure and a declared total not satisfied by completely paginated rows is `INCOMPLETE_UNIVERSE`. Both tests must fail before the implementation change.

In `src/stock_analyzer/data/cninfo_disclosure_client.py`, extend `_query_pages()` and `_query_page()` with an explicit `searchkey` parameter. For a mapped code keep `stock=f"{code},{org_id}"` and blank `searchkey`; for an unmapped frozen code use blank `stock` and exact six-digit `searchkey`. Reuse the existing total-stability and exact-row-count pagination checks, and retain `_normalize_announcement(expected_code=...)` as the fail-closed exact-code validator. Never infer an empty result from map absence, never use `stock=f"{code},"`, never fetch an unbounded all-market universe, and never alter `target_codes`.

Run:

```bash
.venv/bin/python -m pytest tests/test_cninfo_disclosure_client.py -q
.venv/bin/python -m pytest tests/test_cninfo_disclosure_client.py tests/test_tushare_formal_client.py tests/test_formal_routes.py tests/test_production_dependencies.py tests/test_formal_live.py tests/test_default_formal_production_entry.py tests/test_july10_formal_readiness_acceptance.py -q
```

Expected: the new tests fail before the source edit; after the edit both commands pass. Commit boundary:

```bash
git add docs/superpowers/specs/2026-07-10-v3-formal-report-data-readiness-design.md docs/superpowers/plans/2026-07-11-v3-formal-production-completion.md src/stock_analyzer/data/cninfo_disclosure_client.py tests/test_cninfo_disclosure_client.py
git commit -m "fix: query unmapped cninfo candidates exactly"
```

- [ ] **Finding 9B: Verify combined recommendation and focus evidence instead of recommendation-only counts**

The resumed real run reached `report_generated`, atomically activated its receipt, and produced 10 daily recommendations plus 4 independent focus-stock snapshots. The active formal ledger therefore correctly contained 14 evidence packages and 84 evaluation tasks. `verify_production_result()` incorrectly required evidence-package count to equal recommendation count and evaluation-task count to equal `recommendations * 6`, causing a false `report_artifact_invalid` after activation.

In `tests/test_ops_job.py`, add `test_verify_accepts_additional_focus_evidence_with_complete_evaluation_tasks`; construct two recommendations, one additional focus-only evidence package, and six tasks for each of all three packages. It must fail before the verifier change. Add `test_verify_rejects_evaluation_task_for_unknown_evidence`; it must fail if total task count happens to match but one task references an evidence ID outside the package set. Keep `test_verify_fails_when_evidence_count_does_not_match_recommendations`, but its assertion now means a recommendation evidence ID is absent rather than raw counts differ.

In `src/stock_analyzer/ops/verify.py`, compare the non-empty recommendation `evidence_id` set as a subset of the unique evidence-package ID set; reject missing or duplicate IDs with `evidence_count_mismatch`. Set the expected task count to `len(evidence_packages) * EVALUATION_TASKS_PER_RECOMMENDATION`, reject task evidence IDs not in the package set, and require exactly six tasks per evidence ID. Do not change Strategy V2, focus selection, report content, activated ledger rows, or the ten-recommendation limit.

Run:

```bash
.venv/bin/python -m pytest tests/test_ops_job.py -q
.venv/bin/python -m pytest tests/test_formal_strategy_runtime.py tests/test_ops_job.py tests/test_default_formal_production_entry.py tests/test_july10_formal_readiness_acceptance.py -q
```

Expected: the new acceptance test fails before the source edit; both commands pass afterward. Commit boundary:

```bash
git add docs/superpowers/specs/2026-07-10-v3-formal-report-data-readiness-design.md docs/superpowers/plans/2026-07-11-v3-formal-production-completion.md src/stock_analyzer/ops/verify.py tests/test_ops_job.py
git commit -m "fix: verify focus evidence independently"
```

- [ ] **Finding 9C: Scope report verification and deployment to the activated receipt artifact set**

The corrected live verifier then found fixture text in an old `600000.SH` report and a visible score in a frozen 2026-07-07 report. Neither path is present in the current receipt's 14 `artifact_hashes`; the verifier scanned the whole historical `reports/` tree, and `prepare_pages_artifact()` would also copy that whole tree. This conflicts with frozen-history preservation and the approved rule that deployment contains only the activated artifact.

In `tests/test_ops_job.py`, add `test_verify_ignores_historical_leaks_outside_activated_receipt_artifacts`: place fixture and score text in an older date path excluded from the receipt and assert current verification passes. Retain the existing tests that put fixture/score text in `index.html`, which is inside every activated receipt and must still fail. Add an unsafe receipt-path test if path validation is not already covered by deployment tests.

In `tests/test_ops_artifacts.py`, add `test_prepare_pages_artifact_excludes_unactivated_historical_reports`: create current and historical files, construct a receipt whose hashes include only `index.html`, current daily files, and current data files, and assert the historical file is absent from `dist/pages`. Retain the existing tampered-current-artifact rejection.

In `src/stock_analyzer/ops/verify.py`, derive a sorted list of safe existing artifact paths from `receipt.artifact_hashes` after rejecting absolute paths and `..`; scan only those paths for fixture/sample and visible-score leaks. In `src/stock_analyzer/ops/artifacts.py`, replace whole-tree copying with copying only receipt-listed regular files after the existing hash verification, then add the middleware. Do not delete, rewrite, or hide historical source reports.

Run:

```bash
.venv/bin/python -m pytest tests/test_ops_job.py tests/test_ops_artifacts.py -q
.venv/bin/python -m pytest tests/test_ops_publish.py tests/test_ops_smoke.py tests/test_default_formal_production_entry.py tests/test_july10_formal_readiness_acceptance.py -q
```

Expected: both new tests fail before source edits; afterward both commands pass and a current receipt leak still fails. Commit boundary:

```bash
git add docs/superpowers/specs/2026-07-10-v3-formal-report-data-readiness-design.md docs/superpowers/plans/2026-07-11-v3-formal-production-completion.md src/stock_analyzer/ops/verify.py src/stock_analyzer/ops/artifacts.py tests/test_ops_job.py tests/test_ops_artifacts.py
git commit -m "fix: deploy only activated report artifacts"
```

- [ ] **Step 1: Verify current Supabase guidance and runtime presence without exposing values**

Fetch `https://supabase.com/changelog.md`, inspect relevant breaking changes, then consult current official docs for RPC, RLS/security-invoker views, and service-role server usage. Run a boolean-only configuration check for `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY`; if absent, use the already authenticated Supabase mechanism or request user authorization rather than displaying or copying a secret.

Expected: schema migrations remain synchronized, security advisors have zero error/warning findings relevant to the formal schema, capacity is below the configured stop threshold.

- [ ] **Step 2: Run the formal daily job with automatic publication still disabled**

Invoke the production runtime through its approved secret loader without reading or echoing `.env.local`:

```bash
PYTHONPATH=src .venv/bin/python -m stock_analyzer ops run-daily-job --trade-date 2026-07-10 --scheduled-slot 18:30 --attempt 1 --prepare-deploy
```

Expected: `success_with_recommendations` or the formally valid no-recommendation terminal state; receipt reaches `report_generated` or `analysis_complete_no_recommendations`; no blocked state; deploy artifact prepared; auto-publish remains off until Task 10.

- [ ] **Step 3: Verify Supabase and local activation atomically**

Using application repository methods, print only counts, IDs/hashes shortened to non-sensitive prefixes, and booleans. Confirm exactly one active receipt for `formal-2026-07-10`, matching receipt/input/artifact hashes, matching active-row hash, no visible pending-only rows, report files matching receipt hashes, and prior pointers unchanged in failure-injection rechecks.

- [ ] **Step 4: Verify report content Gate**

Run report verification and scans for fixture/sample markers, visible total score, secret names/values, missing evidence IDs, wrong trade date, unresolved asset paths, and report/receipt hash mismatch.

Expected: PASS; both daily recommendation and focus sections reflect the existing Strategy V2 output contract. A valid no-recommendation run is accepted only if the committed focus analysis and receipt are complete.

- [ ] **Step 5: Update evidence status and commit**

Advance `STORE-003`, `ACT-001`, `REPORT-001`, `REPORT-002`, `OPS-001`, and the applicable formal-run Gate only when their exact evidence passed.

```bash
git add docs/operations/production-capability-matrix.md docs/operations/runbook.md
git commit -m "docs: record verified formal production run"
```

---

### Task 10: Publish once, activate automation, and verify operations

**Files:**
- Runtime Cloudflare deployment and local auto-publish flag
- Local generated launchd plist under `~/Library/LaunchAgents/` (not committed)
- Modify after success: `docs/operations/production-capability-matrix.md`
- Modify after success: `docs/operations/runbook.md`
- Modify after success: `docs/operations/cloudflare-pages.md`

- [ ] **Finding 10A: Prevent runtime environment loading from writing to launchd logs**

Before installation, the versioned launchd template still used bare `source .env.local`. The authorized runtime must load those values, but neither normal output nor shell-side diagnostics from that file may reach launchd stdout/stderr logs. In `tests/test_ops_notify.py`, extend `test_launchd_template_uses_project_root_and_env_contract_without_secrets` to require the literal fail-closed loader `source .env.local >/dev/null 2>&1`. It must fail before the template edit. Update only that line in `ops/launchd/com.ccrt.stock-analysis-assistant.daily.plist.example`; keep the missing-file check, three slots, and no embedded value. Run `pytest tests/test_ops_notify.py -q` and `plutil -lint` on the template; both must pass. Include this file in the Task 10 operational-evidence commit.

- [ ] **Step 1: Verify Cloudflare configuration without exposing values**

Check only presence/auth status, project identity, branch, report password variable name, and prepared artifact manifest. Do not print tokens, account IDs, passwords, session secrets, or `.env.local`.

- [ ] **Step 2: Perform the first one-command publish**

```bash
PYTHONPATH=src .venv/bin/python -m stock_analyzer ops publish-report-site --trade-date 2026-07-10
```

Expected: deploy succeeds; online password/date/content/redaction smoke passes; deployment points to the activated receipt artifact; one retry/rollback logic remains unused or succeeds safely; only then is the auto-publish flag atomically set true.

- [ ] **Step 3: Generate and load the launchd service**

Copy the versioned plist template to the user LaunchAgents directory, replace `__PROJECT_ROOT__` only in the local generated copy with the resolved worktree path, validate it with `plutil -lint`, ensure the file contains no credential values, bootstrap it with `launchctl`, and verify the service with `launchctl print gui/$(id -u)/com.ccrt.stock-analysis-assistant.daily`.

Expected: service loaded; configured attempts are 18:30, 19:00, and 19:30; command uses the approved runtime secret loader; no job is manually forced outside its schedule during installation.

- [ ] **Step 4: Run non-mutating operational smoke**

Run health/config checks, verify the loaded service command resolves, the latest activated report remains online, and the next scheduled run will fail closed if any capability expires. Do not place orders or connect to a broker.

- [ ] **Step 5: Update activation evidence and commit**

Advance `OPS-002`, `PUB-002`, and `PUB-003` only for successful evidence.

```bash
git add docs/operations/production-capability-matrix.md docs/operations/runbook.md docs/operations/cloudflare-pages.md
git commit -m "docs: record report publication and automation activation"
```

---

### Task 11: Final review, complete verification, push, and goal closure

**Files:**
- Review every file changed since `d7e3c2e` and all production evidence/status documents.

- [ ] **Finding 11A: Make completed-run reuse and later launchd slots operationally idempotent**

The final production recheck proved that a second invocation of `formal-2026-07-10` raises `cannot resume from report_generated`. Separately, the existing retry preflight converts a 19:00 invocation after an 18:30 success into `failed_needs_human`; because launchd schedules all three slots unconditionally, that would overwrite every successful day's status with a false failure.

In `tests/test_formal_pipeline.py`, add `test_report_generated_run_is_reused_without_callbacks_or_revision`; complete a run, clear the callback/route recorder, invoke the identical run again, and assert the same receipt revision/candidate ID returns with zero acquisition, screen, analysis, LLM, render, verify, or ledger activity. In `tests/test_ops_job.py`, change `test_run_daily_job_attempt_two_after_success_does_not_cleanup_or_run` to require the prior successful `JobStatus` to be returned unchanged, and add `test_run_daily_job_attempt_three_after_attempt_one_success_is_noop` to prove fixed calendar slots do not require an immediately preceding retry record. Both fail before the source edits.

In `src/stock_analyzer/ops/formal_run.py`, after exact date/cutoff/contract validation, return the existing `REPORT_GENERATED` receipt and frozen candidate set before constructing any mutable pipeline stage. Do not treat blocked or failed states as success. In `src/stock_analyzer/ops/job.py`, before retry preflight, load a same-date prior status; when its status is `success_with_recommendations`, `success_no_recommendations`, or `skipped_non_trading_day` and its attempt is lower than the scheduled attempt, return it without writing status, cleanup, health checks, run, verification, deployment, publication, or notification. All other retry states retain the existing strict preflight.

Run:

```bash
.venv/bin/python -m pytest tests/test_formal_pipeline.py tests/test_ops_job.py -q
.venv/bin/python -m pytest tests/test_default_formal_production_entry.py tests/test_july10_formal_readiness_acceptance.py tests/test_ops_notify.py -q
```

Expected: the new tests fail before the source edit; both commands pass afterward. Commit boundary:

```bash
git add docs/superpowers/specs/2026-07-10-v3-formal-report-data-readiness-design.md docs/superpowers/plans/2026-07-11-v3-formal-production-completion.md src/stock_analyzer/ops/formal_run.py src/stock_analyzer/ops/job.py tests/test_formal_pipeline.py tests/test_ops_job.py
git commit -m "fix: reuse completed formal runs idempotently"
```

- [ ] **Step 1: Perform the read-only final review**

Review design-to-code traceability, exact provider semantics, paging/coverage, pacing, primary/backup isolation, candidate freeze, LLM/report reachability, Supabase atomicity, Cloudflare artifact scope, launchd secret loading, hardcoding, and rollback. Do not dispatch a subagent unless the required GPT-5.6 sol/high/standard configuration is explicitly available. Fix every Critical or Important finding with a failing regression test and focused commit.

- [ ] **Step 2: Rerun targeted tests after review fixes**

Run the Task 7 targeted command.

Expected: PASS.

- [ ] **Step 3: Rerun the complete suite exactly once after final fixes**

```bash
.venv/bin/python -m pytest -q
```

Expected: all tests pass, zero failures.

- [ ] **Step 4: Re-run production acceptance checks**

Confirm: exact 82 sessions; CNINFO live event evidence; Tushare event permission denied without capability; formal receipt and row hashes active; report verification; online smoke; auto-publish enabled; launchd loaded; no broker/order path; no secret/hardcoded runtime value; all matrix levels supported by evidence.

- [ ] **Step 5: Confirm Git integrity and push**

```bash
git status --short --branch
git log --oneline d7e3c2e..HEAD
git push origin codex/v3-mvp
git status --short --branch
```

Expected: before push, only intended committed changes and no untracked production secret/evidence files; push succeeds; after push, branch equals `origin/codex/v3-mvp` and worktree is clean.

- [ ] **Step 6: Complete `/goal` only after every Gate is true**

Final report must list design/plan/implementation/evidence commits, targeted and complete test counts, real capability result, 82-session result, formal analysis/LLM/report result, Supabase activation/read-back, Cloudflare URL/smoke result without secrets, launchd status, push result, and explicitly state that no broker connection or order operation occurred.
