from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

import typer

from stock_analyzer.config import AppConfig


app = typer.Typer(no_args_is_help=True)
data_app = typer.Typer(no_args_is_help=True)
app.add_typer(data_app, name="data")


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
            f"waiting={item.waiting_upstream} limited={item.limited} "
            f"failed={item.failed}"
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
            f"limited={item.limited} failed={item.failed}"
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
        parsed = _resolve_research_stage_date(
            runtime.tushare,
            stage,
            datetime.now(ZoneInfo("Asia/Shanghai")),
        )
    else:
        parsed = date.fromisoformat(data_date)
    summaries = run_research_stage(runtime, stage=stage, data_date=parsed)
    for item in summaries:
        typer.echo(
            f"{stage}/{item.scope}: committed={item.committed} skipped={item.skipped} "
            f"waiting={item.waiting_upstream} limited={item.limited} "
            f"failed={item.failed}"
        )
        if item.scope == "derived-research-features" and item.issues:
            typer.echo(item.issues[0])

    from stock_analyzer.ops.research_health import (
        build_research_health_report,
        write_health_report,
    )

    health = build_research_health_report(
        runtime.warehouse,
        parsed,
        full_history=False,
    )
    health_path, _ = write_health_report(
        health,
        runtime.config.local_archive_dir / "data_health",
    )
    typer.echo(
        f"stage health: core_complete={str(health.complete_core_date).lower()} "
        f"output={health_path}"
    )
    if any(item.failed for item in summaries):
        raise typer.Exit(code=2)


@data_app.command("derive")
def data_derive(
    data_date: str = typer.Option(..., "--data-date"),
) -> None:
    """Recompute governed observations from facts already stored locally."""

    from stock_analyzer.ops.research_features import run_research_features
    from stock_analyzer.storage.research_warehouse import ResearchWarehouse

    config = AppConfig.load()
    summary = run_research_features(
        ResearchWarehouse(config.local_warehouse_dir),
        date.fromisoformat(data_date),
    )
    typer.echo(summary.plain_language_summary)
    if summary.failed_feature_sets:
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
        report,
        config.local_archive_dir / "data_health",
    )
    typer.echo(
        f"data health {parsed}: core_complete={str(report.complete_core_date).lower()} "
        f"datasets={len(report.datasets)} gaps={sum(report.gap_counts.values())} "
        f"output={json_path}"
    )


def _resolve_research_stage_date(client, stage: str, now: datetime) -> date:
    local_now = now.astimezone(ZoneInfo("Asia/Shanghai"))
    today = local_now.date()
    calendar = client.fetch_trade_calendar(today - timedelta(days=14), today)
    open_dates = sorted(
        value
        for value in calendar.loc[calendar["is_open"], "cal_date"].tolist()
        if value <= today
    )
    if not open_dates:
        _fail("cannot resolve a trading date for research data stage")

    cutoffs = {
        "close": time(18, 30),
        "evening": time(21, 30),
    }
    if stage == "next-morning":
        candidates = [value for value in open_dates if value < today]
    elif stage in cutoffs:
        today_is_open = today in open_dates
        if today_is_open and local_now.time() >= cutoffs[stage]:
            return today
        candidates = [value for value in open_dates if value < today]
    else:
        _fail(f"unknown research data stage: {stage}")
    if not candidates:
        _fail(f"cannot resolve prior trading date for {stage} stage")
    return candidates[-1]


def _fail(message: str) -> None:
    typer.echo(f"Error: {message}", err=True)
    raise typer.Exit(code=2)
