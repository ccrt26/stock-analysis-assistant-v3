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
