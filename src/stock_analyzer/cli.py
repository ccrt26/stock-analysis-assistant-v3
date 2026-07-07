from datetime import date
from pathlib import Path
from typing import Optional

import typer

from stock_analyzer.config import AppConfig
from stock_analyzer.data.health import run_health_checks
from stock_analyzer.pipeline import run_daily_pipeline
from stock_analyzer.storage.repositories import InMemoryAnalysisRepository, SupabaseAnalysisRepository
from stock_analyzer.storage.supabase_client import create_supabase_client


app = typer.Typer(no_args_is_help=True)


@app.command("health-check")
def health_check() -> None:
    report = run_health_checks(AppConfig.load())
    for line in report.as_lines():
        typer.echo(line)


@app.command("run-daily")
def run_daily(
    dry_run: bool = typer.Option(False, "--dry-run"),
    trade_date: str = typer.Option(..., "--trade-date"),
) -> None:
    parsed_trade_date = date.fromisoformat(trade_date)
    config = AppConfig.load()
    repository = _analysis_repository(config)
    result = run_daily_pipeline(
        parsed_trade_date,
        config.reports_dir,
        dry_run=dry_run,
        repository=repository,
    )

    if dry_run:
        typer.echo(f"daily run dry-run completed for {result.trade_date.isoformat()}")
        return
    typer.echo(f"daily run completed for {result.trade_date.isoformat()}")
    typer.echo(f"recommendations: {len(result.recommendations)}")
    typer.echo(f"evaluation_tasks: {len(result.evaluation_tasks)}")


@app.command("render-report")
def render_report(
    trade_date: str = typer.Option(..., "--trade-date"),
    output_dir: Optional[Path] = typer.Option(None, "--output-dir"),
) -> None:
    parsed_trade_date = date.fromisoformat(trade_date)
    config = AppConfig.load()
    target_dir = output_dir or config.reports_dir
    result = run_daily_pipeline(
        parsed_trade_date,
        target_dir,
        dry_run=False,
        repository=_analysis_repository(config),
    )
    typer.echo(f"report rendered for {result.trade_date.isoformat()}")


def _analysis_repository(config: AppConfig):
    if config.supabase_url and config.supabase_service_role_key:
        return SupabaseAnalysisRepository(create_supabase_client(config))
    return InMemoryAnalysisRepository()
