# V3 Phase 2 Cloudflare Automation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Phase 2 Cloudflare automation: one local one-command publish, automatic smoke verification, last-known-good rollback, local status page, and automatic publishing after the first successful manual publish.

**Architecture:** Add a focused `stock_analyzer.ops.publish` module that orchestrates the Phase 1 deploy artifact and smoke primitives without changing stock analysis logic. Keep Cloudflare deployment behind an injectable Wrangler runner so unit tests never perform real network deploys. Persist publish state locally only, with redaction and a simple status page for the user.

**Tech Stack:** Python 3.12, Typer, Pydantic, HTTPX smoke client already present, Cloudflare Wrangler invoked through `subprocess.run`, pytest, macOS notification wrapper already present, local filesystem state under `logs/publish/` and `local_archive/publish/`.

## Global Constraints

- Project root for production artifacts is `/Users/ccrt/股票分析助手`.
- Development worktree is `/Users/ccrt/股票分析助手/.worktrees/codex/v3-mvp`, accessible through `/Users/ccrt/Documents/股票分析助手`.
- Phase 2 first version uses local `.env.local` / environment variables, not GitHub Secrets.
- Do not print, copy, commit, or log `.env.local`, `SUPABASE_SERVICE_ROLE_KEY`, Tushare token, Cloudflare token, report password, or session secret.
- First real Cloudflare deployment requires explicit user approval after tests and review.
- After the first successful one-command publish and online smoke, auto publish is enabled automatically.
- Auto publish runs only after the whole Phase 1 daily production flow eventually succeeds.
- Do not publish non-trading-day reports.
- Do not publish zero-recommendation reports.
- Publish 1-9 recommendation reports; quality is Phase 3 Strategy V2.
- Publish status remains local only; do not write Phase 2 publish results to Supabase.
- Use Wrangler for Phase 2 first version; keep Cloudflare API and GitHub Actions as future directions.
- Every implementer, reviewer, and subagent for this plan must use GPT-5.5 xhigh. Mini models are forbidden for Phase 2.

---

## Model Assignment

| Task | Implementer | Reviewer | Reason |
| --- | --- | --- | --- |
| Task 1 | GPT-5.5 xhigh | GPT-5.5 xhigh | Publish state and redaction are safety-critical shared contracts |
| Task 2 | GPT-5.5 xhigh | GPT-5.5 xhigh | Candidate selection decides what reaches production Cloudflare |
| Task 3 | GPT-5.5 xhigh | GPT-5.5 xhigh | Wrangler invocation touches Cloudflare credentials and deploy output |
| Task 4 | GPT-5.5 xhigh | GPT-5.5 xhigh | Orchestration controls retry, rollback, and success marking |
| Task 5 | GPT-5.5 xhigh | GPT-5.5 xhigh | CLI and auto-publish integration affect daily production behavior |
| Task 6 | GPT-5.5 xhigh | GPT-5.5 xhigh | User-facing status/notification must be clear and safe |
| Task 7 | GPT-5.5 xhigh | GPT-5.5 xhigh | Docs and config health lock the operating procedure |
| Final review | GPT-5.5 xhigh | GPT-5.5 xhigh | Whole-system production safety review before real deployment |

No task may be assigned to GPT-5.4, GPT-5 mini, or any low-config model. If subagents are used, dispatch each task with the model requirement above in the task prompt.

## File Structure

- Create `src/stock_analyzer/ops/publish.py` for publish models, preflight, candidate selection, Wrangler runner, publish orchestration, rollback, state persistence, and status-page rendering.
- Modify `src/stock_analyzer/config.py` to load publish-related environment variable names and safe non-secret configuration.
- Modify `src/stock_analyzer/cli.py` to add `ops publish-report-site`, add a `stock_analyzer_publish()` console entrypoint, and pass dependencies into `run_daily_job`.
- Modify `pyproject.toml` to register the fixed user command `stock-analyzer-publish`.
- Modify `src/stock_analyzer/ops/job.py` to optionally trigger auto publish after successful Phase 1 completion.
- Modify `src/stock_analyzer/ops/status.py` only if a new failure class is needed for publish integration; prefer Phase 2-specific enums in `publish.py`.
- Test with `tests/test_ops_publish.py`.
- Extend `tests/test_ops_job.py` for auto-publish integration.
- Extend `tests/test_cli.py` or create publish CLI tests in `tests/test_ops_publish.py`.
- Modify `docs/operations/cloudflare-pages.md` with the new one-command publish flow.
- Modify `docs/operations/mandatory-next-phases.md` to mark Phase 2 design/plan status and later Phase 3/4 sequence.
- Modify `tests/test_config_health.py` so docs assertions include the new Phase 2 safety boundaries.

## Shared Interfaces To Implement

These interfaces are used across tasks. Keep names stable once introduced.

```python
class PublishStatus(str, Enum):
    READY_SKIPPED = "ready_skipped"
    SUCCESS = "success"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_NEEDS_HUMAN = "failed_needs_human"

class PublishFailureClass(str, Enum):
    NO_PUBLISHABLE_REPORT = "no_publishable_report"
    ZERO_RECOMMENDATIONS = "zero_recommendations"
    NON_TRADING_DAY = "non_trading_day"
    SUPABASE_CAPACITY_STOP = "supabase_capacity_stop"
    CONFIG_MISSING = "config_missing"
    ARTIFACT_INVALID = "artifact_invalid"
    WRANGLER_TEMPORARY_FAILURE = "wrangler_temporary_failure"
    WRANGLER_AUTH_FAILURE = "wrangler_auth_failure"
    SMOKE_FAILED = "smoke_failed"
    ROLLBACK_FAILED = "rollback_failed"
    SECRET_LEAK_BLOCKED = "secret_leak_blocked"

class PublishMode(str, Enum):
    MANUAL_ONCE = "manual_once"
    AUTO = "auto"

class PublishState(BaseModel):
    trade_date: date | None
    status: PublishStatus
    mode: PublishMode
    started_at: datetime
    finished_at: datetime | None
    published_url: str | None
    report_site_url: str | None
    recommendations: int | None
    failure_class: PublishFailureClass | None
    rollback_performed: bool
    auto_publish_enabled: bool
    last_known_good_path: str | None
    summary_for_user: str
    user_action_required: str | None
    error_message_redacted: str | None
    checks: tuple[str, ...]

@dataclass(frozen=True)
class PublishConfig:
    project_root: Path
    report_site_url: str
    cloudflare_pages_project_name: str
    report_password_env: str = "REPORT_PASSWORD"
    report_session_secret_env: str = "REPORT_SESSION_SECRET"
    cloudflare_token_env: str = "CLOUDFLARE_API_TOKEN"
    cloudflare_account_id_env: str = "CLOUDFLARE_ACCOUNT_ID"
    auto_publish_flag_path: Path
    state_path: Path
    status_page_path: Path
    last_known_good_dir: Path

@dataclass(frozen=True)
class PublishCandidate:
    trade_date: date
    recommendations: int
    job_status_path: Path
    reports_dir: Path

@dataclass(frozen=True)
class WranglerResult:
    exit_code: int
    stdout_redacted: str
    stderr_redacted: str
    deployment_url: str | None
```

## Task 1: Publish State, Config, and Redaction Contracts

**Files:**
- Create: `src/stock_analyzer/ops/publish.py`
- Modify: `src/stock_analyzer/config.py`
- Test: `tests/test_ops_publish.py`

**Interfaces:**
- Produces: `PublishStatus`, `PublishFailureClass`, `PublishMode`, `PublishState`, `PublishConfig`, `PublishCandidate`, `WranglerResult`.
- Produces: `PublishState.write_json(path: Path) -> None`.
- Produces: `PublishConfig.from_app_config(config: AppConfig) -> PublishConfig`.
- Consumes: `stock_analyzer.ops.redaction.redact_secrets`.

- [ ] **Step 1: Write failing tests for publish state redaction**

Add `tests/test_ops_publish.py` with:

```python
from __future__ import annotations

import json
from datetime import date, datetime, timezone

from stock_analyzer.config import AppConfig
from stock_analyzer.ops.publish import (
    PublishConfig,
    PublishFailureClass,
    PublishMode,
    PublishState,
    PublishStatus,
)


def test_publish_state_write_json_redacts_secret_like_text(tmp_path):
    state = PublishState(
        trade_date=date(2026, 7, 9),
        status=PublishStatus.FAILED_NEEDS_HUMAN,
        mode=PublishMode.MANUAL_ONCE,
        started_at=datetime(2026, 7, 9, 12, 0, tzinfo=timezone.utc),
        finished_at=datetime(2026, 7, 9, 12, 1, tzinfo=timezone.utc),
        published_url=None,
        report_site_url="https://stock-analysis-assistant-v3.pages.dev",
        recommendations=3,
        failure_class=PublishFailureClass.CONFIG_MISSING,
        rollback_performed=False,
        auto_publish_enabled=False,
        last_known_good_path=None,
        summary_for_user="发布失败：CLOUDFLARE_API_TOKEN=secret-value",
        user_action_required="检查 Authorization: Bearer secret-token",
        error_message_redacted="REPORT_PASSWORD=secret-password",
        checks=("preflight",),
    )

    output_path = tmp_path / "logs" / "publish" / "latest-status.json"
    state.write_json(output_path)

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    rendered = json.dumps(payload, ensure_ascii=False)
    assert payload["status"] == "failed_needs_human"
    assert payload["mode"] == "manual_once"
    assert "secret-value" not in rendered
    assert "secret-token" not in rendered
    assert "secret-password" not in rendered
    assert "[REDACTED]" in rendered


def test_publish_config_from_app_config_uses_local_paths(tmp_path):
    config = AppConfig.load(
        {
            "PROJECT_ROOT": str(tmp_path),
            "REPORT_SITE_URL": "https://stock-analysis-assistant-v3.pages.dev",
            "CLOUDFLARE_PAGES_PROJECT_NAME": "stock-analysis-assistant-v3",
        }
    )

    publish_config = PublishConfig.from_app_config(config)

    assert publish_config.project_root == tmp_path
    assert publish_config.report_site_url == "https://stock-analysis-assistant-v3.pages.dev"
    assert publish_config.cloudflare_pages_project_name == "stock-analysis-assistant-v3"
    assert publish_config.state_path == tmp_path / "logs" / "publish" / "latest-status.json"
    assert publish_config.status_page_path == tmp_path / "logs" / "publish" / "status.html"
    assert publish_config.last_known_good_dir == tmp_path / "local_archive" / "publish" / "last-known-good"
    assert publish_config.auto_publish_flag_path == tmp_path / "logs" / "publish" / "auto-publish-enabled.json"
```

- [ ] **Step 2: Run tests to verify failure**

Run: `.venv/bin/python -m pytest tests/test_ops_publish.py -v`

Expected: FAIL because `stock_analyzer.ops.publish` does not exist.

- [ ] **Step 3: Implement publish enums and state models**

In `src/stock_analyzer/ops/publish.py`, add:

```python
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator

from stock_analyzer.config import AppConfig
from stock_analyzer.ops.redaction import redact_secrets


class PublishStatus(str, Enum):
    READY_SKIPPED = "ready_skipped"
    SUCCESS = "success"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_NEEDS_HUMAN = "failed_needs_human"


class PublishFailureClass(str, Enum):
    NO_PUBLISHABLE_REPORT = "no_publishable_report"
    ZERO_RECOMMENDATIONS = "zero_recommendations"
    NON_TRADING_DAY = "non_trading_day"
    SUPABASE_CAPACITY_STOP = "supabase_capacity_stop"
    CONFIG_MISSING = "config_missing"
    ARTIFACT_INVALID = "artifact_invalid"
    WRANGLER_TEMPORARY_FAILURE = "wrangler_temporary_failure"
    WRANGLER_AUTH_FAILURE = "wrangler_auth_failure"
    SMOKE_FAILED = "smoke_failed"
    ROLLBACK_FAILED = "rollback_failed"
    SECRET_LEAK_BLOCKED = "secret_leak_blocked"

    @property
    def retryable(self) -> bool:
        return self in {
            PublishFailureClass.WRANGLER_TEMPORARY_FAILURE,
            PublishFailureClass.SMOKE_FAILED,
        }


class PublishMode(str, Enum):
    MANUAL_ONCE = "manual_once"
    AUTO = "auto"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class PublishState(BaseModel):
    trade_date: date | None
    status: PublishStatus
    mode: PublishMode
    started_at: datetime = Field(default_factory=_utc_now)
    finished_at: datetime | None = None
    published_url: str | None = None
    report_site_url: str | None = None
    recommendations: int | None = None
    failure_class: PublishFailureClass | None = None
    rollback_performed: bool = False
    auto_publish_enabled: bool = False
    last_known_good_path: str | None = None
    summary_for_user: str
    user_action_required: str | None = None
    error_message_redacted: str | None = None
    checks: tuple[str, ...] = ()

    @field_validator(
        "published_url",
        "report_site_url",
        "last_known_good_path",
        "summary_for_user",
        "user_action_required",
        "error_message_redacted",
    )
    @classmethod
    def _redact_text(cls, value: str | None) -> str | None:
        return redact_secrets(value) if value is not None else None

    def write_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = _redact_payload(self.model_dump(mode="json"))
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


@dataclass(frozen=True)
class PublishConfig:
    project_root: Path
    report_site_url: str
    cloudflare_pages_project_name: str
    report_password_env: str
    report_session_secret_env: str
    cloudflare_token_env: str
    cloudflare_account_id_env: str
    auto_publish_flag_path: Path
    state_path: Path
    status_page_path: Path
    last_known_good_dir: Path

    @classmethod
    def from_app_config(cls, config: AppConfig) -> "PublishConfig":
        root = config.project_root
        return cls(
            project_root=root,
            report_site_url=config.report_site_url or "",
            cloudflare_pages_project_name=config.cloudflare_pages_project_name or "",
            report_password_env=config.report_password_env,
            report_session_secret_env=config.report_session_secret_env,
            cloudflare_token_env=config.cloudflare_token_env,
            cloudflare_account_id_env=config.cloudflare_account_id_env,
            auto_publish_flag_path=root / "logs" / "publish" / "auto-publish-enabled.json",
            state_path=root / "logs" / "publish" / "latest-status.json",
            status_page_path=root / "logs" / "publish" / "status.html",
            last_known_good_dir=root / "local_archive" / "publish" / "last-known-good",
        )


@dataclass(frozen=True)
class PublishCandidate:
    trade_date: date
    recommendations: int
    job_status_path: Path
    reports_dir: Path


@dataclass(frozen=True)
class WranglerResult:
    exit_code: int
    stdout_redacted: str
    stderr_redacted: str
    deployment_url: str | None


def _redact_payload(value: Any) -> Any:
    if isinstance(value, str):
        return redact_secrets(value)
    if isinstance(value, list):
        return [_redact_payload(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_payload(item) for item in value)
    if isinstance(value, dict):
        return {key: _redact_payload(item) for key, item in value.items()}
    return value
```

- [ ] **Step 4: Extend AppConfig with non-secret publish config names**

In `src/stock_analyzer/config.py`, add fields:

```python
    report_site_url: Optional[str] = None
    cloudflare_pages_project_name: Optional[str] = None
    report_password_env: str = "REPORT_PASSWORD"
    report_session_secret_env: str = "REPORT_SESSION_SECRET"
    cloudflare_token_env: str = "CLOUDFLARE_API_TOKEN"
    cloudflare_account_id_env: str = "CLOUDFLARE_ACCOUNT_ID"
```

In `AppConfig.load()`, pass:

```python
            report_site_url=values.get("REPORT_SITE_URL"),
            cloudflare_pages_project_name=values.get("CLOUDFLARE_PAGES_PROJECT_NAME"),
            report_password_env=values.get("REPORT_PASSWORD_ENV", "REPORT_PASSWORD"),
            report_session_secret_env=values.get(
                "REPORT_SESSION_SECRET_ENV",
                "REPORT_SESSION_SECRET",
            ),
            cloudflare_token_env=values.get("CLOUDFLARE_TOKEN_ENV", "CLOUDFLARE_API_TOKEN"),
            cloudflare_account_id_env=values.get(
                "CLOUDFLARE_ACCOUNT_ID_ENV",
                "CLOUDFLARE_ACCOUNT_ID",
            ),
```

Do not add actual secret values to `AppConfig`.

- [ ] **Step 5: Verify tests**

Run: `.venv/bin/python -m pytest tests/test_ops_publish.py tests/test_config_health.py -v`

Expected: PASS for new publish tests and existing config health tests.

- [ ] **Step 6: Commit**

```bash
git add src/stock_analyzer/ops/publish.py src/stock_analyzer/config.py tests/test_ops_publish.py
git commit -m "feat: add publish state contracts"
```

## Task 2: Publish Candidate Selection and Preflight Gates

**Files:**
- Modify: `src/stock_analyzer/ops/publish.py`
- Test: `tests/test_ops_publish.py`

**Interfaces:**
- Consumes: `PublishConfig`, `PublishCandidate`, `PublishFailureClass`, `PublishState`.
- Produces: `load_publish_candidate(config: PublishConfig, trade_date: date | None = None) -> PublishCandidate`.
- Produces: `preflight_publish(config: PublishConfig, candidate: PublishCandidate, *, env: Mapping[str, str], capacity_checker: Callable[[], CapacityStatus] | None = None) -> tuple[str, ...]`.
- Produces: `PublishPreflightError(RuntimeError)` with `.failure_class` and `.user_action_required`.

- [ ] **Step 1: Add failing tests for candidate selection**

Append to `tests/test_ops_publish.py`:

```python
import os
from datetime import date

import pytest

from stock_analyzer.ops.publish import (
    PublishCandidate,
    PublishPreflightError,
    load_publish_candidate,
    preflight_publish,
)
from stock_analyzer.storage.capacity_guard import CapacityStatus


def _write_job_status(root, payload):
    status_path = root / "logs" / "run-daily" / "latest-status.json"
    status_path.parent.mkdir(parents=True)
    status_path.write_text(json.dumps(payload), encoding="utf-8")
    return status_path


def _write_report(root, trade_date):
    reports = root / "reports"
    (reports / "daily" / trade_date.isoformat()).mkdir(parents=True)
    (reports / "index.html").write_text(f"<html>{trade_date.isoformat()}</html>", encoding="utf-8")
    (reports / "daily" / trade_date.isoformat() / "index.html").write_text(
        f"<html>{trade_date.isoformat()}</html>",
        encoding="utf-8",
    )


def _publish_config(root):
    return PublishConfig(
        project_root=root,
        report_site_url="https://stock-analysis-assistant-v3.pages.dev",
        cloudflare_pages_project_name="stock-analysis-assistant-v3",
        report_password_env="REPORT_PASSWORD",
        report_session_secret_env="REPORT_SESSION_SECRET",
        cloudflare_token_env="CLOUDFLARE_API_TOKEN",
        cloudflare_account_id_env="CLOUDFLARE_ACCOUNT_ID",
        auto_publish_flag_path=root / "logs" / "publish" / "auto-publish-enabled.json",
        state_path=root / "logs" / "publish" / "latest-status.json",
        status_page_path=root / "logs" / "publish" / "status.html",
        last_known_good_dir=root / "local_archive" / "publish" / "last-known-good",
    )


def test_load_publish_candidate_uses_today_success_with_recommendations(tmp_path):
    trade_date = date(2026, 7, 9)
    _write_report(tmp_path, trade_date)
    status_path = _write_job_status(
        tmp_path,
        {
            "trade_date": trade_date.isoformat(),
            "status": "success_with_recommendations",
            "recommendations": 3,
        },
    )

    candidate = load_publish_candidate(_publish_config(tmp_path), trade_date=trade_date)

    assert candidate == PublishCandidate(
        trade_date=trade_date,
        recommendations=3,
        job_status_path=status_path,
        reports_dir=tmp_path / "reports",
    )


def test_load_publish_candidate_rejects_zero_recommendations(tmp_path):
    trade_date = date(2026, 7, 9)
    _write_report(tmp_path, trade_date)
    _write_job_status(
        tmp_path,
        {
            "trade_date": trade_date.isoformat(),
            "status": "success_no_recommendations",
            "recommendations": 0,
        },
    )

    with pytest.raises(PublishPreflightError) as exc_info:
        load_publish_candidate(_publish_config(tmp_path), trade_date=trade_date)

    assert exc_info.value.failure_class is PublishFailureClass.ZERO_RECOMMENDATIONS
    assert "当天无推荐" in exc_info.value.user_action_required


def test_load_publish_candidate_rejects_non_trading_day(tmp_path):
    trade_date = date(2026, 7, 11)
    _write_job_status(
        tmp_path,
        {
            "trade_date": trade_date.isoformat(),
            "status": "skipped_non_trading_day",
            "recommendations": None,
        },
    )

    with pytest.raises(PublishPreflightError) as exc_info:
        load_publish_candidate(_publish_config(tmp_path), trade_date=trade_date)

    assert exc_info.value.failure_class is PublishFailureClass.NON_TRADING_DAY


def test_preflight_requires_local_publish_config_without_printing_secret_names(tmp_path):
    trade_date = date(2026, 7, 9)
    candidate = PublishCandidate(trade_date, 3, tmp_path / "status.json", tmp_path / "reports")

    with pytest.raises(PublishPreflightError) as exc_info:
        preflight_publish(_publish_config(tmp_path), candidate, env={})

    assert exc_info.value.failure_class is PublishFailureClass.CONFIG_MISSING
    assert "配置" in exc_info.value.user_action_required


def test_preflight_blocks_supabase_capacity_stop(tmp_path):
    trade_date = date(2026, 7, 9)
    candidate = PublishCandidate(trade_date, 3, tmp_path / "status.json", tmp_path / "reports")
    env = {
        "REPORT_PASSWORD": "pw",
        "REPORT_SESSION_SECRET": "session",
        "CLOUDFLARE_API_TOKEN": "token",
        "CLOUDFLARE_ACCOUNT_ID": "account",
    }

    with pytest.raises(PublishPreflightError) as exc_info:
        preflight_publish(
            _publish_config(tmp_path),
            candidate,
            env=env,
            capacity_checker=lambda: CapacityStatus(size_mb=401.0, warn=True, stop_large_writes=True),
        )

    assert exc_info.value.failure_class is PublishFailureClass.SUPABASE_CAPACITY_STOP
    assert "401.0 MB" in exc_info.value.user_action_required
```

- [ ] **Step 2: Run tests to verify failure**

Run: `.venv/bin/python -m pytest tests/test_ops_publish.py -v`

Expected: FAIL because candidate/preflight functions do not exist.

- [ ] **Step 3: Implement `PublishPreflightError` and candidate loading**

Add to `src/stock_analyzer/ops/publish.py`:

```python
import os
from collections.abc import Callable, Mapping

from stock_analyzer.storage.capacity_guard import CapacityStatus


class PublishPreflightError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        failure_class: PublishFailureClass,
        user_action_required: str,
    ) -> None:
        super().__init__(redact_secrets(message))
        self.failure_class = failure_class
        self.user_action_required = redact_secrets(user_action_required)


def load_publish_candidate(
    config: PublishConfig,
    trade_date: date | None = None,
) -> PublishCandidate:
    status_path = config.project_root / "logs" / "run-daily" / "latest-status.json"
    if not status_path.is_file():
        raise PublishPreflightError(
            "No Phase 1 production status file was found.",
            failure_class=PublishFailureClass.NO_PUBLISHABLE_REPORT,
            user_action_required="今天还没有可发布报告；先等待生产流程成功完成。",
        )
    payload = json.loads(status_path.read_text(encoding="utf-8"))
    status_trade_date = date.fromisoformat(str(payload.get("trade_date")))
    if trade_date is not None and status_trade_date != trade_date:
        raise PublishPreflightError(
            f"Latest production status is for {status_trade_date}, not {trade_date}.",
            failure_class=PublishFailureClass.NO_PUBLISHABLE_REPORT,
            user_action_required="今天还没有可发布报告；如需补发历史日期，请人工指定日期并先确认报告存在。",
        )
    run_status = str(payload.get("status"))
    recommendations = int(payload.get("recommendations") or 0)
    if run_status == "skipped_non_trading_day":
        raise PublishPreflightError(
            "Latest production status is non-trading day.",
            failure_class=PublishFailureClass.NON_TRADING_DAY,
            user_action_required="今天不是交易日，不发布新报告；线上保留上一版。",
        )
    if recommendations == 0:
        raise PublishPreflightError(
            "Latest production status has zero recommendations.",
            failure_class=PublishFailureClass.ZERO_RECOMMENDATIONS,
            user_action_required="当天无推荐，不发布新报告；线上保留上一版。",
        )
    if run_status != "success_with_recommendations":
        raise PublishPreflightError(
            f"Latest production status is {run_status}.",
            failure_class=PublishFailureClass.NO_PUBLISHABLE_REPORT,
            user_action_required="今天生产流程还没有成功完成，暂不发布。",
        )
    reports_dir = config.project_root / "reports"
    daily_index = reports_dir / "daily" / status_trade_date.isoformat() / "index.html"
    if not (reports_dir / "index.html").is_file() or not daily_index.is_file():
        raise PublishPreflightError(
            "Report files are missing.",
            failure_class=PublishFailureClass.NO_PUBLISHABLE_REPORT,
            user_action_required="报告文件缺失；请先重新生成当天报告。",
        )
    return PublishCandidate(
        trade_date=status_trade_date,
        recommendations=recommendations,
        job_status_path=status_path,
        reports_dir=reports_dir,
    )
```

- [ ] **Step 4: Implement preflight**

Add:

```python
def preflight_publish(
    config: PublishConfig,
    candidate: PublishCandidate,
    *,
    env: Mapping[str, str] | None = None,
    capacity_checker: Callable[[], CapacityStatus] | None = None,
) -> tuple[str, ...]:
    values = os.environ if env is None else env
    missing: list[str] = []
    if not config.report_site_url:
        missing.append("REPORT_SITE_URL")
    if not config.cloudflare_pages_project_name:
        missing.append("CLOUDFLARE_PAGES_PROJECT_NAME")
    for env_name in (
        config.report_password_env,
        config.report_session_secret_env,
        config.cloudflare_token_env,
    ):
        if not str(values.get(env_name, "")).strip():
            missing.append(env_name)
    if missing:
        raise PublishPreflightError(
            "Missing publish configuration: " + ", ".join(missing),
            failure_class=PublishFailureClass.CONFIG_MISSING,
            user_action_required="发布配置不完整；请检查本机 .env.local 中的 Cloudflare 和报告密码配置。",
        )
    checks = ["config_present"]
    if capacity_checker is not None:
        capacity = capacity_checker()
        checks.append(f"supabase_capacity={capacity.size_mb:.1f}MB")
        if capacity.stop_large_writes:
            raise PublishPreflightError(
                f"Supabase capacity stop at {capacity.size_mb:.1f} MB.",
                failure_class=PublishFailureClass.SUPABASE_CAPACITY_STOP,
                user_action_required=(
                    f"Supabase 容量已到 {capacity.size_mb:.1f} MB，停止发布；"
                    "请先处理容量问题。"
                ),
            )
    return tuple(checks)
```

- [ ] **Step 5: Verify tests**

Run: `.venv/bin/python -m pytest tests/test_ops_publish.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/stock_analyzer/ops/publish.py tests/test_ops_publish.py
git commit -m "feat: gate publish candidates"
```

## Task 3: Wrangler Deploy Runner and Artifact Safety

**Files:**
- Modify: `src/stock_analyzer/ops/publish.py`
- Test: `tests/test_ops_publish.py`

**Interfaces:**
- Consumes: `PublishConfig`, `WranglerResult`.
- Produces: `run_wrangler_deploy(config: PublishConfig, artifact_dir: Path, *, env: Mapping[str, str] | None = None, runner: Callable[..., subprocess.CompletedProcess[str]] | None = None) -> WranglerResult`.
- Produces: `prepare_publish_artifact(config: PublishConfig, prepare_artifact: Callable[[Path, Path], Path] | None = None) -> Path`.

- [ ] **Step 1: Add failing tests for artifact preparation and Wrangler**

Append:

```python
import subprocess

from stock_analyzer.ops.publish import prepare_publish_artifact, run_wrangler_deploy


def test_prepare_publish_artifact_always_rebuilds_dist_pages(tmp_path):
    config = _publish_config(tmp_path)
    stale = tmp_path / "dist" / "pages" / "stale.txt"
    stale.parent.mkdir(parents=True)
    stale.write_text("stale", encoding="utf-8")

    def fake_prepare(project_root, output_dir):
        assert project_root == tmp_path
        assert output_dir == tmp_path / "dist" / "pages"
        assert not stale.exists()
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "index.html").write_text("fresh", encoding="utf-8")
        return output_dir

    artifact_dir = prepare_publish_artifact(config, prepare_artifact=fake_prepare)

    assert artifact_dir == tmp_path / "dist" / "pages"
    assert (artifact_dir / "index.html").read_text(encoding="utf-8") == "fresh"


def test_run_wrangler_deploy_invokes_official_command_without_printing_token(tmp_path):
    config = _publish_config(tmp_path)
    artifact_dir = tmp_path / "dist" / "pages"
    artifact_dir.mkdir(parents=True)
    calls = []

    def fake_runner(command, *, cwd, env, text, capture_output, check):
        calls.append((command, cwd, env, text, capture_output, check))
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="Success: https://stock-analysis-assistant-v3.pages.dev",
            stderr="",
        )

    result = run_wrangler_deploy(
        config,
        artifact_dir,
        env={"CLOUDFLARE_API_TOKEN": "secret-token"},
        runner=fake_runner,
    )

    command, cwd, env, text, capture_output, check = calls[0]
    assert command == [
        "npx",
        "wrangler",
        "pages",
        "deploy",
        str(artifact_dir),
        "--project-name",
        "stock-analysis-assistant-v3",
    ]
    assert cwd == tmp_path
    assert env["CLOUDFLARE_API_TOKEN"] == "secret-token"
    assert text is True
    assert capture_output is True
    assert check is False
    assert result.exit_code == 0
    assert result.deployment_url == "https://stock-analysis-assistant-v3.pages.dev"
    assert "secret-token" not in result.stdout_redacted


def test_run_wrangler_deploy_classifies_auth_failure(tmp_path):
    config = _publish_config(tmp_path)
    artifact_dir = tmp_path / "dist" / "pages"
    artifact_dir.mkdir(parents=True)

    def fake_runner(command, *, cwd, env, text, capture_output, check):
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="Authentication error")

    result = run_wrangler_deploy(
        config,
        artifact_dir,
        env={"CLOUDFLARE_API_TOKEN": "secret-token"},
        runner=fake_runner,
    )

    assert result.exit_code == 1
    assert "Authentication error" in result.stderr_redacted
```

- [ ] **Step 2: Run tests to verify failure**

Run: `.venv/bin/python -m pytest tests/test_ops_publish.py -v`

Expected: FAIL because functions do not exist.

- [ ] **Step 3: Implement artifact preparation wrapper**

Add:

```python
import shutil
import subprocess
from collections.abc import Mapping

from stock_analyzer.ops.artifacts import prepare_pages_artifact


def prepare_publish_artifact(
    config: PublishConfig,
    *,
    prepare_artifact=None,
) -> Path:
    output_dir = config.project_root / "dist" / "pages"
    if output_dir.exists():
        shutil.rmtree(output_dir)
    prepare_func = prepare_artifact or prepare_pages_artifact
    return prepare_func(config.project_root, output_dir)
```

- [ ] **Step 4: Implement Wrangler runner**

Add:

```python
_URL_PATTERN = re.compile(r"https://[^\s]+")


def run_wrangler_deploy(
    config: PublishConfig,
    artifact_dir: Path,
    *,
    env: Mapping[str, str] | None = None,
    runner=None,
) -> WranglerResult:
    command = [
        "npx",
        "wrangler",
        "pages",
        "deploy",
        str(artifact_dir),
        "--project-name",
        config.cloudflare_pages_project_name,
    ]
    values = dict(os.environ if env is None else env)
    run = runner or subprocess.run
    completed = run(
        command,
        cwd=config.project_root,
        env=values,
        text=True,
        capture_output=True,
        check=False,
    )
    stdout = redact_secrets(completed.stdout or "", explicit_secrets=values.values())
    stderr = redact_secrets(completed.stderr or "", explicit_secrets=values.values())
    deployment_url = _extract_deployment_url(stdout + "\n" + stderr)
    return WranglerResult(
        exit_code=int(completed.returncode),
        stdout_redacted=stdout,
        stderr_redacted=stderr,
        deployment_url=deployment_url,
    )


def _extract_deployment_url(text: str) -> str | None:
    for match in _URL_PATTERN.finditer(text):
        value = match.group(0).rstrip(".,)")
        if ".pages.dev" in value or value.startswith("https://"):
            return value
    return None
```

Also add `import re`.

- [ ] **Step 5: Verify tests**

Run: `.venv/bin/python -m pytest tests/test_ops_publish.py tests/test_ops_artifacts.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/stock_analyzer/ops/publish.py tests/test_ops_publish.py
git commit -m "feat: wrap wrangler report publishing"
```

## Task 4: Publish Orchestrator, Retry, Rollback, and Auto-Enable

**Files:**
- Modify: `src/stock_analyzer/ops/publish.py`
- Test: `tests/test_ops_publish.py`

**Interfaces:**
- Consumes: candidate selection, preflight, artifact preparation, Wrangler runner, `smoke_report_site`.
- Produces: `publish_report_site(config: PublishConfig, *, mode: PublishMode, trade_date: date | None = None, env: Mapping[str, str] | None = None, capacity_checker=None, prepare_artifact=None, deploy_runner=None, smoke_func=None, notify_func=None, notify_enabled: bool = False) -> PublishState`.
- Produces: `is_auto_publish_enabled(config: PublishConfig) -> bool`.
- Produces: `set_auto_publish_enabled(config: PublishConfig, enabled: bool) -> None`.

- [ ] **Step 1: Add failing tests for happy path and auto-enable**

Append:

```python
from stock_analyzer.ops.smoke import SmokeResult
from stock_analyzer.ops.publish import (
    is_auto_publish_enabled,
    publish_report_site,
    set_auto_publish_enabled,
)


def _successful_smoke(url, password, *, expected_trade_date=None):
    return SmokeResult(
        base_url=url,
        passed=True,
        checks=("redirect_to_login", "password_login", "report_date_matches"),
        failures=(),
    )


def test_publish_report_site_success_saves_last_known_good_and_enables_auto(tmp_path):
    trade_date = date(2026, 7, 9)
    _write_report(tmp_path, trade_date)
    _write_job_status(
        tmp_path,
        {
            "trade_date": trade_date.isoformat(),
            "status": "success_with_recommendations",
            "recommendations": 3,
        },
    )
    config = _publish_config(tmp_path)

    def fake_prepare(project_root, output_dir):
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "index.html").write_text("fresh", encoding="utf-8")
        (output_dir / "functions").mkdir()
        (output_dir / "functions" / "_middleware.ts").write_text("export {}", encoding="utf-8")
        return output_dir

    def fake_deploy(config_arg, artifact_dir, *, env=None):
        return WranglerResult(0, "ok https://stock-analysis-assistant-v3.pages.dev", "", "https://stock-analysis-assistant-v3.pages.dev")

    state = publish_report_site(
        config,
        mode=PublishMode.MANUAL_ONCE,
        trade_date=trade_date,
        env={
            "REPORT_PASSWORD": "pw",
            "REPORT_SESSION_SECRET": "session",
            "CLOUDFLARE_API_TOKEN": "token",
        },
        prepare_artifact=fake_prepare,
        deploy_runner=fake_deploy,
        smoke_func=_successful_smoke,
    )

    assert state.status is PublishStatus.SUCCESS
    assert state.auto_publish_enabled is True
    assert is_auto_publish_enabled(config) is True
    assert (config.last_known_good_dir / "index.html").read_text(encoding="utf-8") == "fresh"
    assert config.state_path.exists()
```

- [ ] **Step 2: Add failing tests for smoke failure rollback**

Append:

```python
def test_publish_report_site_rolls_back_last_known_good_when_smoke_fails(tmp_path):
    trade_date = date(2026, 7, 9)
    _write_report(tmp_path, trade_date)
    _write_job_status(
        tmp_path,
        {
            "trade_date": trade_date.isoformat(),
            "status": "success_with_recommendations",
            "recommendations": 3,
        },
    )
    config = _publish_config(tmp_path)
    config.last_known_good_dir.mkdir(parents=True)
    (config.last_known_good_dir / "index.html").write_text("last good", encoding="utf-8")
    deploy_calls = []
    smoke_calls = []

    def fake_prepare(project_root, output_dir):
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "index.html").write_text("new", encoding="utf-8")
        return output_dir

    def fake_deploy(config_arg, artifact_dir, *, env=None):
        deploy_calls.append(artifact_dir)
        return WranglerResult(0, "ok", "", config.report_site_url)

    def fake_smoke(url, password, *, expected_trade_date=None):
        smoke_calls.append(expected_trade_date)
        if len(smoke_calls) == 1:
            return SmokeResult(url, False, ("redirect_to_login",), ())
        return SmokeResult(url, True, ("redirect_to_login",), ())

    state = publish_report_site(
        config,
        mode=PublishMode.AUTO,
        trade_date=trade_date,
        env={
            "REPORT_PASSWORD": "pw",
            "REPORT_SESSION_SECRET": "session",
            "CLOUDFLARE_API_TOKEN": "token",
        },
        prepare_artifact=fake_prepare,
        deploy_runner=fake_deploy,
        smoke_func=fake_smoke,
    )

    assert state.status is PublishStatus.FAILED_NEEDS_HUMAN
    assert state.failure_class is PublishFailureClass.SMOKE_FAILED
    assert state.rollback_performed is True
    assert deploy_calls[-1] == config.last_known_good_dir
    assert "已回退" in state.summary_for_user
```

- [ ] **Step 3: Add failing test for retry once on temporary Wrangler failure**

Append:

```python
def test_publish_report_site_retries_wrangler_once_for_temporary_failure(tmp_path):
    trade_date = date(2026, 7, 9)
    _write_report(tmp_path, trade_date)
    _write_job_status(
        tmp_path,
        {
            "trade_date": trade_date.isoformat(),
            "status": "success_with_recommendations",
            "recommendations": 3,
        },
    )
    config = _publish_config(tmp_path)
    calls = []

    def fake_prepare(project_root, output_dir):
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "index.html").write_text("fresh", encoding="utf-8")
        return output_dir

    def flaky_deploy(config_arg, artifact_dir, *, env=None):
        calls.append(artifact_dir)
        if len(calls) == 1:
            return WranglerResult(1, "", "Network timeout", None)
        return WranglerResult(0, "ok", "", config.report_site_url)

    state = publish_report_site(
        config,
        mode=PublishMode.AUTO,
        trade_date=trade_date,
        env={
            "REPORT_PASSWORD": "pw",
            "REPORT_SESSION_SECRET": "session",
            "CLOUDFLARE_API_TOKEN": "token",
        },
        prepare_artifact=fake_prepare,
        deploy_runner=flaky_deploy,
        smoke_func=_successful_smoke,
    )

    assert len(calls) == 2
    assert state.status is PublishStatus.SUCCESS
```

- [ ] **Step 4: Run tests to verify failure**

Run: `.venv/bin/python -m pytest tests/test_ops_publish.py -v`

Expected: FAIL because orchestrator functions do not exist.

- [ ] **Step 5: Implement auto-publish flag helpers**

Add:

```python
def is_auto_publish_enabled(config: PublishConfig) -> bool:
    if not config.auto_publish_flag_path.is_file():
        return False
    try:
        payload = json.loads(config.auto_publish_flag_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    return bool(payload.get("enabled"))


def set_auto_publish_enabled(config: PublishConfig, enabled: bool) -> None:
    config.auto_publish_flag_path.parent.mkdir(parents=True, exist_ok=True)
    config.auto_publish_flag_path.write_text(
        json.dumps({"enabled": enabled}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
```

- [ ] **Step 6: Implement last-known-good save/restore helpers**

Add:

```python
def _replace_tree(source: Path, target: Path) -> None:
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target)


def _save_last_known_good(artifact_dir: Path, target_dir: Path) -> None:
    target_dir.parent.mkdir(parents=True, exist_ok=True)
    _replace_tree(artifact_dir, target_dir)
```

- [ ] **Step 7: Implement orchestrator**

Add:

```python
def publish_report_site(
    config: PublishConfig,
    *,
    mode: PublishMode,
    trade_date: date | None = None,
    env: Mapping[str, str] | None = None,
    capacity_checker=None,
    prepare_artifact=None,
    deploy_runner=None,
    smoke_func=None,
    notify_func=None,
    notify_enabled: bool = False,
) -> PublishState:
    started_at = _utc_now()
    checks: list[str] = []
    values = os.environ if env is None else env
    try:
        candidate = load_publish_candidate(config, trade_date=trade_date)
        checks.extend(preflight_publish(config, candidate, env=values, capacity_checker=capacity_checker))
        artifact_dir = prepare_publish_artifact(config, prepare_artifact=prepare_artifact)
        checks.append("artifact_prepared")
        deploy = _deploy_with_one_retry(config, artifact_dir, env=values, deploy_runner=deploy_runner)
        checks.append("wrangler_deployed")
        if deploy.exit_code != 0:
            return _write_publish_failure(
                config,
                mode,
                started_at,
                candidate,
                PublishFailureClass.WRANGLER_AUTH_FAILURE,
                "发布失败：Cloudflare 上传没有成功。",
                "请检查 Cloudflare 凭据和项目名。",
                checks,
                rollback_performed=False,
                error_message=deploy.stderr_redacted or deploy.stdout_redacted,
                notify_func=notify_func,
                notify_enabled=notify_enabled,
            )
        smoke = (smoke_func or smoke_report_site)(
            config.report_site_url,
            values.get(config.report_password_env),
            expected_trade_date=candidate.trade_date,
        )
        checks.extend(smoke.checks)
        if not smoke.passed:
            rollback_ok = _rollback_last_known_good(config, values, deploy_runner, smoke_func, candidate.trade_date)
            summary = "发布后线上检查失败，系统已回退上一版正常报告。" if rollback_ok else "发布后线上检查失败，且自动回退失败。"
            return _write_publish_failure(
                config,
                mode,
                started_at,
                candidate,
                PublishFailureClass.SMOKE_FAILED if rollback_ok else PublishFailureClass.ROLLBACK_FAILED,
                summary,
                "请查看本地发布状态页，并检查 Cloudflare 密码配置或报告日期。",
                checks,
                rollback_performed=rollback_ok,
                error_message=smoke.fix_suggestion,
                notify_func=notify_func,
                notify_enabled=notify_enabled,
            )
        _save_last_known_good(artifact_dir, config.last_known_good_dir)
        set_auto_publish_enabled(config, True)
        state = PublishState(
            trade_date=candidate.trade_date,
            status=PublishStatus.SUCCESS,
            mode=mode,
            started_at=started_at,
            finished_at=_utc_now(),
            published_url=deploy.deployment_url or config.report_site_url,
            report_site_url=config.report_site_url,
            recommendations=candidate.recommendations,
            failure_class=None,
            rollback_performed=False,
            auto_publish_enabled=True,
            last_known_good_path=str(config.last_known_good_dir),
            summary_for_user=f"发布成功：线上报告 {candidate.trade_date.isoformat()}，链接：{config.report_site_url}",
            user_action_required=None,
            error_message_redacted=None,
            checks=tuple(checks),
        )
        state.write_json(config.state_path)
        return state
    except PublishPreflightError as exc:
        state = PublishState(
            trade_date=trade_date,
            status=PublishStatus.READY_SKIPPED,
            mode=mode,
            started_at=started_at,
            finished_at=_utc_now(),
            published_url=None,
            report_site_url=config.report_site_url,
            recommendations=None,
            failure_class=exc.failure_class,
            rollback_performed=False,
            auto_publish_enabled=is_auto_publish_enabled(config),
            last_known_good_path=str(config.last_known_good_dir) if config.last_known_good_dir.exists() else None,
            summary_for_user=str(exc),
            user_action_required=exc.user_action_required,
            error_message_redacted=str(exc),
            checks=tuple(checks),
        )
        state.write_json(config.state_path)
        return state
```

Also implement helper functions referenced above:

```python
from stock_analyzer.ops.notify import notify_mac
from stock_analyzer.ops.smoke import smoke_report_site


def _deploy_with_one_retry(config, artifact_dir, *, env, deploy_runner):
    deploy_func = deploy_runner or run_wrangler_deploy
    first = deploy_func(config, artifact_dir, env=env)
    if first.exit_code == 0:
        return first
    combined = f"{first.stdout_redacted}\n{first.stderr_redacted}".lower()
    if any(marker in combined for marker in ("timeout", "temporar", "network", "5xx", "econnreset")):
        return deploy_func(config, artifact_dir, env=env)
    return first


def _rollback_last_known_good(config, env, deploy_runner, smoke_func, trade_date):
    if not config.last_known_good_dir.is_dir():
        return False
    deploy_func = deploy_runner or run_wrangler_deploy
    deploy = deploy_func(config, config.last_known_good_dir, env=env)
    if deploy.exit_code != 0:
        return False
    smoke = (smoke_func or smoke_report_site)(
        config.report_site_url,
        env.get(config.report_password_env),
        expected_trade_date=None,
    )
    return smoke.passed


def _write_publish_failure(
    config,
    mode,
    started_at,
    candidate,
    failure_class,
    summary,
    user_action_required,
    checks,
    *,
    rollback_performed,
    error_message,
    notify_func,
    notify_enabled,
):
    state = PublishState(
        trade_date=candidate.trade_date,
        status=PublishStatus.FAILED_NEEDS_HUMAN,
        mode=mode,
        started_at=started_at,
        finished_at=_utc_now(),
        published_url=None,
        report_site_url=config.report_site_url,
        recommendations=candidate.recommendations,
        failure_class=failure_class,
        rollback_performed=rollback_performed,
        auto_publish_enabled=is_auto_publish_enabled(config),
        last_known_good_path=str(config.last_known_good_dir) if config.last_known_good_dir.exists() else None,
        summary_for_user=summary,
        user_action_required=user_action_required,
        error_message_redacted=error_message,
        checks=tuple(checks),
    )
    state.write_json(config.state_path)
    if notify_enabled:
        (notify_func or notify_mac)("股票分析助手发布需要处理", state.summary_for_user, enabled=True)
    return state
```

- [ ] **Step 8: Verify publish tests**

Run: `.venv/bin/python -m pytest tests/test_ops_publish.py -v`

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add src/stock_analyzer/ops/publish.py tests/test_ops_publish.py
git commit -m "feat: orchestrate cloudflare publishing"
```

## Task 5: CLI Entry and Auto-Publish Integration

**Files:**
- Modify: `src/stock_analyzer/cli.py`
- Modify: `src/stock_analyzer/ops/job.py`
- Modify: `pyproject.toml`
- Test: `tests/test_ops_publish.py`
- Test: `tests/test_ops_job.py`

**Interfaces:**
- Consumes: `publish_report_site`, `PublishConfig.from_app_config`, `is_auto_publish_enabled`.
- Produces CLI: `stock_analyzer ops publish-report-site [--trade-date YYYY-MM-DD] [--notify-mac]`.
- Produces fixed user command: `stock-analyzer-publish`.
- Produces `run_daily_job(..., auto_publish: bool = False, publish_func: Callable[..., PublishState] | None = None) -> JobStatus`.

- [ ] **Step 1: Add failing CLI test**

Append to `tests/test_ops_publish.py`:

```python
from typer.testing import CliRunner
from pathlib import Path

from stock_analyzer.cli import app


def test_ops_publish_report_site_cli_outputs_simple_success(monkeypatch, tmp_path):
    trade_date = date(2026, 7, 9)
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("REPORT_SITE_URL", "https://stock-analysis-assistant-v3.pages.dev")
    monkeypatch.setenv("CLOUDFLARE_PAGES_PROJECT_NAME", "stock-analysis-assistant-v3")

    def fake_publish(config, *, mode, trade_date=None, notify_enabled=False, **kwargs):
        return PublishState(
            trade_date=date(2026, 7, 9),
            status=PublishStatus.SUCCESS,
            mode=mode,
            published_url=config.report_site_url,
            report_site_url=config.report_site_url,
            recommendations=3,
            failure_class=None,
            rollback_performed=False,
            auto_publish_enabled=True,
            last_known_good_path=str(config.last_known_good_dir),
            summary_for_user="发布成功：线上报告 2026-07-09，链接：https://stock-analysis-assistant-v3.pages.dev",
            user_action_required=None,
            error_message_redacted=None,
            checks=("ok",),
        )

    monkeypatch.setattr("stock_analyzer.cli.publish_report_site", fake_publish)

    result = CliRunner().invoke(app, ["ops", "publish-report-site"])

    assert result.exit_code == 0
    assert "发布成功：线上报告 2026-07-09" in result.output
    assert "checks" not in result.output


def test_pyproject_registers_stock_analyzer_publish_command():
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")

    assert "stock-analyzer-publish" in pyproject
    assert "stock_analyzer.cli:stock_analyzer_publish" in pyproject
```

- [ ] **Step 2: Add failing job auto-publish integration test**

Append to `tests/test_ops_job.py`:

```python
def test_run_daily_job_triggers_auto_publish_after_success(tmp_path):
    trade_date = date(2026, 7, 9)
    publish_calls = []

    def fake_publish(project_root, trade_date_arg):
        publish_calls.append((project_root, trade_date_arg))

    status = run_daily_job(
        tmp_path,
        trade_date,
        "18:30",
        1,
        prepare_deploy=False,
        repository=FakeJobRepository(),
        calendar_decider=lambda *_args, **_kwargs: TradingDayDecision(
            status="trading_day",
            source="supabase",
            message="market open",
        ),
        health_check=lambda *_args: None,
        run_daily=lambda *_args: None,
        verifier=lambda *_args: _successful_verification_with_recommendations(trade_date),
        auto_publish=True,
        publish_func=fake_publish,
    )

    assert status.status == RunStatus.SUCCESS_WITH_RECOMMENDATIONS
    assert publish_calls == [(tmp_path, trade_date)]


def test_run_daily_job_does_not_auto_publish_zero_recommendations(tmp_path):
    trade_date = date(2026, 7, 9)
    publish_calls = []

    status = run_daily_job(
        tmp_path,
        trade_date,
        "18:30",
        1,
        prepare_deploy=False,
        repository=FakeJobRepository(),
        calendar_decider=lambda *_args, **_kwargs: TradingDayDecision(
            status="trading_day",
            source="supabase",
            message="market open",
        ),
        health_check=lambda *_args: None,
        run_daily=lambda *_args: None,
        verifier=lambda *_args: _successful_verification(trade_date),
        auto_publish=True,
        publish_func=lambda project_root, trade_date_arg: publish_calls.append(
            (project_root, trade_date_arg)
        ),
    )

    assert status.status == RunStatus.SUCCESS_NO_RECOMMENDATIONS
    assert publish_calls == []
```

Add helper near existing helpers:

```python
def _successful_verification_with_recommendations(trade_date: date) -> ProductionVerification:
    return ProductionVerification(
        trade_date=trade_date,
        status=RunStatus.SUCCESS_WITH_RECOMMENDATIONS,
        passed=True,
        recommendations=1,
        evidence_packages=1,
        evaluation_tasks=6,
        market_price_daily_current_day_rows=1,
        daily_basic_indicator_current_day_rows=1,
        report_index_exists=True,
        daily_report_index_exists=True,
        report_json_exists=True,
        failures=(),
    )
```

- [ ] **Step 3: Run tests to verify failure**

Run: `.venv/bin/python -m pytest tests/test_ops_publish.py tests/test_ops_job.py -v`

Expected: FAIL because CLI command and job kwargs do not exist.

- [ ] **Step 4: Add CLI command**

In `src/stock_analyzer/cli.py`, import:

```python
from stock_analyzer.ops.publish import (
    PublishConfig,
    PublishMode,
    PublishStatus,
    publish_report_site,
)
```

Add:

```python
@ops_app.command("publish-report-site")
def ops_publish_report_site(
    trade_date: Optional[str] = typer.Option(None, "--trade-date"),
    notify_mac: bool = typer.Option(False, "--notify-mac"),
) -> None:
    config = AppConfig.load()
    publish_config = PublishConfig.from_app_config(config)
    parsed_trade_date = date.fromisoformat(trade_date) if trade_date else None
    state = publish_report_site(
        publish_config,
        mode=PublishMode.MANUAL_ONCE,
        trade_date=parsed_trade_date,
        notify_enabled=notify_mac or config.notify_mac,
    )
    typer.echo(state.summary_for_user)
    if state.user_action_required:
        typer.echo(f"需要你处理：{state.user_action_required}", err=True)
    if state.status != PublishStatus.SUCCESS:
        raise typer.Exit(code=2)


def stock_analyzer_publish() -> None:
    app(args=["ops", "publish-report-site"], prog_name="stock-analyzer-publish")
```

- [ ] **Step 5: Register fixed user command**

In `pyproject.toml`, add:

```toml
[project.scripts]
stock-analyzer-publish = "stock_analyzer.cli:stock_analyzer_publish"
```

- [ ] **Step 6: Extend `run_daily_job` signature and behavior**

In `src/stock_analyzer/ops/job.py`, add parameters:

```python
    auto_publish: bool = False,
    publish_func: Callable[[Path, date], Any] | None = None,
```

After successful verification and deploy artifact preparation, before returning final success status, call:

```python
        if auto_publish and verification.status == RunStatus.SUCCESS_WITH_RECOMMENDATIONS:
            effective_publish = publish_func or _default_publish
            effective_publish(root, trade_date)
```

Add helper:

```python
def _default_publish(project_root: Path, trade_date: date) -> Any:
    config = AppConfig.load()
    from stock_analyzer.ops.publish import (
        PublishConfig,
        PublishMode,
        is_auto_publish_enabled,
        publish_report_site,
    )

    publish_config = PublishConfig.from_app_config(config)
    if not is_auto_publish_enabled(publish_config):
        return None
    return publish_report_site(
        publish_config,
        mode=PublishMode.AUTO,
        trade_date=trade_date,
        notify_enabled=config.notify_mac,
    )
```

In CLI `ops_run_daily_job`, pass:

```python
        auto_publish=True,
```

The `run_daily_job` helper must internally skip auto publish unless `is_auto_publish_enabled` is true, so enabling the kwarg in the CLI is safe before the first manual publish.

- [ ] **Step 7: Verify tests**

Run: `.venv/bin/python -m pytest tests/test_ops_publish.py tests/test_ops_job.py tests/test_cli.py -v`

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/stock_analyzer/cli.py src/stock_analyzer/ops/job.py pyproject.toml tests/test_ops_publish.py tests/test_ops_job.py
git commit -m "feat: add report publish command"
```

## Task 6: Local Status Page and Human Notification

**Files:**
- Modify: `src/stock_analyzer/ops/publish.py`
- Test: `tests/test_ops_publish.py`

**Interfaces:**
- Consumes: `PublishState`.
- Produces: `render_publish_status_page(state: PublishState, output_path: Path) -> Path`.
- Updates: `publish_report_site` writes status page after every terminal state.

- [ ] **Step 1: Add failing tests for status page**

Append:

```python
def test_render_publish_status_page_shows_only_user_summary(tmp_path):
    state = PublishState(
        trade_date=date(2026, 7, 9),
        status=PublishStatus.FAILED_NEEDS_HUMAN,
        mode=PublishMode.AUTO,
        published_url=None,
        report_site_url="https://stock-analysis-assistant-v3.pages.dev",
        recommendations=3,
        failure_class=PublishFailureClass.WRANGLER_AUTH_FAILURE,
        rollback_performed=True,
        auto_publish_enabled=True,
        last_known_good_path="/private/path/last-good",
        summary_for_user="发布失败，系统已回退上一版。",
        user_action_required="请检查 Cloudflare 凭据。",
        error_message_redacted="technical stderr should stay machine-only",
        checks=("wrangler_deployed", "smoke_failed"),
    )

    output = render_publish_status_page(state, tmp_path / "logs" / "publish" / "status.html")
    html = output.read_text(encoding="utf-8")

    assert "发布失败，系统已回退上一版。" in html
    assert "请检查 Cloudflare 凭据。" in html
    assert "https://stock-analysis-assistant-v3.pages.dev" in html
    assert "technical stderr" not in html
    assert "wrangler_deployed" not in html
    assert "/private/path" not in html
```

- [ ] **Step 2: Run test to verify failure**

Run: `.venv/bin/python -m pytest tests/test_ops_publish.py::test_render_publish_status_page_shows_only_user_summary -v`

Expected: FAIL because renderer does not exist.

- [ ] **Step 3: Implement status page renderer**

Add:

```python
from html import escape


def render_publish_status_page(state: PublishState, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    trade_date_text = state.trade_date.isoformat() if state.trade_date else "暂无"
    problem_text = state.user_action_required or "无"
    status_text = "成功" if state.status == PublishStatus.SUCCESS else "需要处理"
    link_html = (
        f'<a href="{escape(state.report_site_url)}">{escape(state.report_site_url)}</a>'
        if state.report_site_url
        else "未配置"
    )
    html = f"""<!doctype html>
<html lang="zh-CN">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>股票分析助手发布状态</title>
<body>
<h1>发布状态</h1>
<p>当前线上报告日期：{escape(trade_date_text)}</p>
<p>最近一次发布：{escape(status_text)}</p>
<p>线上报告链接：{link_html}</p>
<p>待处理问题：{escape(problem_text)}</p>
<p>{escape(state.summary_for_user)}</p>
</body>
</html>
"""
    output_path.write_text(html, encoding="utf-8")
    return output_path
```

- [ ] **Step 4: Write status page from orchestrator**

After every `state.write_json(config.state_path)` in `publish_report_site` and `_write_publish_failure`, add:

```python
        render_publish_status_page(state, config.status_page_path)
```

For preflight skip state, also render status page.

- [ ] **Step 5: Verify tests**

Run: `.venv/bin/python -m pytest tests/test_ops_publish.py tests/test_ops_notify.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/stock_analyzer/ops/publish.py tests/test_ops_publish.py
git commit -m "feat: render publish status page"
```

## Task 7: Docs, Config Health, and Final Verification

**Files:**
- Modify: `docs/operations/cloudflare-pages.md`
- Modify: `docs/operations/mandatory-next-phases.md`
- Modify: `README.md`
- Modify: `tests/test_config_health.py`
- Modify only if verification reveals defects: `src/stock_analyzer/**`, `tests/**`

**Interfaces:**
- Consumes: all previous tasks.
- Produces: updated operator docs and final verified branch.

- [ ] **Step 1: Add failing docs tests**

Extend `tests/test_config_health.py` to assert:

```python
def test_phase2_cloudflare_automation_docs_are_present():
    cloudflare_pages = read_project_file("docs/operations/cloudflare-pages.md")
    mandatory_next_phases = read_project_file("docs/operations/mandatory-next-phases.md")
    readme = read_project_file("README.md")

    assert "stock-analyzer-publish" in cloudflare_pages
    assert "第一次发布成功" in cloudflare_pages
    assert "自动转为全自动" in cloudflare_pages
    assert "last known good" in cloudflare_pages.lower()
    assert "不要打印、复制、提交或记录" in cloudflare_pages
    assert "Phase 3 Strategy V2" in mandatory_next_phases
    assert "Phase 4 Product UI" in mandatory_next_phases
    assert "Phase 2 Cloudflare automation" in readme
```

- [ ] **Step 2: Run docs test to verify failure**

Run: `.venv/bin/python -m pytest tests/test_config_health.py -v`

Expected: FAIL until docs are updated.

- [ ] **Step 3: Update Cloudflare operations doc**

In `docs/operations/cloudflare-pages.md`, add a Phase 2 section with these exact operational rules:

```markdown
## Phase 2 One-Command Publish

Phase 2 adds a local one-command publish flow. The first real Cloudflare deployment still requires explicit approval. After the first one-command publish succeeds and online smoke passes, the system automatically enables full auto publish for later successful daily production runs.

Use the simple entrypoint:

```bash
stock-analyzer-publish
```

The command publishes the current trading day's successful report when recommendations are greater than zero. It does not publish non-trading days, failed production runs, or zero-recommendation reports.

The command must:

- rebuild `dist/pages` before upload;
- deploy with Wrangler;
- run online smoke;
- save the successful artifact as last known good;
- roll back to last known good if the newly deployed site fails smoke;
- write local publish status and a simple local status page;
- avoid printing or logging credentials.

Do not print, copy, commit, or log Cloudflare token, report password, report session secret, Supabase service-role key, Tushare token, or `.env.local` contents.
```

Also keep the manual `wrangler pages deploy` section as lower-level fallback, not the preferred Phase 2 path.

- [ ] **Step 4: Update mandatory phases and README**

In `docs/operations/mandatory-next-phases.md`, clarify that Phase 2 implementation is in progress and Phase 3/4 remain mandatory.

In `README.md`, add an operations link:

```markdown
- Phase 2 Cloudflare automation: see `docs/operations/cloudflare-pages.md` and `docs/superpowers/specs/2026-07-09-v3-phase-2-cloudflare-automation-design.md`.
```

- [ ] **Step 5: Run focused tests**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_ops_publish.py \
  tests/test_ops_job.py \
  tests/test_ops_artifacts.py \
  tests/test_ops_smoke.py \
  tests/test_ops_notify.py \
  tests/test_config_health.py \
  -v
```

Expected: PASS.

- [ ] **Step 6: Run full tests**

Run: `.venv/bin/python -m pytest -q`

Expected: PASS.

- [ ] **Step 7: Run secret-oriented scans**

Run:

```bash
rg -n "SUPABASE_SERVICE_ROLE_KEY|TUSHARE_TOKEN|CLOUDFLARE_API_TOKEN|REPORT_PASSWORD|REPORT_SESSION_SECRET" reports dist logs docs src tests
```

Expected: Only variable names in docs/tests/source, no secret values. If generated `reports`, `dist`, or `logs` contain these names, inspect and fix before review.

- [ ] **Step 8: Commit**

```bash
git add README.md docs/operations tests/test_config_health.py
git commit -m "docs: document cloudflare publish automation"
```

## Final Review Gate

- [ ] **Step 1: Request GPT-5.5 xhigh implementation review**

Ask reviewer to inspect:

- publish candidate selection;
- secret redaction;
- Wrangler command and env handling;
- retry and rollback behavior;
- auto-enable behavior after first success;
- run-daily auto-publish integration;
- docs and user-facing wording.

- [ ] **Step 2: Fix actionable review findings**

Use `superpowers:receiving-code-review` before making any review-driven changes.

- [ ] **Step 3: Re-run full verification**

Run: `.venv/bin/python -m pytest -q`

Expected: PASS.

- [ ] **Step 4: Handoff**

Summarize:

- tests passed;
- real Cloudflare deployment not executed;
- first real one-command publish still requires explicit user approval;
- which env variable names must exist locally, without printing values.

## Plan Self-Review

- Spec coverage: Tasks 1-6 cover local one-command publish, auto-enable, auto publish integration, preflight, capacity, Wrangler, smoke, retry, rollback, local state, status page, notification, and secret redaction. Task 7 covers docs and final verification. GitHub Actions and Cloudflare API are recorded as future directions only.
- Placeholder scan: No open-work markers or vague error-handling instructions remain.
- Type consistency: `PublishConfig`, `PublishState`, `PublishCandidate`, `WranglerResult`, `PublishMode`, `PublishStatus`, and `PublishFailureClass` are defined once in Task 1 and consumed consistently by later tasks.
