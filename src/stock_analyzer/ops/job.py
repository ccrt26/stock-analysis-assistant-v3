from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from stock_analyzer.config import AppConfig
from stock_analyzer.data.health import HealthStatus, run_health_checks
from stock_analyzer.data.provider import (
    CurrentLiveDataUnavailable,
    build_production_market_data_provider,
)
from stock_analyzer.ops.calendar import decide_trading_day
from stock_analyzer.ops.cleanup import cleanup_trade_date
from stock_analyzer.ops.redaction import redact_secrets
from stock_analyzer.ops.status import FailureClass, JobStatus, RunStatus
from stock_analyzer.ops.verify import ProductionVerification, verify_production_result
from stock_analyzer.pipeline import ProductionDataSourceUnavailable, run_daily_pipeline
from stock_analyzer.storage.capacity_guard import (
    SupabaseCapacityGuard,
    SupabaseCapacityLimitExceeded,
    SupabaseWriteScopeError,
)
from stock_analyzer.storage.local_archive import LocalArchive
from stock_analyzer.storage.local_warehouse import LocalWarehouse
from stock_analyzer.storage.repositories import SupabaseAnalysisRepository
from stock_analyzer.storage.supabase_client import create_supabase_client


MAX_ATTEMPTS = 3
ACTION_REQUIRED_STATUSES = {
    RunStatus.FAILED_NEEDS_HUMAN,
    RunStatus.FAILED_RETRYABLE,
    RunStatus.CALENDAR_UNKNOWN,
}


class RetryableJobError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        failure_class: FailureClass,
        fix_suggestion: str | None = None,
    ) -> None:
        super().__init__(message)
        if not failure_class.retryable:
            raise ValueError("RetryableJobError requires a retryable failure_class")
        self.failure_class = failure_class
        self.fix_suggestion = fix_suggestion


class HumanInterventionJobError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        failure_class: FailureClass,
        fix_suggestion: str | None = None,
    ) -> None:
        super().__init__(message)
        self.failure_class = failure_class
        self.fix_suggestion = fix_suggestion


def run_daily_job(
    project_root: Path,
    trade_date: date,
    scheduled_slot: str,
    attempt: int,
    prepare_deploy: bool,
    *,
    repository=None,
    calendar_decider: Callable[..., Any] | None = None,
    tushare_calendar_loader=None,
    cleanup: Callable[[Path, Any, date], Any] | None = None,
    health_check: Callable[..., Any] | None = None,
    run_daily: Callable[..., Any] | None = None,
    verifier: Callable[[Path, Any, date], ProductionVerification] | None = None,
    prepare_deploy_func: Callable[[Path], Any] | None = None,
    status_path: Path | None = None,
) -> JobStatus:
    root = Path(project_root)
    started_at = _utc_now()
    status_file = status_path or root / "logs" / "run-daily" / "latest-status.json"
    cleanup_summary: dict[str, Any] = {}
    cleanup_performed = False

    try:
        repo = repository if repository is not None else _default_repository()
    except Exception as exc:
        return _write_status(
            status_file,
            trade_date=trade_date,
            attempt=attempt,
            scheduled_slot=scheduled_slot,
            started_at=started_at,
            status=RunStatus.FAILED_NEEDS_HUMAN,
            stage="calendar",
            failure_class=_human_failure_class(exc),
            fix_suggestion="Configure production storage credentials before rerunning.",
            error_message_redacted=str(exc),
        )

    calendar = calendar_decider or decide_trading_day
    cleanup_func = cleanup or cleanup_trade_date
    health_check_func = health_check or _default_health_check
    run_daily_func = run_daily or _default_run_daily
    verify_func = verifier or verify_production_result
    prepare_deploy_func = prepare_deploy_func or _default_prepare_deploy

    try:
        if tushare_calendar_loader is None and calendar_decider is None:
            tushare_calendar_loader = _default_tushare_calendar_loader()
        calendar_decision = calendar(
            trade_date,
            repo,
            tushare_calendar_loader=tushare_calendar_loader,
        )
    except Exception as exc:
        return _write_status(
            status_file,
            trade_date=trade_date,
            attempt=attempt,
            scheduled_slot=scheduled_slot,
            started_at=started_at,
            status=RunStatus.CALENDAR_UNKNOWN,
            stage="calendar",
            failure_class=FailureClass.CALENDAR_UNKNOWN,
            fix_suggestion="Review the market calendar source and rerun this job.",
            error_message_redacted=str(exc),
        )

    if calendar_decision.status == "non_trading_day":
        return _write_status(
            status_file,
            trade_date=trade_date,
            attempt=attempt,
            scheduled_slot=scheduled_slot,
            started_at=started_at,
            status=RunStatus.SKIPPED_NON_TRADING_DAY,
            stage="complete",
            publish_skipped_reason="non_trading_day",
            fix_suggestion=calendar_decision.message,
        )

    if calendar_decision.status == "calendar_unknown":
        return _write_status(
            status_file,
            trade_date=trade_date,
            attempt=attempt,
            scheduled_slot=scheduled_slot,
            started_at=started_at,
            status=RunStatus.CALENDAR_UNKNOWN,
            stage="calendar",
            failure_class=FailureClass.CALENDAR_UNKNOWN,
            fix_suggestion=calendar_decision.message,
            error_message_redacted=calendar_decision.message,
        )

    if attempt > 1:
        try:
            cleanup_result = cleanup_func(root, repo, trade_date)
            cleanup_summary = _cleanup_summary_to_dict(cleanup_result)
            cleanup_performed = True
        except Exception as exc:
            return _write_status(
                status_file,
                trade_date=trade_date,
                attempt=attempt,
                scheduled_slot=scheduled_slot,
                started_at=started_at,
                status=RunStatus.FAILED_NEEDS_HUMAN,
                stage="cleanup",
                failure_class=FailureClass.CLEANUP_FAILED,
                cleanup_performed=False,
                cleanup_summary=cleanup_summary,
                fix_suggestion=(
                    "Inspect same-day cleanup for the target trade_date before retrying."
                ),
                error_message_redacted=str(exc),
            )

    try:
        _invoke(health_check_func, root, repo, trade_date)
    except Exception as exc:
        return _failure_status(
            status_file,
            trade_date=trade_date,
            attempt=attempt,
            scheduled_slot=scheduled_slot,
            started_at=started_at,
            stage="health_check",
            exc=exc,
            cleanup_performed=cleanup_performed,
            cleanup_summary=cleanup_summary,
        )

    try:
        _invoke(run_daily_func, root, repo, trade_date)
    except Exception as exc:
        return _failure_status(
            status_file,
            trade_date=trade_date,
            attempt=attempt,
            scheduled_slot=scheduled_slot,
            started_at=started_at,
            stage="run_daily",
            exc=exc,
            cleanup_performed=cleanup_performed,
            cleanup_summary=cleanup_summary,
        )

    try:
        verification = verify_func(root, repo, trade_date)
    except Exception as exc:
        return _failure_status(
            status_file,
            trade_date=trade_date,
            attempt=attempt,
            scheduled_slot=scheduled_slot,
            started_at=started_at,
            stage="verify",
            exc=exc,
            cleanup_performed=cleanup_performed,
            cleanup_summary=cleanup_summary,
        )

    if not verification.passed:
        failure_class = verification.failure_class or FailureClass.REPORT_ARTIFACT_INVALID
        status = _failed_status_for_failure_class(failure_class, attempt)
        return _write_status(
            status_file,
            trade_date=trade_date,
            attempt=attempt,
            scheduled_slot=scheduled_slot,
            started_at=started_at,
            status=status,
            stage="verify",
            failure_class=failure_class,
            cleanup_performed=cleanup_performed,
            cleanup_summary=cleanup_summary,
            fix_suggestion=verification.fix_suggestion,
            recommendations=verification.recommendations,
            evidence_packages=verification.evidence_packages,
            evaluation_tasks=verification.evaluation_tasks,
            market_price_daily_current_day_rows=(
                verification.market_price_daily_current_day_rows
            ),
            daily_basic_indicator_current_day_rows=(
                verification.daily_basic_indicator_current_day_rows
            ),
            report_index_exists=verification.report_index_exists,
        )

    deploy_artifact_prepared = False
    publish_skipped_reason = None
    if prepare_deploy:
        try:
            prepare_deploy_func(root)
            deploy_artifact_prepared = True
        except Exception as exc:
            return _failure_status(
                status_file,
                trade_date=trade_date,
                attempt=attempt,
                scheduled_slot=scheduled_slot,
                started_at=started_at,
                stage="prepare_deploy",
                exc=RetryableJobError(
                    str(exc),
                    failure_class=FailureClass.DEPLOY_ARTIFACT_NOT_READY,
                    fix_suggestion=(
                        "Prepare deploy artifacts after confirming report outputs exist."
                    ),
                ),
                cleanup_performed=cleanup_performed,
                cleanup_summary=cleanup_summary,
                recommendations=verification.recommendations,
                evidence_packages=verification.evidence_packages,
                evaluation_tasks=verification.evaluation_tasks,
            )
    else:
        publish_skipped_reason = "prepare_deploy_flag_not_set"

    return _write_status(
        status_file,
        trade_date=trade_date,
        attempt=attempt,
        scheduled_slot=scheduled_slot,
        started_at=started_at,
        status=verification.status,
        stage="complete",
        cleanup_performed=cleanup_performed,
        cleanup_summary=cleanup_summary,
        recommendations=verification.recommendations,
        evidence_packages=verification.evidence_packages,
        evaluation_tasks=verification.evaluation_tasks,
        market_price_daily_current_day_rows=(
            verification.market_price_daily_current_day_rows
        ),
        daily_basic_indicator_current_day_rows=(
            verification.daily_basic_indicator_current_day_rows
        ),
        report_index_exists=verification.report_index_exists,
        deploy_artifact_prepared=deploy_artifact_prepared,
        publish_skipped_reason=publish_skipped_reason,
    )


def _default_repository():
    config = AppConfig.load()
    if not config.has_supabase_config:
        raise HumanInterventionJobError(
            "Supabase production credentials are required for run-daily-job.",
            failure_class=FailureClass.SUPABASE_CREDENTIAL_MISSING_OR_INVALID,
        )
    client = create_supabase_client(config)
    return SupabaseAnalysisRepository(
        client,
        capacity_guard=SupabaseCapacityGuard(
            client,
            warn_mb=config.supabase_warn_mb,
            stop_mb=config.supabase_stop_mb,
        ),
    )


def _default_tushare_calendar_loader():
    config = AppConfig.load()
    token = config.resolve_tushare_token()
    if not token:
        return None
    from stock_analyzer.data.tushare_source import TushareMarketDataSource

    return TushareMarketDataSource(token=token)


def _default_health_check(*_args) -> None:
    report = run_health_checks(AppConfig.load())
    failing = [item for item in report.items if item.status == HealthStatus.FAIL]
    if failing:
        raise HumanInterventionJobError(
            "; ".join(item.message for item in failing),
            failure_class=FailureClass.TUSHARE_CREDENTIAL_MISSING_OR_INVALID,
            fix_suggestion="Configure production data credentials before rerunning.",
        )


def _default_run_daily(project_root: Path, repository, trade_date: date) -> None:
    config = AppConfig.load()
    try:
        market_data_provider = build_production_market_data_provider(config)
    except CurrentLiveDataUnavailable as exc:
        raise RetryableJobError(
            str(exc),
            failure_class=FailureClass.TUSHARE_DATA_TEMPORARILY_UNAVAILABLE,
            fix_suggestion="Retry after the live data provider publishes current rows.",
        ) from exc

    try:
        run_daily_pipeline(
            trade_date,
            config.reports_dir,
            dry_run=False,
            repository=repository,
            persist=True,
            fixture_mode=False,
            market_data_provider=market_data_provider,
            local_warehouse=LocalWarehouse(config.local_warehouse_dir),
            local_archive=LocalArchive(config.local_archive_dir),
        )
    except ProductionDataSourceUnavailable as exc:
        raise RetryableJobError(
            str(exc),
            failure_class=FailureClass.TUSHARE_DATA_TEMPORARILY_UNAVAILABLE,
            fix_suggestion="Retry after confirming current production data is available.",
        ) from exc


def _default_prepare_deploy(project_root: Path) -> Path:
    from stock_analyzer.ops.artifacts import prepare_pages_artifact

    root = Path(project_root)
    return prepare_pages_artifact(root, root / "dist" / "pages")


def _failure_status(
    status_path: Path,
    *,
    trade_date: date,
    attempt: int,
    scheduled_slot: str,
    started_at: datetime,
    stage: str,
    exc: Exception,
    cleanup_performed: bool,
    cleanup_summary: dict[str, Any],
    recommendations: int | None = None,
    evidence_packages: int | None = None,
    evaluation_tasks: int | None = None,
) -> JobStatus:
    failure_class = _failure_class(exc)
    status = _failed_status_for_failure_class(failure_class, attempt)
    if status == RunStatus.FAILED_NEEDS_HUMAN and isinstance(exc, RetryableJobError):
        failure_class = FailureClass.MAX_ATTEMPTS_EXCEEDED
    return _write_status(
        status_path,
        trade_date=trade_date,
        attempt=attempt,
        scheduled_slot=scheduled_slot,
        started_at=started_at,
        status=status,
        stage=stage,
        failure_class=failure_class,
        cleanup_performed=cleanup_performed,
        cleanup_summary=cleanup_summary,
        recommendations=recommendations,
        evidence_packages=evidence_packages,
        evaluation_tasks=evaluation_tasks,
        fix_suggestion=_fix_suggestion(exc, failure_class, status),
        error_message_redacted=str(exc),
    )


def _failed_status_for_failure_class(
    failure_class: FailureClass,
    attempt: int,
) -> RunStatus:
    if failure_class.retryable and attempt < MAX_ATTEMPTS:
        return RunStatus.FAILED_RETRYABLE
    return RunStatus.FAILED_NEEDS_HUMAN


def _failure_class(exc: Exception) -> FailureClass:
    if isinstance(exc, RetryableJobError | HumanInterventionJobError):
        return exc.failure_class
    if isinstance(exc, ImportError):
        return FailureClass.IMPORT_ERROR
    if isinstance(exc, SupabaseCapacityLimitExceeded):
        return FailureClass.SUPABASE_CAPACITY_STOP
    if isinstance(exc, SupabaseWriteScopeError):
        return FailureClass.POSSIBLE_FULL_MARKET_WRITE
    return _classify_message(str(exc))


def _human_failure_class(exc: Exception) -> FailureClass:
    failure_class = _failure_class(exc)
    if failure_class.retryable:
        return FailureClass.SCHEMA_MISMATCH
    return failure_class


def _classify_message(message: str) -> FailureClass:
    lowered = message.lower()
    if "timeout" in lowered:
        return FailureClass.NETWORK_TIMEOUT
    if "dns" in lowered:
        return FailureClass.DNS_FAILURE
    if "5xx" in lowered or "server error" in lowered:
        return FailureClass.SUPABASE_SERVER_ERROR
    if "connection" in lowered and "temporary" in lowered:
        return FailureClass.TEMPORARY_CONNECTION_FAILURE
    if "schema" in lowered:
        return FailureClass.SCHEMA_MISMATCH
    if "migration" in lowered:
        return FailureClass.MIGRATION_DRIFT
    if "tushare" in lowered and ("token" in lowered or "credential" in lowered):
        return FailureClass.TUSHARE_CREDENTIAL_MISSING_OR_INVALID
    if "supabase" in lowered and ("key" in lowered or "credential" in lowered):
        return FailureClass.SUPABASE_CREDENTIAL_MISSING_OR_INVALID
    if "tushare" in lowered:
        return FailureClass.TUSHARE_DATA_TEMPORARILY_UNAVAILABLE
    return FailureClass.REPORT_ARTIFACT_INVALID


def _fix_suggestion(
    exc: Exception,
    failure_class: FailureClass,
    status: RunStatus,
) -> str:
    if isinstance(exc, RetryableJobError | HumanInterventionJobError):
        if exc.fix_suggestion:
            return exc.fix_suggestion
    if failure_class == FailureClass.MAX_ATTEMPTS_EXCEEDED:
        return "Three attempts failed; stop automation and inspect the run logs."
    if status == RunStatus.FAILED_RETRYABLE:
        return "Retry at the next scheduled slot after same-day cleanup."
    return "Stop automation and review the failed stage before rerunning."


def _cleanup_summary_to_dict(summary: Any) -> dict[str, Any]:
    if summary is None:
        return {}
    if is_dataclass(summary):
        return _jsonable(asdict(summary))
    if hasattr(summary, "model_dump"):
        return _jsonable(summary.model_dump(mode="json"))
    if isinstance(summary, dict):
        return _jsonable(summary)
    return {"summary": redact_secrets(str(summary))}


def _write_status(
    path: Path,
    *,
    trade_date: date,
    attempt: int,
    scheduled_slot: str,
    started_at: datetime,
    status: RunStatus,
    stage: str,
    failure_class: FailureClass | None = None,
    cleanup_performed: bool = False,
    cleanup_summary: dict[str, Any] | None = None,
    recommendations: int | None = None,
    evidence_packages: int | None = None,
    evaluation_tasks: int | None = None,
    market_price_daily_current_day_rows: int | None = None,
    daily_basic_indicator_current_day_rows: int | None = None,
    report_index_exists: bool | None = None,
    deploy_artifact_prepared: bool = False,
    publish_skipped_reason: str | None = None,
    fix_suggestion: str | None = None,
    error_message_redacted: str | None = None,
) -> JobStatus:
    job_status = JobStatus(
        trade_date=trade_date,
        attempt=attempt,
        scheduled_slot=scheduled_slot,
        started_at=started_at,
        finished_at=_utc_now(),
        status=status,
        stage=stage,
        failure_class=failure_class,
        cleanup_performed=cleanup_performed,
        cleanup_summary=cleanup_summary or {},
        recommendations=recommendations,
        evidence_packages=evidence_packages,
        evaluation_tasks=evaluation_tasks,
        market_price_daily_current_day_rows=market_price_daily_current_day_rows,
        daily_basic_indicator_current_day_rows=daily_basic_indicator_current_day_rows,
        report_index_exists=report_index_exists,
        deploy_artifact_prepared=deploy_artifact_prepared,
        publish_skipped_reason=publish_skipped_reason,
        fix_suggestion=fix_suggestion,
        error_message_redacted=error_message_redacted,
    )
    job_status.write_json(path)
    return job_status


def _invoke(func: Callable[..., Any], *args) -> Any:
    return func(*args)


def _jsonable(value: Any) -> Any:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, str):
        return redact_secrets(value)
    return value


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)
