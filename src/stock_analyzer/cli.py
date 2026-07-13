from datetime import date, datetime, timedelta
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
from stock_analyzer.ops.formal_warehouse_ops import (
    run_formal_warehouse_audit,
    run_formal_warehouse_deletion_manifest,
    run_formal_warehouse_inventory,
    run_formal_warehouse_migration,
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
from stock_analyzer.storage.evidence_store import FrozenReportReference
from stock_analyzer.storage.formal_warehouse import FormalWarehouse
from stock_analyzer.storage.capacity_guard import SupabaseCapacityGuard
from stock_analyzer.storage.repositories import (
    InMemoryAnalysisRepository,
    SupabaseAnalysisRepository,
)
from stock_analyzer.storage.supabase_client import create_supabase_client


app = typer.Typer(no_args_is_help=True)
ops_app = typer.Typer(no_args_is_help=True)
data_app = typer.Typer(no_args_is_help=True)
app.add_typer(ops_app, name="ops")
app.add_typer(data_app, name="data")
DEFAULT_REPORT_PASSWORD_ENV = "REPORT_" "PASSWORD"

MISSING_SUPABASE_CONFIG_MESSAGE = (
    "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required for production "
    "run-daily/render-report. Use --fixture-mode or set "
    "STOCK_ANALYZER_FIXTURE_MODE=1 only for local fixture data."
)


@data_app.command("inspect-legacy-market")
def data_inspect_legacy_market(
    source_root: Path = typer.Option(..., "--source-root"),
    output: Optional[Path] = typer.Option(None, "--output"),
) -> None:
    from stock_analyzer.storage.research_migration import inspect_legacy_market

    audit = inspect_legacy_market(source_root)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(audit.model_dump_json(indent=2), encoding="utf-8")
    typer.echo(
        f"legacy market: physical={audit.physical_rows} "
        f"unique={audit.unique_business_keys} duplicates={audit.duplicate_rows} "
        f"versions={audit.version_count} conflicts={audit.conflicting_business_keys}"
    )


@data_app.command("migrate-legacy-market")
def data_migrate_legacy_market(
    source_root: Path = typer.Option(..., "--source-root"),
    migration_id: str = typer.Option(..., "--migration-id"),
) -> None:
    from stock_analyzer.storage.research_migration import migrate_legacy_market
    from stock_analyzer.storage.research_warehouse import ResearchWarehouse

    config = AppConfig.load()
    report = migrate_legacy_market(
        source_root,
        ResearchWarehouse(config.local_warehouse_dir),
        migration_id=migration_id,
    )


@data_app.command("audit-migration")
def data_audit_migration(
    migration_id: str = typer.Option(..., "--migration-id"),
    source_root: Path = typer.Option(
        Path("local_warehouse/parquet/formal"), "--source-root"
    ),
    strict_hashes: bool = typer.Option(False, "--strict-hashes"),
) -> None:
    from stock_analyzer.storage.research_migration import (
        audit_legacy_market_migration,
    )
    from stock_analyzer.storage.research_warehouse import ResearchWarehouse

    config = AppConfig.load()
    audit = audit_legacy_market_migration(
        source_root,
        ResearchWarehouse(config.local_warehouse_dir),
        migration_id=migration_id,
        strict_hashes=strict_hashes,
    )
    typer.echo(
        f"migration audit {migration_id}: passed={str(audit.passed).lower()} "
        f"missing={audit.missing_target_keys} extra={audit.extra_target_keys} "
        f"value_mismatches={audit.value_mismatches}"
    )
    if not audit.passed:
        raise typer.Exit(code=2)
    typer.echo(
        f"migration {migration_id}: unique={report.migrated_business_keys} "
        f"revisions={report.revision_rows} partitions={report.partition_count} "
        f"already_completed={str(report.already_completed).lower()}"
    )


@data_app.command("backfill")
def data_backfill(
    through: str = typer.Option(..., "--through"),
    start: Optional[str] = typer.Option(None, "--start"),
    scope: str = typer.Option("all", "--scope"),
    resume: bool = typer.Option(True, "--resume/--no-resume"),
) -> None:
    from stock_analyzer.ops.research_data_job import (
        build_research_data_runtime,
        run_research_backfill,
    )

    through_date = date.fromisoformat(through)
    start_date = (
        date.fromisoformat(start)
        if start is not None
        else through_date - timedelta(days=5 * 366)
    )
    runtime = build_research_data_runtime(AppConfig.load())
    summaries = run_research_backfill(
        runtime,
        start=start_date,
        through=through_date,
        scope=scope,
        resume=resume,
    )
    for item in summaries:
        typer.echo(
            f"{item.scope}: committed={item.committed} skipped={item.skipped} "
            f"waiting={item.waiting_upstream} failed={item.failed}"
        )
    if any(item.failed for item in summaries):
        raise typer.Exit(code=2)


@data_app.command("repair-gaps")
def data_repair_gaps(
    through: str = typer.Option(..., "--through"),
) -> None:
    from stock_analyzer.ops.research_data_job import (
        build_research_data_runtime,
        repair_research_gaps,
    )

    runtime = build_research_data_runtime(AppConfig.load())
    summaries = repair_research_gaps(
        runtime,
        through=date.fromisoformat(through),
    )
    for item in summaries:
        typer.echo(
            f"repair/{item.scope}: committed={item.committed} "
            f"skipped={item.skipped} waiting={item.waiting_upstream} "
            f"failed={item.failed}"
        )
    if any(item.failed for item in summaries):
        raise typer.Exit(code=2)


@data_app.command("run-stage")
def data_run_stage(
    stage: str = typer.Option(..., "--stage"),
    data_date: str = typer.Option(..., "--data-date"),
) -> None:
    from stock_analyzer.ops.research_data_job import (
        build_research_data_runtime,
        run_research_stage,
    )

    runtime = build_research_data_runtime(AppConfig.load())
    if data_date == "auto":
        today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
        if stage == "next-morning":
            calendar_start = today - timedelta(days=14)
            calendar = runtime.tushare.fetch_trade_calendar(calendar_start, today)
            candidates = sorted(
                value
                for value in calendar.loc[calendar["is_open"], "cal_date"].tolist()
                if value < today
            )
            if not candidates:
                _fail("cannot resolve previous trading date for next-morning stage")
            parsed = candidates[-1]
        else:
            parsed = today
    else:
        parsed = date.fromisoformat(data_date)
    summaries = run_research_stage(runtime, stage=stage, data_date=parsed)
    for item in summaries:
        typer.echo(
            f"{stage}/{item.scope}: committed={item.committed} skipped={item.skipped} "
            f"waiting={item.waiting_upstream} failed={item.failed}"
        )
    if any(item.failed for item in summaries):
        raise typer.Exit(code=2)


@data_app.command("health")
def data_health(
    data_date: str = typer.Option(..., "--data-date"),
    full_history: bool = typer.Option(False, "--full-history/--latest-only"),
) -> None:
    from stock_analyzer.ops.research_health import (
        build_research_health_report,
        write_health_report,
    )
    from stock_analyzer.storage.research_warehouse import ResearchWarehouse

    config = AppConfig.load()
    parsed = date.fromisoformat(data_date)
    report = build_research_health_report(
        ResearchWarehouse(config.local_warehouse_dir),
        parsed,
        full_history=full_history,
    )
    json_path, _ = write_health_report(
        report, config.local_archive_dir / "data_health"
    )
    typer.echo(
        f"data health {parsed}: core_complete={str(report.complete_core_date).lower()} "
        f"datasets={len(report.datasets)} gaps={sum(report.gap_counts.values())} "
        f"output={json_path}"
    )


@app.command("formal-warehouse-inventory")
def formal_warehouse_inventory(
    source_root: Path = typer.Option(..., "--source-root"),
    output: Path = typer.Option(..., "--output"),
) -> None:
    inventory = run_formal_warehouse_inventory(source_root, output)
    typer.echo(
        f"formal warehouse inventory: files={len(inventory.items)} "
        f"unknown={len(inventory.unknown_paths)} output={output}"
    )
    if inventory.unknown_paths:
        raise typer.Exit(code=2)


@app.command("formal-warehouse-migrate")
def formal_warehouse_migrate(
    source_root: Path = typer.Option(..., "--source-root"),
    warehouse_root: Path = typer.Option(..., "--warehouse-root"),
    migration_id: str = typer.Option(..., "--migration-id"),
    output: Path = typer.Option(..., "--output"),
) -> None:
    audit = run_formal_warehouse_migration(
        source_root,
        warehouse_root,
        migration_id,
        output,
    )
    typer.echo(
        f"formal warehouse migration: items={len(audit.items)} "
        f"deletion_eligible={str(audit.deletion_eligible).lower()} output={output}"
    )
    if not audit.deletion_eligible:
        raise typer.Exit(code=2)


@app.command("formal-warehouse-audit")
def formal_warehouse_audit(
    warehouse_root: Path = typer.Option(..., "--warehouse-root"),
    strict_hashes: bool = typer.Option(False, "--strict-hashes"),
    output: Path = typer.Option(..., "--output"),
) -> None:
    audit = run_formal_warehouse_audit(
        warehouse_root,
        output,
        strict_hashes=strict_hashes,
    )
    typer.echo(
        f"formal warehouse audit: complete={str(audit.complete).lower()} "
        f"versions={audit.version_count} rows={audit.row_count} output={output}"
    )
    if not audit.complete:
        raise typer.Exit(code=2)


@app.command("formal-warehouse-deletion-manifest")
def formal_warehouse_deletion_manifest(
    source_root: Path = typer.Option(..., "--source-root"),
    warehouse_root: Path = typer.Option(..., "--warehouse-root"),
    migration_id: str = typer.Option(..., "--migration-id"),
    output: Path = typer.Option(..., "--output"),
) -> None:
    try:
        manifest = run_formal_warehouse_deletion_manifest(
            source_root,
            warehouse_root,
            migration_id,
            output,
        )
    except (FileNotFoundError, ValueError) as exc:
        _fail(str(exc))
    typer.echo(
        f"formal warehouse deletion manifest: files={len(manifest.files)} "
        f"bytes={manifest.total_bytes} output={output}"
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
        store = FormalWarehouse(config.local_warehouse_dir)
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
        receipt_store = FormalWarehouse(config.local_warehouse_dir)
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
            FormalWarehouse(config.local_warehouse_dir),
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
        FormalWarehouse(config.local_warehouse_dir),
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
