from datetime import date

import typer

from stock_analyzer.config import AppConfig
from stock_analyzer.data.health import run_health_checks
from stock_analyzer.pipeline import run_daily_pipeline


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
    result = run_daily_pipeline(parsed_trade_date, config.reports_dir, dry_run=dry_run)

    if dry_run:
        typer.echo(f"daily run dry-run completed for {result.trade_date.isoformat()}")
        return
    typer.echo(f"daily run completed for {result.trade_date.isoformat()}")
    typer.echo(f"recommendations: {len(result.recommendations)}")
    typer.echo(f"evaluation_tasks: {len(result.evaluation_tasks)}")
