# V3 Production Operations and Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Phase 1 of V3 production operations: a local Mac daily automation flow that runs only on trading days, retries safely after cleaning same-day partial results, writes machine-readable status, prepares Cloudflare Pages artifacts, and provides online smoke verification without automatically deploying.

**Architecture:** Keep production execution local because `local_warehouse`, `local_archive`, Tushare credentials, and Supabase service-role access are long-lived local production state. A new `stock_analyzer.ops` package owns calendar gating, cleanup, retry classification, status writing, deploy artifact preparation, Mac notifications, and online smoke checks. Cloudflare receives only a prepared `dist/pages` tree; automatic Cloudflare upload, Strategy V2, and Product UI are mandatory later phases, not part of this Phase 1 implementation.

**Tech Stack:** Python 3.12 in project `.venv`, Typer, Pydantic, Supabase Python client, Tushare existing dependency, DuckDB/Parquet existing local warehouse, HTTPX, pytest, macOS `launchd`, AppleScript/`osascript` only through a gated notification wrapper, Cloudflare Pages Functions TypeScript, Wrangler documented but not invoked automatically.

## Global Constraints

- Project root for production artifacts is `/Users/ccrt/股票分析助手`.
- Development worktree is `/Users/ccrt/股票分析助手/.worktrees/codex/v3-mvp`, accessible through `/Users/ccrt/Documents/股票分析助手`.
- Daily schedule is 18:30 first run, 19:00 first retry, 19:30 second retry.
- First automation target is local Mac `launchd`.
- `.env.local`, `SUPABASE_SERVICE_ROLE_KEY`, Tushare token, Cloudflare API token, report password, and session secret must never be printed, committed, copied into generated reports, or written into logs.
- User-facing output is the stock analysis report; operational status is machine-readable and must not dominate the report.
- Non-trading days write status `skipped_non_trading_day`, do not run analysis, do not prepare a new deploy package, and do not overwrite reports.
- Calendar source is Supabase `market_calendar` first; if missing, use Tushare calendar and write back; if both fail, status is `calendar_unknown` and human intervention is required.
- Retryable failures clean same-day partial results before retry.
- Cleanup is scoped only to the current `trade_date`; never delete historical dates, whole Supabase tables, whole `stock_master`, whole `local_archive`, or whole `local_warehouse`.
- `reports/`, `local_warehouse/`, `local_archive/`, `logs/`, and `dist/` remain untracked generated artifacts.
- Success prepares `dist/pages` but does not upload Cloudflare.
- Online smoke command is provided for manual Cloudflare deployments.
- Mac notification fires only for `failed_needs_human`.
- Real production runs, real same-day cleanup against Supabase, real Cloudflare deploy, launchd enabling, and any Supabase schema change require explicit user confirmation after tests and review.
- Every Phase 1 implementer and reviewer uses GPT-5.5 xhigh. Do not use mini models for any Phase 1 task.
- Final whole-branch review uses GPT-5.5 xhigh.

---

## File Structure

- Create `src/stock_analyzer/ops/__init__.py`
- Create `src/stock_analyzer/ops/status.py` for job status models and failure taxonomy.
- Create `src/stock_analyzer/ops/redaction.py` for secret redaction.
- Create `src/stock_analyzer/ops/calendar.py` for trading-day decisions.
- Create `src/stock_analyzer/ops/cleanup.py` for same-day partial-result cleanup.
- Create `src/stock_analyzer/ops/verify.py` for post-run quality gates.
- Create `src/stock_analyzer/ops/artifacts.py` for `dist/pages` preparation.
- Create `src/stock_analyzer/ops/notify.py` for Mac notification wrapper.
- Create `src/stock_analyzer/ops/job.py` for run orchestration and retry policy.
- Create `src/stock_analyzer/ops/smoke.py` for online report-site smoke.
- Modify `src/stock_analyzer/cli.py` to add `ops` subcommands.
- Add tests: `tests/test_ops_status.py`, `tests/test_ops_calendar.py`, `tests/test_ops_cleanup.py`, `tests/test_ops_artifacts.py`, `tests/test_ops_job.py`, `tests/test_ops_smoke.py`, `tests/test_ops_notify.py`.
- Create `ops/launchd/com.ccrt.stock-analysis-assistant.daily.plist.example`.
- Create `docs/operations/runbook.md`.
- Create `docs/operations/cloudflare-pages.md`.
- Create `docs/operations/mandatory-next-phases.md`.
- Modify `.gitignore` to include `logs/` and `dist/`.

## Model Assignment

| Task | Implementer | Reviewer | Reason |
| --- | --- | --- | --- |
| Task 1 | GPT-5.5 xhigh | GPT-5.5 xhigh | Status taxonomy and redaction define every later safety gate |
| Task 2 | GPT-5.5 xhigh | GPT-5.5 xhigh | Trading-day mistakes can create false reports |
| Task 3 | GPT-5.5 xhigh | GPT-5.5 xhigh | Cleanup touches production data and must be exact |
| Task 4 | GPT-5.5 xhigh | GPT-5.5 xhigh | Verification protects analysis/report credibility |
| Task 5 | GPT-5.5 xhigh | GPT-5.5 xhigh | Retry orchestration controls production writes |
| Task 6 | GPT-5.5 xhigh | GPT-5.5 xhigh | Cloudflare artifact and smoke protect published reports |
| Task 7 | GPT-5.5 xhigh | GPT-5.5 xhigh | launchd and notifications touch local production automation |
| Task 8 | GPT-5.5 xhigh | GPT-5.5 xhigh | Final docs and handoff lock operational process |
| Final review | GPT-5.5 xhigh | GPT-5.5 xhigh | Whole-system production safety review |

## Task 1: Status Taxonomy and Secret Redaction

**Files:**
- Create: `src/stock_analyzer/ops/__init__.py`
- Create: `src/stock_analyzer/ops/status.py`
- Create: `src/stock_analyzer/ops/redaction.py`
- Test: `tests/test_ops_status.py`

**Interfaces:**
- Produces: `RunStatus` enum with `success_with_recommendations`, `success_no_recommendations`, `skipped_non_trading_day`, `calendar_unknown`, `warning`, `failed_retryable`, `failed_needs_human`.
- Produces: `FailureClass` enum with retryable and human-intervention categories.
- Produces: `JobStatus.write_json(path: Path) -> None`.
- Produces: `redact_secrets(text: str, explicit_secrets: Iterable[str] = ()) -> str`.

- [ ] **Step 1: Write failing tests**

Create `tests/test_ops_status.py` with tests that:

- instantiate `JobStatus` for `success_no_recommendations`;
- write it to JSON;
- assert fields include `trade_date`, `attempt`, `scheduled_slot`, `status`, `stage`, `fix_suggestion`;
- assert explicit fake secrets and `Authorization: Bearer` values are redacted.

Run: `.venv/bin/python -m pytest tests/test_ops_status.py -v`

Expected: FAIL because `stock_analyzer.ops.status` does not exist.

- [ ] **Step 2: Implement status and redaction**

Implement `RunStatus`, `FailureClass`, `JobStatus`, and `redact_secrets`. `JobStatus` must include every field listed in the design `latest-status.json` section. `write_json()` must create parent directories and write UTF-8 JSON with `ensure_ascii=False`.

- [ ] **Step 3: Verify**

Run: `.venv/bin/python -m pytest tests/test_ops_status.py -v`

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add src/stock_analyzer/ops tests/test_ops_status.py
git commit -m "feat: add operations status taxonomy"
```

## Task 2: Trading-Day Gate

**Files:**
- Create: `src/stock_analyzer/ops/calendar.py`
- Modify: `src/stock_analyzer/storage/repositories.py` only if an existing calendar method is missing.
- Test: `tests/test_ops_calendar.py`

**Interfaces:**
- Produces: `TradingDayDecision(status: Literal["trading_day", "non_trading_day", "calendar_unknown"], source: str, message: str)`.
- Produces: `decide_trading_day(trade_date: date, repository, tushare_calendar_loader=None) -> TradingDayDecision`.

- [ ] **Step 1: Write failing tests**

Create `tests/test_ops_calendar.py` with fake repository and fake Tushare loader tests:

- Supabase calendar says trading day -> returns `trading_day`, source `supabase`.
- Supabase calendar says non-trading day -> returns `non_trading_day`, source `supabase`.
- Supabase missing and Tushare says trading -> writes calendar row and returns `trading_day`.
- Supabase missing and Tushare fails -> returns `calendar_unknown`.

Run: `.venv/bin/python -m pytest tests/test_ops_calendar.py -v`

Expected: FAIL because module does not exist.

- [ ] **Step 2: Implement calendar decision**

Implement the gate without guessing by weekday. If both Supabase and Tushare are unavailable, return `calendar_unknown`.

- [ ] **Step 3: Verify**

Run: `.venv/bin/python -m pytest tests/test_ops_calendar.py tests/test_repositories.py -v`

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add src/stock_analyzer/ops/calendar.py src/stock_analyzer/storage/repositories.py tests/test_ops_calendar.py
git commit -m "feat: add trading day automation gate"
```

## Task 3: Same-Day Cleanup Guard

**Files:**
- Create: `src/stock_analyzer/ops/cleanup.py`
- Modify: `src/stock_analyzer/storage/repositories.py`
- Test: `tests/test_ops_cleanup.py`

**Interfaces:**
- Produces: `CleanupSummary`.
- Produces: `cleanup_trade_date(project_root: Path, repository, trade_date: date) -> CleanupSummary`.
- Repository must expose a same-day cleanup method that deletes only the target `trade_date` rows from approved tables.

- [ ] **Step 1: Write failing tests**

Create `tests/test_ops_cleanup.py` with fake repository/filesystem tests:

- cleanup calls repository only for the target date;
- cleanup removes `reports/daily/YYYY-MM-DD`;
- cleanup removes `local_archive/manifests/YYYY-MM-DD.json`;
- cleanup removes `local_archive/reports/YYYY-MM-DD`;
- cleanup refuses to run if `trade_date` is missing or malformed;
- cleanup failure raises and prevents retry.

Run: `.venv/bin/python -m pytest tests/test_ops_cleanup.py -v`

Expected: FAIL because cleanup module does not exist.

- [ ] **Step 2: Implement cleanup**

Implement cleanup with an allowlist:

- `recommendation_daily`
- `focus_watchlist_state`
- `evidence_package_index`
- `evaluation_task`
- `market_price_daily`
- `daily_basic_indicator`
- `data_source_run`

Do not delete `stock_master`. Do not delete any whole table. Do not delete historical dates.

- [ ] **Step 3: Verify**

Run: `.venv/bin/python -m pytest tests/test_ops_cleanup.py tests/test_repositories.py -v`

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add src/stock_analyzer/ops/cleanup.py src/stock_analyzer/storage/repositories.py tests/test_ops_cleanup.py
git commit -m "feat: clean same-day partial run outputs"
```

## Task 4: Production Verification Gates

**Files:**
- Create: `src/stock_analyzer/ops/verify.py`
- Test: `tests/test_ops_job.py`

**Interfaces:**
- Produces: `ProductionVerification`.
- Produces: `verify_production_result(project_root: Path, repository, trade_date: date) -> ProductionVerification`.

- [ ] **Step 1: Write failing tests**

Create/extend `tests/test_ops_job.py` with checks for:

- recommendations are between 0 and 10;
- `0` recommendations is success state `success_no_recommendations`;
- evidence count matches recommendations;
- evaluation task count is consistent with recommendations;
- selected market rows do not approach full-market scale;
- report date equals trade date;
- fixture/sample strings fail verification;
- missing `reports/index.html` fails verification.

Run: `.venv/bin/python -m pytest tests/test_ops_job.py -v`

Expected: FAIL because verification module does not exist.

- [ ] **Step 2: Implement verification**

Implement verification as machine gate, not user-facing report content. It must produce `fix_suggestion` values for failures.

- [ ] **Step 3: Verify**

Run: `.venv/bin/python -m pytest tests/test_ops_job.py tests/test_report_generation.py -v`

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add src/stock_analyzer/ops/verify.py tests/test_ops_job.py
git commit -m "feat: verify production run outputs"
```

## Task 5: Retry Orchestrator

**Files:**
- Create: `src/stock_analyzer/ops/job.py`
- Modify: `src/stock_analyzer/cli.py`
- Test: `tests/test_ops_job.py`

**Interfaces:**
- Consumes: calendar gate, cleanup, verification, status, redaction.
- Produces: `run_daily_job(project_root: Path, trade_date: date, scheduled_slot: str, attempt: int, prepare_deploy: bool) -> JobStatus`.
- CLI: `stock_analyzer ops run-daily-job --trade-date YYYY-MM-DD --scheduled-slot HH:MM --attempt N --prepare-deploy`.

- [ ] **Step 1: Write failing orchestrator tests**

Extend `tests/test_ops_job.py`:

- non-trading day skips without calling production run;
- calendar unknown returns `calendar_unknown`;
- retryable failure attempt 2 calls cleanup before rerun;
- cleanup failure returns `failed_needs_human`;
- third failed attempt returns `failed_needs_human`;
- success with zero recommendations writes `success_no_recommendations`;
- status JSON is redacted.

Run: `.venv/bin/python -m pytest tests/test_ops_job.py -v`

Expected: FAIL because orchestrator does not exist.

- [ ] **Step 2: Implement orchestrator**

Implement stage transitions:

1. `calendar`
2. `cleanup` when `attempt > 1`
3. `health_check`
4. `run_daily`
5. `verify`
6. `prepare_deploy`
7. `complete`

Do not run real Cloudflare deploy. Return non-zero CLI exit for `failed_needs_human`, `failed_retryable`, and `calendar_unknown`.

- [ ] **Step 3: Verify**

Run: `.venv/bin/python -m pytest tests/test_ops_job.py tests/test_cli.py -v`

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add src/stock_analyzer/ops/job.py src/stock_analyzer/cli.py tests/test_ops_job.py
git commit -m "feat: orchestrate daily production automation"
```

## Task 6: Deploy Artifact and Online Smoke

**Files:**
- Create: `src/stock_analyzer/ops/artifacts.py`
- Create: `src/stock_analyzer/ops/smoke.py`
- Modify: `src/stock_analyzer/cli.py`
- Test: `tests/test_ops_artifacts.py`
- Test: `tests/test_ops_smoke.py`

**Interfaces:**
- Produces: `prepare_pages_artifact(project_root: Path, output_dir: Path) -> Path`.
- Produces: `smoke_report_site(base_url: str, password: str | None) -> SmokeResult`.
- CLI: `stock_analyzer ops prepare-deploy --output-dir dist/pages`.
- CLI: `stock_analyzer ops smoke-report-site --url URL --password-env REPORT_PASSWORD`.

- [ ] **Step 1: Write failing artifact and smoke tests**

Tests must assert:

- `dist/pages` contains report files and `functions/_middleware.ts`;
- forbidden paths are absent;
- smoke validates redirect to `/login`;
- smoke can submit password without printing it;
- smoke fails if fixture/sample appears in page content;
- smoke fails if sensitive variable names or fake secret patterns appear.

Run: `.venv/bin/python -m pytest tests/test_ops_artifacts.py tests/test_ops_smoke.py -v`

Expected: FAIL because modules do not exist.

- [ ] **Step 2: Implement artifact preparation and smoke**

Artifact preparation must copy only allowed static files. Smoke must never echo the password.

- [ ] **Step 3: Verify**

Run: `.venv/bin/python -m pytest tests/test_ops_artifacts.py tests/test_ops_smoke.py tests/test_cloudflare_middleware.py -v`

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add src/stock_analyzer/ops/artifacts.py src/stock_analyzer/ops/smoke.py src/stock_analyzer/cli.py tests/test_ops_artifacts.py tests/test_ops_smoke.py
git commit -m "feat: prepare and smoke test report deployment"
```

## Task 7: Mac Notification and Launchd Template

**Files:**
- Create: `src/stock_analyzer/ops/notify.py`
- Create: `ops/launchd/com.ccrt.stock-analysis-assistant.daily.plist.example`
- Modify: `.gitignore`
- Test: `tests/test_ops_notify.py`
- Test: `tests/test_config_health.py`

**Interfaces:**
- Produces: `should_notify(status: JobStatus) -> bool`.
- Produces: `notify_mac(title: str, message: str, enabled: bool) -> None`.
- Produces: launchd template for 18:30/19:00/19:30 slots.

- [ ] **Step 1: Write failing tests**

Tests must assert:

- only `failed_needs_human` notifies;
- success, warning, retryable failure, no recommendation, and non-trading-day do not notify;
- notification text is redacted;
- launchd template contains all three schedule slots or documents separate plist entries;
- launchd template uses `/Users/ccrt/股票分析助手` and `.env.local`;
- template is not installed or enabled by tests.

Run: `.venv/bin/python -m pytest tests/test_ops_notify.py tests/test_config_health.py -v`

Expected: FAIL because notify/template does not exist.

- [ ] **Step 2: Implement notification wrapper and launchd template**

Use a wrapper that can be disabled in tests. Do not call `osascript` during unit tests.

- [ ] **Step 3: Ignore generated files**

Add to `.gitignore`:

```gitignore
logs/
dist/
```

- [ ] **Step 4: Verify**

Run: `.venv/bin/python -m pytest tests/test_ops_notify.py tests/test_config_health.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/stock_analyzer/ops/notify.py ops/launchd/com.ccrt.stock-analysis-assistant.daily.plist.example .gitignore tests/test_ops_notify.py tests/test_config_health.py
git commit -m "feat: add mac automation notification template"
```

## Task 8: Operations Runbook and Mandatory Next Phases

**Files:**
- Create: `docs/operations/runbook.md`
- Create: `docs/operations/cloudflare-pages.md`
- Create: `docs/operations/mandatory-next-phases.md`
- Modify: `README.md`
- Test: `tests/test_config_health.py`

**Interfaces:**
- Produces human runbook for Phase 1.
- Produces Cloudflare manual publish and smoke checklist.
- Produces mandatory Phase 2-4 roadmap.

- [ ] **Step 1: Write failing docs tests**

Tests must assert docs include:

- 18:30/19:00/19:30 schedule;
- cleanup-before-retry rule;
- non-trading-day skip rule;
- manual `wrangler pages deploy dist/pages`;
- Strategy V2 and Product UI marked mandatory, not optional;
- GPT-5.5 xhigh requirement for subagents.

Run: `.venv/bin/python -m pytest tests/test_config_health.py -v`

Expected: FAIL until docs are written.

- [ ] **Step 2: Write docs**

Write concise docs with commands and explicit “do not enable without approval” notes.

- [ ] **Step 3: Link from README**

Add an operations section pointing to the three docs.

- [ ] **Step 4: Verify**

Run: `.venv/bin/python -m pytest tests/test_config_health.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add README.md docs/operations tests/test_config_health.py
git commit -m "docs: add production operations runbooks"
```

## Task 9: Final Verification and Handoff

**Files:**
- Modify only if verification reveals a concrete defect in Tasks 1-8.

**Interfaces:**
- Consumes all Phase 1 interfaces.
- Produces branch ready for explicit user-approved implementation actions: installing launchd, production run, manual Cloudflare deploy.

- [ ] **Step 1: Run full local tests**

Run: `.venv/bin/python -m pytest`

Expected: all tests pass.

- [ ] **Step 2: Prepare deploy artifact without upload**

Run:

```bash
PROJECT_ROOT=/Users/ccrt/股票分析助手 PYTHONPATH=src .venv/bin/python -m stock_analyzer ops prepare-deploy --output-dir /tmp/stock-analysis-pages
```

Expected: `/tmp/stock-analysis-pages/index.html` and `/tmp/stock-analysis-pages/functions/_middleware.ts` exist.

- [ ] **Step 3: Check forbidden files**

Run:

```bash
find /tmp/stock-analysis-pages -maxdepth 4 \( -name '.env*' -o -name '.git' -o -name '.venv' -o -name 'local_warehouse' -o -name 'local_archive' -o -name 'logs' -o -name '.superpowers' \)
```

Expected: no output.

- [ ] **Step 4: Run verification command without production write**

Run:

```bash
PROJECT_ROOT=/Users/ccrt/股票分析助手 PYTHONPATH=src .venv/bin/python -m stock_analyzer ops verify-production --trade-date 2026-07-08
```

Expected: exits 0 if existing production artifacts are present. If missing, report that a user-approved production run is required; do not run production automatically.

- [ ] **Step 5: Confirm no secret assignments in tracked files**

Run:

```bash
rg -n "SUPABASE_SERVICE_ROLE_KEY=.*|TUSHARE_TOKEN=.*|CLOUDFLARE_API_TOKEN=.*|REPORT_PASSWORD=.*|REPORT_SESSION_SECRET=.*" README.md docs src tests scripts ops functions
```

Expected: no real assignments. Mentions of variable names without values are allowed.

- [ ] **Step 6: Final review**

Dispatch final whole-branch review on GPT-5.5 xhigh. Fix Critical/Important findings and re-review.

- [ ] **Step 7: Handoff**

Report:

- test results;
- artifact preparation result;
- launchd install is not enabled;
- Cloudflare deploy is not executed;
- next real-world actions requiring explicit approval.

## Self-Review Checklist

- Spec coverage: Mac automation, retry cleanup, calendar gate, status JSON, Mac notification, deploy artifact, online smoke, and mandatory later phases are covered.
- Completion scan: no unresolved marker text remains.
- Type consistency: status, calendar, cleanup, verify, artifact, notify, job, and smoke interfaces are introduced before use.
- Safety: no automatic production run, cleanup, launchd enable, or Cloudflare deploy is performed by this plan.
- Model policy: every Phase 1 task uses GPT-5.5 xhigh; mini is prohibited.

## Execution Choice

Recommended execution: **Subagent-Driven**. Dispatch one GPT-5.5 xhigh implementer and one GPT-5.5 xhigh reviewer per task, then run a GPT-5.5 xhigh whole-branch review before any real production action.
