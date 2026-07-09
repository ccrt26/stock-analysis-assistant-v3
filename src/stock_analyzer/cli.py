from datetime import date
from pathlib import Path
from typing import Optional

import typer

from stock_analyzer.config import AppConfig
from stock_analyzer.data.health import run_health_checks
from stock_analyzer.data.provider import (
    CurrentLiveDataUnavailable,
    build_production_market_data_provider,
)
from stock_analyzer.ops.job import ACTION_REQUIRED_STATUSES, run_daily_job
from stock_analyzer.pipeline import (
    ProductionDataSourceUnavailable,
    StoredAnalysisNotFound,
    render_report_for_date,
    run_daily_pipeline,
)
from stock_analyzer.storage.capacity_guard import SupabaseCapacityGuard
from stock_analyzer.storage.local_archive import LocalArchive
from stock_analyzer.storage.local_warehouse import LocalWarehouse
from stock_analyzer.storage.repositories import (
    InMemoryAnalysisRepository,
    SupabaseAnalysisRepository,
)
from stock_analyzer.storage.supabase_client import create_supabase_client


app = typer.Typer(no_args_is_help=True)
ops_app = typer.Typer(no_args_is_help=True)
app.add_typer(ops_app, name="ops")

MISSING_SUPABASE_CONFIG_MESSAGE = (
    "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required for production "
    "run-daily/render-report. Use --fixture-mode or set "
    "STOCK_ANALYZER_FIXTURE_MODE=1 only for local fixture data."
)


@app.command("health-check")
def health_check(
    live_tushare_smoke: bool = typer.Option(False, "--live-tushare-smoke"),
) -> None:
    config = AppConfig.load()
    report = run_health_checks(config)
    for line in report.as_lines():
        typer.echo(line)
    if live_tushare_smoke:
        token = config.resolve_tushare_token()
        if not token:
            _fail("Tushare token missing; set TUSHARE_TOKEN or TUSHARE_TOKEN_PATH")
        try:
            source = _build_tushare_source(token)
            rows = source.fetch_daily(date(2026, 7, 8))
        except Exception as exc:
            _fail(f"live Tushare smoke failed: {_mask_secret(str(exc), token)}")
        typer.echo(f"live_tushare_smoke: rows={len(rows)}")


@app.command("run-daily")
def run_daily(
    dry_run: bool = typer.Option(False, "--dry-run"),
    fixture_mode: bool = typer.Option(False, "--fixture-mode"),
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

    market_data_provider = None
    if not effective_fixture_mode and not dry_run:
        try:
            market_data_provider = build_production_market_data_provider(config)
        except CurrentLiveDataUnavailable as exc:
            _fail(str(exc))

    try:
        result = run_daily_pipeline(
            parsed_trade_date,
            config.reports_dir,
            dry_run=dry_run,
            repository=repository,
            persist=not dry_run,
            fixture_mode=effective_fixture_mode,
            market_data_provider=market_data_provider,
            local_warehouse=(
                LocalWarehouse(config.local_warehouse_dir)
                if not dry_run and not effective_fixture_mode
                else None
            ),
            local_archive=(
                LocalArchive(config.local_archive_dir)
                if not dry_run and not effective_fixture_mode
                else None
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
) -> None:
    parsed_trade_date = date.fromisoformat(trade_date)
    config = AppConfig.load()
    status = run_daily_job(
        project_root=config.project_root,
        trade_date=parsed_trade_date,
        scheduled_slot=scheduled_slot,
        attempt=attempt,
        prepare_deploy=prepare_deploy,
    )
    typer.echo(f"{status.status.value} stage={status.stage}")
    if status.status in ACTION_REQUIRED_STATUSES:
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
