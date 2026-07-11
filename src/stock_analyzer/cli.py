from datetime import date, datetime
import json
import os
from pathlib import Path
from typing import Optional
import uuid
from zoneinfo import ZoneInfo

import typer

from stock_analyzer.config import AppConfig
from stock_analyzer.data.health import run_health_checks
from stock_analyzer.data.readiness import FormalRunState
from stock_analyzer.ops.job import (
    ACTION_REQUIRED_STATUSES,
    FORMAL_FIRST_ATTEMPT_CUTOFF,
    HumanInterventionJobError,
    RetryableJobError,
    _default_run_daily,
    run_daily_job,
)
from stock_analyzer.ops.formal_live import (
    LiveCapabilityVerificationError,
    verify_and_record_live_capabilities,
)
from stock_analyzer.ops.production_dependencies import (
    ProductionDependencyError,
    load_default_external_runtime,
)
from stock_analyzer.ops.artifacts import DeployArtifactError, prepare_pages_artifact
from stock_analyzer.ops.activation import ActivationError, FormalActivationCoordinator
from stock_analyzer.ops.publish import (
    PublishConfig,
    PublishMode,
    PublishStatus,
    build_publish_capacity_checker,
    publish_report_site,
)
from stock_analyzer.ops.smoke import smoke_report_site
from stock_analyzer.ops.verify import verify_production_result
from stock_analyzer.pipeline import (
    ProductionDataSourceUnavailable,
    StoredAnalysisNotFound,
    latest_committed_report_receipt,
    render_report_for_date,
    run_daily_pipeline,
)
from stock_analyzer.storage.evidence_store import FrozenReportReference, LocalEvidenceStore
from stock_analyzer.storage.capacity_guard import SupabaseCapacityGuard
from stock_analyzer.storage.repositories import (
    InMemoryAnalysisRepository,
    SupabaseAnalysisRepository,
)
from stock_analyzer.storage.supabase_client import create_supabase_client


app = typer.Typer(no_args_is_help=True)
ops_app = typer.Typer(no_args_is_help=True)
app.add_typer(ops_app, name="ops")
DEFAULT_REPORT_PASSWORD_ENV = "REPORT_" "PASSWORD"

MISSING_SUPABASE_CONFIG_MESSAGE = (
    "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required for production "
    "run-daily/render-report. Use --fixture-mode or set "
    "STOCK_ANALYZER_FIXTURE_MODE=1 only for local fixture data."
)


@app.command("health-check")
def health_check(
    live_tushare_smoke: bool = typer.Option(False, "--live-tushare-smoke"),
    live_tushare_trade_date: Optional[str] = typer.Option(
        None,
        "--live-tushare-trade-date",
    ),
) -> None:
    config = AppConfig.load()
    report = run_health_checks(config)
    for line in report.as_lines():
        typer.echo(line)
    if live_tushare_smoke:
        token = config.resolve_tushare_token()
        if not token:
            _fail("Tushare token missing; set TUSHARE_TOKEN or TUSHARE_TOKEN_PATH")
        if live_tushare_trade_date is None:
            _fail("--live-tushare-trade-date is required for live Tushare smoke")
        smoke_trade_date = date.fromisoformat(live_tushare_trade_date)
        try:
            source = _build_tushare_source(token)
            rows = source.fetch_daily(smoke_trade_date)
        except Exception as exc:
            _fail(f"live Tushare smoke failed: {_mask_secret(str(exc), token)}")
        typer.echo(f"live_tushare_smoke: rows={len(rows)}")


@app.command("run-daily")
def run_daily(
    dry_run: bool = typer.Option(False, "--dry-run"),
    fixture_mode: bool = typer.Option(False, "--fixture-mode"),
    strategy_v2: bool = typer.Option(False, "--strategy-v2"),
    allow_data_insufficient_output: bool = typer.Option(
        False,
        "--allow-data-insufficient-output",
    ),
    trade_date: str = typer.Option(..., "--trade-date"),
) -> None:
    parsed_trade_date = date.fromisoformat(trade_date)
    config = AppConfig.load()
    effective_fixture_mode = fixture_mode or config.fixture_mode
    if not dry_run and not effective_fixture_mode:
        if not config.has_supabase_config:
            _fail(MISSING_SUPABASE_CONFIG_MESSAGE)
    try:
        repository = _analysis_repository(
            config,
            require_supabase=not dry_run,
            fixture_mode=effective_fixture_mode,
        )
    except MissingSupabaseConfig as exc:
        _fail(str(exc))

    if not dry_run and not effective_fixture_mode:
        try:
            formal_result = _default_run_daily(
                config.project_root,
                repository,
                parsed_trade_date,
            )
        except (HumanInterventionJobError, RetryableJobError, RuntimeError) as exc:
            _fail(str(exc))
        if formal_result.receipt.state.value == "blocked_needs_human":
            _fail(
                "Formal run blocked_needs_human; inspect logs/run-daily/latest-status.json."
            )
        typer.echo(
            f"daily formal run completed for {parsed_trade_date.isoformat()} "
            f"({formal_result.receipt.state.value})"
        )
        return

    try:
        result = run_daily_pipeline(
            parsed_trade_date,
            config.reports_dir,
            dry_run=dry_run,
            repository=repository,
            persist=not dry_run,
            fixture_mode=effective_fixture_mode,
            strategy_v2=strategy_v2,
            allow_data_insufficient_output=(
                allow_data_insufficient_output and (effective_fixture_mode or dry_run)
            ),
        )
    except ProductionDataSourceUnavailable as exc:
        _fail(str(exc))

    if dry_run:
        typer.echo(
            "daily run dry-run completed for "
            f"{result.trade_date.isoformat()} (local sample data, no persistence)"
        )
        return
    if effective_fixture_mode:
        typer.echo(f"daily fixture run completed for {result.trade_date.isoformat()}")
        typer.echo(f"recommendations: {len(result.recommendations)}")
        typer.echo(f"evaluation_tasks: {len(result.evaluation_tasks)}")
        return
    typer.echo(f"daily run completed for {result.trade_date.isoformat()}")
    typer.echo(f"recommendations: {len(result.recommendations)}")
    typer.echo(f"evaluation_tasks: {len(result.evaluation_tasks)}")


@app.command("prepare-formal-report-candidate")
def prepare_formal_report_candidate(
    trade_date: str = typer.Option(..., "--trade-date"),
) -> None:
    parsed_trade_date = date.fromisoformat(trade_date)
    config = AppConfig.load()
    if not config.has_supabase_config:
        _fail(MISSING_SUPABASE_CONFIG_MESSAGE)
    try:
        repository = _analysis_repository(
            config,
            require_supabase=True,
            fixture_mode=False,
        )
        result = _default_run_daily(
            config.project_root,
            repository,
            parsed_trade_date,
            require_human_acceptance=True,
            run_id=(
                f"formal-report-readability-{parsed_trade_date.isoformat()}-"
                f"{uuid.uuid4().hex}"
            ),
        )
    except (
        MissingSupabaseConfig,
        HumanInterventionJobError,
        RetryableJobError,
        RuntimeError,
        ValueError,
    ) as exc:
        _fail(str(exc))
    if result.receipt.state is not FormalRunState.AWAITING_HUMAN_ACCEPTANCE:
        _fail(
            "Formal candidate was not prepared; inspect the redacted formal run status."
        )
    candidate = result.prepared_candidate
    if candidate is None:
        _fail("Formal candidate metadata is missing.")
    typer.echo(f"run_id: {candidate.run_id}")
    typer.echo(f"candidate_root: {candidate.candidate_root}")
    typer.echo("automated_gates_passed: true")
    typer.echo(f"candidate_hash: {candidate.candidate_hash}")
    typer.echo("product_acceptance: awaiting_human_readability_acceptance")


@app.command("activate-formal-report-candidate")
def activate_formal_report_candidate(
    run_id: str = typer.Option(..., "--run-id"),
    expected_candidate_hash: str = typer.Option(
        ...,
        "--expected-candidate-hash",
    ),
    accept_readability: bool = typer.Option(False, "--accept-readability"),
) -> None:
    if not accept_readability:
        _fail("--accept-readability is required after human readability review")
    config = AppConfig.load()
    if not config.has_supabase_config:
        _fail(MISSING_SUPABASE_CONFIG_MESSAGE)
    try:
        repository = _analysis_repository(
            config,
            require_supabase=True,
            fixture_mode=False,
        )
        store = LocalEvidenceStore(config.local_warehouse_dir / "formal_evidence")
        coordinator = FormalActivationCoordinator(
            config.reports_dir,
            store,
            repository,
        )
        candidate = coordinator.load_prepared_candidate(run_id)
        completed = coordinator.activate_prepared_candidate(
            candidate,
            expected_candidate_hash,
        )
        if completed.input_set_id is None:
            raise ActivationError("activated receipt lacks input set")
        store.save_frozen_report_reference(
            FrozenReportReference(
                run_id=completed.run_id,
                input_set_id=completed.input_set_id,
                group_version_ids=tuple(
                    completed.group_version_ids[key]
                    for key in sorted(completed.group_version_ids)
                ),
                artifact_hashes=completed.artifact_hashes,
            )
        )
    except (MissingSupabaseConfig, ActivationError, FileNotFoundError, ValueError) as exc:
        _fail(str(exc))
    typer.echo(
        f"formal report candidate activated for run {completed.run_id} "
        f"({completed.state.value})"
    )


@app.command("render-report")
def render_report(
    trade_date: str = typer.Option(..., "--trade-date"),
    output_dir: Optional[Path] = typer.Option(None, "--output-dir"),
    fixture_mode: bool = typer.Option(False, "--fixture-mode"),
) -> None:
    parsed_trade_date = date.fromisoformat(trade_date)
    config = AppConfig.load()
    target_dir = output_dir or config.reports_dir
    effective_fixture_mode = fixture_mode or config.fixture_mode
    receipt_store = None
    expected_input_set_id = None
    if not effective_fixture_mode:
        receipt_store = LocalEvidenceStore(
            config.local_warehouse_dir / "formal_evidence"
        )
        committed = latest_committed_report_receipt(
            receipt_store,
            parsed_trade_date,
        )
        if committed is not None:
            expected_input_set_id = committed.input_set_id
    try:
        result = render_report_for_date(
            parsed_trade_date,
            target_dir,
            repository=_analysis_repository(
                config,
                require_supabase=True,
                fixture_mode=effective_fixture_mode,
            ),
            allow_fixture_fallback=effective_fixture_mode,
            receipt_store=receipt_store,
            expected_input_set_id=expected_input_set_id,
        )
    except (MissingSupabaseConfig, StoredAnalysisNotFound) as exc:
        _fail(str(exc))
    if effective_fixture_mode:
        typer.echo(f"fixture report rendered for {result.trade_date.isoformat()}")
        return
    typer.echo(f"report rendered for {result.trade_date.isoformat()}")


@ops_app.command("run-daily-job")
def ops_run_daily_job(
    trade_date: str = typer.Option(..., "--trade-date"),
    scheduled_slot: str = typer.Option(..., "--scheduled-slot"),
    attempt: int = typer.Option(..., "--attempt", min=1),
    prepare_deploy: bool = typer.Option(False, "--prepare-deploy"),
    notify_mac: bool = typer.Option(False, "--notify-mac"),
) -> None:
    parsed_trade_date = date.fromisoformat(trade_date)
    config = AppConfig.load()
    status = run_daily_job(
        project_root=config.project_root,
        trade_date=parsed_trade_date,
        scheduled_slot=scheduled_slot,
        attempt=attempt,
        prepare_deploy=prepare_deploy,
        notify_enabled=notify_mac or config.notify_mac,
        auto_publish=True,
    )
    typer.echo(f"{status.status.value} stage={status.stage}")
    if status.status in ACTION_REQUIRED_STATUSES:
        raise typer.Exit(code=2)


@ops_app.command("verify-formal-capabilities")
def ops_verify_formal_capabilities(
    trade_date: str = typer.Option(..., "--trade-date"),
    confirm_live_read: bool = typer.Option(False, "--confirm-live-read"),
) -> None:
    if not confirm_live_read:
        _fail("--confirm-live-read is required before any provider call")
    parsed_trade_date = date.fromisoformat(trade_date)
    cutoff = datetime.combine(
        parsed_trade_date,
        FORMAL_FIRST_ATTEMPT_CUTOFF,
        tzinfo=ZoneInfo("Asia/Shanghai"),
    )
    config = AppConfig.load()
    try:
        runtime = load_default_external_runtime(config)
        result = verify_and_record_live_capabilities(
            runtime,
            parsed_trade_date,
            cutoff,
            confirm_live_read=True,
        )
    except (ProductionDependencyError, LiveCapabilityVerificationError, RuntimeError) as exc:
        _fail(str(exc))
    typer.echo(
        "formal capability verification completed: "
        f"routes={len(result.bundle.routes)} "
        f"screening_versions={len(result.primary_screening_versions)}"
    )


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
        capacity_checker=build_publish_capacity_checker(config),
        notify_enabled=notify_mac or config.notify_mac,
    )
    typer.echo(state.summary_for_user)
    if state.user_action_required:
        typer.echo(f"需要你处理：{state.user_action_required}", err=True)
    if state.status != PublishStatus.SUCCESS:
        raise typer.Exit(code=2)


def stock_analyzer_publish() -> None:
    app(args=["ops", "publish-report-site"], prog_name="stock-analyzer-publish")


@ops_app.command("prepare-deploy")
def ops_prepare_deploy(
    output_dir: Path = typer.Option(Path("dist/pages"), "--output-dir"),
) -> None:
    config = AppConfig.load()
    target_dir = output_dir if output_dir.is_absolute() else config.project_root / output_dir
    try:
        report_payload = json.loads(
            (config.reports_dir / "data" / "latest.json").read_text(encoding="utf-8")
        )
        report_date = date.fromisoformat(report_payload["trade_date"])
        receipt = latest_committed_report_receipt(
            LocalEvidenceStore(config.local_warehouse_dir / "formal_evidence"),
            report_date,
        )
        artifact_dir = prepare_pages_artifact(
            config.project_root,
            target_dir,
            receipt=receipt,
        )
    except (DeployArtifactError, OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        _fail(str(exc))
    typer.echo(f"deploy artifact prepared: {artifact_dir}")


@ops_app.command("smoke-report-site")
def ops_smoke_report_site(
    url: str = typer.Option(..., "--url"),
    password_env: str = typer.Option(DEFAULT_REPORT_PASSWORD_ENV, "--password-env"),
    expected_trade_date: Optional[str] = typer.Option(
        None,
        "--expected-trade-date",
    ),
) -> None:
    password = os.environ.get(password_env)
    parsed_expected_trade_date = (
        date.fromisoformat(expected_trade_date) if expected_trade_date else None
    )
    try:
        result = smoke_report_site(
            url,
            password,
            expected_trade_date=parsed_expected_trade_date,
        )
    except ValueError as exc:
        _fail(str(exc))
    if result.passed:
        typer.echo("smoke-report-site passed")
        return
    for failure in result.failures:
        typer.echo(
            f"smoke-report-site failed [{failure.code}]: {failure.message}",
            err=True,
        )
        typer.echo(f"fix: {failure.fix_suggestion}", err=True)
    raise typer.Exit(code=2)


@ops_app.command("verify-production")
def ops_verify_production(
    trade_date: str = typer.Option(..., "--trade-date"),
) -> None:
    parsed_trade_date = date.fromisoformat(trade_date)
    config = AppConfig.load()
    try:
        repository = _analysis_repository(config, require_supabase=True)
    except MissingSupabaseConfig as exc:
        _fail(str(exc))
    receipt = latest_committed_report_receipt(
        LocalEvidenceStore(config.local_warehouse_dir / "formal_evidence"),
        parsed_trade_date,
    )
    try:
        verification = verify_production_result(
            config.project_root,
            repository,
            parsed_trade_date,
            receipt=receipt,
        )
    except ValueError as exc:
        _fail(str(exc))
    typer.echo(
        f"{verification.status.value} "
        f"recommendations={verification.recommendations} "
        f"evidence_packages={verification.evidence_packages} "
        f"evaluation_tasks={verification.evaluation_tasks}"
    )
    if verification.passed:
        return
    for failure in verification.failures:
        typer.echo(
            f"verify-production failed [{failure.code}]: {failure.message}",
            err=True,
        )
        typer.echo(f"fix: {failure.fix_suggestion}", err=True)
    raise typer.Exit(code=2)


class MissingSupabaseConfig(RuntimeError):
    pass


def _analysis_repository(
    config: AppConfig,
    *,
    require_supabase: bool = True,
    fixture_mode: bool = False,
):
    if fixture_mode:
        return InMemoryAnalysisRepository()
    if not require_supabase:
        return InMemoryAnalysisRepository()
    if config.has_supabase_config:
        client = create_supabase_client(config)
        return SupabaseAnalysisRepository(
            client,
            capacity_guard=SupabaseCapacityGuard(
                client,
                warn_mb=config.supabase_warn_mb,
                stop_mb=config.supabase_stop_mb,
            ),
        )
    raise MissingSupabaseConfig(MISSING_SUPABASE_CONFIG_MESSAGE)


def _build_tushare_source(token: str):
    from stock_analyzer.data.tushare_source import TushareMarketDataSource

    return TushareMarketDataSource(token=token)


def _mask_secret(message: str, secret: str) -> str:
    return message.replace(secret, "[masked]") if secret else message


def _fail(message: str) -> None:
    typer.echo(f"Error: {message}", err=True)
    raise typer.Exit(code=2)
