from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from stock_analyzer.config import AppConfig
from stock_analyzer.data.health import HealthStatus, run_health_checks
from stock_analyzer.data.readiness import FormalRunState
from stock_analyzer.ops.calendar import decide_trading_day
from stock_analyzer.ops.cleanup import cleanup_trade_date
from stock_analyzer.ops.notify import notify_mac, should_notify
from stock_analyzer.ops.redaction import redact_secrets
from stock_analyzer.ops.status import FailureClass, JobStatus, RunStatus
from stock_analyzer.ops.verify import ProductionVerification, verify_production_result
from stock_analyzer.ops.formal_run import run_formal_strategy_v2
from stock_analyzer.ops.production_dependencies import (
    ProductionExternalRuntime,
    build_production_formal_dependencies,
)
from stock_analyzer.storage.capacity_guard import (
    SupabaseCapacityGuard,
    SupabaseCapacityLimitExceeded,
    SupabaseWriteScopeError,
)
from stock_analyzer.storage.repositories import SupabaseAnalysisRepository
from stock_analyzer.storage.supabase_client import create_supabase_client


MAX_ATTEMPTS = 3
FORMAL_FIRST_ATTEMPT_CUTOFF = time(hour=18, minute=30)
ACTION_REQUIRED_STATUSES = {
    RunStatus.FAILED_NEEDS_HUMAN,
    RunStatus.FAILED_RETRYABLE,
    RunStatus.CALENDAR_UNKNOWN,
    RunStatus.BLOCKED_NEEDS_HUMAN,
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
    notify_enabled: bool = False,
    notify_func: Callable[..., Any] | None = None,
    auto_publish: bool = False,
    publish_func: Callable[[Path, date], Any] | None = None,
) -> JobStatus:
    root = Path(project_root)
    started_at = _utc_now()
    status_file = status_path or root / "logs" / "run-daily" / "latest-status.json"
    cleanup_summary: dict[str, Any] = {}
    cleanup_performed = False
    effective_notify_func = notify_func or notify_mac

    def write_status(**kwargs) -> JobStatus:
        return _maybe_notify(
            _write_status(status_file, **kwargs),
            notify_enabled=notify_enabled,
            notify_func=effective_notify_func,
        )

    def failure_status(**kwargs) -> JobStatus:
        return _maybe_notify(
            _failure_status(status_file, **kwargs),
            notify_enabled=notify_enabled,
            notify_func=effective_notify_func,
        )

    if attempt > MAX_ATTEMPTS:
        return write_status(
            trade_date=trade_date,
            attempt=attempt,
            scheduled_slot=scheduled_slot,
            started_at=started_at,
            status=RunStatus.FAILED_NEEDS_HUMAN,
            stage="retry_preflight",
            failure_class=FailureClass.MAX_ATTEMPTS_EXCEEDED,
            fix_suggestion="Reject attempts above 3; inspect latest-status.json.",
        )

    prior_terminal_status = _prior_terminal_status(
        status_file,
        trade_date,
        attempt,
    )
    if prior_terminal_status is not None:
        return prior_terminal_status

    if attempt > 1:
        retry_preflight_error = _retry_preflight_error(
            status_file,
            trade_date,
            attempt,
        )
        if retry_preflight_error is not None:
            return write_status(
                trade_date=trade_date,
                attempt=attempt,
                scheduled_slot=scheduled_slot,
                started_at=started_at,
                status=RunStatus.FAILED_NEEDS_HUMAN,
                stage="retry_preflight",
                failure_class=FailureClass.RETRY_PREFLIGHT_BLOCKED,
                fix_suggestion=retry_preflight_error,
                error_message_redacted=retry_preflight_error,
            )

    try:
        repo = repository if repository is not None else _default_repository()
    except Exception as exc:
        return write_status(
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
    use_default_verifier = verifier is None
    verify_func = verifier or verify_production_result
    use_default_prepare_deploy = prepare_deploy_func is None
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
        return write_status(
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
        return write_status(
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
        return write_status(
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
            return write_status(
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
        return failure_status(
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
        run_result = _invoke(run_daily_func, root, repo, trade_date)
    except Exception as exc:
        return failure_status(
            trade_date=trade_date,
            attempt=attempt,
            scheduled_slot=scheduled_slot,
            started_at=started_at,
            stage="run_daily",
            exc=exc,
            cleanup_performed=cleanup_performed,
            cleanup_summary=cleanup_summary,
        )

    receipt = getattr(run_result, "receipt", None)
    if (
        receipt is not None
        and getattr(receipt, "state", None) == FormalRunState.BLOCKED_NEEDS_HUMAN
    ):
        return write_status(
            run_id=receipt.run_id,
            trade_date=trade_date,
            attempt=attempt,
            scheduled_slot=scheduled_slot,
            started_at=started_at,
            status=RunStatus.BLOCKED_NEEDS_HUMAN,
            stage="run_daily",
            cleanup_performed=cleanup_performed,
            cleanup_summary=cleanup_summary,
            publish_skipped_reason="data_readiness_blocked",
            fix_suggestion=(
                "Inspect the local blocked run status and restore a complete approved route before retrying."
            ),
            error_message_redacted="; ".join(
                getattr(receipt, "blocked_reasons", ())
            ),
        )

    try:
        if use_default_verifier:
            verification = verify_func(
                root,
                repo,
                trade_date,
                receipt=receipt,
            )
        else:
            verification = verify_func(root, repo, trade_date)
    except Exception as exc:
        return failure_status(
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
        return write_status(
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
            recommendation_state=verification.recommendation_state,
            focus_state=verification.focus_state,
            blocking_missing_fields=list(verification.blocking_missing_fields),
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
            if use_default_prepare_deploy:
                prepare_deploy_func(root, receipt=receipt)
            else:
                prepare_deploy_func(root)
            deploy_artifact_prepared = True
        except Exception as exc:
            return failure_status(
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

    final_status = write_status(
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
        recommendation_state=verification.recommendation_state,
        focus_state=verification.focus_state,
        blocking_missing_fields=list(verification.blocking_missing_fields),
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
    if auto_publish and final_status.status == RunStatus.SUCCESS_WITH_RECOMMENDATIONS:
        effective_publish = publish_func or _default_publish
        effective_publish(root, trade_date)

    return final_status


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


def _default_run_daily(
    project_root: Path,
    repository,
    trade_date: date,
    *,
    runtime: ProductionExternalRuntime | None = None,
    require_human_acceptance: bool = False,
    run_id: str | None = None,
):
    dependencies = (
        build_production_formal_dependencies(
            Path(project_root),
            repository,
            trade_date,
            runtime=runtime,
        )
        if runtime is not None
        else build_production_formal_dependencies(
            Path(project_root),
            repository,
            trade_date,
        )
    )
    report_cutoff = datetime.combine(
        trade_date,
        FORMAL_FIRST_ATTEMPT_CUTOFF,
        tzinfo=ZoneInfo("Asia/Shanghai"),
    )
    run_options = {}
    if require_human_acceptance:
        run_options["require_human_acceptance"] = True
    return run_formal_strategy_v2(
        trade_date,
        report_cutoff,
        dependencies,
        run_id=run_id or f"formal-{trade_date.isoformat()}",
        **run_options,
    )


def _default_prepare_deploy(project_root: Path, *, receipt=None) -> Path:
    from stock_analyzer.ops.artifacts import prepare_pages_artifact

    root = Path(project_root)
    return prepare_pages_artifact(
        root,
        root / "dist" / "pages",
        receipt=receipt,
    )


def _default_publish(project_root: Path, trade_date: date) -> Any:
    config = AppConfig.load()
    from stock_analyzer.ops.publish import (
        PublishConfig,
        PublishMode,
        build_publish_capacity_checker,
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
        capacity_checker=build_publish_capacity_checker(config),
        notify_enabled=config.notify_mac,
    )


def _retry_preflight_error(
    status_path: Path,
    trade_date: date,
    attempt: int,
) -> str | None:
    if not status_path.is_file():
        return (
            "Previous latest-status.json is required before retry attempts; "
            "do not clean or rerun production."
        )
    try:
        previous = JobStatus.model_validate_json(status_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return redact_secrets(
            "Previous latest-status.json could not be read before retry: "
            f"{exc}"
        )
    if previous.trade_date != trade_date:
        return (
            "Previous latest-status.json is for "
            f"{previous.trade_date.isoformat()}, not {trade_date.isoformat()}; "
            "do not clean or rerun production."
        )
    if previous.attempt != attempt - 1:
        return (
            "Previous latest-status.json attempt must be exactly "
            f"{attempt - 1} before attempt {attempt}; do not clean or rerun "
            "production."
        )
    if previous.status != RunStatus.FAILED_RETRYABLE:
        return (
            "Previous latest-status.json status must be failed_retryable before "
            "a retry slot can clean or rerun production."
        )
    return None


def _prior_terminal_status(
    status_path: Path,
    trade_date: date,
    attempt: int,
) -> JobStatus | None:
    if not status_path.is_file():
        return None
    try:
        previous = JobStatus.model_validate_json(
            status_path.read_text(encoding="utf-8")
        )
    except Exception:
        return None
    terminal_noop_statuses = {
        RunStatus.SUCCESS_WITH_RECOMMENDATIONS,
        RunStatus.SUCCESS_NO_RECOMMENDATIONS,
        RunStatus.SKIPPED_NON_TRADING_DAY,
    }
    if (
        previous.trade_date == trade_date
        and previous.attempt <= attempt
        and previous.status in terminal_noop_statuses
    ):
        return previous
    return None


def _maybe_notify(
    status: JobStatus,
    *,
    notify_enabled: bool,
    notify_func: Callable[..., Any],
) -> JobStatus:
    if not notify_enabled or not should_notify(status):
        return status
    title = redact_secrets("Stock analysis assistant needs attention")
    detail = (
        status.fix_suggestion
        or status.error_message_redacted
        or "Review logs/run-daily/latest-status.json."
    )
    message = redact_secrets(
        f"{status.trade_date.isoformat()} {status.status.value} "
        f"at {status.stage}: {detail}"
    )
    try:
        notify_func(title, message, enabled=True)
    except Exception:
        return status
    return status


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
    run_id: str | None = None,
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
    recommendation_state: str | None = None,
    focus_state: str | None = None,
    blocking_missing_fields: list[str] | None = None,
    market_price_daily_current_day_rows: int | None = None,
    daily_basic_indicator_current_day_rows: int | None = None,
    report_index_exists: bool | None = None,
    deploy_artifact_prepared: bool = False,
    publish_skipped_reason: str | None = None,
    fix_suggestion: str | None = None,
    error_message_redacted: str | None = None,
) -> JobStatus:
    job_status = JobStatus(
        run_id=run_id,
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
        recommendation_state=recommendation_state,
        focus_state=focus_state,
        blocking_missing_fields=blocking_missing_fields or [],
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
