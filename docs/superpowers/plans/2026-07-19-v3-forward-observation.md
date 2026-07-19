# V3 Continuous Forward Observation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and start an append-only forward-observation workflow that freezes the current V3 attention and action-confirmation rules, forms the first real 2026-07-17 batch, and later appends only real next-open and mature 5/10/20/30-session evidence.

**Architecture:** Add one isolated `stock_analyzer.evaluation.v3_forward` package with pure frozen-rule functions, a strict point-in-time input loader, an immutable USB ledger, Chinese report rendering, and a manual `form`/`update` command. Reuse the existing formation-only V3 evidence builder, single-attention compression, governed fact-query APIs, and baseline action mask; never import or read historical outcome tables in the formation path.

**Tech Stack:** Python 3.12, pandas, PyArrow/Parquet, DuckDB read-only queries, pytest, argparse, SHA-256 manifests.

## Global Constraints

- Rule version is exactly `v3-forward-baseline-01`.
- Real output root is exactly `/Volumes/ZHUTONG/股票分析助手-V3回测/2026-07-19-v3-forward-observation/`.
- Use current local `main`; do not create a branch or worktree.
- Preserve all unrelated working-tree changes.
- Do not activate or invoke old report jobs, write Supabase, publish Cloudflare, modify launchd, connect a broker, or place an order.
- Do not implement lifecycle, replacement, holding, sell, stop-loss, position, cost, or portfolio behavior.
- Formation may use only facts visible by 23:59:59 Asia/Shanghai on the specified formation date.
- The attention list is unranked, contains 0–10 stocks, and is not padded.
- Action confirmation is exactly `return_5d > 0`, `relative_return_20d > 0`, and `current_amount_ratio_20d >= 1` for a selected `关注` row that is not hard-invalid.
- Missing confirmation values evaluate false.
- Entry day is the first real market session after formation and counts as observation session 1.
- A missing quote/suspension and a one-price limit-up are not executable; an open at limit that trades below the limit is executable.
- Formation evidence is immutable; later entry and snapshot evidence is appended in separate bundles.
- A rule change requires a new version; old batches are never recomputed under the new rule.
- First real formation must read the unified fact warehouse, never fixtures or historical outcome/action-path tables.

## File Structure

- Create `src/stock_analyzer/evaluation/v3_forward/__init__.py`: public constants and service exports.
- Create `src/stock_analyzer/evaluation/v3_forward/rules.py`: frozen rule manifest, field guards, action confirmations, entry classification, and mature-window calculations.
- Create `src/stock_analyzer/evaluation/v3_forward/ledger.py`: canonical serialization, immutable bundle creation, identity conflict detection, and directory layout.
- Create `src/stock_analyzer/evaluation/v3_forward/inputs.py`: health/derived-manifest verification, strict as-of fact loading, and current attention-list formation.
- Create `src/stock_analyzer/evaluation/v3_forward/reports.py`: Chinese formation, entry, and snapshot Markdown.
- Create `src/stock_analyzer/evaluation/v3_forward/service.py`: `form_observation()` and `update_observations()` orchestration.
- Create `src/stock_analyzer/evaluation/v3_forward/__main__.py`: manual argparse entry with only `form` and `update`.
- Create `tests/test_v3_forward_rules.py`: pure rule and path tests.
- Create `tests/test_v3_forward_ledger.py`: immutability, path restriction, and idempotence tests.
- Create `tests/test_v3_forward_inputs.py`: strict cutoff and attention formation tests.
- Create `tests/test_v3_forward_service.py`: orchestration, waiting, append, report, and no-future integration tests.

---

### Task 1: Freeze rule contracts and pure calculations

**Files:**
- Create: `src/stock_analyzer/evaluation/v3_forward/__init__.py`
- Create: `src/stock_analyzer/evaluation/v3_forward/rules.py`
- Test: `tests/test_v3_forward_rules.py`

**Interfaces:**
- Produces: `RULE_VERSION`, `TARGET_RETURN`, `OBSERVATION_WINDOWS`, `rule_manifest()`, `rule_manifest_hash()`, `reject_future_fields(frame)`, `add_action_confirmations(frame)`, `classify_entry(row)`, and `compute_window_snapshot(prices, entry, horizon)`.
- Consumes: `v3_selection_accuracy_pareto.baseline_action_mask` for the final action result.

- [ ] **Step 1: Write failing tests for rule identity, future-field rejection, and action semantics**

```python
def test_rule_manifest_is_stable_and_frozen():
    manifest = rule_manifest()
    assert manifest["rule_version"] == "v3-forward-baseline-01"
    assert manifest["candidate_cap"] == 10
    assert manifest["target_return"] == 0.20
    assert manifest["observation_windows"] == [5, 10, 20, 30]
    assert rule_manifest_hash() == rule_manifest_hash()

def test_formation_rejects_any_known_future_field():
    with pytest.raises(ValueError, match="future field"):
        reject_future_fields(pd.DataFrame({"ts_code": ["A"], "action_price": [10]}))

def test_confirmation_matches_frozen_baseline_and_missing_is_false():
    frame = pd.DataFrame({
        "user_layer": ["关注", "关注", "关注"],
        "hard_invalid": [False, False, False],
        "return_5d": [0.01, -0.01, None],
        "relative_return_20d": [0.02, 0.02, 0.02],
        "current_amount_ratio_20d": [1.1, 1.1, 1.1],
    })
    result = add_action_confirmations(frame)
    assert result["action_confirmed"].tolist() == [True, False, False]
    assert result["action_confirmed"].equals(baseline_action_mask(result))
```

- [ ] **Step 2: Run the rule tests and verify they fail because the package does not exist**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_v3_forward_rules.py -q`

Expected: collection error for `stock_analyzer.evaluation.v3_forward`.

- [ ] **Step 3: Implement the frozen manifest, explicit future-field denylist, and baseline-backed confirmations**

```python
RULE_VERSION = "v3-forward-baseline-01"
TARGET_RETURN = 0.20
OBSERVATION_WINDOWS = (5, 10, 20, 30)
CANDIDATE_CAP = 10
FUTURE_FIELDS = frozenset({
    "entry_date", "entry_status", "executable_entry", "action_price",
    "target_price", "target_touched", "close_confirmed", "retain_1",
    "retain_3", "retain_5", "window_min_return", "pre_touch_min_return",
    "terminal_return", "first_touch_date", "first_close_confirm_date",
})

def add_action_confirmations(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result["confirm_return_5d_positive"] = pd.to_numeric(result["return_5d"], errors="coerce").gt(0)
    result["confirm_relative_return_20d_positive"] = pd.to_numeric(result["relative_return_20d"], errors="coerce").gt(0)
    result["confirm_amount_ratio_20d"] = pd.to_numeric(result["current_amount_ratio_20d"], errors="coerce").ge(1)
    result["action_confirmed"] = baseline_action_mask(result)
    return result
```

- [ ] **Step 4: Add failing entry-status and window-maturity tests**

```python
@pytest.mark.parametrize(("quote", "expected"), [
    ({"open": None}, ("no_quote_or_suspended", False)),
    ({"open": 11, "high": 11, "low": 11, "up_limit": 11}, ("one_price_limit_up", False)),
    ({"open": 11, "high": 11, "low": 10.5, "up_limit": 11}, ("open_at_limit_not_one_price", True)),
    ({"open": 10.5, "high": 11, "low": 10, "up_limit": 11}, ("executable_entry", True)),
])
def test_entry_classification(quote, expected):
    assert classify_entry(pd.Series(quote))[:2] == expected

def test_window_requires_exact_market_session_maturity():
    with pytest.raises(ValueError, match="not mature"):
        compute_window_snapshot(four_rows, entry, horizon=5)
```

- [ ] **Step 5: Implement entry classification and deterministic window metrics**

The snapshot must use adjusted open as the baseline, adjusted highs for intraday touch and minimum return, adjusted closes for close confirmation and close-to-close maximum drawdown, entry day as session 1, and three quoted sessions after the first close confirmation for `retain_3`.

- [ ] **Step 6: Run tests and commit**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_v3_forward_rules.py -q`

Expected: all rule tests pass.

Commit only Task 1 files with message `feat: freeze V3 forward observation rules`.

---

### Task 2: Build the immutable USB ledger

**Files:**
- Create: `src/stock_analyzer/evaluation/v3_forward/ledger.py`
- Test: `tests/test_v3_forward_ledger.py`

**Interfaces:**
- Produces: `ForwardLedger(root: Path, *, enforce_real_root: bool = True)`, `write_formation_bundle(payload: Mapping[str, Any], candidates: pd.DataFrame, report: str) -> BundleWriteResult`, `write_entry_bundle(formation_date: date, entry_date: date, entries: pd.DataFrame, report: str) -> BundleWriteResult`, `write_snapshot_bundle(formation_date: date, as_of_date: date, horizon: int, snapshots: pd.DataFrame, report: str) -> BundleWriteResult`, `load_formations() -> tuple[FormationBundle, ...]`, and `sha256_file(path: Path) -> str`.
- Consumes: deterministic JSON-safe payloads and pandas frames from later services.

- [ ] **Step 1: Write failing tests for path restriction and canonical identities**

```python
def test_real_mode_rejects_non_frozen_output_root(tmp_path):
    with pytest.raises(ValueError, match="U盘专用目录"):
        ForwardLedger(tmp_path, enforce_real_root=True)

def test_formation_identity_is_rule_date_and_stock_unique(test_ledger):
    payload = formation_payload(codes=["A", "A"])
    with pytest.raises(ValueError, match="duplicate"):
        test_ledger.write_formation_bundle(payload, candidates)
```

- [ ] **Step 2: Run and observe missing implementation**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_v3_forward_ledger.py -q`

Expected: import failure or missing `ForwardLedger`.

- [ ] **Step 3: Implement allowed-root validation and stable layout**

The real constructor must accept only the exact frozen USB experiment root. Tests may pass `enforce_real_root=False` and use `tmp_path`. Create only these children: `formations`, `entries`, `snapshots`, `tables`, `manifests`, `reports`, `logs`.

- [ ] **Step 4: Write failing idempotence and conflict tests**

```python
def test_identical_formation_rerun_is_noop_and_preserves_bytes(test_ledger):
    first = test_ledger.write_formation_bundle(PAYLOAD, CANDIDATES, "报告")
    before = sha256_file(first.path / "formation.json")
    second = test_ledger.write_formation_bundle(PAYLOAD, CANDIDATES, "报告")
    assert second.idempotent is True
    assert sha256_file(first.path / "formation.json") == before

def test_different_content_for_same_identity_fails_without_overwrite(test_ledger):
    first = test_ledger.write_formation_bundle(PAYLOAD, CANDIDATES, "报告")
    before = sha256_file(first.path / "formation.json")
    changed = {**PAYLOAD, "action_count": 9}
    with pytest.raises(ImmutableEvidenceConflict):
        test_ledger.write_formation_bundle(changed, CANDIDATES, "报告")
    assert sha256_file(first.path / "formation.json") == before

def test_entry_and_snapshot_do_not_change_formation_hash(test_ledger):
    formation = test_ledger.write_formation_bundle(PAYLOAD, CANDIDATES, "报告")
    before = sha256_file(formation.path / "formation.json")
    test_ledger.write_entry_bundle(FORMATION_DATE, ENTRY_DATE, ENTRIES, "开盘")
    test_ledger.write_snapshot_bundle(FORMATION_DATE, ENTRY_DATE, 5, SNAPSHOTS, "快照")
    assert sha256_file(formation.path / "formation.json") == before
```

- [ ] **Step 5: Implement staged immutable bundle creation**

Write each bundle into a sibling `mkdtemp` directory, fsync its files, write `manifest.json` last, fsync the directory, and rename it to the final identity directory. If the final directory exists, validate its manifest and deterministic content hash: identical returns `idempotent=True`; different raises `ImmutableEvidenceConflict`. Never delete or overwrite the final directory.

- [ ] **Step 6: Run tests and commit**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_v3_forward_ledger.py -q`

Expected: all ledger tests pass.

Commit Task 2 files with message `feat: add immutable V3 forward ledger`.

---

### Task 3: Load strict formation inputs and form the attention list

**Files:**
- Create: `src/stock_analyzer/evaluation/v3_forward/inputs.py`
- Test: `tests/test_v3_forward_inputs.py`

**Interfaces:**
- Produces: `FormationInputs`, `load_formation_inputs(warehouse_root, archive_root, formation_date)`, and `form_attention_list(inputs)`.
- Consumes: `ResearchWarehouse`, `ResearchQuery`, read-only `research_derived_partitions`, the three governed Parquet partitions, `_build_route_evidence`, `_latest_company_facts`, `compress_decision_list`, and Task 1 confirmation functions.

- [ ] **Step 1: Write failing health and cutoff tests**

```python
def test_loader_rejects_incomplete_health_report(formation_store):
    formation_store.write_health(complete_core_date=False)
    with pytest.raises(ValueError, match="core data is incomplete"):
        formation_store.load()

def test_loader_rejects_derived_manifest_after_cutoff(formation_store):
    formation_store.write_derived_manifest(as_of="2026-07-18T00:00:00+08:00")
    with pytest.raises(ValueError, match="derived input exceeds cutoff"):
        formation_store.load()

def test_loader_rejects_fact_available_after_formation(formation_store):
    formation_store.write_fact(available_at="2026-07-18T00:00:00+08:00")
    with pytest.raises(ValueError, match="future evidence"):
        formation_store.load()
```

- [ ] **Step 2: Implement read-only health and governed partition verification**

Require `complete_core_date is True`. For `market_context`, `sector_hotspot`, and `stock_trading_context`, require one registered partition for the formation date, allowed quality status, exact formula version, `input_manifest_json.fact_snapshot.as_of <= cutoff`, and a matching file SHA-256 before reading Parquet.

- [ ] **Step 3: Write failing strict financial/member snapshot tests**

Use `ResearchQuery` at the formation cutoff to resolve financial indicator, cash flow, industry/theme catalogs and members, security master, company profile, and relevant announcement facts. Assert every returned `available_at` is no later than cutoff and preserve the fact input manifest in `FormationInputs`.

- [ ] **Step 4: Implement `form_attention_list` without outcome imports**

Construct only the formation inputs expected by `_build_route_evidence`; pass the frozen caps and supported routes; discard its historical decision output; run `compress_decision_list(evidence, candidate_cap=10, focus_cap=5)`; select `user_layer == "关注"`; call `reject_future_fields`; call `add_action_confirmations`; attach as-of names and risks; sort deterministically by upstream evidence row order, never by a new score.

- [ ] **Step 5: Test 0–10 cap, empty list, no duplicates, exact confirmations, and forbidden imports**

The test must scan `inputs.py` and assert it contains no `compute_forward_outcomes`, `build_action_paths`, `outcomes_all`, `action_paths`, or `recompressed_action_outcomes` reference.

- [ ] **Step 6: Run tests and commit**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_v3_forward_inputs.py tests/test_v3_compression_revalidation.py tests/test_v3_selection_accuracy_pareto.py -q`

Expected: all focused formation and frozen-baseline tests pass.

Commit Task 3 files with message `feat: form strict V3 forward attention lists`.

---

### Task 4: Orchestrate formation and real next-open append

**Files:**
- Create: `src/stock_analyzer/evaluation/v3_forward/service.py`
- Test: `tests/test_v3_forward_service.py`

**Interfaces:**
- Produces: `form_observation(*, warehouse_root: Path, archive_root: Path, output_root: Path, formation_date: date, now: datetime | None = None, enforce_real_root: bool = True) -> FormationRunResult` and `update_observations(*, warehouse_root: Path, output_root: Path, as_of_date: date, now: datetime | None = None, enforce_real_root: bool = True) -> UpdateRunResult`.
- Consumes: Tasks 1–3 and local equity/adjustment/limit partitions.

- [ ] **Step 1: Write failing formation-service tests**

Verify batch metadata records distinct `formation_date`, `data_cutoff_at`, and honest `generated_at`; candidate count is at most ten; action count may be zero; all entries start as waiting; input and rule hashes are present; a byte-identical rerun is idempotent.

- [ ] **Step 2: Implement `form_observation`**

Load strict inputs, form attention, create one batch payload and candidates Parquet, render no future fields, and call `write_formation_bundle`. In real mode reject fixture flags and any source path containing historical outcome tables.

- [ ] **Step 3: Write failing real-entry append tests**

Cover: no later market session means waiting and no entry bundle; first later session is used; no quote does not roll forward; only `action_confirmed=true` items receive entry evaluation; one-price limit-up is preserved but excluded from executable observations.

- [ ] **Step 4: Implement entry discovery and append**

Read actual local trade-calendar/equity/adjustment/limit facts only through `as_of_date`. The first market session after formation is fixed even when a stock has no quote. Append raw open, adjustment factor, adjusted open, formation adjusted close, gap, target price, entry status, executable flag, source hashes, and observed time in an immutable entry bundle.

- [ ] **Step 5: Run tests and commit**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_v3_forward_service.py -q`

Expected: all formation and entry tests pass.

Commit Task 4 files with message `feat: append real V3 forward entries`.

---

### Task 5: Add mature snapshots, Chinese reports, and manual CLI

**Files:**
- Create: `src/stock_analyzer/evaluation/v3_forward/reports.py`
- Create: `src/stock_analyzer/evaluation/v3_forward/__main__.py`
- Modify: `src/stock_analyzer/evaluation/v3_forward/service.py`
- Modify: `tests/test_v3_forward_service.py`

**Interfaces:**
- Produces manual commands:
  - `python -m stock_analyzer.evaluation.v3_forward form --formation-date YYYY-MM-DD --warehouse-root PATH --archive-root PATH --output-root PATH`
  - `python -m stock_analyzer.evaluation.v3_forward update --as-of-date YYYY-MM-DD --warehouse-root PATH --output-root PATH`

- [ ] **Step 1: Write failing snapshot maturity tests**

Assert no 5-day file at four market sessions, a 5-day file at five sessions, and no 10/20/30 result before each exact maturity. Assert the formation bundle hash remains unchanged after every update.

- [ ] **Step 2: Implement mature-window append**

For each executable entry, build the exact entry-day-through-horizon market-session grid, retain missing stock quotes as missing rows, call `compute_window_snapshot`, and write only newly mature horizon bundles. Existing identical bundles are idempotent; conflicts fail.

- [ ] **Step 3: Write failing report-content tests**

The Chinese formation report must include `关注股票`, `满足行动确认`, `未来结果尚未到达`, rule version, data cutoff, generated time, input hashes, per-stock market/hotspot/company/price evidence and risks, and the non-advice statement. Entry and snapshot reports must label their stage and never call 5/10-day output final validation.

- [ ] **Step 4: Implement Markdown rendering and immutable report placement**

Render formation reports under `reports/formation_date=<YYYY-MM-DD>/formation.md`, entry reports under `reports/entry_date=<YYYY-MM-DD>/entries.md`, and snapshot reports under `reports/as_of_date=<YYYY-MM-DD>/snapshots.md`. Treat reports as immutable projections of the corresponding evidence manifests.

- [ ] **Step 5: Implement argparse without production registration**

The command accepts explicit warehouse, archive, and output roots, defaulting only to the current project’s local data and frozen USB output. It exposes no scheduler, Supabase, publication, report activation, broker, lifecycle, or trading option.

- [ ] **Step 6: Run focused and adjacent tests, then commit**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_v3_forward_rules.py tests/test_v3_forward_ledger.py tests/test_v3_forward_inputs.py tests/test_v3_forward_service.py tests/test_v3_compression_revalidation.py tests/test_v3_next_day_entry_validation.py tests/test_v3_selection_accuracy_pareto.py -q`

Expected: all focused and adjacent tests pass.

Commit Task 5 files with message `feat: report and update V3 forward observations`.

---

### Task 6: Verify and start the first real forward batch

**Files:**
- Runtime only: `/Volumes/ZHUTONG/股票分析助手-V3回测/2026-07-19-v3-forward-observation/`
- No repository code change unless verification finds a defect, in which case return to the failing-test step before fixing.

**Interfaces:**
- Consumes the manual CLI and real unified local data.
- Produces the first immutable formation, manifests, tables, logs, and Chinese report.

- [ ] **Step 1: Run the full relevant test suite**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_v3_forward_rules.py tests/test_v3_forward_ledger.py tests/test_v3_forward_inputs.py tests/test_v3_forward_service.py tests/test_v3_layered_validation.py tests/test_v3_compression_revalidation.py tests/test_v3_next_day_entry_validation.py tests/test_v3_selection_accuracy_pareto.py -q`

Expected: all tests pass with zero failures.

- [ ] **Step 2: Form the real 2026-07-17 batch**

Run the manual `form` command with:

```text
formation-date = 2026-07-17
warehouse-root = /Users/ccrt/Documents/股票分析助手/local_warehouse
archive-root = /Users/ccrt/Documents/股票分析助手/local_archive
output-root = /Volumes/ZHUTONG/股票分析助手-V3回测/2026-07-19-v3-forward-observation
```

Expected: 0–10 attention rows, 0–N confirmed rows, entry state waiting, and no entry/snapshot future values.

- [ ] **Step 3: Independently audit real artifacts**

Recompute every output file SHA-256, validate rule and input manifest hashes, scan formation JSON/Parquet for future fields and any date after 2026-07-17, verify all output paths are on the USB, verify no Supabase/report/deploy/launchd state changed, and record the audit under the USB `manifests` directory.

- [ ] **Step 4: Rerun formation to prove idempotence**

Record the complete formation directory file hashes before and after the rerun. Expected: byte-for-byte identical files, no duplicate stock-date records, and an idempotent result.

- [ ] **Step 5: Run update through 2026-07-19**

Expected: 2026-07-20 data is absent, so every confirmed item remains waiting; no simulated entry price or snapshot is created.

- [ ] **Step 6: Run final verification-before-completion checks**

Use `superpowers:verification-before-completion`; inspect git diff/status, focused test output, USB tree, first report, all manifests, and immutable hashes before claiming success.

Do not activate a scheduler. Future daily execution remains the same explicit `form` plus `update` commands after pure data tasks finish.
