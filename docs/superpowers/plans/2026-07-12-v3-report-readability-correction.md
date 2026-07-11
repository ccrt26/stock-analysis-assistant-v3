# V3 REPORT-004 User-Readable Formal Report Correction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task in the current session. Do not use subagents unless the user later requests them.

**Goal:** Restore the approved Phase 3 outcome in which Codex analyzes each stock from verified evidence and the formal HTML presents a plain-language decision report, while immutable Strategy V2 decisions and the prior active report remain protected.

**Architecture:** Project one isolated, allowlisted analysis request per unique stock from `FormalReportPayload`, invoke locally authenticated `codex exec` with `gpt-5.6-sol`, high reasoning, standard speed, and an exact JSON schema, then validate every response against evidence and decision locks. Render the validated narrative into the home and stock pages, preserve six-module evidence as collapsed audit detail, and split candidate preparation from atomic activation so the first real corrected report cannot replace the active report before human readability acceptance.

**Tech Stack:** Python 3.11+, Pydantic 2, subprocess, Codex CLI, Jinja2, pytest, existing local evidence store, existing Supabase formal ledger, existing Cloudflare Pages publication path.

## Global Constraints

- The normative design is `docs/superpowers/specs/2026-07-10-v3-phase-3-strategy-v2-design.md`, including the approved 2026-07-12 REPORT-004 correction.
- The production model is exactly `gpt-5.6-sol`; reasoning effort is `high`; standard speed is enforced by disabling the optional fast tier.
- Codex uses the existing ChatGPT login. No OpenAI API key, new paid API account, local model, or legacy V1/V2 runtime is introduced.
- Each unique stock is analyzed independently. Its request may contain only that stock's verified facts, applicable market/board/industry/concept context, matched knowledge references, explicit gaps, five-session focus history, and immutable Strategy V2 decision.
- Model reasoning may bridge a missing local interpretation method, but missing facts remain missing. Model text is never a new factual authority.
- Codex cannot change action, position, risk-if-wrong, required confirmation, observation condition, invalidation condition, exit condition, or ranking.
- The home page prioritizes market conclusion, frozen ranking, action/position, three core reasons, buy/watch conditions, invalidation/exit conditions, and focus-stock five-session progress.
- Six modules, evidence IDs, source versions, knowledge references, and internal technical metadata are collapsed audit details. User main views do not contain Gate, input set, thesis quality, receipt, or readiness credential terminology.
- Missing, partial, invalid, timed-out, unauthenticated, quota-limited, or decision-inconsistent Codex output fails closed before rendering, ledger activation, pointer activation, deployment, or publication.
- `.env.local` may be loaded silently by the existing production entry. No credential value may enter model input, stdout, stderr, logs, commits, reports, or deploy artifacts.
- Candidate generation and automated validation do not constitute product acceptance. REPORT-004 remains `BLOCKED` until the user explicitly accepts a real candidate report.
- The existing active local report, Supabase activation, Cloudflare deployment, formal data gates, source failover, candidate freeze, focus five-day rule, and main launchd job remain unchanged until the human Gate passes.
- No broker connection or order execution is added.

---

## File Responsibility Map

- Create `src/stock_analyzer/ops/formal_narrative.py`: typed market/stock narrative contracts, stock-isolated request projection, decision locks, evidence/number whitelist validation, and exact Codex response aggregation.
- Create `src/stock_analyzer/ops/codex_expression_client.py`: safe non-interactive Codex CLI process adapter with fixed model settings, schema output, timeout, redacted failures, and no repository/raw-path input.
- Modify `src/stock_analyzer/ops/formal_strategy_runtime.py`: carry exact five-session stock history, require a validated `FormalNarrative`, and pass it to rendering.
- Modify `src/stock_analyzer/ops/production_dependencies.py`: construct the concrete Codex client by default and reject a production dependency graph without it.
- Modify `src/stock_analyzer/data/readiness.py`: add the local pre-activation `AWAITING_HUMAN_ACCEPTANCE` state.
- Modify `src/stock_analyzer/ops/formal_run.py`: expose candidate-only execution and exact candidate activation without re-running acquisition, analysis, or Codex.
- Modify `src/stock_analyzer/ops/activation.py`: split render/verify candidate preparation from ledger/pointer activation and protect the candidate with hashes.
- Modify `src/stock_analyzer/storage/evidence_store.py`: persist and reload the hash-protected local candidate activation bundle outside report/deploy artifacts.
- Modify `src/stock_analyzer/reports/generator.py`: build narrative views, require complete formal narrative for production Strategy V2 HTML, and feed narrative to both page types.
- Modify `src/stock_analyzer/reports/templates/index.html.j2`: decision-first home page with narrative and collapsed audit detail.
- Modify `src/stock_analyzer/reports/templates/stock.html.j2`: stock-specific narrative first and six modules collapsed.
- Modify `src/stock_analyzer/ops/verify.py`: verify narrative markers, user-view content, audit folding, forbidden internal terms, and candidate/receipt artifact hashes.
- Modify `src/stock_analyzer/cli.py`: add explicit candidate preparation and hash-bound human activation commands.
- Modify `src/stock_analyzer/ops/job.py`: keep scheduled production fail-closed when the concrete model client is unavailable; do not auto-accept the initial REPORT-004 candidate.
- Modify `docs/operations/runbook.md`: document Codex preflight, candidate review, acceptance, activation, publication, rollback preservation, and truthful status wording.
- Modify `docs/operations/production-capability-matrix.md`: retain REPORT-004 `BLOCKED` until real human acceptance, then record exact evidence without conflating technical and product success.
- Extend focused tests in `tests/test_formal_narrative.py`, `tests/test_codex_expression_client.py`, `tests/test_formal_runtime_render.py`, `tests/test_production_dependencies.py`, `tests/test_report_generation.py`, `tests/test_formal_activation.py`, `tests/test_formal_pipeline.py`, `tests/test_cli.py`, `tests/test_ops_job.py`, and `tests/test_ops_verify.py`.

---

### Task 1: Typed Per-Stock Narrative Contract and Fail-Closed Validation

**Files:**
- Create: `src/stock_analyzer/ops/formal_narrative.py`
- Create: `tests/test_formal_narrative.py`
- Modify: `src/stock_analyzer/ops/formal_strategy_runtime.py`
- Test: `tests/test_formal_strategy_runtime.py`

**Interfaces:**
- Produce `DecisionLock`, containing exact `action`, `position_min_pct`, `position_max_pct`, `risk_if_wrong`, `required_confirmation`, `observation_conditions`, `invalidation_conditions`, and `exit_conditions`.
- Produce `FocusProgressDay(trade_date, evidence_id, thesis, action, supportive)` and add `focus_history_by_code: dict[str, list[FocusProgressDay]]` to `FormalReportPayload`.
- Produce `StockAnalysisRequest(ts_code, name, evidence_id, is_daily_recommendation, is_focus_stock, evidence, knowledge_refs, explicit_gaps, focus_history, decision_lock)`.
- Produce `NarrativePoint(text, evidence_ids)`, `StockNarrative`, `MarketNarrative`, and `FormalNarrative` Pydantic models with `extra="forbid"`.
- Produce `build_stock_analysis_requests(payload: FormalReportPayload) -> Sequence[StockAnalysisRequest]` and `validate_formal_narrative(payload: FormalReportPayload, narrative: FormalNarrative) -> FormalNarrative`.

- [ ] **Step 1: Write RED isolation, five-session, and mutation tests**

Create tests with concrete assertions:

```python
def test_requests_are_deduplicated_and_contain_only_their_stock_evidence():
    payload = two_stock_payload_with_overlap()
    requests = build_stock_analysis_requests(payload)
    assert [item.ts_code for item in requests] == ["600000.SH", "000001.SZ"]
    first = requests[0].model_dump_json()
    second = requests[1].model_dump_json()
    assert "000001.SZ" not in first
    assert "600000.SH" not in second
    assert requests[0].is_daily_recommendation is True
    assert requests[0].is_focus_stock is True


def test_focus_request_contains_exact_five_eligible_sessions():
    request = build_stock_analysis_requests(focus_payload())[0]
    assert [item.trade_date.isoformat() for item in request.focus_history] == [
        "2026-07-03", "2026-07-06", "2026-07-07", "2026-07-08", "2026-07-09"
    ]


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("action", "小仓试探"),
        ("position_max_pct", 90.0),
        ("risk_if_wrong", "没有风险"),
        ("required_confirmation", ["无条件买入"]),
        ("invalidation_conditions", ["永不失效"]),
        ("exit_conditions", ["不退出"]),
    ],
)
def test_narrative_cannot_mutate_strategy_decision(field, replacement):
    payload = one_stock_payload()
    narrative = valid_narrative(payload)
    changed = narrative.model_copy(
        update={
            "stocks": [
                narrative.stocks[0].model_copy(update={field: replacement})
            ]
        }
    )
    with pytest.raises(ValueError, match="decision lock"):
        validate_formal_narrative(payload, changed)


def test_narrative_rejects_foreign_evidence_and_new_numeric_fact():
    payload = one_stock_payload()
    narrative = valid_narrative(payload)
    foreign = narrative.model_copy(
        update={
            "stocks": [
                narrative.stocks[0].model_copy(
                    update={
                        "core_reasons": [
                            NarrativePoint(text="目标价 99.99 元", evidence_ids=["foreign-id"]),
                            *narrative.stocks[0].core_reasons[1:],
                        ]
                    }
                )
            ]
        }
    )
    with pytest.raises(ValueError, match="evidence whitelist|numeric whitelist"):
        validate_formal_narrative(payload, foreign)
```

- [ ] **Step 2: Run RED tests**

Run:

```bash
/Users/ccrt/股票分析助手/.venv/bin/python -m pytest tests/test_formal_narrative.py tests/test_formal_strategy_runtime.py -q
```

Expected: FAIL because the contract module and five-session payload field do not exist.

- [ ] **Step 3: Implement the minimal typed projection and validators**

Use frozen Pydantic contracts and validate:

```python
class NarrativePoint(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    text: str = Field(min_length=1, max_length=600)
    evidence_ids: list[str] = Field(min_length=1)


class StockNarrative(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    ts_code: str
    evidence_id: str
    narrative_marker: str = Field(pattern=r"^NARRATIVE-[A-F0-9]{12}$")
    analysis_summary: NarrativePoint
    core_reasons: list[NarrativePoint] = Field(min_length=3, max_length=3)
    action: str
    position_min_pct: float
    position_max_pct: float
    risk_if_wrong: str
    required_confirmation: list[str]
    observation_conditions: list[str]
    invalidation_conditions: list[str]
    exit_conditions: list[str]
    five_day_progress: list[NarrativePoint]


class FormalNarrative(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    market: MarketNarrative
    stocks: list[StockNarrative]
```

Normalize decision fields only from existing Strategy V2 objects. Extract decimal/percentage/date/stock-code tokens from narrative text and reject tokens absent from the request's canonical JSON. Require every `NarrativePoint.evidence_ids` value to belong to the same stock request. Require one narrative for every unique recommendation/focus stock and no extras.

- [ ] **Step 4: Run GREEN tests and regressions**

Run:

```bash
/Users/ccrt/股票分析助手/.venv/bin/python -m pytest tests/test_formal_narrative.py tests/test_formal_strategy_runtime.py tests/test_focus_strategy_v2.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 1**

```bash
git add src/stock_analyzer/ops/formal_narrative.py src/stock_analyzer/ops/formal_strategy_runtime.py tests/test_formal_narrative.py tests/test_formal_strategy_runtime.py
git commit -m "feat: define evidence-bound stock narratives"
```

---

### Task 2: Concrete Codex CLI Production Client

**Files:**
- Create: `src/stock_analyzer/ops/codex_expression_client.py`
- Create: `tests/test_codex_expression_client.py`
- Modify: `src/stock_analyzer/ops/production_dependencies.py`
- Modify: `tests/test_production_dependencies.py`
- Modify: `tests/test_default_formal_production_entry.py`

**Interfaces:**
- Produce `CodexExpressionConfig(binary, model="gpt-5.6-sol", reasoning_effort="high", timeout_seconds=600)`.
- Produce `CodexExpressionClient.express(payload: FormalReportPayload) -> FormalNarrative`.
- Invoke one subprocess per unique stock request plus one market-summary subprocess after the stock responses validate.
- Invoke `codex exec` with `--ephemeral`, `--ignore-user-config`, `--skip-git-repo-check`, `--sandbox read-only`, `--model gpt-5.6-sol`, `-c model_reasoning_effort="high"`, `--disable fast_mode`, `--output-schema <temporary-schema>`, `--output-last-message <temporary-output>`, and prompt input on stdin.
- Use a new empty temporary working directory. Do not pass a repository path, `.env.local`, raw warehouse path, receipt, deployment state, or credential.
- Convert nonzero exit, timeout, missing output, schema failure, authentication failure, and quota failure into redacted `CodexExpressionError`.

- [ ] **Step 1: Write RED command, isolation, parsing, and failure tests**

```python
def test_codex_client_uses_approved_model_high_reasoning_and_standard_speed(tmp_path):
    runner = RecordingRunner(valid_stock_and_market_outputs())
    client = CodexExpressionClient(runner=runner, temp_root=tmp_path)
    client.express(one_stock_payload())
    command = runner.calls[0].command
    assert command[:2] == [client.config.binary, "exec"]
    assert "--ephemeral" in command
    assert "--ignore-user-config" in command
    assert ["--model", "gpt-5.6-sol"] == command[command.index("--model"):command.index("--model") + 2]
    assert 'model_reasoning_effort="high"' in command
    assert command[command.index("--disable") + 1] == "fast_mode"
    assert runner.calls[0].cwd != Path.cwd()
    assert runner.calls[0].input_text


def test_codex_client_never_serializes_other_stock_or_runtime_paths(tmp_path):
    runner = RecordingRunner(valid_two_stock_outputs())
    CodexExpressionClient(runner=runner, temp_root=tmp_path).express(two_stock_payload())
    first_prompt = runner.calls[0].input_text
    assert "000001.SZ" not in first_prompt
    assert ".env.local" not in first_prompt
    assert "run_receipt" not in first_prompt
    assert "/Users/" not in first_prompt


@pytest.mark.parametrize("failure", ["timeout", "auth", "quota", "invalid_json"])
def test_codex_failure_is_redacted_and_fail_closed(tmp_path, failure):
    client = CodexExpressionClient(runner=FailingRunner(failure), temp_root=tmp_path)
    with pytest.raises(CodexExpressionError) as raised:
        client.express(one_stock_payload())
    assert "secret-sentinel" not in str(raised.value)
```

- [ ] **Step 2: Run RED tests**

Run:

```bash
/Users/ccrt/股票分析助手/.venv/bin/python -m pytest tests/test_codex_expression_client.py tests/test_production_dependencies.py -q
```

Expected: FAIL because the concrete client is absent and production still accepts `expression_client=None`.

- [ ] **Step 3: Implement the client and production factory binding**

Build the client in `load_default_external_runtime()` after data clients initialize. Bind `partial(express_formal_analysis, client=runtime.expression_client)` unconditionally in `build_production_formal_dependencies()`. Raise `ProductionDependencyError("formal Codex expression client is required")` when a caller supplies a runtime without a client.

Recorded tests use `RecordedCodexExpressionClient` returning a valid typed narrative; they no longer model `None` as production-valid.

- [ ] **Step 4: Run GREEN tests and the default recorded path**

```bash
/Users/ccrt/股票分析助手/.venv/bin/python -m pytest tests/test_codex_expression_client.py tests/test_production_dependencies.py tests/test_default_formal_production_entry.py -q
```

Expected: PASS; the default recorded path contains designated narrative markers in its staged artifacts.

- [ ] **Step 5: Commit Task 2**

```bash
git add src/stock_analyzer/ops/codex_expression_client.py src/stock_analyzer/ops/production_dependencies.py tests/test_codex_expression_client.py tests/test_production_dependencies.py tests/test_default_formal_production_entry.py
git commit -m "feat: bind the formal Codex analysis client"
```

---

### Task 3: Decision-First Home and Stock HTML

**Files:**
- Modify: `src/stock_analyzer/reports/generator.py`
- Modify: `src/stock_analyzer/reports/templates/index.html.j2`
- Modify: `src/stock_analyzer/reports/templates/stock.html.j2`
- Modify: `src/stock_analyzer/ops/formal_strategy_runtime.py`
- Modify: `tests/test_report_generation.py`
- Modify: `tests/test_formal_runtime_render.py`

**Interfaces:**
- Change the relevant renderer contract to `render_reports(output_dir: Path, recommendations: list[Recommendation], focus_states: list[FocusState], formal_narrative: FormalNarrative | None = None, fixture_mode: bool = False) -> None` while retaining the existing optional report inputs.
- Production Strategy V2 rendering requires a complete validated narrative; fixture rendering may omit it.
- Add `_narrative_stock_view(ts_code, formal_narrative)` and pass `market_narrative` plus `stock_narratives` into the home template and one matching `stock_narrative` into each stock template.
- Render each `narrative_marker` verbatim in a `data-narrative-marker` attribute and visible narrative text on both applicable pages.
- Render audit material only inside `<details class="audit-details"><summary>审计详情</summary><!-- escaped audit content --></details>` without `open`.

- [ ] **Step 1: Write RED narrative-consumption and readability tests**

```python
def test_validated_narrative_is_visible_on_home_and_stock_pages(tmp_path):
    payload, narrative = report_payload_and_narrative(marker="NARRATIVE-ABCDEF123456")
    render_payload(tmp_path, payload, narrative)
    home = (tmp_path / "index.html").read_text(encoding="utf-8")
    stock = (tmp_path / "daily/2026-07-10/stocks/600000.SH.html").read_text(encoding="utf-8")
    for html in (home, stock):
        assert "NARRATIVE-ABCDEF123456" in html
        assert "当前先等待确认" in html
        assert "三条核心理由" in html
        assert "买入或继续观察的条件" in html
        assert "失效和退出条件" in html


def test_main_view_is_decision_first_and_audit_is_collapsed(tmp_path):
    payload, narrative = report_payload_and_narrative()
    render_payload(tmp_path, payload, narrative)
    html = (tmp_path / "index.html").read_text(encoding="utf-8")
    main_view = html.split('<details class="audit-details">', 1)[0]
    assert main_view.index("市场总体结论") < main_view.index("推荐股票排序")
    assert "Gate" not in main_view
    assert "input set" not in main_view.lower()
    assert "receipt" not in main_view.lower()
    assert '<details class="audit-details">' in html
    assert '<details class="audit-details" open>' not in html


def test_focus_stock_displays_five_eligible_session_progress(tmp_path):
    payload, narrative = focus_payload_and_narrative()
    render_payload(tmp_path, payload, narrative)
    html = (tmp_path / "daily/2026-07-10/stocks/600000.SH.html").read_text(encoding="utf-8")
    for day in ("07-03", "07-06", "07-07", "07-08", "07-09"):
        assert day in html


def test_production_strategy_report_rejects_missing_narrative(tmp_path):
    payload, _ = report_payload_and_narrative()
    with pytest.raises(ValueError, match="validated formal narrative is required"):
        render_payload(tmp_path, payload, None)
```

- [ ] **Step 2: Run RED tests**

```bash
/Users/ccrt/股票分析助手/.venv/bin/python -m pytest tests/test_report_generation.py tests/test_formal_runtime_render.py -q
```

Expected: FAIL because HTML does not consume the JSON narrative and six modules are expanded.

- [ ] **Step 3: Implement narrative views and templates**

Home-page visible headings are exactly:

```text
市场总体结论
推荐股票排序
明确动作与仓位
三条核心理由
买入或继续观察的条件
失效和退出条件
重点股票五日进展
```

Stock-page visible sections use the same decision language. Preserve raw six-module atoms, evidence IDs, source versions, and knowledge references only in the collapsed audit details.

- [ ] **Step 4: Run GREEN tests and template fallback tests**

```bash
/Users/ccrt/股票分析助手/.venv/bin/python -m pytest tests/test_report_generation.py tests/test_formal_runtime_render.py tests/test_pipeline_smoke.py -q
```

Expected: PASS with Jinja present and with the existing no-Jinja fallback monkeypatch.

- [ ] **Step 5: Commit Task 3**

```bash
git add src/stock_analyzer/reports/generator.py src/stock_analyzer/reports/templates/index.html.j2 src/stock_analyzer/reports/templates/stock.html.j2 src/stock_analyzer/ops/formal_strategy_runtime.py tests/test_report_generation.py tests/test_formal_runtime_render.py
git commit -m "feat: render user-readable formal narratives"
```

---

### Task 4: Automated REPORT-004 Verification Gate

**Files:**
- Modify: `src/stock_analyzer/ops/formal_strategy_runtime.py`
- Modify: `src/stock_analyzer/ops/verify.py`
- Modify: `tests/test_formal_runtime_render.py`
- Modify: `tests/test_ops_job.py`
- Modify: `tests/test_ops_verify.py`

**Interfaces:**
- `verify_staged_formal_report()` requires `latest.json.formal_narrative`, exactly one narrative per unique stock, and matching marker presence in home and stock artifacts.
- `verify_production_result()` repeats the receipt-scoped marker/content/folding/internal-term checks after activation.
- Failure maps to existing redacted human-intervention status and prevents deploy artifact preparation and publication.

- [ ] **Step 1: Write RED tamper and missing-marker tests**

```python
def test_staged_verifier_rejects_json_only_narrative(tmp_path):
    receipt, hashes = write_valid_candidate(tmp_path)
    stock = tmp_path / "daily/2026-07-10/stocks/600000.SH.html"
    stock.write_text(stock.read_text(encoding="utf-8").replace("NARRATIVE-ABCDEF123456", ""), encoding="utf-8")
    assert verify_staged_formal_report(tmp_path, hash_artifact_tree(tmp_path), receipt) is False


def test_staged_verifier_rejects_internal_terms_in_main_view(tmp_path):
    receipt, hashes = write_valid_candidate(tmp_path)
    home = tmp_path / "index.html"
    home.write_text(home.read_text(encoding="utf-8").replace("市场总体结论", "Gate receipt input set"), encoding="utf-8")
    assert verify_staged_formal_report(tmp_path, hash_artifact_tree(tmp_path), receipt) is False


def test_job_preserves_prior_report_when_codex_output_is_invalid(tmp_path):
    prior = seed_prior_active_report(tmp_path)
    status = run_job_with_invalid_codex(tmp_path)
    assert status.status.value == "blocked_needs_human"
    assert (tmp_path / "reports/index.html").read_bytes() == prior
    assert not (tmp_path / "dist/pages").exists()
```

- [ ] **Step 2: Run RED tests**

```bash
/Users/ccrt/股票分析助手/.venv/bin/python -m pytest tests/test_formal_runtime_render.py tests/test_ops_job.py tests/test_ops_verify.py -q
```

Expected: FAIL because current verification accepts JSON-only narrative and has no readability main-view Gate.

- [ ] **Step 3: Implement receipt-scoped readability verification**

Parse HTML with bounded string checks, not network or browser execution. Split the main view before the audit `<details>` block. Require exact marker counts, decision headings, five-session focus dates, no visible score, no fixture/sample text, no secret shape, and no internal terms. Keep existing artifact hash and manifest checks unchanged.

- [ ] **Step 4: Run GREEN tests and all operations tests**

```bash
/Users/ccrt/股票分析助手/.venv/bin/python -m pytest tests/test_formal_runtime_render.py tests/test_ops_job.py tests/test_ops_verify.py tests/test_ops_artifacts.py tests/test_ops_publish.py -q
```

Expected: PASS; invalid narrative cannot reach deploy or publish.

- [ ] **Step 5: Commit Task 4**

```bash
git add src/stock_analyzer/ops/formal_strategy_runtime.py src/stock_analyzer/ops/verify.py tests/test_formal_runtime_render.py tests/test_ops_job.py tests/test_ops_verify.py
git commit -m "feat: enforce formal report readability gates"
```

---

### Task 5: Human-Gated Candidate Preparation and Exact Atomic Activation

**Files:**
- Modify: `src/stock_analyzer/data/readiness.py`
- Modify: `src/stock_analyzer/ops/formal_run.py`
- Modify: `src/stock_analyzer/ops/activation.py`
- Modify: `src/stock_analyzer/storage/evidence_store.py`
- Modify: `src/stock_analyzer/cli.py`
- Modify: `tests/test_formal_run_state.py`
- Modify: `tests/test_formal_activation.py`
- Modify: `tests/test_formal_pipeline.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Add `FormalRunState.AWAITING_HUMAN_ACCEPTANCE`.
- Produce `PreparedReportCandidate(run_id, candidate_root, artifact_hashes, candidate_hash, ledger_rows_hash, narrative_hash)`.
- Produce `FormalActivationCoordinator.prepare_candidate(receipt: RunReceipt, render: Callable[[Path], None], verify: Callable[[Path, dict[str, str]], bool], ledger_rows: Sequence[dict[str, Any]], pointer_payloads: dict[Path, bytes], advance_report_pointer: bool = True) -> PreparedReportCandidate` and `FormalActivationCoordinator.activate_prepared_candidate(candidate: PreparedReportCandidate, expected_candidate_hash: str) -> RunReceipt`.
- Persist a canonical candidate bundle below `local_warehouse/formal_evidence/report_candidates/<run_id>.json`; exclude it from receipt artifacts and deploy packages.
- Add `run_formal_strategy_v2(trade_date: date, report_cutoff: datetime, dependencies: FormalPipelineDependencies, run_id: str | None = None, require_human_acceptance: bool = False) -> FormalRunResult`. When true, stop in `AWAITING_HUMAN_ACCEPTANCE` after render and verify.
- Add CLI commands:
  - `prepare-formal-report-candidate --trade-date YYYY-MM-DD`
  - `activate-formal-report-candidate --run-id RUN_ID --expected-candidate-hash SHA256 --accept-readability`
- The activation command requires the explicit boolean flag, exact candidate hash, unchanged artifacts, matching evidence/ledger/narrative hashes, and the awaiting state. It performs existing Supabase two-phase activation and local pointer activation, with no provider or Codex call.

- [ ] **Step 1: Write RED prior-report, exact-hash, and no-rerun tests**

```python
def test_prepare_candidate_preserves_active_report_and_ledger(tmp_path):
    prior = seed_prior_active_report(tmp_path)
    candidate = prepare_candidate(tmp_path)
    assert candidate.receipt.state is FormalRunState.AWAITING_HUMAN_ACCEPTANCE
    assert (tmp_path / "reports/index.html").read_bytes() == prior
    assert candidate.ledger.active == {}
    assert candidate.candidate_root.is_dir()


def test_activation_requires_human_flag_and_exact_candidate_hash(tmp_path):
    candidate = prepare_candidate(tmp_path)
    result = runner.invoke(app, [
        "activate-formal-report-candidate",
        "--run-id", candidate.run_id,
        "--expected-candidate-hash", "0" * 64,
        "--accept-readability",
    ])
    assert result.exit_code != 0
    assert candidate.ledger.active == {}


def test_exact_candidate_activation_does_not_reacquire_or_reinvoke_codex(tmp_path):
    candidate, recorder = prepare_recorded_candidate(tmp_path)
    recorder.clear()
    activate_candidate(candidate, expected_candidate_hash=candidate.candidate_hash)
    assert recorder.calls == []
    assert candidate.ledger.activation_count == 1
    assert (tmp_path / "reports/index.html").read_bytes() == (candidate.candidate_root / "index.html").read_bytes()
```

- [ ] **Step 2: Run RED tests**

```bash
/Users/ccrt/股票分析助手/.venv/bin/python -m pytest tests/test_formal_run_state.py tests/test_formal_activation.py tests/test_formal_pipeline.py tests/test_cli.py -q
```

Expected: FAIL because candidate preparation and awaiting-human state do not exist.

- [ ] **Step 3: Split preparation from activation**

Refactor the current coordinator without changing its ledger/pointer order. `prepare_candidate()` owns RENDERING and VERIFYING and records hashes. `activate_prepared_candidate()` owns COMMITTING, ledger register/prepare/activate/readback, immutable artifact preservation, pointer batch, receipt activation IDs, and active marker. The old `activate()` composes both methods only when human acceptance is not required, preserving existing callers and failure-injection coverage.

- [ ] **Step 4: Run GREEN tests and atomic-failure matrix**

```bash
/Users/ccrt/股票分析助手/.venv/bin/python -m pytest tests/test_formal_run_state.py tests/test_formal_activation.py tests/test_formal_pipeline.py tests/test_cli.py tests/test_july10_formal_readiness_acceptance.py -q
```

Expected: PASS; every injected failure preserves the previous report and no unaccepted candidate becomes visible.

- [ ] **Step 5: Commit Task 5**

```bash
git add src/stock_analyzer/data/readiness.py src/stock_analyzer/ops/formal_run.py src/stock_analyzer/ops/activation.py src/stock_analyzer/storage/evidence_store.py src/stock_analyzer/cli.py tests/test_formal_run_state.py tests/test_formal_activation.py tests/test_formal_pipeline.py tests/test_cli.py
git commit -m "feat: require human acceptance before report activation"
```

---

### Task 6: Operations Documentation, Full Verification, Real Candidate, and Release Closure

**Files:**
- Modify: `docs/operations/runbook.md`
- Modify: `docs/operations/production-capability-matrix.md`
- Modify: `README.md`
- Review: every file changed from `8cac572`

**Interfaces and commands:**
- Codex preflight checks login and model catalog without printing credentials.
- Candidate preparation prints only run ID, candidate directory, boolean Gate results, and shortened non-secret hash prefixes.
- Human acceptance command requires the full candidate hash supplied from the local candidate manifest and the explicit `--accept-readability` flag.
- REPORT-004 remains `BLOCKED` after technical success and before user acceptance.

- [ ] **Step 1: Document exact operations and truthful status wording**

Document these commands:

```bash
codex login status
codex debug models
stock-analyzer-publish prepare-formal-report-candidate --trade-date 2026-07-10
stock-analyzer-publish ops verify-production --trade-date 2026-07-10
stock-analyzer-publish activate-formal-report-candidate --run-id <printed-run-id> --expected-candidate-hash <printed-full-hash> --accept-readability
stock-analyzer-publish ops prepare-deploy --trade-date 2026-07-10
stock-analyzer-publish ops publish-report-site --trade-date 2026-07-10
```

The runbook states that the final four activation/publication commands are forbidden until the user explicitly accepts the rendered candidate.

- [ ] **Step 2: Run focused security and hardcoding scans**

```bash
rg -n "OPENAI_API_KEY|sk-[A-Za-z0-9]|SUPABASE_SERVICE_ROLE_KEY=.*|CLOUDFLARE_API_TOKEN=.*|REPORT_PASSWORD=.*" src tests docs README.md
rg -n "/Users/ccrt|\.worktrees/|2026-07-10" src/stock_analyzer --glob '*.py'
git diff --check 8cac572
```

Expected: no credential values; no new production absolute path, worktree literal, or fixed report date; no whitespace errors.

- [ ] **Step 3: Run targeted and complete tests**

```bash
/Users/ccrt/股票分析助手/.venv/bin/python -m pytest tests/test_formal_narrative.py tests/test_codex_expression_client.py tests/test_formal_runtime_render.py tests/test_report_generation.py tests/test_production_dependencies.py tests/test_formal_activation.py tests/test_formal_pipeline.py tests/test_ops_job.py tests/test_ops_verify.py -q
/Users/ccrt/股票分析助手/.venv/bin/python -m pytest -q
```

Expected: all focused tests pass, then the complete suite passes with zero failures.

- [ ] **Step 4: Perform a read-only final review and repair every Critical/Important finding**

Review `git diff --stat 8cac572`, `git diff 8cac572`, all changed call sites, the candidate/activation boundary, subprocess security, narrative validators, HTML escaping, receipt hashes, failure injections, publish artifact scoping, and status wording. For each finding, add a reproducing test, run it RED, implement one fix, run GREEN, and commit:

```bash
git add <finding-test-files> <finding-source-files>
git commit -m "fix: address report readability review findings"
```

If no Critical/Important finding exists, make no review-only commit.

- [ ] **Step 5: Commit documentation before the real candidate**

```bash
git add docs/operations/runbook.md docs/operations/production-capability-matrix.md README.md
git commit -m "docs: add report readability acceptance runbook"
```

- [ ] **Step 6: Prepare and verify the real candidate without activation**

Silently load `/Users/ccrt/股票分析助手/.env.local` through the existing production entry. Run the Codex login/model preflight and candidate preparation for the frozen real formal date. Verify the candidate's structured decisions, evidence whitelist, numeric whitelist, narrative markers, home/stock HTML, exact five-session focus progress, secret scans, and artifact hashes. Confirm the active local report digest, active Supabase receipt/rows, Cloudflare content, deploy artifact, and publication flag are unchanged.

Expected: candidate state is `AWAITING_HUMAN_ACCEPTANCE`; all automated Gates pass; REPORT-004 remains `BLOCKED`; no activation or publication occurs.

- [ ] **Step 7: Pause only at the human readability Gate**

Provide the user clickable local candidate home and stock report paths plus the candidate hash. State separately:

- Automated technical Gate: PASS or exact failure.
- Product readability acceptance: waiting for user; not yet complete.
- Active online report: unchanged.
- Broker/order status: no broker connection and no order execution.

- [ ] **Step 8: After explicit user acceptance, activate, publish, and verify**

Run exact hash-bound activation, verify Supabase two-phase strong readback and active artifact hashes, prepare the receipt-scoped Pages artifact, publish to the existing Cloudflare Pages project, and run authenticated date/content/redaction smoke. Verify the new online narrative markers and all stock pages. Only then change REPORT-004 from `BLOCKED` to the evidence-supported completion level and commit the evidence.

- [ ] **Step 9: Verify launchd, merge, push, and clean up**

Verify `launchctl print gui/501/com.ccrt.stock-analysis-assistant.daily` still resolves the canonical main checkout, has the three approved calendar triggers, and contains no temporary worktree path. Merge the temporary branch into `main`, run the complete suite on main, push `origin/main`, remove the temporary worktree, delete local and remote temporary branches, restore `/Users/ccrt/Documents/股票分析助手` to the canonical supported path if needed, and prove the main worktree is clean and `main == origin/main`.

## Plan Self-Review

- Spec coverage: Tasks 1-2 cover per-stock evidence-bound Codex analysis and exact model settings; Tasks 3-4 cover user-visible narrative and automated Gates; Task 5 covers human-before-activation safety; Task 6 covers real evidence, human acceptance, publication, launchd, merge, push, and cleanup.
- Placeholder scan: every implementation step and test command is concrete. Angle-bracket values appear only in post-generation operator commands whose exact run ID/hash are printed by the candidate command.
- Type consistency: `FormalNarrative`, `StockNarrative`, `NarrativePoint`, `PreparedReportCandidate`, `prepare_candidate()`, and `activate_prepared_candidate()` retain the same names and responsibilities across all tasks.
- Scope control: no Strategy V2 scoring/action/position changes, no source-route changes, no broker/order work, no V1/V2 import, and no active report mutation before explicit human acceptance.
