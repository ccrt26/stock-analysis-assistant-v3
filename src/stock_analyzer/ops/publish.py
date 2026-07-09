from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator

from stock_analyzer.config import AppConfig
from stock_analyzer.ops.redaction import redact_secrets
from stock_analyzer.storage.capacity_guard import CapacityStatus


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


_MAX_PUBLISH_RECOMMENDATIONS = 10


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
    recommendation_value = payload.get("recommendations")
    if run_status == "skipped_non_trading_day":
        raise PublishPreflightError(
            "Latest production status is non-trading day.",
            failure_class=PublishFailureClass.NON_TRADING_DAY,
            user_action_required="今天不是交易日，不发布新报告；线上保留上一版。",
        )

    recommendations = _parse_recommendation_count(recommendation_value)
    if run_status == "success_no_recommendations":
        if recommendations == 0:
            raise PublishPreflightError(
                "Latest production status has zero recommendations.",
                failure_class=PublishFailureClass.ZERO_RECOMMENDATIONS,
                user_action_required="当天无推荐，不发布新报告；线上保留上一版。",
            )
        raise PublishPreflightError(
            "Latest production status has an invalid zero-recommendation payload.",
            failure_class=PublishFailureClass.NO_PUBLISHABLE_REPORT,
            user_action_required="生产状态和推荐数不一致；请人工检查，先不要发布。",
        )
    if run_status != "success_with_recommendations":
        raise PublishPreflightError(
            f"Latest production status is {run_status}.",
            failure_class=PublishFailureClass.NO_PUBLISHABLE_REPORT,
            user_action_required="今天生产流程还没有成功完成，暂不发布。",
        )
    if recommendations == 0:
        raise PublishPreflightError(
            "Latest production status has zero recommendations.",
            failure_class=PublishFailureClass.ZERO_RECOMMENDATIONS,
            user_action_required="当天无推荐，不发布新报告；线上保留上一版。",
        )
    if recommendations is None or not 1 <= recommendations <= _MAX_PUBLISH_RECOMMENDATIONS:
        raise PublishPreflightError(
            f"Latest production recommendation count is {recommendation_value!r}.",
            failure_class=PublishFailureClass.NO_PUBLISHABLE_REPORT,
            user_action_required="推荐数异常，超出 1 到 10 的发布范围；请人工检查，先不要发布。",
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


def preflight_publish(
    config: PublishConfig,
    candidate: PublishCandidate,
    *,
    env: Mapping[str, str] | None = None,
    capacity_checker: Callable[[], CapacityStatus] | None = None,
) -> tuple[str, ...]:
    values = os.environ if env is None else env
    missing_count = 0
    if not config.report_site_url:
        missing_count += 1
    if not config.cloudflare_pages_project_name:
        missing_count += 1
    for env_name in (
        config.report_password_env,
        config.report_session_secret_env,
        config.cloudflare_token_env,
    ):
        if not str(values.get(env_name, "")).strip():
            missing_count += 1
    if missing_count:
        raise PublishPreflightError(
            f"Missing publish configuration ({missing_count} item(s)).",
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


def _parse_recommendation_count(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
