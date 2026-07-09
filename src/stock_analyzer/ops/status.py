from __future__ import annotations

import json
from datetime import date, datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from stock_analyzer.ops.redaction import redact_secrets


class RunStatus(str, Enum):
    SUCCESS_WITH_RECOMMENDATIONS = "success_with_recommendations"
    SUCCESS_NO_RECOMMENDATIONS = "success_no_recommendations"
    SKIPPED_NON_TRADING_DAY = "skipped_non_trading_day"
    CALENDAR_UNKNOWN = "calendar_unknown"
    WARNING = "warning"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_NEEDS_HUMAN = "failed_needs_human"


class FailureClass(str, Enum):
    TUSHARE_DATA_TEMPORARILY_UNAVAILABLE = "tushare_data_temporarily_unavailable"
    NETWORK_TIMEOUT = "network_timeout"
    DNS_FAILURE = "dns_failure"
    TEMPORARY_CONNECTION_FAILURE = "temporary_connection_failure"
    SUPABASE_REQUEST_TIMEOUT = "supabase_request_timeout"
    SUPABASE_SERVER_ERROR = "supabase_server_error"
    REPORT_GENERATION_IO_ERROR = "report_generation_io_error"
    DEPLOY_ARTIFACT_NOT_READY = "deploy_artifact_not_ready"
    ENV_FILE_MISSING = "env_file_missing"
    SUPABASE_CREDENTIAL_MISSING_OR_INVALID = "supabase_credential_missing_or_invalid"
    TUSHARE_CREDENTIAL_MISSING_OR_INVALID = "tushare_credential_missing_or_invalid"
    SUPABASE_CAPACITY_STOP = "supabase_capacity_stop"
    CLEANUP_FAILED = "cleanup_failed"
    IMPORT_ERROR = "import_error"
    SCHEMA_MISMATCH = "schema_mismatch"
    MIGRATION_DRIFT = "migration_drift"
    POSSIBLE_FULL_MARKET_WRITE = "possible_full_market_write"
    FIXTURE_SAMPLE_IN_PRODUCTION = "fixture_sample_in_production"
    REPORT_ARTIFACT_INVALID = "report_artifact_invalid"
    RETRY_PREFLIGHT_BLOCKED = "retry_preflight_blocked"
    MAX_ATTEMPTS_EXCEEDED = "max_attempts_exceeded"
    CALENDAR_UNKNOWN = "calendar_unknown"

    @property
    def retryable(self) -> bool:
        return self in {
            FailureClass.TUSHARE_DATA_TEMPORARILY_UNAVAILABLE,
            FailureClass.NETWORK_TIMEOUT,
            FailureClass.DNS_FAILURE,
            FailureClass.TEMPORARY_CONNECTION_FAILURE,
            FailureClass.SUPABASE_REQUEST_TIMEOUT,
            FailureClass.SUPABASE_SERVER_ERROR,
            FailureClass.REPORT_GENERATION_IO_ERROR,
            FailureClass.DEPLOY_ARTIFACT_NOT_READY,
        }

    @property
    def needs_human(self) -> bool:
        return not self.retryable


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class JobStatus(BaseModel):
    trade_date: date
    attempt: int = Field(ge=1)
    scheduled_slot: str
    started_at: datetime = Field(default_factory=_utc_now)
    finished_at: datetime | None = None
    status: RunStatus
    stage: str
    failure_class: FailureClass | None = None
    retryable: bool = False
    cleanup_performed: bool = False
    cleanup_summary: dict[str, Any] = Field(default_factory=dict)
    recommendations: int | None = None
    evidence_packages: int | None = None
    evaluation_tasks: int | None = None
    market_price_daily_current_day_rows: int | None = None
    daily_basic_indicator_current_day_rows: int | None = None
    supabase_database_size_mb: float | None = None
    report_index_exists: bool | None = None
    archive_manifest_exists: bool | None = None
    warehouse_updated: bool | None = None
    deploy_artifact_prepared: bool = False
    publish_skipped_reason: str | None = None
    fix_suggestion: str | None = None
    error_message_redacted: str | None = None

    @field_validator(
        "scheduled_slot",
        "stage",
        "publish_skipped_reason",
        "fix_suggestion",
        "error_message_redacted",
    )
    @classmethod
    def _redact_text_field(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return redact_secrets(value)

    @model_validator(mode="after")
    def _derive_retryable(self) -> "JobStatus":
        if self.status == RunStatus.FAILED_RETRYABLE:
            self.retryable = True
        elif self.status in {
            RunStatus.CALENDAR_UNKNOWN,
            RunStatus.FAILED_NEEDS_HUMAN,
        }:
            self.retryable = False
        elif self.failure_class is not None:
            self.retryable = self.failure_class.retryable
        return self

    def write_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = _redact_payload(self.model_dump(mode="json"))
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


def _redact_payload(value: Any) -> Any:
    if isinstance(value, str):
        return redact_secrets(value)
    if isinstance(value, list):
        return [_redact_payload(item) for item in value]
    if isinstance(value, dict):
        return {key: _redact_payload(item) for key, item in value.items()}
    return value
